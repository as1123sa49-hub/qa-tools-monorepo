import logging
import time

import pytest
import yaml

from core.game_utils import (
    check_for_big_win_animation,
    extract_balance,
    navigate_to_game,
    perform_spin_action,
    try_rescue_click,
    verify_final_balance_integrity,
)

try:
    from core.visual_auditor import VisualAuditor
except ImportError:
    VisualAuditor = None

logger = logging.getLogger(__name__)


def play_free_game_sequence_sleep(
    page, console_listener, hybrid_locator, total_spins, artifact_handler
):
    """🔥 God Mode: Sleep Skip (Continuous 專屬邏輯)"""
    SECONDS_PER_SPIN = 3.0
    duration = total_spins * SECONDS_PER_SPIN
    logger.info(f"🎰 GOD MODE: FG Detected ({total_spins} spins). Sleeping {duration}s...")

    w = page.viewport_size["width"]
    h = page.viewport_size["height"]
    page.mouse.click(w / 2, h / 2)
    time.sleep(2)

    time.sleep(duration)

    logger.info("⏰ Waking up... Verifying Base Game status...")
    for _ in range(10):
        console_listener.clear()
        time.sleep(1.5)
        mode = console_listener.get_hint("game_mode")
        is_fg = console_listener.get_hint("is_free_game")
        if (mode is not None and int(mode) != 1) or (is_fg is True):
            logger.info("💤 Log says still in FG. Sleeping 2s more...")
            continue
        break

    logger.info("⏩ Closing Total Win Popup...")
    page.mouse.click(w / 2, h / 2)
    time.sleep(3)

    final_log_bal = console_listener.get_hint("current_balance")
    if final_log_bal:
        verify_final_balance_integrity(
            page, hybrid_locator, final_log_bal, artifact_handler, round_idx="FG_End"
        )


@pytest.mark.parametrize("game_id", ["prosperous_tiger", "fruit_rush"])
@pytest.mark.parametrize("spin_count", [10])
def test_continuous_betting(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    spin_count,
    page,
    console_listener,
    artifact_handler,
):
    """連續下注測試 (完整版)"""
    page = login_to_lobby

    with open("config/games.yaml") as f:
        game_conf = yaml.safe_load(f)["games"][game_id]
        game_conf["id"] = game_id

    logger.info(f"🎮 Test Start: {game_conf['name']} (Target Spins: {spin_count})")

    # --- Step 2: 進入遊戲 ---
    if not navigate_to_game(page, hybrid_locator, ui_scanner, game_conf, artifact_handler):
        pytest.fail("Failed to enter game.")

    time.sleep(5)

    # Pre-balance Check with Retry
    before_balance_list = []
    for attempt in range(5):
        s = page.screenshot()
        ocr = hybrid_locator.ocr.reader.readtext(s)
        before_balance_list = extract_balance(ocr)
        if before_balance_list:
            logger.info(f"✅ Initial balance detected: {before_balance_list}")
            break
        logger.warning(f"⚠️ Balance not detected on attempt {attempt+1}, retrying...")
        time.sleep(1)

    if not before_balance_list:
        artifact_handler.capture(page, "fail_pre_balance", "failures", True)
        logger.error("Critical: No balance detected before first spin!")

    # --- Step 3: Loop ---
    spin_config = game_conf["spin_button"]
    failed_spins = 0
    try:
        page.evaluate("window.debug = true;")
    except:
        pass

    current_spin = 0
    consecutive_retries = 0

    while current_spin < spin_count:
        display_round = current_spin + 1
        logger.info(f"\n--- 🎰 Round {display_round}/{spin_count} Start ---")

        console_listener.clear()
        time.sleep(1)

        is_fg_mode = console_listener.get_hint("is_free_game", False)
        action_performed = False
        coords = None

        if is_fg_mode:
            logger.warning(f"⚠️ Round {display_round}: Log says FG active. Entering monitor...")
        else:
            before_balance_list = []
            try:
                s = page.screenshot()
                ocr = hybrid_locator.ocr.reader.readtext(s)
                before_balance_list = extract_balance(ocr)
            except:
                pass

            coords, _ = perform_spin_action(
                page, hybrid_locator, spin_config, game_id, display_round, artifact_handler
            )

            if coords:
                action_performed = True
            elif try_rescue_click(page, hybrid_locator, game_id, artifact_handler):
                logger.info("✅ Rescue executed.")
            else:
                artifact_handler.capture(
                    page, f"fail_spin_missing_{display_round}", "failures", True
                )
                pytest.fail("Critical: Spin button missing.")

        # Monitor
        start_time = time.time()
        settled = False
        target_balance = None
        log_arrival_time = 0
        fg_awarded = 0
        visual_bypass = False

        while time.time() - start_time < 30:
            time.sleep(0.5)

            if target_balance is None:
                val = console_listener.get_hint("current_balance")
                if val:
                    target_balance = float(val)
                    log_arrival_time = time.time()

            fg = console_listener.get_hint("fg_total", 0)
            if fg > 0:
                fg_awarded = fg
                break

            screen_nums = []
            try:
                s = page.screenshot()
                ocr = hybrid_locator.ocr.reader.readtext(s)
                screen_nums = extract_balance(ocr)
            except:
                pass

            if target_balance and any(abs(n - target_balance) < 0.1 for n in screen_nums):
                logger.info(f"✅ Settled (Log Match: {target_balance}).")
                settled = True
                break

            if time.time() - log_arrival_time > 5 and target_balance:
                page.mouse.click(page.viewport_size["width"] / 2, page.viewport_size["height"] / 2)

            if screen_nums and before_balance_list and screen_nums != before_balance_list:
                logger.info("⏩ Visual Change Detected (Breaking wait).")
                visual_bypass = True
                break

        # Decision
        if fg_awarded > 0:
            play_free_game_sequence_sleep(
                page, console_listener, hybrid_locator, fg_awarded, artifact_handler
            )
            current_spin += 1
            consecutive_retries = 0
            continue

        if settled:
            check_for_big_win_animation(page, hybrid_locator)
            current_spin += 1
            consecutive_retries = 0
            logger.info(f"👉 Round {current_spin} Counted (Settled).")
            if target_balance:
                verify_final_balance_integrity(
                    page, hybrid_locator, target_balance, artifact_handler, display_round
                )

        elif visual_bypass:
            if action_performed:
                current_spin += 1
                consecutive_retries = 0
                logger.info(f"👉 Round {current_spin} Counted (Visual Change).")
            else:
                consecutive_retries += 1
                logger.warning(f"⚠️ Visual bypass without action ({consecutive_retries}/3).")
                if consecutive_retries >= 3:
                    logger.error("🆘 Too many retries. Forcing Rescue Click & Count...")
                    try_rescue_click(page, hybrid_locator, game_id, artifact_handler)
                    current_spin += 1
                    consecutive_retries = 0

        elif not action_performed:
            consecutive_retries += 1
            logger.warning(f"⚠️ Wait cycle ({consecutive_retries}/3)...")
            if consecutive_retries >= 3:
                logger.error("🆘 No action/change for 3 cycles. Forcing Rescue...")
                try_rescue_click(page, hybrid_locator, game_id, artifact_handler)
                current_spin += 1
                consecutive_retries = 0

        else:
            logger.error(f"❌ Round {display_round} Failed!")
            artifact_handler.capture(page, f"fail_round_{display_round}", "failures", True)

            if VisualAuditor:
                is_valid, reason = VisualAuditor.check_screen_validity(page.screenshot())
                if not is_valid:
                    logger.error(f"💀 Visual Defect: {reason}")

            failed_spins += 1
            current_spin += 1

    logger.info(f"\n📊 Summary: {spin_count - failed_spins}/{spin_count} OK.")
    if failed_spins > 0:
        pytest.fail(f"Test failed with {failed_spins} errors.")
