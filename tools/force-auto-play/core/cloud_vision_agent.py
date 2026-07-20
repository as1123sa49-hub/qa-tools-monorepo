"""
Cloud Vision Agent — 雙層成本架構

┌─────────────────────────────────────────────────────────┐
│  Layer 1: Layout Discovery（昂貴模型，每個遊戲只跑一次）  │
│  → 截圖 → 辨識所有靜態 UI 元素位置 → 存 JSON 快取        │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Execution（便宜模型，每次 spin 用）             │
│  → 載入快取座標直接 click（無需模型）                     │
│  → 狀態檢查只問 "還在轉嗎？有彈窗嗎？" → 一行 JSON       │
└─────────────────────────────────────────────────────────┘

環境變數：
  SIRAYA_API_KEY              必填
  SIRAYA_DISCOVERY_MODEL      昂貴模型，layout discovery 用（預設 gemini-2.5-pro）
  SIRAYA_STATE_MODEL          便宜模型，每步狀態檢查用（預設 qwen3.5-flash）
  SIRAYA_BASE_URL             API base URL（預設 https://llm.siraya.ai/v1）
"""
import asyncio
import base64
import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from openai import AsyncOpenAI
from PIL import Image

logger = logging.getLogger(__name__)

# ============================================================
# 快取目錄
# ============================================================
_CACHE_DIR = Path("config/specs/layout_cache")

# ============================================================
# Discovery Prompt（昂貴模型，只跑一次）
# 目標：準確解析遊戲 UI 的所有靜態座標
# ============================================================
_DISCOVERY_SYSTEM = """You are an expert UI analyst for HTML5 slot/casino games.
Analyze the provided screenshot and identify ALL interactive UI elements.

CRITICAL: Return ONLY valid JSON. No markdown, no explanation outside JSON.

Return this exact structure:
{
  "spin_button":    {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>},
  "balance_region": {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>},
  "bet_increase":   {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "bet_decrease":   {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "auto_spin":      {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "turbo":          {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "menu":           {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "extra_bet":      {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "buy_feature":    {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "super_buy":      {"x1": <0.0-1.0>, "y1": <0.0-1.0>, "x2": <0.0-1.0>, "y2": <0.0-1.0>} or null,
  "notes": "<brief notes about this game UI layout>"
}

Rules:
  - ALL elements use bounding box format (x1,y1 = top-left corner, x2,y2 = bottom-right corner)
  - x=0.0 is left edge, x=1.0 is right edge; y=0.0 is top edge, y=1.0 is bottom edge
  - Draw a tight bounding box around each element, not just a single point
  - Spin button is usually a round button at bottom-center or bottom-right
  - Balance/credits area is typically at the bottom of the screen
  - bet_increase / bet_decrease are the +/- buttons near the bet amount
  - If an element is not visible, set it to null
"""

_DISCOVERY_USER = (
    "This is a fully loaded slot game. "
    "Identify all interactive UI elements and return their coordinates as JSON."
)

# ============================================================
# State Check Prompt（便宜模型，每步用）
# 只需回答 2 個問題：是否還在轉 + 有無彈窗
# ============================================================
_STATE_SYSTEM = """You are checking the state of a slot game screenshot.
Return ONLY this JSON object, nothing else:
{
  "spinning": <true|false>,
  "popup_visible": <true|false>,
  "popup_close": {"x": <0.0-1.0>, "y": <0.0-1.0>} or null
}

spinning: true if reels are moving or animation is playing
popup_visible: true if any modal, dialog, or overlay is visible
popup_close: coordinates of the close/X button if popup_visible is true
"""

_STATE_USER = "What is the current state of this slot game?"

# ============================================================
# 預設目標（依 category）
# ============================================================
_DEFAULT_GOALS = {
    "slot": "Play 1 spin: click spin, wait for reels to stop, confirm completion.",
    "egame": "Click the main action button once and wait for the result.",
    "fish": "Click the shoot button once to fire.",
}


class CloudVisionAgent:
    """
    雙層成本架構的 Siraya 雲端視覺 Agent。

    discovery_model: 昂貴、精準，每個遊戲只呼叫一次，結果快取到 JSON 檔。
    state_model:     便宜、快速，每步只問 "spinning? popup?" 兩個問題。
    """

    def __init__(
        self,
        api_key: str,
        discovery_model: str = "gemini-2.5-pro",
        state_model: str = "qwen3.5-flash",
        base_url: str = "https://llm.siraya.ai/v1",
        max_image_width: int = 1280,
        cache_dir: Path | str = _CACHE_DIR,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.discovery_model = discovery_model
        self.state_model = state_model
        self.max_image_width = max_image_width
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"[CloudAgent] discovery={discovery_model} | state={state_model} | "
            f"base_url={base_url}"
        )

    # ----------------------------------------------------------
    # Screenshot helpers
    # ----------------------------------------------------------
    def _encode(self, screenshot_bytes: bytes, quality: int = 70) -> str:
        """Resize + base64 encode。Discovery 用高品質，state check 可降質。"""
        img = Image.open(io.BytesIO(screenshot_bytes))
        if img.width > self.max_image_width:
            ratio = self.max_image_width / img.width
            img = img.resize(
                (self.max_image_width, int(img.height * ratio)), Image.LANCZOS
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()

    def _parse_json(self, content: str) -> dict | None:
        """解析模型回應的 JSON，容忍 markdown code fence。"""
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        logger.warning(f"[CloudAgent] Cannot parse JSON: {content[:300]}")
        return None

    # ----------------------------------------------------------
    # Layer 1: Layout Discovery（只跑一次，結果存檔）
    # ----------------------------------------------------------
    def _cache_path(self, game_id: str) -> Path:
        safe_id = re.sub(r"[^\w\-]", "_", str(game_id))
        return self.cache_dir / f"{safe_id}.json"

    def _load_cache(self, game_id: str) -> dict | None:
        path = self._cache_path(game_id)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                logger.info(
                    f"[CloudAgent] ✅ Layout cache hit: {path.name} "
                    f"(discovered {data.get('discovered_at', '?')})"
                )
                return data
            except Exception as e:
                logger.warning(f"[CloudAgent] Cache read error: {e}")
        return None

    def _save_cache(self, game_id: str, game_name: str, layout: dict) -> None:
        path = self._cache_path(game_id)
        payload = {
            "game_id": game_id,
            "game_name": game_name,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "discovery_model": self.discovery_model,
            "layout": layout,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"[CloudAgent] 💾 Layout cache saved: {path}")

    async def _discover_layout(
        self, page, game_id: str, game_name: str
    ) -> dict | None:
        """
        用昂貴模型做一次全面的 UI 元素辨識，結果快取到檔案。
        後續執行直接讀快取，不再呼叫昂貴模型。
        """
        logger.info(
            f"[CloudAgent] 🔍 Discovering layout for '{game_name}' "
            f"using {self.discovery_model} (expensive, runs once)..."
        )
        try:
            ss_bytes = await page.screenshot(type="jpeg", quality=92)
        except Exception as e:
            logger.error(f"[CloudAgent] Screenshot failed during discovery: {e}")
            return None

        # Discovery 用高品質截圖，讓昂貴模型看清楚
        img_b64 = await asyncio.to_thread(self._encode, ss_bytes, 92)

        try:
            response = await self.client.chat.completions.create(
                model=self.discovery_model,
                messages=[
                    {"role": "system", "content": _DISCOVERY_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _DISCOVERY_USER},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                },
                            },
                        ],
                    },
                ],
                max_tokens=600,
                temperature=0,
            )
        except Exception as e:
            logger.error(f"[CloudAgent] Discovery API call failed: {e}")
            return None

        raw = response.choices[0].message.content or ""
        logger.info(f"[CloudAgent] Discovery response: {raw}")

        layout = self._parse_json(raw)
        if layout and "spin_button" in layout:
            self._save_cache(game_id, game_name, layout)
            return layout

        logger.error("[CloudAgent] Discovery returned invalid layout JSON")
        return None

    # ----------------------------------------------------------
    # Layer 2: State Check（便宜模型，每步用）
    # ----------------------------------------------------------
    async def _check_state(self, screenshot_bytes: bytes) -> dict:
        """
        用便宜模型只問兩個問題：spinning? popup?
        截圖用低品質，再壓 token 成本。
        失敗時回傳 safe default（視為已停止、無彈窗）。
        """
        img_b64 = await asyncio.to_thread(self._encode, screenshot_bytes, 55)
        try:
            response = await self.client.chat.completions.create(
                model=self.state_model,
                messages=[
                    {"role": "system", "content": _STATE_SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _STATE_USER},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                },
                            },
                        ],
                    },
                ],
                max_tokens=100,
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            result = self._parse_json(raw)
            if result and "spinning" in result:
                return result
        except Exception as e:
            logger.warning(f"[CloudAgent] State check failed: {e}")
        return {"spinning": False, "popup_visible": False, "popup_close": None}

    # ----------------------------------------------------------
    # Main: run_goal（快取座標 + 便宜狀態檢查）
    # ----------------------------------------------------------
    async def run_goal(
        self,
        page,
        game_cfg: dict,
        max_spins: int = 1,
        max_wait_steps: int = 20,
        wait_interval: float = 2.0,
    ) -> bool:
        """
        執行高層目標。

        流程：
          1. 讀 layout 快取；若無則呼叫昂貴 discovery 模型並存檔
          2. 針對每次 spin：
             a. 關閉彈窗（便宜模型）
             b. 用快取座標直接 click spin 按鈕（不呼叫任何模型）
             c. 便宜模型輪詢等待 reels 停止
          3. 完成 max_spins 次後回傳 True
        """
        game_id = game_cfg.get("id", "unknown")
        game_name = game_cfg.get("name", game_id)
        vp = page.viewport_size
        vp_w, vp_h = vp["width"], vp["height"]

        # ── Step 1: 取得 layout（快取優先，沒有才 discover）─────────────
        cache_data = self._load_cache(game_id)
        if cache_data:
            layout = cache_data["layout"]
        else:
            layout = await self._discover_layout(page, game_id, game_name)
            if layout is None:
                logger.error("[CloudAgent] Layout discovery failed, aborting")
                return False

        spin = layout.get("spin_button")
        if not spin:
            logger.error("[CloudAgent] No spin_button in layout, aborting")
            return False

        def _bbox_center(bbox: dict) -> tuple[float, float]:
            """取 bounding box 中心點的絕對像素座標。"""
            cx = (bbox["x1"] + bbox["x2"]) / 2 * vp_w
            cy = (bbox["y1"] + bbox["y2"]) / 2 * vp_h
            return cx, cy

        spin_x, spin_y = _bbox_center(spin)
        logger.info(
            f"[CloudAgent] Spin button bbox [{spin['x1']:.2f},{spin['y1']:.2f} → "
            f"{spin['x2']:.2f},{spin['y2']:.2f}] center=({spin_x:.0f},{spin_y:.0f})"
        )

        # 是否從現有快取載入（用於決定 spin 失敗時是否重新 discover）
        loaded_from_cache = cache_data is not None

        # ── Step 2: 執行 max_spins 次 spin ──────────────────────────────
        for spin_no in range(1, max_spins + 1):
            logger.info(f"[CloudAgent] === Spin {spin_no}/{max_spins} ===")

            # (a) 關閉可能存在的彈窗（便宜模型）
            ss = await page.screenshot(type="jpeg", quality=65)
            state = await self._check_state(ss)
            if state.get("popup_visible"):
                close_coord = state.get("popup_close")
                if close_coord:
                    cx = close_coord["x"] * vp_w
                    cy = close_coord["y"] * vp_h
                    logger.info(f"[CloudAgent] Dismissing popup at ({cx:.0f}, {cy:.0f})")
                    await page.mouse.click(cx, cy)
                else:
                    logger.warning("[CloudAgent] Popup detected, trying top-right corner")
                    await page.mouse.click(vp_w * 0.95, vp_h * 0.05)
                await asyncio.sleep(1.5)

            # (b) 直接 click 快取的 spin 座標（zero model calls）
            logger.info(f"[CloudAgent] 🎰 Clicking spin at ({spin_x:.0f}, {spin_y:.0f})")
            await page.mouse.click(spin_x, spin_y)
            await asyncio.sleep(2.0)  # 等動畫啟動

            # (b2) 驗證 spin 是否真的啟動（防止座標打偏）
            ss_verify = await page.screenshot(type="jpeg", quality=60)
            verify_state = await self._check_state(ss_verify)
            if not verify_state.get("spinning") and not verify_state.get("popup_visible"):
                if loaded_from_cache:
                    # 快取座標可能因 UI 更新而失效 → 清快取、重新 discover
                    logger.warning(
                        "[CloudAgent] ⚠️ Spin not detected after cache click — "
                        "invalidating cache and re-discovering layout..."
                    )
                    self.invalidate_cache(game_id)
                    layout = await self._discover_layout(page, game_id, game_name)
                    if layout and layout.get("spin_button"):
                        spin = layout["spin_button"]
                        spin_x, spin_y = _bbox_center(spin)
                        loaded_from_cache = False
                        logger.info(f"[CloudAgent] Retrying spin at ({spin_x:.0f}, {spin_y:.0f})")
                        await page.mouse.click(spin_x, spin_y)
                        await asyncio.sleep(2.0)
                    else:
                        logger.error("[CloudAgent] Re-discovery failed, aborting spin")
                        return False
                else:
                    # 剛 discover 就點不到 → 模型識別有誤，記錄但繼續（等 timeout）
                    logger.warning(
                        "[CloudAgent] ⚠️ Spin not detected after fresh discovery click "
                        "— continuing to wait anyway"
                    )
            else:
                logger.info("[CloudAgent] ✅ Spin verified as started")

            # (c) 輪詢等待 reels 停止（便宜模型）
            settled = False
            for wait_step in range(max_wait_steps):
                ss = await page.screenshot(type="jpeg", quality=55)
                state = await self._check_state(ss)
                logger.info(
                    f"[CloudAgent] Wait {wait_step+1}/{max_wait_steps}: "
                    f"spinning={state.get('spinning')}, "
                    f"popup={state.get('popup_visible')}"
                )

                if state.get("popup_visible"):
                    close_coord = state.get("popup_close")
                    if close_coord:
                        cx = close_coord["x"] * vp_w
                        cy = close_coord["y"] * vp_h
                        logger.info(f"[CloudAgent] Mid-spin popup dismissed at ({cx:.0f}, {cy:.0f})")
                        await page.mouse.click(cx, cy)
                        await asyncio.sleep(1)

                if not state.get("spinning", True):
                    logger.info(f"[CloudAgent] ✅ Spin {spin_no} settled after {wait_step+1} checks")
                    settled = True
                    break

                await asyncio.sleep(wait_interval)

            if not settled:
                logger.warning(f"[CloudAgent] ⚠️ Spin {spin_no} wait timeout, treating as settled")

            await asyncio.sleep(1)  # 短暫停頓後再下一次 spin

        logger.info(f"[CloudAgent] ✅ Goal complete: {max_spins} spin(s) done")
        return True

    # ----------------------------------------------------------
    # Utility
    # ----------------------------------------------------------
    @staticmethod
    def goal_for_game(game_cfg: dict) -> str:
        """讀 games.yaml 的 goal 欄位，或依 category 推斷預設目標。"""
        custom = game_cfg.get("goal")
        if custom:
            return custom
        category = game_cfg.get("category", "slot")
        return _DEFAULT_GOALS.get(category, _DEFAULT_GOALS["slot"])

    def invalidate_cache(self, game_id: str) -> bool:
        """手動清除某個遊戲的 layout 快取（遊戲 UI 更新後使用）。"""
        path = self._cache_path(game_id)
        if path.exists():
            path.unlink()
            logger.info(f"[CloudAgent] Cache deleted: {path}")
            return True
        return False
