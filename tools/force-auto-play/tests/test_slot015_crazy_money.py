"""
Slot015 Crazy Money (瘋狂金錢) - 目標導向測試腳本

支援的 high-level 意圖：
  - 觸發 Feature Game (WHEEL)
  - 觸發 Respin
  - 觸發 Jackpot
  - 觸發 Big Win 表演

玩法特性（無 Free Game）：
  - 盤面: 1x3+1 (3 一般輪 + 1 特殊輪)
  - 單線賠付，數字即得分
  - 第四輪出現 SS1/SS2 → 觸發 WHEEL
  - 第四輪出現 JP 符號 → JP輪重轉
  - 第四輪出現 Respin → 重轉一次
  - bet >= 5 才有 Scatter (WHEEL)

⚠️ 注意：Crazy Money 是第三方遊戲 (JILI)，在 iframe 中運行，
   console_listener 完全無法接收遊戲內部資料。
   所有偵測皆透過 OCR 視覺方式完成。
"""

import logging
import time

import numpy as np
import pytest
import yaml

from core.game_utils import (
    check_for_big_win_animation,
    extract_balance,
    navigate_to_game,
    perform_spin_action,
    try_rescue_click,
)

try:
    from core.visual_auditor import VisualAuditor
except ImportError:
    VisualAuditor = None

logger = logging.getLogger(__name__)

# ============================================================
# 共用常數
# ============================================================
MAX_SPINS = 2000         # 安全上限（WHEEL 約每 100 局，但機率浮動大）
SETTLE_TIMEOUT = 15      # 每次 spin 結算最長等待秒數
GAME_ID = "slot015_crazy_money"

# 觸發 Feature Game 時畫面上可能出現的 OCR 關鍵字
FEATURE_KEYWORDS = [
    "wheel", "scatter", "bonus", "congratulations", "congrats",
    "prize", "spin the wheel", "free",
]

# Jackpot 相關 OCR 關鍵字
JP_KEYWORDS = ["mini", "minor", "major", "grand", "jackpot"]

# Respin 相關 OCR 關鍵字
RESPIN_KEYWORDS = ["respin", "re-spin", "re spin"]

# Big Win 相關 OCR 關鍵字
BIG_WIN_KEYWORDS = ["big win", "mega win", "super win", "epic win", "max win"]


def load_game_config():
    """載入 Crazy Money 的遊戲設定"""
    with open("config/games.yaml") as f:
        game_conf = yaml.safe_load(f)["games"][GAME_ID]
        game_conf["id"] = GAME_ID
    return game_conf


def ocr_screen(page, hybrid_locator):
    """截圖 + OCR，回傳 (ocr_results, all_text_lower)"""
    try:
        s = page.screenshot()
        ocr = hybrid_locator.ocr.reader.readtext(s)
        texts = [text.lower() for (_, text, _) in ocr]
        full_text = " ".join(texts)
        return ocr, full_text
    except Exception:
        return [], ""


def screenshots_are_similar(img1_bytes, img2_bytes, threshold=0.95):
    """比較兩張截圖的相似度，判斷畫面是否已穩定"""
    try:
        arr1 = np.frombuffer(img1_bytes, dtype=np.uint8)
        arr2 = np.frombuffer(img2_bytes, dtype=np.uint8)
        if len(arr1) != len(arr2):
            return False
        matches = np.sum(arr1 == arr2)
        similarity = matches / len(arr1)
        return similarity > threshold
    except Exception:
        return False


def check_keywords_on_screen(page, hybrid_locator, keywords):
    """OCR 掃描畫面，檢查是否包含任一關鍵字"""
    _, full_text = ocr_screen(page, hybrid_locator)
    for kw in keywords:
        if kw in full_text:
            logger.info(f"🔍 OCR detected keyword: '{kw}' on screen")
            return kw
    return None


def wait_for_spin_complete(page, settle_timeout=SETTLE_TIMEOUT):
    """
    等待 spin 動畫結束（純視覺方式）。
    連續兩次截圖相似度 > 95% → 判定轉輪停止。
    """
    time.sleep(2)  # 先等動畫開始

    prev_screenshot = page.screenshot()
    start = time.time()

    while time.time() - start < settle_timeout:
        time.sleep(1.0)
        curr_screenshot = page.screenshot()
        if screenshots_are_similar(prev_screenshot, curr_screenshot):
            return True
        prev_screenshot = curr_screenshot

    return False


def handle_feature_sequence(page, hybrid_locator, artifact_handler):
    """
    處理 Feature Game (WHEEL) 流程：
    等待動畫完成 → 點擊跳過 → 回到 Base Game
    """
    logger.info("🎡 Feature Game detected! Capturing and waiting for animation...")
    artifact_handler.capture(page, "feature_triggered", "gameplay", True)

    w = page.viewport_size["width"]
    h = page.viewport_size["height"]

    # 等待 WHEEL 動畫 + 出獎
    time.sleep(10)

    # 反覆點擊直到畫面回到正常（spin 按鈕區域重新出現）
    for attempt in range(15):
        page.mouse.click(w / 2, h / 2)
        time.sleep(2)

        # 檢查是否有 spin 按鈕（代表回到 base game）
        _, full_text = ocr_screen(page, hybrid_locator)
        # Base game 通常會顯示 bet/balance 等文字
        has_bet = any(kw in full_text for kw in ["bet", "balance", "credit", "spin"])
        # 且不再有 wheel/bonus 文字
        has_feature = any(kw in full_text for kw in FEATURE_KEYWORDS)

        if has_bet and not has_feature:
            logger.info(f"✅ Returned to Base Game after feature (attempt {attempt + 1})")
            break
        logger.info(f"  Feature still active, clicking... ({attempt + 1}/15)")

    artifact_handler.capture(page, "feature_completed", "gameplay", True)


# ============================================================
# 測試案例
# ============================================================


class TestSlot015CrazyMoney:
    """Slot015 Crazy Money 目標導向測試（純視覺偵測，不依賴 console log）"""

    @pytest.fixture(autouse=True)
    def _setup_game(
        self,
        login_to_lobby,
        hybrid_locator,
        ui_scanner,
        global_config,
        page,
        console_listener,
        artifact_handler,
    ):
        """共用 setup：登入 → 進入遊戲"""
        self.page = login_to_lobby
        self.hybrid_locator = hybrid_locator
        self.ui_scanner = ui_scanner
        self.console_listener = console_listener
        self.artifact_handler = artifact_handler

        self.game_conf = load_game_config()

        logger.info(f"🎮 Entering game: {self.game_conf['name']}")
        if not navigate_to_game(
            self.page, self.hybrid_locator, self.ui_scanner, self.game_conf, self.artifact_handler
        ):
            pytest.fail("Failed to enter Crazy Money.")

        time.sleep(8)  # 多等一點讓遊戲完全載入

        # 截圖確認遊戲已載入
        self.artifact_handler.capture(self.page, "game_loaded", "setup", True)

        # 偵測初始餘額
        for attempt in range(5):
            ocr, full_text = ocr_screen(self.page, self.hybrid_locator)
            balance = extract_balance(ocr)
            if balance:
                logger.info(f"✅ Initial balance detected: {balance}")
                self._initial_balance = balance
                break
            time.sleep(2)
        else:
            self._initial_balance = []
            logger.warning("⚠️ Could not detect initial balance, continuing anyway")

    def _spin_and_detect(self, round_idx, target_keywords):
        """
        執行一次 spin，等待結算，OCR 掃描是否命中目標關鍵字。

        Returns:
            dict:
                spun (bool): 是否成功執行 spin
                keyword_hit (str|None): 命中的關鍵字
                balance (list): 當前偵測到的餘額
        """
        # 執行 spin
        spin_config = self.game_conf["spin_button"]
        coords, _ = perform_spin_action(
            self.page, self.hybrid_locator, spin_config, GAME_ID, round_idx, self.artifact_handler
        )

        if not coords:
            if not try_rescue_click(self.page, self.hybrid_locator, GAME_ID, self.artifact_handler):
                return {"spun": False, "keyword_hit": None, "balance": []}

        # 等待轉輪停止
        wait_for_spin_complete(self.page)

        # OCR 掃描結果畫面
        ocr, full_text = ocr_screen(self.page, self.hybrid_locator)
        balance = extract_balance(ocr)

        # 檢查目標關鍵字
        hit = None
        for kw in target_keywords:
            if kw in full_text:
                hit = kw
                logger.info(f"🎯 Keyword HIT: '{kw}' detected on screen!")
                self.artifact_handler.capture(
                    self.page, f"keyword_hit_{kw}_{round_idx}", "gameplay", True
                )
                break

        # 也順便檢查 big win 動畫
        for kw in BIG_WIN_KEYWORDS:
            if kw in full_text:
                logger.info(f"🏅 Big Win detected: '{kw}'")
                check_for_big_win_animation(self.page, self.hybrid_locator)
                time.sleep(2)
                break

        return {"spun": True, "keyword_hit": hit, "balance": balance}

    def _play_until_keyword(self, target_keywords, target_name, max_spins=MAX_SPINS):
        """
        核心迴圈：持續 spin 直到 OCR 偵測到目標關鍵字。

        Args:
            target_keywords: OCR 要匹配的關鍵字列表
            target_name: 目標描述
            max_spins: 最大 spin 數
        """
        logger.info(f"🎯 Target: {target_name} (max_spins={max_spins})")
        logger.info(f"   Keywords: {target_keywords}")

        consecutive_failures = 0

        for spin_idx in range(1, max_spins + 1):
            if spin_idx % 50 == 0 or spin_idx <= 3:
                logger.info(f"\n--- 🎰 Spin {spin_idx}/{max_spins} | Target: {target_name} ---")

            result = self._spin_and_detect(spin_idx, target_keywords)

            if not result["spun"]:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    self.artifact_handler.capture(
                        self.page, f"fail_consecutive_{spin_idx}", "failures", True
                    )
                    pytest.fail(f"5 consecutive spin failures at spin {spin_idx}")
                continue

            consecutive_failures = 0

            if result["keyword_hit"]:
                logger.info(
                    f"🎉 Target achieved at spin {spin_idx}: {target_name} "
                    f"(keyword: {result['keyword_hit']})"
                )
                return spin_idx

        pytest.fail(f"Target [{target_name}] not achieved within {max_spins} spins.")

    # --- 測試：觸發 Feature Game (WHEEL) ---
    def test_play_until_feature_game(self):
        """
        意圖：「幫我玩 Crazy Money 直到觸發 Feature Game」
        前置：bet >= 5（解鎖 Scatter）
        偵測：OCR 偵測 WHEEL/SCATTER/BONUS 等關鍵字
        """
        spin_count = self._play_until_keyword(
            target_keywords=FEATURE_KEYWORDS,
            target_name="Feature Game (WHEEL)",
        )

        handle_feature_sequence(
            self.page, self.hybrid_locator, self.artifact_handler
        )

        logger.info(f"📊 Feature Game triggered after {spin_count} spins.")

    # --- 測試：觸發 Respin ---
    def test_play_until_respin(self):
        """
        意圖：「幫我玩 Crazy Money 直到觸發 Respin」
        偵測：OCR 偵測 RESPIN 文字
        """
        spin_count = self._play_until_keyword(
            target_keywords=RESPIN_KEYWORDS,
            target_name="Respin",
        )

        logger.info(f"📊 Respin triggered after {spin_count} spins. Waiting for re-spin...")
        time.sleep(5)
        wait_for_spin_complete(self.page)
        logger.info("✅ Respin completed.")

    # --- 測試：觸發 Jackpot ---
    def test_play_until_jackpot(self):
        """
        意圖：「幫我玩 Crazy Money 直到觸發 Jackpot」
        偵測：OCR 偵測 MINI/MINOR/MAJOR/GRAND/JACKPOT 文字
        """
        spin_count = self._play_until_keyword(
            target_keywords=JP_KEYWORDS,
            target_name="Jackpot",
        )

        logger.info(f"📊 Jackpot triggered after {spin_count} spins.")
        time.sleep(8)

        # 點擊跳過 JP 動畫
        w = self.page.viewport_size["width"]
        h = self.page.viewport_size["height"]
        for _ in range(5):
            self.page.mouse.click(w / 2, h / 2)
            time.sleep(2)

    # --- 測試：觸發 Big Win 表演 ---
    def test_play_until_big_win(self):
        """
        意圖：「幫我玩 Crazy Money 直到觸發 Big Win」
        偵測：OCR 偵測 BIG WIN / MEGA WIN / SUPER WIN / EPIC WIN
        """
        spin_count = self._play_until_keyword(
            target_keywords=BIG_WIN_KEYWORDS,
            target_name="Big Win Animation",
        )

        check_for_big_win_animation(self.page, self.hybrid_locator)
        time.sleep(3)

        logger.info(f"📊 Big Win triggered after {spin_count} spins.")
