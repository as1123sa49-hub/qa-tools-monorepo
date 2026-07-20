"""
Goal Agent — LLM-driven ReAct tool-calling agent for casino game automation.

架構：
  GoalAgent（本檔）
    ├── 持有 CloudVisionAgent 做低階操作（截圖、click、state check、layout cache）
    ├── 把低階操作封裝成 LLM 可呼叫的 tools（OpenAI function calling）
    └── 執行 ReAct 循環：goal → plan → tool call → observe → repeat

三層模型：
  plan_model     （claude-sonnet-4.5）：根據目標決定下一步 action（每步 spin 後一次）
  state_model    （qwen3.5-flash）   ：截圖分析遊戲狀態（輪詢用，每 2 秒一次）
  discovery_model（gemini-2.5-pro）  ：一次性 UI 元素座標辨識（有快取則跳過）

支援的目標範例：
  "spin 3 times"
  "spin until feature game triggers"
  "set bet to minimum, then spin 3 times"
  "click buy_feature with bet 20"
  "enable extra_bet, then spin 3 times"
  "spin until balance increases by 100"

環境變數：
  SIRAYA_API_KEY          必填
  SIRAYA_PLAN_MODEL       規劃模型（預設 claude-sonnet-4.5）
  SIRAYA_STATE_MODEL      狀態模型（預設 qwen3.5-flash）
  SIRAYA_DISCOVERY_MODEL  發現模型（預設 gemini-2.5-pro）
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from core.cloud_vision_agent import CloudVisionAgent

logger = logging.getLogger(__name__)

# ============================================================
# Tool Definitions（OpenAI function calling format）
# ============================================================
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_state",
            "description": (
                "Take a screenshot and analyze the current game state. "
                "Returns: spinning (bool), popup info, feature_triggered (bool), "
                "current_bet (float|null), current_balance (float|null), notes (str)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_element",
            "description": (
                "Click a named UI element discovered in the game layout. "
                "Only use names present in the layout. "
                "Common names: spin_button, bet_increase, bet_decrease, auto_spin, "
                "turbo, menu, extra_bet, buy_feature, super_buy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "element": {
                        "type": "string",
                        "description": "Name of the UI element to click.",
                    }
                },
                "required": ["element"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_at",
            "description": (
                "Click at a specific normalized coordinate (0.0–1.0 range). "
                "Use for popup close buttons or ad-hoc coordinates from check_state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "Normalized x (0.0=left, 1.0=right)"},
                    "y": {"type": "number", "description": "Normalized y (0.0=top, 1.0=bottom)"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_settled",
            "description": (
                "Wait until the reels stop spinning (game returns to idle). "
                "Automatically handles mid-spin popups. "
                "Returns the final game state including feature_triggered."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Maximum seconds to wait (default 60).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Pause execution for a given number of seconds (0.5 to 10).",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "number",
                        "description": "Seconds to wait.",
                    }
                },
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete",
            "description": (
                "Signal that the goal is achieved or cannot be achieved. "
                "Always call this when done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why goal succeeded or failed.",
                    },
                },
                "required": ["success", "reason"],
            },
        },
    },
]

# ============================================================
# Rich State Check Prompt（比 CloudVisionAgent 的 basic check 更多欄位）
# ============================================================

_RICH_STATE_SYSTEM = """You are analyzing a casino slot game screenshot.\nReturn ONLY this JSON object, nothing else:\n{\n  \"spinning\": <true if reels are moving or any spin animation is playing>,\n  \"popup_visible\": <true if any modal, dialog, or overlay is blocking gameplay>,\n  \"popup_close\": {\"x\": <0.0-1.0>, \"y\": <0.0-1.0>} or null,\n  \"popup_elements\": {\n    <element_name>: {\"x\": <0.0-1.0>, \"y\": <0.0-1.0>}\n    // ...\n  } or { },\n  \"feature_triggered\": <true if free game / bonus / feature game just started or is active>,\n  \"current_bet\": <visible bet/total-bet amount as float, null if not readable>,\n  \"current_balance\": <visible balance/credits/coin as float, null if not readable>,\n  \"notes\": \"<one sentence describing what is happening on screen. If there are multiple bet value buttons or options, you MUST return ALL of them in popup_elements, do not omit any.>\"\n}\nCoordinates: x=0.0 is left edge, x=1.0 is right edge; y=0.0 is top, y=1.0 is bottom.\nIf popup_visible is true, you MUST find and return ALL actionable/clickable elements in the popup (e.g., buy_feature, confirm, close, bet value, etc.) and return their normalized coordinates in popup_elements. DO NOT OMIT any element. If none, return {}.\nIf you cannot find a close/exit button, set popup_close to null."""

_RICH_STATE_USER = "Analyze game state (yes/no & numbers only)."

# ============================================================
# Planning System Prompt Template
# ============================================================
_PLAN_SYSTEM_TMPL = """You are a casino game QA automation agent.
You control a real browser running a casino slot/game.
Use the provided tools to achieve the stated goal, step by step.

## Available UI Elements (from layout analysis)
{layout_summary}

## Rules
- After clicking spin_button, ALWAYS call wait_settled() before any next action.
- Use check_state() to verify the current state before making decisions.
- Popup handling: if popup_visible is true, call click_at() with the popup_close coordinates.
- Bet adjustment: repeatedly click bet_increase/bet_decrease, then check_state() to read current_bet.
- Feature detection: monitor feature_triggered field in check_state() / wait_settled() results.
- When the goal is achieved → call complete(success=true, reason="...").
- If stuck or impossible after multiple attempts → call complete(success=false, reason="...").
- Step budget: {max_steps} tool calls total.

## Game Context
Game: {game_name} ({game_id})
Provider: {provider}
"""


class GoalAgent:
    """
    LLM-driven ReAct agent for casino game automation.

    Wraps CloudVisionAgent primitives as LLM-callable tools.
    The planning model decides which tool to call at each step.
    """


    def __init__(
        self,
        api_key: str,
        plan_model: str = "deepseek-v4-pro",
        state_model: str = "gemini-2.5-pro",
        discovery_model: str = "gemini-2.5-pro",
        base_url: str = "https://llm.siraya.ai/v1",
        max_steps: int = 20,
        cache_dir: Path | str = Path("config/specs/layout_cache"),
        artifact_handler=None,
    ):
        self.plan_model = plan_model
        self.max_steps = max_steps

        # Low-level executor — handles screenshot, click, state, layout cache
        self.executor = CloudVisionAgent(
            api_key=api_key,
            discovery_model=discovery_model,
            state_model=state_model,
            base_url=base_url,
            cache_dir=cache_dir,
        )

        # Plan client reuses the same AsyncOpenAI instance
        self.plan_client = self.executor.client

        # Optional artifact handler for Allure attach
        self.artifact_handler = artifact_handler

        logger.info(
            f"[GoalAgent] plan={plan_model} | state={state_model} | "
            f"discovery={discovery_model} | max_steps={max_steps}"
        )

    # ----------------------------------------------------------
    # Rich state check（擴充版，回傳更多欄位）
    # ----------------------------------------------------------
    async def _rich_check_state(self, screenshot_bytes: bytes, step_name: str = None) -> dict:
        # Attach screenshot to Allure if artifact_handler is present
        if self.artifact_handler:
            # Use step_name or timestamp for unique naming
            import time
            name = step_name or f"state_{int(time.time()*1000)}"
            try:
                self.artifact_handler.capture(
                    page=None,  # Not available here, see below
                    name=name,
                    category="gameplay",
                    attach_to_allure=True
                )
            except Exception as e:
                logger.warning(f"[GoalAgent] Allure attach failed: {e}")
        img_b64 = await asyncio.to_thread(self.executor._encode, screenshot_bytes, 55)
        try:
            # 強化版 state check：要求回傳 popup_elements
            response = await self.executor.client.chat.completions.create(
                model=self.executor.state_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": _RICH_STATE_SYSTEM,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                },
                            },
                        ],
                    },
                ],
                max_tokens=1024,
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            result = self.executor._parse_json(raw)
            if result and "spinning" in result:
                # 確保 popup_elements 欄位存在
                if "popup_elements" not in result:
                    result["popup_elements"] = {}
                return result
        except Exception as e:
            logger.warning(f"[GoalAgent] State check failed: {e}")
        return {
            "spinning": False,
            "popup_visible": False,
            "popup_close": None,
            "popup_elements": {},
            "feature_triggered": False,
            "current_bet": None,
            "current_balance": None,
            "notes": "error",
        }

    # ----------------------------------------------------------
    # Layout summary（for system prompt）
    # ----------------------------------------------------------
    @staticmethod
    def _layout_summary(layout: dict) -> str:
        lines = []
        for name, val in layout.items():
            if name == "notes":
                lines.append(f"  notes: {val}")
            elif isinstance(val, dict) and "x1" in val:
                cx = (val["x1"] + val["x2"]) / 2
                cy = (val["y1"] + val["y2"]) / 2
                lines.append(f"  {name}: center≈({cx:.2f}, {cy:.2f})")
            elif val is None:
                lines.append(f"  {name}: not visible")
        return "\n".join(lines) if lines else "  (no elements discovered)"

    # ----------------------------------------------------------
    # Tool dispatch
    # ----------------------------------------------------------
    async def _dispatch(
        self,
        page,
        layout: dict,
        vp_w: int,
        vp_h: int,
        tool_name: str,
        tool_args: dict,
    ) -> dict:
        logger.info(f"[GoalAgent] → {tool_name}({json.dumps(tool_args)})")

        # Always attach screenshot to Allure if artifact_handler exists
        if self.artifact_handler:
            try:
                step_label = f"{tool_name}_{int(time.time()*1000)}"
                self.artifact_handler.capture(
                    page=page,
                    name=step_label,
                    category="gameplay",
                    attach_to_allure=True
                )
            except Exception as e:
                logger.warning(f"[GoalAgent] Allure attach failed: {e}")

        if tool_name == "check_state":
            ss = await page.screenshot(type="jpeg", quality=60)
            state = await self._rich_check_state(ss)
            logger.info(f"[GoalAgent] state: spinning={state.get('spinning')} popup={state.get('popup_visible')} feature={state.get('feature_triggered')}")
            return state

        elif tool_name == "click_element":
            element = tool_args.get("element", "")
            bbox = layout.get(element)
            if not bbox:
                available = [k for k, v in layout.items() if v and k != "notes"]
                msg = f"Element '{element}' not in layout. Available: {available}"
                logger.warning(f"[GoalAgent] {msg}")
                return {"error": msg}
            cx = (bbox["x1"] + bbox["x2"]) / 2 * vp_w
            cy = (bbox["y1"] + bbox["y2"]) / 2 * vp_h
            logger.info(f"[GoalAgent] click '{element}' at ({cx:.0f}, {cy:.0f})")
            await page.mouse.click(cx, cy)
            await asyncio.sleep(0.5)
            return {"clicked": element, "pixel": [round(cx), round(cy)]}

        elif tool_name == "click_at":
            x = float(tool_args.get("x", 0.5))
            y = float(tool_args.get("y", 0.5))
            px = x * vp_w
            py = y * vp_h
            logger.info(f"[GoalAgent] click_at ({x:.3f}, {y:.3f}) → ({px:.0f}, {py:.0f})")
            await page.mouse.click(px, py)
            await asyncio.sleep(0.5)
            return {"clicked_at": [round(x, 3), round(y, 3)]}

        elif tool_name == "wait_settled":
            timeout = float(tool_args.get("timeout_seconds", 60))
            max_polls = max(1, int(timeout / 2))
            await asyncio.sleep(1.5)  # 讓動畫先啟動
            for poll in range(max_polls):
                ss = await page.screenshot(type="jpeg", quality=55)
                state = await self._rich_check_state(ss)
                logger.info(
                    f"[GoalAgent] wait_settled poll {poll + 1}: "
                    f"spinning={state.get('spinning')}, "
                    f"feature={state.get('feature_triggered')}"
                )
                if state.get("popup_visible") and state.get("popup_close"):
                    close = state["popup_close"]
                    logger.info(f"[GoalAgent] auto-dismiss popup at {close}")
                    await page.mouse.click(close["x"] * vp_w, close["y"] * vp_h)
                    await asyncio.sleep(0.5)
                    continue
                if not state.get("spinning"):
                    return {"settled": True, "final_state": state}
                await asyncio.sleep(2)
            return {"settled": False, "timeout": True}

        elif tool_name == "wait":
            seconds = min(max(float(tool_args.get("seconds", 1)), 0.1), 10)
            await asyncio.sleep(seconds)
            return {"waited": seconds}

        elif tool_name == "complete":
            return {
                "_complete": True,
                "success": bool(tool_args.get("success", False)),
                "reason": str(tool_args.get("reason", "")),
            }

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    # ----------------------------------------------------------
    # Main: run()
    # ----------------------------------------------------------
    async def run(self, page, game_cfg: dict, goal: str) -> bool:
        """
        執行高層目標。

        Args:
            page:     Playwright page object（已在遊戲頁面內）
            game_cfg: games.yaml 裡的遊戲設定 dict（含 id、name、provider_label）
            goal:     自然語言目標，例如 "spin 3 times" 或 "spin until feature game"

        Returns:
            True if goal was achieved, False otherwise.
        """
        game_id = game_cfg.get("id", "unknown")
        game_name = game_cfg.get("name", game_id)
        provider = game_cfg.get("provider_label", "unknown")
        vp = page.viewport_size
        vp_w, vp_h = vp["width"], vp["height"]

        logger.info(f"[GoalAgent] 🎯 Goal: {goal}")

        # ── Step 1: 取得 layout ──────────────────────────────────────
        cache_data = self.executor._load_cache(game_id)
        if cache_data:
            layout = cache_data["layout"]
            logger.info(f"[GoalAgent] ✅ Layout loaded from cache")
        else:
            layout = await self.executor._discover_layout(page, game_id, game_name)
            if not layout:
                logger.error("[GoalAgent] Layout discovery failed, aborting")
                return False

        layout_summary = self._layout_summary(layout)

        # ── Step 2: 初始狀態 ─────────────────────────────────────────
        ss = await page.screenshot(type="jpeg", quality=65)
        initial_state = await self._rich_check_state(ss)
        logger.info(f"[GoalAgent] Initial state: {initial_state}")

        # ── Step 3: 建立 messages ────────────────────────────────────
        system_prompt = _PLAN_SYSTEM_TMPL.format(
            layout_summary=layout_summary,
            max_steps=self.max_steps,
            game_name=game_name,
            game_id=game_id,
            provider=provider,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Goal: {goal}\n\n"
                    f"Initial state: spinning={initial_state.get('spinning')}, "
                    f"popup={initial_state.get('popup_visible')}, "
                    f"feature={initial_state.get('feature_triggered')}, "
                    f"bet={initial_state.get('current_bet')}, "
                    f"balance={initial_state.get('current_balance')}"
                ),
            },
        ]

        # ── Step 4: ReAct 循環 ───────────────────────────────────────
        t_loop_start = time.perf_counter()
        loop_timeout = 300  # 5 分鐘上限（防止無限迴圈）
        prev_tool_names = []  # 記錄最近 3 個 tool name（檢測重複）
        total_tokens = 0

        for step in range(self.max_steps):
            # ── 超時檢查 ──────────────────────────────────────
            elapsed = time.perf_counter() - t_loop_start
            if elapsed > loop_timeout:
                logger.warning(f"[GoalAgent] ⏱️  超時 ({elapsed:.0f}s > {loop_timeout}s)，停止")
                return False

            logger.info(f"[GoalAgent] === Step {step + 1}/{self.max_steps} === ({elapsed:.0f}s 已耗)")

            try:
                # ── Message 窗口（防止 context 無限成長） ──────────
                # 保留：system + initial user + 最後 5 條 (assistant+tool pairs)
                window_size = 10  # ~5 pairs of (assistant, tool result)
                if len(messages) > window_size + 2:  # +2 for system & initial
                    messages = [
                        messages[0],  # system
                        messages[1],  # initial user
                        *messages[-(window_size):],  # last N messages
                    ]
                    logger.debug(f"[GoalAgent] Message 窗口: 保留最後 {window_size} 條")

                response = await self.plan_client.chat.completions.create(
                    model=self.plan_model,
                    messages=messages,
                    tools=_TOOLS,
                    tool_choice="auto",
                    max_tokens=500,
                    temperature=0,
                )
                # 累積 token
                total_tokens += response.usage.prompt_tokens + response.usage.completion_tokens
            except Exception as e:
                logger.error(f"[GoalAgent] Plan API call failed: {e}")
                break

            msg = response.choices[0].message

            if not msg.tool_calls:
                logger.warning("[GoalAgent] No tool call returned, stopping")
                break

            # ── 行為重複檢測（最近 3 個 step 都在做同一個 action） ──────
            current_tool_names = [tc.function.name for tc in msg.tool_calls]
            prev_tool_names.append(current_tool_names)
            if len(prev_tool_names) > 3:
                prev_tool_names.pop(0)

            if (len(prev_tool_names) >= 3 and
                all(t == prev_tool_names[0] for t in prev_tool_names)):
                logger.warning(
                    f"[GoalAgent] 🔄 行為重複: {prev_tool_names[0]} 連續 3 次無進展，停止"
                )
                return False

            # 把 assistant 回覆加入 messages
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # 執行每個 tool call
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_args = {}

                result = await self._dispatch(
                    page, layout, vp_w, vp_h, tool_name, tool_args
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

                # 檢查是否完成
                if result.get("_complete"):
                    success = result["success"]
                    reason = result["reason"]
                    logger.info(
                        f"[GoalAgent] {'✅' if success else '❌'} Complete: {reason}"
                    )
                    return success

        logger.warning(
            f"[GoalAgent] ⚠️ Max steps ({self.max_steps}) reached without completion"
        )
        elapsed_total = time.perf_counter() - t_loop_start
        logger.info(f"[GoalAgent] 📊 統計: {step + 1} steps | {total_tokens} tokens | {elapsed_total:.1f}s")
        return False

    @staticmethod
    def default_goal(game_cfg: dict) -> str:
        """從 game_cfg 讀取 goal 欄位，或依 category 給出預設目標。"""
        custom = game_cfg.get("goal")
        if custom:
            return custom
        category = game_cfg.get("category", "slot")
        defaults = {
            "slot": "Spin once and wait for the reels to stop.",
            "egame": "Click the main action button once and wait for the result.",
            "fish": "Click the shoot button once to fire.",
        }
        return defaults.get(category, defaults["slot"])
