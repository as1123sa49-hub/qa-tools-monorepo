import logging
import time

import pytest
import yaml

from core.balance_audit import (
    audit_console_summary_key,
    audit_in_game_b1_key,
    audit_lobby_b0_key,
    capture_lobby_wallet_b0,
    is_plausible_ingame_balance,
    log_footer_primary_read_failure,
    ocr_spin_started_primary,
    primary_balance_spin_delta,
    read_in_game_fc_footer_strip,
    read_in_game_jdb_footer_strip,
    read_in_game_footer_primary,
    resolve_effective_spin_bet,
    resolve_spin_delta_min_bet,
    run_post_spin_lobby_audit,
    return_to_lobby,
    wallet_spin_formula_ok,
)
from core.comboburst_lobby import navigate_via_comboburst_portal
from core.env_config import ENTRY_MODE_COMBOBURST_PORTAL, ENTRY_MODE_JC_LOBBY, get_comboburst_config, resolve_entry_mode
from core.fail_codes import (
    FAIL_AUDIT,
    FAIL_ENTRY_NETWORK,
    FAIL_ENTRY_UNKNOWN,
    FAIL_PRE_BALANCE,
    FAIL_SETTLE,
    FAIL_SPIN_ACK,
    FAIL_SPIN_NETWORK,
    FAIL_TIMEOUT,
    format_fail,
)
from core.run_evidence import (
    enrich_balances_from_footer,
    init_run_evidence,
    record_console_settlement_to_evidence,
    record_footer_strip_to_evidence,
    set_audit_fields,
    set_balance_fields,
    write_run_evidence,
)
from core.game_frame_utils import enable_game_debug
from core.log_format import log_phase, log_retry
from core.game_utils import (
    SPIN_MULTI_CLICK_TIMEOUT_SEC,
    dismiss_extra_bet_teaching_overlay_if_present,
    extract_balance,
    get_entry_error_reason,
    navigate_to_game,
    perform_spin_action,
    resolve_spin_button_config,
    verify_final_balance_integrity,
    verify_spin_settlement,
    _overlay_vlm_fallback_allowed,
)

try:
    from core.visual_auditor import VisualAuditor
except ImportError:
    VisualAuditor = None

logger = logging.getLogger(__name__)

GAMES_YAML_PATH = "config/games.yaml"


def _load_provider_game_ids(provider_name: str, category: str | None = None) -> list[str]:
    with open(GAMES_YAML_PATH, encoding="utf-8") as f:
        all_games = yaml.safe_load(f) or {}
    provider_games = all_games.get(provider_name, {})
    ids: list[str] = []
    for game_id, cfg in provider_games.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("betting_test") is False:
            continue
        if category and cfg.get("category") != category:
            continue
        ids.append(game_id)
    return ids


def _game_display_name(game_id: str) -> str:
    """Pytest node id label (human name); parameter remains game_id."""
    try:
        with open(GAMES_YAML_PATH, encoding="utf-8") as f:
            all_games = yaml.safe_load(f) or {}
        for provider_games in all_games.values():
            if isinstance(provider_games, dict) and game_id in provider_games:
                entry = provider_games[game_id]
                if isinstance(entry, dict):
                    name = (entry.get("name") or "").strip()
                    if name:
                        # Avoid brackets which break pytest node ids.
                        return name.replace("[", "(").replace("]", ")")
    except Exception:
        pass
    return str(game_id)


COMBO_GAMES = _load_provider_game_ids("COMBO", "slot")
FC_GAMES = _load_provider_game_ids("FC", "slot")
JDB_GAMES = _load_provider_game_ids("JDB", "slot")
if not JDB_GAMES:
    JDB_GAMES = _load_provider_game_ids("JDB")
JILI_GAMES = ["JILI-FISH-001", "JILI-FISH-002", "JILI-FISH-003", "JILI-FISH-004", "JILI-FISH-005", "JILI-FISH-006", "JILI-FISH-007", "JILI-FISH-008", "JILI-FISH-009", "JILI-FISH-011", "JILI-FISH-012", "JILI-FISH-013", "JILI-SLOT-002", "JILI-SLOT-003", "JILI-SLOT-004", "JILI-SLOT-005", "JILI-SLOT-006", "JILI-SLOT-007", "JILI-SLOT-008", "JILI-SLOT-009", "JILI-SLOT-010", "JILI-SLOT-012", "JILI-SLOT-013", "JILI-SLOT-014", "JILI-SLOT-015", "JILI-SLOT-016", "JILI-SLOT-017", "JILI-SLOT-018", "JILI-SLOT-019", "JILI-SLOT-020", "JILI-SLOT-021", "JILI-SLOT-022", "JILI-SLOT-023", "JILI-SLOT-024", "JILI-SLOT-025", "JILI-SLOT-026", "JILI-SLOT-027", "JILI-SLOT-028", "JILI-SLOT-029", "JILI-SLOT-030", "JILI-SLOT-031", "JILI-SLOT-037", "JILI-SLOT-038", "JILI-SLOT-039", "JILI-SLOT-040", "JILI-SLOT-041", "JILI-SLOT-042", "JILI-SLOT-043", "JILI-SLOT-044", "JILI-SLOT-045", "JILI-SLOT-046", "JILI-SLOT-047", "JILI-SLOT-048", "JILI-SLOT-049", "JILI-SLOT-050", "JILI-SLOT-051", "JILI-SLOT-052", "JILI-SLOT-053", "JILI-SLOT-054", "JILI-SLOT-056", "JILI-SLOT-057", "JILI-SLOT-058", "JILI-SLOT-059", "JILI-SLOT-060", "JILI-SLOT-061", "JILI-SLOT-062", "JILI-SLOT-063", "JILI-SLOT-070", "JILI-SLOT-071", "JILI-SLOT-072", "JILI-SLOT-073", "JILI-SLOT-074", "JILI-SLOT-075", "JILI-SLOT-076", "JILI-SLOT-077", "JILI-SLOT-078", "JILI-SLOT-079", "JILI-SLOT-080", "JILI-SLOT-081", "JILI-SLOT-082", "JILI-SLOT-083", "JILI-SLOT-084", "JILI-SLOT-085", "JILI-SLOT-086", "JILI-SLOT-087", "JILI-SLOT-088", "JILI-SLOT-089", "JILI-SLOT-090", "JILI-SLOT-091", "JILI-SLOT-092", "JILI-SLOT-093", "JILI-SLOT-094", "JILI-SLOT-095", "JILI-SLOT-096", "JILI-SLOT-097", "JILI-SLOT-098", "JILI-SLOT-099", "JILI-SLOT-100", "JILI-SLOT-101", "JILI-SLOT-102", "JILI-SLOT-103", "JILI-SLOT-104", "JILI-SLOT-105", "JILI-SLOT-106", "JILI-SLOT-107", "JILI-SLOT-108", "JILI-SLOT-109", "JILI-SLOT-110", "JILI-SLOT-111", "JILI-SLOT-112", "JILI-SLOT-113", "JILI-SLOT-114", "JILI-SLOT-115", "JILI-SLOT-116", "JILI-SLOT-117", "JILI-SLOT-118", "JILI-SLOT-121", "JILI-SLOT-123", "JILI-SLOT-124", "JILI-SLOT-126", "JILI-SLOT-127", "JILI-SLOT-131", "JILI-SLOT-134"]
PG_GAMES = ["PG-SLOT-041", "PG-SLOT-058", "PG-SLOT-065", "PG-SLOT-075", "PG-SLOT-101", "PG-SLOT-105", "PG-SLOT-135", "PG-SLOT-136", "PG-SLOT-138", "PG-SLOT-143", "PG-SLOT-144", "PG-SLOT-146", "PG-SLOT-150", "PG-SLOT-151", "PG-SLOT-153"]
PP_GAMES = ["PP-SLOT-082", "PP-SLOT-464", "PP-SLOT-586"]
SEXYBCRT_GAMES = ["MX-LIVE-001-C08", "MX-LIVE-001-C09", "MX-LIVE-001-C10", "MX-LIVE-016-131"]

SPIN_SETTLE_TIMEOUT_SEC = 20
FG_SETTLE_TIMEOUT_SEC = 180
VISUAL_SETTLE_TIMEOUT_SEC = 30
# JDB footer OCR is slow; allow more wall-clock for settle polls.
JDB_VISUAL_SETTLE_TIMEOUT_SEC = 90

# Late spin-ack confirm: the reels/WIN animation can outlast the click ack window
# so the footer balance change lands after perform_spin_action gave up. Re-read a
# few times before declaring "no spin" to avoid false negatives (e.g. FC War Of The
# Universe). This only rescues real spins — it still relies on balance delta / formula.
SPIN_LATE_CONFIRM_ATTEMPTS = 3
SPIN_LATE_CONFIRM_POLL_SEC = 1.5

# Settled balance (B1) must be stable across two reads before it is stored for the
# cross-venue audit. A single animating/blurred frame can misread one digit (e.g. FC
# Queen of Inca 399.25 → 394.25), which then fails the lobby audit for a phantom loss.
B1_CONFIRM_EPS = 0.05

ERROR_KWS = [
    "system error",
    "error occurred",
    "something went wrong",
    "network error",
    "network anomalies",
    "network anomal",
    "your network anomalies",
    "(20999)",
    "20999",
]
DISMISS_KWS = ["ok", "close", "confirm", "retry", "dismiss", "reload", "yes"]
NETWORK_SPIN_KWS = (
    "network error",
    "network anomalies",
    "network anomal",
    "your network anomalies",
    "(20999)",
    "20999",
)


def _is_network_spin_error(all_text: str) -> bool:
    return any(k in all_text for k in NETWORK_SPIN_KWS)


def _pytest_fail(
    artifact_handler,
    code: str,
    message: str,
    *,
    game_conf=None,
    settle_path: str | None = None,
) -> None:
    """Fail with ``[CODE]`` prefix, evidence JSON, and one-line numeric summary."""
    from core.run_evidence import format_evidence_summary

    if game_conf is not None:
        summary = format_evidence_summary(game_conf, code)
        if summary:
            message = f"{message} | {summary}"
        write_run_evidence(
            artifact_handler,
            game_conf,
            "fail",
            code,
            settle_path=settle_path,
        )
    if artifact_handler is not None:
        artifact_handler.set_fail_code(code)
    pytest.fail(format_fail(code, message))


def _dismiss_error_dialog(page, ocr_check, s_check, test_errors, artifact_handler, error_kws, dismiss_kws):
    logger.warning("⚠️ Error dialog detected during spin wait. Dismissing...")
    artifact_handler.capture(page, "error_dialog_during_spin", "failures", True)
    matched_kw = next(k for k in error_kws if k in " ".join([r[1].lower() for r in ocr_check]))
    test_errors.append(f"System error dialog detected during spin (keyword: '{matched_kw}')")
    dismiss = [r for r in ocr_check if any(x in r[1].lower() for x in dismiss_kws)]
    # Prefer Reload over generic OK when both exist (FC network anomalies dialog).
    reload_btns = [r for r in dismiss if "reload" in r[1].lower()]
    chosen = reload_btns[0] if reload_btns else (dismiss[0] if dismiss else None)
    if chosen is not None:
        import io as _io

        from PIL import Image as _Image

        _img = _Image.open(_io.BytesIO(s_check))
        _dpr = _img.width / page.viewport_size["width"]
        _bb = chosen[0]
        page.mouse.click(
            (_bb[0][0] + _bb[2][0]) / 2 / _dpr,
            (_bb[0][1] + _bb[2][1]) / 2 / _dpr,
        )
    else:
        page.mouse.click(
            page.viewport_size["width"] / 2,
            page.viewport_size["height"] / 2,
        )
    time.sleep(1)


def _poll_error_dialog(page, hybrid_locator, test_errors, artifact_handler):
    """Return 'network' | True | False — network means abort settle / skip lobby audit."""
    s_check = page.screenshot()
    ocr_check = hybrid_locator.ocr.reader.readtext(s_check)
    all_text_check = " ".join([r[1].lower() for r in ocr_check])
    if not any(k in all_text_check for k in ERROR_KWS):
        return False
    is_network = _is_network_spin_error(all_text_check)
    _dismiss_error_dialog(
        page, ocr_check, s_check, test_errors, artifact_handler, ERROR_KWS, DISMISS_KWS
    )
    return "network" if is_network else True


def _wait_for_console_balance(console_listener, timeout_sec: float = 5.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if console_listener.get_hint("current_balance") is not None:
            return True
        time.sleep(0.5)
    return False


def _make_spin_started_check(console_listener, page=None, hybrid_locator=None, before_primary=None, game_conf=None):
    """Return callback for perform_spin_action multi-point retry (COMBO console)."""
    last_visual_check = 0.0
    from core.game_utils import (
        FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC,
        LAYOUT_PORTRAIT,
        SPIN_MULTI_CLICK_TIMEOUT_SEC,
        _RESOLVED_LAYOUT_KEY,
        _game_config_is_fc,
        _game_config_is_jdb,
        use_fc_portrait_footer_strip,
        use_jdb_portrait_footer_strip,
    )

    resolved = None
    if game_conf:
        resolved = game_conf.get(_RESOLVED_LAYOUT_KEY) or game_conf.get("layout")
    visual_strip = use_fc_portrait_footer_strip(game_conf, page, hybrid_locator) or (
        use_jdb_portrait_footer_strip(game_conf, page, hybrid_locator)
    ) or (
        (_game_config_is_fc(game_conf) or _game_config_is_jdb(game_conf))
        and resolved == LAYOUT_PORTRAIT
    )
    ocr_interval = 0.35 if visual_strip else 0.5
    default_timeout = (
        FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC if visual_strip else SPIN_MULTI_CLICK_TIMEOUT_SEC
    )

    def check(timeout_sec: float | None = None) -> bool:
        nonlocal last_visual_check
        window = default_timeout if timeout_sec is None else timeout_sec
        deadline = time.time() + window
        while time.time() < deadline:
            if console_listener.get_hint("spin_response_ok"):
                return True
            if console_listener.has_spin_acknowledged():
                return True
            if console_listener.get_hint("balance_after_bet") is not None:
                return True
            if console_listener.get_hint("spin_triggered") or console_listener.has_spin_acknowledged():
                return True
            if page and hybrid_locator and before_primary is not None:
                if time.time() - last_visual_check >= ocr_interval:
                    last_visual_check = time.time()
                    if ocr_spin_started_primary(
                        page, hybrid_locator, before_primary, game_conf
                    ):
                        console_listener.note_visual_spin_started()
                        return True
            time.sleep(0.15)
        return False

    return check


def _wait_combo_settlement(
    page,
    hybrid_locator,
    console_listener,
    test_errors,
    artifact_handler,
    game_conf=None,
    before_primary=None,
):
    """COMBO: console log + B0 - Bet + Win formula verification."""
    game_conf = game_conf or {}
    start = time.time()
    timeout_sec = SPIN_SETTLE_TIMEOUT_SEC

    while time.time() - start < timeout_sec:
        if console_listener.get_hint("in_free_game"):
            timeout_sec = max(timeout_sec, FG_SETTLE_TIMEOUT_SEC)

        time.sleep(1)

        poll = _poll_error_dialog(page, hybrid_locator, test_errors, artifact_handler)
        if poll == "network":
            artifact_handler.capture(page, "fail_spin_network", "failures", True)
            _pytest_fail(
                artifact_handler,
                FAIL_SPIN_NETWORK,
                "Network anomalies during spin settlement; skipping lobby audit",
                game_conf=game_conf,
                settle_path="console",
            )
        if poll:
            continue

        if console_listener.is_spin_settled():
            summary = console_listener.get_settlement_summary()
            logger.info(f"📊 Settlement: {summary}")
            ok, reason, _ = verify_spin_settlement(console_listener)
            if not ok:
                artifact_handler.capture(page, "fail_settlement", "failures", True)
                _pytest_fail(
                    artifact_handler,
                    FAIL_SETTLE,
                    f"Spin settlement failed: {reason}\nSummary: {summary}",
                    game_conf=game_conf,
                    settle_path="console",
                )

            artifact_handler.capture(page, "success_settlement", "gameplay", True)
            summary = console_listener.get_settlement_summary()
            game_conf[audit_console_summary_key()] = summary
            b1 = console_listener.get_hint("balance_after_settle")
            balance_ok = verify_final_balance_integrity(
                page,
                hybrid_locator,
                b1,
                artifact_handler,
                "SingleBet",
            )
            if not balance_ok:
                test_errors.append("Balance OCR audit failed (SingleBet)")
            if test_errors:
                _pytest_fail(
                    artifact_handler,
                    FAIL_SETTLE,
                    "Test completed with errors:\n" + "\n".join(f"  - {e}" for e in test_errors),
                    game_conf=game_conf,
                    settle_path="console",
                )
            logger.info("✅ Success: spin settled and balance formula verified.")
            b1 = console_listener.get_hint("balance_after_settle")
            record_console_settlement_to_evidence(
                game_conf, console_listener.get_settlement_summary()
            )
            if b1 is not None:
                game_conf[audit_in_game_b1_key()] = float(b1)
            else:
                footer_b1 = read_in_game_footer_primary(page, hybrid_locator, game_conf)
                if footer_b1 is not None:
                    game_conf[audit_in_game_b1_key()] = footer_b1
            return

        if console_listener.get_hint("visual_spin_started") and before_primary is not None:
            try:
                after_primary = read_in_game_footer_primary(page, hybrid_locator, game_conf)
                delta_min = resolve_spin_delta_min_bet(None, game_conf)
                if primary_balance_spin_delta(
                    before_primary, after_primary, min_bet=delta_min
                ) is not None:
                    logger.info("✅ Success (visual settlement: footer primary balance changed).")
                    artifact_handler.capture(page, "success_visual_combo", "gameplay", True)
                    if after_primary is not None:
                        game_conf[audit_in_game_b1_key()] = after_primary
                    if test_errors:
                        _pytest_fail(
                            artifact_handler,
                            FAIL_SETTLE,
                            "Test completed with errors:\n"
                            + "\n".join(f"  - {e}" for e in test_errors),
                            game_conf=game_conf,
                            settle_path="console",
                        )
                    return
            except Exception:
                pass

    artifact_handler.capture(page, "fail_timeout", "failures", True)
    if VisualAuditor:
        is_valid, reason = VisualAuditor.check_screen_validity(page.screenshot())
        if not is_valid:
            logger.error(f"Visual Defect: {reason}")
            test_errors.append(f"Visual defect at timeout: {reason}")

    summary = console_listener.get_settlement_summary()
    timeout_msg = (
        f"Timeout waiting for spin settlement ({timeout_sec}s). "
        f"Last state: triggered={console_listener.get_hint('spin_triggered')}, "
        f"response_ok={console_listener.get_hint('spin_response_ok')}, "
        f"has_response={console_listener.get_hint('has_spin_response')}, "
        f"in_fg={console_listener.get_hint('in_free_game')}, "
        f"settled={console_listener.get_hint('spin_settled')}, "
        f"summary={summary}"
    )
    if test_errors:
        timeout_msg = timeout_msg + "\n" + "\n".join(f"  - {e}" for e in test_errors)
    _pytest_fail(
        artifact_handler,
        FAIL_TIMEOUT,
        timeout_msg,
        game_conf=game_conf,
        settle_path="console",
    )


def _wait_visual_settlement(
    page,
    hybrid_locator,
    console_listener,
    before_balance_list,
    game_conf,
    test_errors,
    artifact_handler,
):
    """Non-COMBO providers: legacy OCR / log match settlement."""
    from core.game_utils import _game_config_is_jdb

    is_jdb = _game_config_is_jdb(game_conf)
    settle_timeout = (
        JDB_VISUAL_SETTLE_TIMEOUT_SEC if is_jdb else VISUAL_SETTLE_TIMEOUT_SEC
    )
    start = time.time()

    while time.time() - start < settle_timeout:
        time.sleep(0.5 if is_jdb else 1)

        poll = _poll_error_dialog(page, hybrid_locator, test_errors, artifact_handler)
        if poll == "network":
            artifact_handler.capture(page, "fail_spin_network", "failures", True)
            _pytest_fail(
                artifact_handler,
                FAIL_SPIN_NETWORK,
                "Network anomalies during spin settlement; skipping lobby audit",
                game_conf=game_conf,
                settle_path="visual",
            )
        if poll:
            continue

        target = None
        val = console_listener.get_hint("current_balance")
        if val:
            target = float(val)

        # JDB: skip full-frame OCR each poll (footer strip already screenshots).
        s_post = None
        ocr_post = None
        curr_nums: list[float] = []
        if target is not None or not is_jdb:
            s_post = page.screenshot()
            ocr_post = hybrid_locator.ocr.reader.readtext(s_post)
            curr_nums = extract_balance(ocr_post)

        if target and any(abs(n - target) < 0.1 for n in curr_nums):
            logger.info("✅ Success (Log Match).")
            artifact_handler.capture(page, "success_log", "gameplay", True)
            balance_ok = verify_final_balance_integrity(
                page,
                hybrid_locator,
                target,
                artifact_handler,
                "SingleBet",
            )
            if not balance_ok:
                test_errors.append("Balance audit failed (SingleBet)")
            if test_errors:
                _pytest_fail(
                    artifact_handler,
                    FAIL_SETTLE,
                    "Test completed with errors:\n" + "\n".join(f"  - {e}" for e in test_errors),
                    game_conf=game_conf,
                    settle_path="visual",
                )
            return

        # Avoid "pass but didn't really spin": delta and/or B0 - bet + win.
        # Unknown / n/a / 0 bet must NOT fall back to fixed DEFAULT 2.5 as a fake stake.
        if before_balance_list and len(before_balance_list) == 1 and before_balance_list[0] is not None:
            before_primary = before_balance_list[0]
            strip = None if is_jdb else read_in_game_fc_footer_strip(
                page, hybrid_locator, game_conf
            )
            jdb_strip = None
            if strip is None:
                jdb_strip = read_in_game_jdb_footer_strip(page, hybrid_locator, game_conf)
            after_primary = (
                strip.balance
                if strip
                else (jdb_strip.balance if jdb_strip else None)
            )
            if after_primary is None and not is_jdb:
                after_primary = read_in_game_footer_primary(page, hybrid_locator, game_conf)
            strip_bet = (
                strip.total_bets
                if strip
                else (jdb_strip.bet if jdb_strip else None)
            )
            strip_win = (
                strip.win if strip else (jdb_strip.win if jdb_strip else None)
            )
            delta_min = resolve_spin_delta_min_bet(strip_bet, game_conf)
            settled = primary_balance_spin_delta(
                before_primary, after_primary, min_bet=delta_min
            ) is not None
            if not settled and after_primary is not None:
                bet = resolve_effective_spin_bet(strip_bet, game_conf)
                if bet is not None:
                    settled = wallet_spin_formula_ok(
                        before_primary, after_primary, bet, strip_win
                    )
            # Reel assist is only for post-click short window — never veto settle here.
            if settled:
                # Double-confirm B1: require a second footer read to agree before
                # accepting the settled balance, so one misread frame does not get
                # stored as the audit B1 (Queen of Inca-style digit error).
                confirm_primary = read_in_game_footer_primary(
                    page, hybrid_locator, game_conf
                )
                if (
                    after_primary is not None
                    and confirm_primary is not None
                    and abs(confirm_primary - after_primary) > B1_CONFIRM_EPS
                ):
                    logger.warning(
                        "⚠️ Settled balance unstable across reads (%.2f vs %.2f); "
                        "re-polling before accepting B1.",
                        after_primary,
                        confirm_primary,
                    )
                    continue
                if confirm_primary is not None:
                    after_primary = confirm_primary
                logger.info("✅ Success (Visual Change: balance delta / wallet formula).")
                artifact_handler.capture(page, "success_visual", "gameplay", True)
                if after_primary is not None and is_plausible_ingame_balance(
                    after_primary, game_conf.get(audit_lobby_b0_key())
                ):
                    game_conf[audit_in_game_b1_key()] = after_primary
                record_footer_strip_to_evidence(
                    game_conf,
                    strip if strip else jdb_strip,
                )
                if test_errors:
                    _pytest_fail(
                        artifact_handler,
                        FAIL_SETTLE,
                        "Test completed with errors:\n"
                        + "\n".join(f"  - {e}" for e in test_errors),
                        game_conf=game_conf,
                        settle_path="visual",
                    )
                return

    artifact_handler.capture(page, "fail_timeout", "failures", True)
    if VisualAuditor:
        is_valid, reason = VisualAuditor.check_screen_validity(page.screenshot())
        if not is_valid:
            logger.error(f"Visual Defect: {reason}")
            test_errors.append(f"Visual defect at timeout: {reason}")

    timeout_msg = "Timeout waiting for settlement"
    if test_errors:
        timeout_msg = timeout_msg + "\n" + "\n".join(f"  - {e}" for e in test_errors)
    _pytest_fail(
        artifact_handler,
        FAIL_TIMEOUT,
        timeout_msg,
        game_conf=game_conf,
        settle_path="visual",
    )


def _run_game_betting(
    provider_name,
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
    settlement_mode: str = "visual",
):
    page = login_to_lobby
    with open(GAMES_YAML_PATH, encoding="utf-8") as f:
        game_conf = yaml.safe_load(f)[provider_name][game_id]
        game_conf["id"] = game_id
        game_conf["provider_key"] = provider_name

    logger.info(f"🎮 Test Start: {game_conf['name']} ({game_id})")
    init_run_evidence(
        game_conf,
        provider=provider_name,
        game_id=game_id,
        game_name=game_conf["name"],
    )
    test_errors: list[str] = []
    entry_mode = resolve_entry_mode(global_config, game_conf)

    log_phase("ENTRY", f"Enter game {game_conf['name']}")
    entered = False
    if provider_name == "COMBO" and entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        logger.info(f"🚪 Entry: comboburst_portal (env={global_config.get('_env', 'uat')})")
        entered = navigate_via_comboburst_portal(
            page,
            game_conf,
            get_comboburst_config(global_config),
            hybrid_locator,
            artifact_handler,
            global_config=global_config,
        )
    else:
        # JC lobby sometimes redirects / fails to load Unity due to transient popups.
        # Retry entering the game once before giving up.
        for enter_try in range(2):
            if entry_mode == ENTRY_MODE_JC_LOBBY and enter_try == 0:
                capture_lobby_wallet_b0(
                    page, hybrid_locator, global_config, entry_mode, game_conf
                )
                b0 = game_conf.get(audit_lobby_b0_key())
                if b0 is not None:
                    set_balance_fields(game_conf, lobby_b0=float(b0))

            entered = navigate_to_game(
                page, hybrid_locator, ui_scanner, game_conf, artifact_handler
            )
            if entered:
                break

            logger.warning(
                f"⚠️ Failed to enter game (try {enter_try + 1}/2); returning to lobby and retrying..."
            )
            return_to_lobby(page, global_config, entry_mode)
            time.sleep(3)

    if not entered:
        entry_reason = get_entry_error_reason(game_conf)
        if entry_reason and "network" in str(entry_reason).lower():
            _pytest_fail(
                artifact_handler,
                FAIL_ENTRY_NETWORK,
                f"Failed to enter game ({entry_reason})",
                game_conf=game_conf,
            )
        if entry_reason:
            _pytest_fail(
                artifact_handler,
                FAIL_ENTRY_UNKNOWN,
                f"Failed to enter game ({entry_reason})",
                game_conf=game_conf,
            )
        _pytest_fail(
            artifact_handler,
            FAIL_ENTRY_UNKNOWN,
            "Failed to enter game",
            game_conf=game_conf,
        )

    page = game_conf.get("_active_game_page", page)

    log_phase("SPIN", "Balance check & spin")
    console_listener.clear()
    game_host = None
    if provider_name == "COMBO" and entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        game_host = get_comboburst_config(global_config).get("game_host")
    if settlement_mode == "console":
        debug_count = enable_game_debug(page, game_host)
        frame_count = console_listener.refresh_frames()
        logger.info(
            "🔧 Game debug: window.debug in %s context(s), %s new frame listener(s)",
            debug_count,
            frame_count,
        )
        if not _wait_for_console_balance(console_listener, timeout_sec=8.0):
            logger.warning("⚠️ No console balance before spin; B0 will be inferred from spin events.")

    # Pre-balance: footer primary only (avoids jackpot/bet OCR noise).
    # Side panel is collapsed only after a balance miss (see read_in_game_footer_primary).
    before_primary = None
    for attempt in range(5):
        before_primary = read_in_game_footer_primary(page, hybrid_locator, game_conf)
        if before_primary is not None:
            logger.info(f"✅ Initial footer primary balance: {before_primary}")
            set_balance_fields(game_conf, before_primary=float(before_primary))
            enrich_balances_from_footer(page, hybrid_locator, game_conf)
            break
        log_retry(
            logger,
            attempt + 1,
            5,
            f"Footer balance not detected on attempt {attempt + 1}, retrying...",
        )
        dismiss_extra_bet_teaching_overlay_if_present(
            page,
            hybrid_locator,
            artifact_handler,
            game_config=game_conf,
            tag=f"pre_balance_retry{attempt + 1}",
            use_vlm_fallback=False,
        )
        time.sleep(1)

    if before_primary is None:
        log_footer_primary_read_failure(page, hybrid_locator, game_conf)
        artifact_handler.capture(page, "fail_pre_balance", "failures", True)
        _pytest_fail(
            artifact_handler,
            FAIL_PRE_BALANCE,
            "No footer primary balance detected before spin",
            game_conf=game_conf,
        )

    spin_config = resolve_spin_button_config(game_conf, page, hybrid_locator)

    spin_success_check = _make_spin_started_check(
        console_listener,
        page=page,
        hybrid_locator=hybrid_locator,
        before_primary=before_primary,
        game_conf=game_conf,
    )
    coords, _ = perform_spin_action(
        page,
        hybrid_locator,
        spin_config,
        game_id,
        1,
        artifact_handler,
        success_check=spin_success_check,
        before_primary=before_primary,
    )
    # perform_spin stores reel baseline on spin_config; settle reads game_conf.
    from core.reel_motion import get_reel_before, store_reel_before

    reel_snap = get_reel_before(spin_config)
    if reel_snap is not None:
        store_reel_before(game_conf, reel_snap)

    spin_confirmed = bool(coords)
    if not spin_confirmed and before_primary is not None:
        # Late confirm: the click may have spun but the footer balance change lagged
        # past the ack window (WIN animation / slow OCR). Re-read before failing.
        for late_try in range(SPIN_LATE_CONFIRM_ATTEMPTS):
            time.sleep(SPIN_LATE_CONFIRM_POLL_SEC)
            if ocr_spin_started_primary(
                page, hybrid_locator, before_primary, game_conf
            ):
                logger.info(
                    "✅ Late confirm (try %s): spin reflected in footer after ack window; "
                    "proceeding to settlement.",
                    late_try + 1,
                )
                spin_confirmed = True
                break

    if spin_confirmed:
        logger.info("Spin initiated. Waiting for settlement...")
        if settlement_mode == "console":
            _wait_combo_settlement(
                page,
                hybrid_locator,
                console_listener,
                test_errors,
                artifact_handler,
                game_conf=game_conf,
                before_primary=before_primary,
            )
        else:
            _wait_visual_settlement(
                page,
                hybrid_locator,
                console_listener,
                [before_primary],
                game_conf,
                test_errors,
                artifact_handler,
            )
        log_phase("SETTLE", "Cross-venue lobby wallet audit")
        audit_ok, audit_reason = run_post_spin_lobby_audit(
            page,
            hybrid_locator,
            global_config,
            entry_mode,
            game_conf,
            artifact_handler,
            require_lobby_change=(settlement_mode == "console"),
        )
        if not audit_ok:
            artifact_handler.capture(page, "fail_lobby_wallet_audit", "failures", True)
            set_audit_fields(game_conf, ok=False, reason=audit_reason)
            enrich_balances_from_footer(page, hybrid_locator, game_conf)
            set_balance_fields(
                game_conf,
                after_primary=game_conf.get(audit_in_game_b1_key()),
            )
            _pytest_fail(
                artifact_handler,
                FAIL_AUDIT,
                f"Lobby wallet cross-audit failed: {audit_reason}",
                game_conf=game_conf,
                settle_path=settlement_mode,
            )
        set_audit_fields(game_conf, ok=True, reason=audit_reason or "cross-venue match")
        enrich_balances_from_footer(page, hybrid_locator, game_conf)
        set_balance_fields(
            game_conf,
            after_primary=game_conf.get(audit_in_game_b1_key()),
        )
        write_run_evidence(
            artifact_handler,
            game_conf,
            "pass",
            settle_path=settlement_mode,
        )
    else:
        artifact_handler.capture(page, "fail_no_spin", "failures", True)
        _pytest_fail(
            artifact_handler,
            FAIL_SPIN_ACK,
            "Spin not triggered after click attempts "
            "(no console ack / footer primary balance change)",
            game_conf=game_conf,
        )


@pytest.mark.parametrize("game_id", COMBO_GAMES, ids=_game_display_name)
def test_game_betting_combo(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: COMBO """
    _run_game_betting(
        "COMBO",
        login_to_lobby,
        hybrid_locator,
        ui_scanner,
        global_config,
        game_id,
        artifact_handler,
        console_listener,
        settlement_mode="console",
    )

@pytest.mark.parametrize("game_id", FC_GAMES, ids=_game_display_name)
def test_game_betting_fc(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: FC """
    _run_game_betting("FC", login_to_lobby, hybrid_locator, ui_scanner, global_config, game_id, artifact_handler, console_listener)

@pytest.mark.parametrize("game_id", JDB_GAMES, ids=_game_display_name)
def test_game_betting_jdb(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: JDB """
    _run_game_betting("JDB", login_to_lobby, hybrid_locator, ui_scanner, global_config, game_id, artifact_handler, console_listener)

@pytest.mark.parametrize("game_id", JILI_GAMES, ids=_game_display_name)
def test_game_betting_jili(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: JILI """
    _run_game_betting("JILI", login_to_lobby, hybrid_locator, ui_scanner, global_config, game_id, artifact_handler, console_listener)

@pytest.mark.parametrize("game_id", PG_GAMES, ids=_game_display_name)
def test_game_betting_pg(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: PG """
    _run_game_betting("PG", login_to_lobby, hybrid_locator, ui_scanner, global_config, game_id, artifact_handler, console_listener)

@pytest.mark.parametrize("game_id", PP_GAMES, ids=_game_display_name)
def test_game_betting_pp(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: PP """
    _run_game_betting("PP", login_to_lobby, hybrid_locator, ui_scanner, global_config, game_id, artifact_handler, console_listener)

@pytest.mark.parametrize("game_id", SEXYBCRT_GAMES, ids=_game_display_name)
def test_game_betting_sexybcrt(
    login_to_lobby,
    hybrid_locator,
    ui_scanner,
    global_config,
    game_id,
    artifact_handler,
    console_listener,
):
    """單手下注測試 - Provider: SEXYBCRT """
    _run_game_betting("SEXYBCRT", login_to_lobby, hybrid_locator, ui_scanner, global_config, game_id, artifact_handler, console_listener)
