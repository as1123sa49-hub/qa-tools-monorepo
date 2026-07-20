import io
import logging
import re
import time

from PIL import Image

from core.click_debug import click_with_marker
from core.log_format import log_retry
from core.ui_locator import lobby_poster_click_y_ok, poster_click_from_label_bbox
from core.canvas_region import (
    LANDSCAPE_SPIN_ANCHOR_X_FRAC,
    LANDSCAPE_SPIN_ANCHOR_Y_FRAC,
    apply_canvas_relative_region,
    canvas_fills_viewport_width,
    map_region_to_viewport,
    point_inside_canvas_rect,
    sample_canvas_viewport_rect,
)
from core.game_frame_utils import iter_game_contexts, unity_canvas_ready
from core.layout_detect import (
    LAYOUT_LANDSCAPE,
    LAYOUT_PORTRAIT,
    _LAYOUT_PROBE_HOST_KEY,
    auto_detect_layout,
    detect_game_layout,
    layout_from_footer_ocr,
    probe_footer_layout,
    sample_canvas_layout,
)
from core.spin_coord_cache import clear_spin_coord, get_spin_coord, save_spin_coord

try:
    from core.visual_auditor import VisualAuditor
except ImportError:
    VisualAuditor = None

logger = logging.getLogger(__name__)

SPIN_CLICK_OFFSET_ORDER = (
    ("center", 0, 0),
    ("right", 1, 0),
    ("left", -1, 0),
    ("down", 0, 1),
    ("up", 0, -1),
)
SPIN_LOOSE_CLICK_OFFSET_ORDER = (
    ("center", 0, 0),
    ("left", -1, 0),
    ("right", 1, 0),
    ("left2", -2, 0),
    ("right2", 2, 0),
    ("left3", -3, 0),
    ("right3", 3, 0),
    ("down", 0, 1),
    ("down2", 0, 2),
    ("up", 0, -1),
)
SPIN_PORTRAIT_CLICK_OFFSET_ORDER = (
    ("center", 0, 0),
    ("up", 0, -1),
    ("down", 0, 1),
    ("left", -1, 0),
    ("right", 1, 0),
)
SPIN_PORTRAIT_LOOSE_CLICK_OFFSET_ORDER = (
    ("center", 0, 0),
    ("up", 0, -1),
    ("down", 0, 1),
    ("up2", 0, -2),
    ("down2", 0, 2),
    ("left", -1, 0),
    ("right", 1, 0),
)
PORTRAIT_DEFAULT_SPIN_REGION = {
    "x_start": 0.38,
    "x_end": 0.62,
    "y_start": 0.72,
    "y_end": 0.88,
}
PORTRAIT_COMBO_SPIN_REGION = {
    "x_start": 0.38,
    "x_end": 0.62,
    "y_start": 0.71,
    "y_end": 0.85,
}
COMBOBURST_PORTAL_CHROME_EXCLUSION = {
    "x_start": 0.28,
    "x_end": 0.72,
    "y_start": 0.87,
    "y_end": 1.0,
}
_COMBOBURST_PORTAL_KEY = "_comboburst_portal"
PORTRAIT_DEFAULT_ACTIVE_REGION = {
    "x_start": 0.26,
    "x_end": 0.74,
    "y_start": 0.08,
    "y_end": 0.95,
}
PORTRAIT_FOOTER_REGION = {
    "x_start": 0.0,
    "x_end": 1.0,
    "y_start": 0.82,
    "y_end": 1.0,
}
# FC portrait slots: info strip (BALANCE/WIN/TOTAL BETS) sits above the spin row.
FC_PORTRAIT_FOOTER_REGION = {
    "x_start": 0.0,
    "x_end": 1.0,
    "y_start": 0.58,
    "y_end": 0.95,
}
# FC mid-strip balance (above spin controls on many titles).
FC_PORTRAIT_BALANCE_REGION = {
    "x_start": 0.0,
    "x_end": 1.0,
    "y_start": 0.58,
    "y_end": 0.85,
}
# Some FC titles put BALANCE/WIN/TOTAL BETS on the absolute bottom bar.
FC_PORTRAIT_BOTTOM_BALANCE_REGION = {
    "x_start": 0.0,
    "x_end": 1.0,
    "y_start": 0.86,
    "y_end": 1.0,
}
# JDB icon strip (Balance|Bet|Win) sits in the letterboxed center column.
JDB_PORTRAIT_ICON_STRIP_REGION = {
    "x_start": 0.28,
    "x_end": 0.72,
    "y_start": 0.70,
    "y_end": 0.92,
}
JDB_PORTRAIT_ICON_STRIP_BOTTOM_REGION = {
    "x_start": 0.28,
    "x_end": 0.72,
    "y_start": 0.82,
    "y_end": 1.0,
}
PORTRAIT_SPLASH_CONTINUE_FY = 0.72
PORTRAIT_LOAD_UI_KEYWORDS = ("balance", "total bet", "bet", "credit", "win:", "autospin")
PORTRAIT_LOADING_KEYWORDS = ("download", "bundle", "loading", "initializ")
LOADING_PROGRESS_PERCENT_RE = re.compile(r"\b([1-9]\d?)%\b")
PORTRAIT_INTRO_BUTTON_WORDS = ("continue", "start", "play")
PORTRAIT_INTRO_CLICK_REGION = {
    "x_start": 0.30,
    "x_end": 0.70,
    "y_start": 0.50,
    "y_end": 0.86,
}
LAYOUT_AUTO = "auto"
_RESOLVED_LAYOUT_KEY = "_resolved_layout"
_ACTIVE_GAME_PAGE_KEY = "_active_game_page"
JC_LOBBY_MARKERS = ("jackpot combo", "provider", "promotions", "deposit", "withdraw")
JC_LOBBY_NAV_TABS = ("slot", "fish", "arcade", "live", "egame", "combo")
LOBBY_DEFAULT_ICON_OFFSET_Y = 70
# Search overlay (results page, back arrow): top strip only.
LOBBY_SEARCH_OVERLAY_MAX_Y = 200
# Feature-home search bar sits below hero banner (~y 0.35–0.55 on 911px viewport).
LOBBY_SEARCH_BAR_Y_MIN = 280
LOBBY_SEARCH_BAR_Y_MAX_FRAC = 0.58
# VLM false positives: huge game-card panels start low and are tall; search bar is a thin strip higher up.
LOBBY_SEARCH_VLM_MAX_TOP_FRAC = 0.52
LOBBY_SEARCH_VLM_MAX_HEIGHT_FRAC = 0.14
GAME_LAUNCH_ERROR_KEYWORDS = (
    "error launching game",
    "failed to launch",
    "game unavailable",
    "unable to launch",
)
# Transient connectivity failures that surface at game launch (Lucky Fortunes-style).
# Treated as an abortable entry error so the enter-retry can re-attempt and the final
# failure reports "network error" instead of a downstream "no balance" symptom.
NETWORK_ERROR_KEYWORDS = (
    "network error",
    "network anomalies",
    "network anomal",
    "your network anomalies",
    "(20999)",
    "20999",
    "connection lost",
    "connection failed",
    "connection error",
    "network connection",
    "check your connection",
    "please try again",
    "reconnect",
    "connection timeout",
    "网络错误",
    "網路錯誤",
    "連線",
    "连线",
)
# Stores the last entry error reason (e.g. "network error") on game_config so the
# test can surface a precise failure message after the enter-retry is exhausted.
_ENTRY_ERROR_REASON_KEY = "_entry_error_reason"
EXTERNAL_REDIRECT_MARKERS = (
    "agoda",
    "see the world for less",
    "hotels & homes",
    "check-in",
    "check-out",
)
PORTRAIT_CANVAS_ASPECT_THRESHOLD = 1.05
PORTRAIT_WEAK_INTRO_WORDS = ("start", "play")
PORTRAIT_MAX_INTRO_ROUNDS = 12
PORTRAIT_READY_STABLE_LOOPS = 2
SPIN_MULTI_CLICK_TIMEOUT_SEC = 2.5
SPIN_POST_CLICK_GRACE_SEC = 1.0
# FC portrait: balance OCR often lags reel motion; allow longer ack window.
# Keep a single click when possible — a second candidate after a false-negative
# double-spins and breaks B0 - bet + win checks.
FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC = 14.0
FC_SPIN_POST_CLICK_GRACE_SEC = 3.0
FC_SPIN_MAX_SUCCESS_CANDIDATES = 1
# Re-click once when ack times out but balance and reels are both unchanged (JDB/FC).
SPIN_CLICK_RETRY_MAX = 1
SPIN_CLICK_RETRY_PRE_CLICK_SEC = 2.5
SPIN_CLICK_RETRY_ACK_TIMEOUT_SEC = 10.0
SPIN_CLICK_RETRY_GRACE_SEC = 2.0
SPIN_MAX_BBOX_RATIO = 0.55
SPIN_DELTA_MIN = 28.0
SPIN_DELTA_MAX = 48.0
SPIN_LOOSE_DELTA_MIN = 40.0
SPIN_LOOSE_DELTA_MAX = 72.0
PORTRAIT_SPIN_ANCHOR_Y_FRAC = 0.62
PORTAL_CHROME_CLICK_MARGIN_PX = 14.0

# ---- Teaching / overlay dismissal (visual-only providers) ----
# FC first-play tutorial: long explanatory copy over the reels (not the permanent
# Extra Bet button, WAYS header, or MISSION sidebar).
TUTORIAL_CENTER_PHRASES = (
    "after activation",
    "original bet",
    "entering the free game",
    "chance of entering",
    "unlocked reel",
    "locked reel",
    "greatly increases",
    "upgraded to",
)
OVERLAY_MAX_DISMISS_PER_ENTRY = 3
_OVERLAY_DISMISS_COUNT_KEY = "_overlay_dismiss_count"
_OVERLAY_PROBE_COUNT_KEY = "_overlay_probe_count"


def _normalize_for_kws(text: str) -> str:
    norm = re.sub(r"[^\w\s]", " ", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def _tutorial_center_region(game_config: dict | None) -> dict:
    active = portrait_active_region(game_config)
    return {
        "x_start": active["x_start"],
        "x_end": active["x_end"],
        "y_start": 0.20,
        "y_end": 0.72,
    }


def _ocr_in_tutorial_center_region(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    game_config: dict | None,
) -> list:
    region = _tutorial_center_region(game_config)
    return _ocr_results_in_fraction_region(ocr_results, screenshot_bytes, page, region)


def _center_tutorial_copy_visible(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    game_config: dict | None = None,
) -> bool:
    """True when reel-center area shows first-play tutorial sentences (not footer/buttons)."""
    center_ocr = _ocr_in_tutorial_center_region(
        ocr_results, screenshot_bytes, page, game_config
    )
    if not center_ocr:
        return False
    blob = " ".join(_normalize_for_kws(res[1]) for res in center_ocr)
    phrase_hits = sum(1 for phrase in TUTORIAL_CENTER_PHRASES if phrase in blob)
    if phrase_hits >= 1:
        return True
    for res in center_ocr:
        norm = _normalize_for_kws(res[1])
        if len(norm) < 28:
            continue
        if "extra bet" not in norm:
            continue
        if any(
            token in norm
            for token in ("activation", "original", "upgrade", "free game", "combination")
        ):
            return True
    return False


def _is_teaching_overlay_present(
    ocr_results,
    all_text: str,
    screenshot_bytes: bytes,
    page,
    game_config: dict | None = None,
) -> bool:
    del all_text  # footer / sidebar text must not drive overlay detection
    return _center_tutorial_copy_visible(
        ocr_results, screenshot_bytes, page, game_config
    )


def _vlm_teaching_overlay_detected(hybrid_locator, screenshot_bytes: bytes) -> bool:
    """VLM fallback when OCR misses semi-transparent tutorial panels."""
    try:
        rect = hybrid_locator.vision.detect_ui_element(
            screenshot_bytes,
            "semi-transparent tutorial overlay or feature explanation panel with text "
            "and arrow blocking the slot reels, not the footer balance bar",
        )
        return rect is not None
    except Exception as exc:
        logger.debug("VLM teaching overlay probe failed: %s", exc)
        return False


def _overlay_dismiss_click_center(
    page,
    game_config: dict | None = None,
) -> tuple[float, float]:
    """Click center of portrait game column (canvas-mapped when letterboxed)."""
    region = portrait_active_region(game_config)
    click_region = {
        "x_start": region["x_start"],
        "x_end": region["x_end"],
        "y_start": max(region["y_start"], 0.32),
        "y_end": min(region["y_end"], 0.70),
    }
    canvas = sample_canvas_viewport_rect(page)
    if canvas and not canvas_fills_viewport_width(canvas, min_width_frac=0.92):
        click_region = map_region_to_viewport(click_region, canvas)
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    cx = (click_region["x_start"] + click_region["x_end"]) / 2 * vp_w
    cy = (click_region["y_start"] + click_region["y_end"]) / 2 * vp_h
    return cx, cy


def dismiss_extra_bet_teaching_overlay_if_present(
    page,
    hybrid_locator,
    artifact_handler,
    *,
    game_config: dict | None = None,
    tag: str = "overlay",
    screenshot_bytes: bytes | None = None,
    ocr_results=None,
    use_vlm_fallback: bool = False,
) -> bool:
    """
    Dismiss FC-style teaching overlay by clicking the game column center.

    Only acts when reel-center tutorial copy is detected (not permanent Extra Bet UI).
    Returns True when a dismissal click is performed.
    """
    if hybrid_locator is None:
        return False
    if game_config is not None:
        dismiss_count = int(game_config.get(_OVERLAY_DISMISS_COUNT_KEY) or 0)
        if dismiss_count >= OVERLAY_MAX_DISMISS_PER_ENTRY:
            return False

    screenshot_bytes = screenshot_bytes if screenshot_bytes is not None else page.screenshot()
    if ocr_results is None:
        ocr_results = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
    all_text = " ".join([res[1].lower() for res in ocr_results])
    detected = _is_teaching_overlay_present(
        ocr_results, all_text, screenshot_bytes, page, game_config
    )
    if not detected and use_vlm_fallback:
        detected = _vlm_teaching_overlay_detected(hybrid_locator, screenshot_bytes)
    if not detected:
        return False

    cx, cy = _overlay_dismiss_click_center(page, game_config)
    logger.warning(
        f"⚠️ Teaching overlay detected ({tag}); clicking game center ({cx:.0f}, {cy:.0f}) to dismiss."
    )
    artifact_handler.capture(page, f"debug_extra_bet_overlay_{tag}", category="setup")
    page.mouse.click(cx, cy)
    time.sleep(2)
    if game_config is not None:
        game_config[_OVERLAY_DISMISS_COUNT_KEY] = int(
            game_config.get(_OVERLAY_DISMISS_COUNT_KEY) or 0
        ) + 1
    return True


_FC_SIDE_PANEL_LABELS = (
    "mission",
    "ranking",
    "favorites",
    "recommended",
    "props",
    "level",
)
_FC_SIDE_PANEL_DISMISS_KEY = "_fc_side_panel_dismiss_count"
_FC_SIDE_PANEL_MAX_DISMISS = 2
# Purple collapse tab under the left MISSION drawer (above turbo / bottom chrome).
_FC_SIDE_PANEL_COLLAPSE_X_FRAC = 0.085
_FC_SIDE_PANEL_COLLAPSE_Y_FRAC = 0.68


def fc_side_panel_open(
    page,
    hybrid_locator,
    *,
    screenshot_bytes: bytes | None = None,
    ocr_results=None,
) -> bool:
    """True when left MISSION/PROPS drawer labels are visible."""
    if hybrid_locator is None or page is None:
        return False
    screenshot_bytes = screenshot_bytes if screenshot_bytes is not None else page.screenshot()
    if ocr_results is None:
        ocr_results = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
    left_region = {"x_start": 0.0, "x_end": 0.28, "y_start": 0.08, "y_end": 0.75}
    left_ocr = _ocr_results_in_fraction_region(
        ocr_results, screenshot_bytes, page, left_region
    )
    hits = 0
    for res in left_ocr:
        norm = _normalize_for_kws(res[1])
        if any(label in norm for label in _FC_SIDE_PANEL_LABELS):
            hits += 1
    return hits >= 2


def dismiss_fc_side_panel_if_open(
    page,
    hybrid_locator,
    artifact_handler=None,
    *,
    game_config: dict | None = None,
    tag: str = "side_panel",
    screenshot_bytes: bytes | None = None,
    ocr_results=None,
    only_if_blocking: bool = False,
) -> bool:
    """Collapse FC MISSION/RANKING side drawer via the purple down-arrow tab.

    When ``only_if_blocking`` is True the caller already failed to read BALANCE —
    collapse only then. When False (legacy callers), still collapse if the panel
    is open, but prefer the dedicated collapse tab over clicking the reel center.
    """
    if hybrid_locator is None or not _game_config_is_fc(game_config):
        return False
    if game_config is not None:
        count = int(game_config.get(_FC_SIDE_PANEL_DISMISS_KEY) or 0)
        if count >= _FC_SIDE_PANEL_MAX_DISMISS:
            return False

    screenshot_bytes = screenshot_bytes if screenshot_bytes is not None else page.screenshot()
    if ocr_results is None:
        ocr_results = hybrid_locator.ocr.reader.readtext(screenshot_bytes)

    if not fc_side_panel_open(
        page,
        hybrid_locator,
        screenshot_bytes=screenshot_bytes,
        ocr_results=ocr_results,
    ):
        return False
    # only_if_blocking is informational for callers; detection already means open.
    _ = only_if_blocking

    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    # Prefer the purple collapse tab under the drawer (not the reel center).
    cx = vp_w * _FC_SIDE_PANEL_COLLAPSE_X_FRAC
    cy = vp_h * _FC_SIDE_PANEL_COLLAPSE_Y_FRAC
    logger.warning(
        "⚠️ FC side panel detected (%s); clicking collapse tab (%.0f, %.0f).",
        tag,
        cx,
        cy,
    )
    if artifact_handler is not None:
        artifact_handler.capture(page, f"debug_fc_side_panel_{tag}", category="setup")
    page.mouse.click(cx, cy)
    time.sleep(1.2)
    if game_config is not None:
        game_config[_FC_SIDE_PANEL_DISMISS_KEY] = int(
            game_config.get(_FC_SIDE_PANEL_DISMISS_KEY) or 0
        ) + 1
    return True


def collapse_fc_side_panel_after_balance_miss(
    page,
    hybrid_locator,
    artifact_handler=None,
    *,
    game_config: dict | None = None,
    tag: str = "balance_miss",
) -> bool:
    """Collapse side panel only when BALANCE was not read and the drawer is open."""
    return dismiss_fc_side_panel_if_open(
        page,
        hybrid_locator,
        artifact_handler,
        game_config=game_config,
        tag=tag,
        only_if_blocking=True,
    )

# ==========================================
# --- 核心工具函式 (Core Utilities) ---
# ==========================================


def _layout_ratio_is_portrait(ratio: float) -> bool:
    from core.layout_detect import layout_ratio_is_portrait

    return layout_ratio_is_portrait(ratio)


def _sample_canvas_layout(page, expected_host: str | None = None) -> str | None:
    return sample_canvas_layout(page, expected_host)


def _game_config_portrait_hint(game_config: dict | None) -> bool:
    """YAML hints that a game is portrait when canvas auto-detect is ambiguous."""
    if not game_config:
        return False
    if game_config.get("portrait_active_region") or game_config.get("portrait_footer_region"):
        return True
    region = (game_config.get("spin_button") or {}).get("region") or {}
    x_start = region.get("x_start", 0)
    x_end = region.get("x_end", 1)
    y_start = region.get("y_start", 0)
    return x_start >= 0.35 and x_end <= 0.65 and y_start >= 0.75


def _game_config_landscape_hint(game_config: dict | None) -> bool:
    """YAML hints bottom-right spin (landscape) when footer OCR is ambiguous."""
    if not game_config:
        return False
    region = (game_config.get("spin_button") or {}).get("region") or {}
    x_start = region.get("x_start", 0)
    x_end = region.get("x_end", 1)
    y_start = region.get("y_start", 0)
    return x_start >= 0.55 and x_end <= 1.0 and y_start >= 0.55


def resolve_game_layout(
    game_config: dict | None,
    page,
    hybrid_locator=None,
    *,
    expected_game_host: str | None = None,
    refresh: bool = False,
    footer_first: bool = False,
) -> str:
    """YAML portrait/landscape overrides; otherwise auto-detect from canvas + OCR footer."""
    if not game_config:
        return LAYOUT_LANDSCAPE

    yaml_layout = game_config.get("layout")
    if yaml_layout in (LAYOUT_PORTRAIT, LAYOUT_LANDSCAPE):
        if game_config.get(_RESOLVED_LAYOUT_KEY) != yaml_layout:
            logger.info(f"📐 Layout from games.yaml: {yaml_layout}")
        game_config[_RESOLVED_LAYOUT_KEY] = yaml_layout
        return yaml_layout

    cached = game_config.get(_RESOLVED_LAYOUT_KEY)
    if cached in (LAYOUT_PORTRAIT, LAYOUT_LANDSCAPE) and not refresh:
        return cached

    probe_host = expected_game_host or game_config.get(_LAYOUT_PROBE_HOST_KEY)
    detected = auto_detect_layout(
        page,
        hybrid_locator,
        expected_host=probe_host,
        footer_first=footer_first,
        portrait_hint=_game_config_portrait_hint(game_config),
        landscape_hint=_game_config_landscape_hint(game_config),
    )
    resolved = detected or LAYOUT_LANDSCAPE
    if resolved == LAYOUT_LANDSCAPE and _game_config_portrait_hint(game_config):
        logger.info(
            "📐 Portrait hint from games.yaml (portrait regions / center spin); using portrait"
        )
        resolved = LAYOUT_PORTRAIT

    previous = cached
    game_config[_RESOLVED_LAYOUT_KEY] = resolved
    if refresh and previous and previous != resolved:
        logger.info(f"📐 Layout updated: {previous} → {resolved}")
    elif detected:
        logger.info(f"📐 Resolved layout: {resolved}")
    else:
        logger.info(f"📐 Layout unknown; defaulting to {resolved}")
    return resolved


def _provisional_layout_for_load(
    game_config: dict,
    page,
    hybrid_locator=None,
) -> str:
    """Canvas/footer hint for load-path dispatch only; does not cache layout."""
    yaml_layout = game_config.get("layout")
    if yaml_layout in (LAYOUT_PORTRAIT, LAYOUT_LANDSCAPE):
        return yaml_layout
    if _game_config_portrait_hint(game_config):
        return LAYOUT_PORTRAIT

    probe_host = game_config.get(_LAYOUT_PROBE_HOST_KEY)
    canvas_layout = sample_canvas_layout(page, probe_host)
    canvas_rect = sample_canvas_viewport_rect(page, probe_host)
    footer_layout = probe_footer_layout(page, hybrid_locator) if hybrid_locator else None
    from core.layout_detect import fuse_layout_signals

    fused = fuse_layout_signals(
        canvas_layout,
        footer_layout,
        portrait_hint=_game_config_portrait_hint(game_config),
        landscape_hint=_game_config_landscape_hint(game_config),
        canvas_rect=canvas_rect,
    )
    if fused:
        return fused
    if canvas_layout == LAYOUT_PORTRAIT:
        return LAYOUT_PORTRAIT
    return LAYOUT_LANDSCAPE


def is_portrait_layout(game_config: dict | None, page=None, hybrid_locator=None) -> bool:
    if not game_config:
        return False
    if page is not None:
        return (
            resolve_game_layout(game_config, page, hybrid_locator) == LAYOUT_PORTRAIT
        )
    cached = game_config.get(_RESOLVED_LAYOUT_KEY)
    if cached in (LAYOUT_PORTRAIT, LAYOUT_LANDSCAPE):
        return cached == LAYOUT_PORTRAIT
    return game_config.get("layout") == LAYOUT_PORTRAIT


def _game_config_is_fc(game_config: dict | None) -> bool:
    if not game_config:
        return False
    provider = game_config.get("provider_key") or game_config.get("_provider_key")
    if provider and str(provider).upper() == "FC":
        return True
    game_id = game_config.get("id") or ""
    return str(game_id).upper().startswith("FC-")


def _game_config_is_jdb(game_config: dict | None) -> bool:
    if not game_config:
        return False
    provider = game_config.get("provider_key") or game_config.get("_provider_key")
    if provider and str(provider).upper() == "JDB":
        return True
    game_id = game_config.get("id") or ""
    return str(game_id).upper().startswith("JDB-")


def use_fc_portrait_footer_strip(
    game_config: dict | None,
    page=None,
    hybrid_locator=None,
) -> bool:
    """FC footer strip OCR applies only to FC games in portrait layout."""
    return _game_config_is_fc(game_config) and is_portrait_layout(
        game_config, page, hybrid_locator
    )


def use_jdb_portrait_footer_strip(
    game_config: dict | None,
    page=None,
    hybrid_locator=None,
) -> bool:
    """JDB icon footer strip (Balance|Bet|Win) for portrait slots."""
    return _game_config_is_jdb(game_config) and is_portrait_layout(
        game_config, page, hybrid_locator
    )


def _game_version_detected(all_text: str) -> bool:
    """True when FC/COMBO/JDB build stamp is visible."""
    if re.search(r"(v\.\d+\.\d+\.\d+\S*)", all_text):
        return True
    # JDB: v4.24.0 / r25ab780
    if re.search(r"\bv\d+\.\d+\.\d+\b", all_text, re.I):
        return True
    return bool(re.search(r"\bver\.\s*\S+", all_text, re.I))


def _fatal_game_launch_error(ocr_results) -> bool:
    all_text = " ".join(res[1].lower() for res in ocr_results)
    return any(k in all_text for k in GAME_LAUNCH_ERROR_KEYWORDS)


def _network_error_present(ocr_results) -> bool:
    """True when OCR shows a connectivity failure at game launch/load."""
    all_text = " ".join(res[1].lower() for res in ocr_results)
    return any(k in all_text for k in NETWORK_ERROR_KEYWORDS)


def set_entry_error_reason(game_config: dict | None, reason: str | None) -> None:
    if game_config is not None:
        game_config[_ENTRY_ERROR_REASON_KEY] = reason


def get_entry_error_reason(game_config: dict | None) -> str | None:
    if not game_config:
        return None
    return game_config.get(_ENTRY_ERROR_REASON_KEY)


def _vlm_coords_to_viewport(page, vlm_rect, screenshot_bytes: bytes) -> tuple[float, float] | None:
    if not vlm_rect:
        return None
    img = Image.open(io.BytesIO(screenshot_bytes))
    iw, ih = img.size
    vp_w = page.viewport_size["width"]
    dpr = iw / vp_w if vp_w > 0 else 1.0
    cx = ((vlm_rect[0] + vlm_rect[2]) / 2 / 1000.0) * iw / dpr
    cy = ((vlm_rect[1] + vlm_rect[3]) / 2 / 1000.0) * ih / dpr
    return cx, cy


def _lobby_search_bar_y_max(page) -> float:
    vp_h = page.viewport_size["height"]
    return vp_h * LOBBY_SEARCH_BAR_Y_MAX_FRAC


def _vlm_rect_height_frac(vlm_rect) -> float:
    if not vlm_rect or len(vlm_rect) < 4:
        return 0.0
    return (vlm_rect[3] - vlm_rect[1]) / 1000.0


def _vlm_rect_top_frac(vlm_rect) -> float:
    if not vlm_rect or len(vlm_rect) < 2:
        return 1.0
    return vlm_rect[1] / 1000.0


def _vlm_search_box_plausible(vlm_rect) -> bool:
    """Reject VLM boxes that span game posters (low + tall), not a search input strip."""
    if not vlm_rect:
        return True
    if _vlm_rect_top_frac(vlm_rect) > LOBBY_SEARCH_VLM_MAX_TOP_FRAC:
        return False
    return _vlm_rect_height_frac(vlm_rect) <= LOBBY_SEARCH_VLM_MAX_HEIGHT_FRAC


def _vlm_search_coords_valid(page, coords: tuple[float, float], vlm_rect=None) -> bool:
    """Accept top search overlay or Feature-home bar; reject low/tall VLM game-card panels."""
    if not coords:
        return False
    if vlm_rect and not _vlm_search_box_plausible(vlm_rect):
        return False
    y = coords[1]
    if y <= LOBBY_SEARCH_OVERLAY_MAX_Y:
        return True
    y_max = _lobby_search_bar_y_max(page)
    return LOBBY_SEARCH_BAR_Y_MIN <= y <= y_max


def _resolve_lobby_search_bar(page, ui_scanner, hybrid_locator) -> tuple[float, float] | None:
    lobby_coords = ui_scanner(context="lobby")
    overlay = lobby_coords.get("search_overlay_input")
    if overlay:
        logger.info("✅ OCR search overlay input at %s", overlay, extra={"category": "ENTRY"})
        return overlay
    placeholder = lobby_coords.get("search_bar_placeholder")
    if placeholder:
        logger.info("✅ OCR search bar placeholder at %s", placeholder, extra={"category": "ENTRY"})
        return placeholder
    legacy = lobby_coords.get("search_bar")
    if legacy:
        logger.info("✅ OCR search bar at %s", legacy, extra={"category": "ENTRY"})
        return legacy

    logger.warning("⚠️ OCR missed search bar. Trying VLM...")
    screenshot = page.screenshot()
    vlm_rect = hybrid_locator.vision.detect_ui_element(
        screenshot,
        "horizontal search input field with magnifying glass icon, white rounded rectangle, "
        "not game poster thumbnails or provider filter chips",
    )
    coords = _vlm_coords_to_viewport(page, vlm_rect, screenshot)
    if _vlm_search_coords_valid(page, coords, vlm_rect):
        logger.info("✅ VLM found search bar at %s", coords)
        return coords
    if coords:
        logger.warning(
            "⚠️ VLM search bar rejected (coords=%s, top_frac=%.2f, height_frac=%.2f)",
            coords,
            _vlm_rect_top_frac(vlm_rect),
            _vlm_rect_height_frac(vlm_rect),
        )
    return None


def _lobby_search_label_visible(ui_scanner, game_config: dict) -> bool:
    label_key = f"{game_config['id']}_label"
    return label_key in ui_scanner(context="lobby")


def _lobby_search_no_data(ocr_results) -> bool:
    all_text = " ".join(res[1].lower() for res in ocr_results)
    return "no data" in all_text


def _lobby_search_results_visible(ocr_results, game_config: dict) -> bool:
    """True when the page looks like JC search results for this keyword (not lobby home)."""
    if _lobby_search_no_data(ocr_results):
        return False
    all_text = " ".join(res[1].lower() for res in ocr_results)
    keyword = (game_config.get("search_keyword") or game_config.get("name") or "").lower().strip()
    if not keyword:
        return False
    tokens = [t for t in keyword.split() if len(t) >= 3]
    if tokens and any(tok in all_text for tok in tokens[:2]):
        return True
    return False


def _lobby_vlm_poster_coords_valid(page, coords: tuple[float, float] | None) -> bool:
    if not coords or len(coords) < 2:
        return False
    _x, y = float(coords[0]), float(coords[1])
    vp_h = page.viewport_size.get("height") or 720
    return lobby_poster_click_y_ok(y, vp_h)


# JC search overlay: second row under Feature/Slot is provider chips (FA CHAI / JDB / …).
LOBBY_PROVIDER_CHIP_Y_MIN_FRAC = 0.36
LOBBY_PROVIDER_CHIP_Y_MAX_FRAC = 0.58
_LOBBY_TYPE_TAB_NORMS = (
    "feature",
    "slot",
    "fish",
    "arcade",
    "live",
    "egame",
    "promo",
    "provider",
)
# OCR aliases for the second-row provider chip text (icons often broken).
JC_PROVIDER_CHIP_ALIASES: dict[str, tuple[str, ...]] = {
    "FC": ("fa chai", "fachai", "f c", "fc"),
    "JDB": ("jdb",),
    "JILI": ("jili",),
    "PG": ("pg soft", "pgsoft", "pg"),
    "PP": ("pragmatic play", "pragmatic", "pp"),
    "COMBO": ("combo",),
    "SEXYBCRT": ("sexy gaming", "sexy", "bcrt"),
}


def _infer_provider_key(game_config: dict | None) -> str | None:
    if not game_config:
        return None
    explicit = game_config.get("provider_key") or game_config.get("_provider_key")
    if explicit:
        return str(explicit).upper()
    game_id = game_config.get("id") or ""
    if "-" in str(game_id):
        return str(game_id).split("-", 1)[0].upper()
    return None


def provider_chip_aliases(provider_key: str | None) -> tuple[str, ...]:
    if not provider_key:
        return ()
    key = str(provider_key).upper()
    return JC_PROVIDER_CHIP_ALIASES.get(key, (key.lower(),))


def ocr_text_matches_provider_chip(text: str, aliases: tuple[str, ...]) -> bool:
    """True when OCR text looks like the target provider chip (not Feature/Slot tabs)."""
    norm = _normalize_for_kws(text)
    if not norm or not aliases:
        return False
    if any(tab == norm or tab in norm.split() for tab in _LOBBY_TYPE_TAB_NORMS):
        return False
    compact = norm.replace(" ", "")
    for alias in aliases:
        a = _normalize_for_kws(alias)
        if not a:
            continue
        ac = a.replace(" ", "")
        if len(ac) <= 2:
            if compact == ac or norm == a:
                return True
            continue
        if a == norm or ac == compact or a in norm or ac in compact:
            return True
    return False


def find_provider_chip_coords(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    aliases: tuple[str, ...],
) -> tuple[float, float] | None:
    """Locate second-row provider chip center in CSS viewport coords."""
    if not aliases or not ocr_results:
        return None
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    img = Image.open(io.BytesIO(screenshot_bytes))
    dpr = img.width / vp_w if vp_w > 0 else 1.0
    y_min = vp_h * LOBBY_PROVIDER_CHIP_Y_MIN_FRAC
    y_max = vp_h * LOBBY_PROVIDER_CHIP_Y_MAX_FRAC
    best = None
    best_len = -1
    for bbox, text, _prob in ocr_results:
        if not ocr_text_matches_provider_chip(text, aliases):
            continue
        cx = (bbox[0][0] + bbox[2][0]) / 2 / dpr
        cy = (bbox[0][1] + bbox[2][1]) / 2 / dpr
        if cy < y_min or cy > y_max:
            continue
        score = len(_normalize_for_kws(text))
        if score > best_len:
            best_len = score
            best = (float(cx), float(cy))
    return best


def click_jc_search_provider_chip(
    page,
    hybrid_locator,
    game_config: dict,
    artifact_handler=None,
) -> bool:
    """Click the second-row provider chip for ``provider_key`` (FA CHAI / JDB / …)."""
    provider = _infer_provider_key(game_config)
    aliases = provider_chip_aliases(provider)
    if not aliases:
        return False
    screenshot = page.screenshot()
    ocr = hybrid_locator.ocr.reader.readtext(screenshot)
    coords = find_provider_chip_coords(ocr, screenshot, page, aliases)
    if not coords:
        logger.warning(
            "⚠️ Provider chip not found for %s (aliases=%s); continuing without filter.",
            provider,
            aliases,
        )
        return False
    logger.info(
        "🎯 Multi-result search: clicking provider chip %s at (%.0f, %.0f)",
        provider,
        coords[0],
        coords[1],
    )
    if artifact_handler is not None:
        artifact_handler.capture(
            page, f"debug_provider_chip_{provider}", category="setup"
        )
    page.mouse.click(coords[0], coords[1])
    time.sleep(1.5)
    return True


def _resolve_poster_click_coords(
    page,
    results_scan: dict,
    game_config: dict,
    label_key: str,
    fallback_offset_y: int,
) -> tuple[float, float, int]:
    """Poster click from label bbox; fallback to legacy offset if bbox missing."""
    game_id = game_config["id"]
    row_cols = int(results_scan.get(f"{game_id}_row_cols") or 2)
    vp_h = page.viewport_size["height"]
    bbox_key = f"{label_key}_bbox"
    bbox = results_scan.get(bbox_key)
    if bbox and len(bbox) == 4:
        cx, cy = poster_click_from_label_bbox(
            tuple(bbox),
            viewport_height=vp_h,
            row_cols=row_cols,
        )
        return cx, cy, row_cols
    target = results_scan[label_key]
    offset = 40 if row_cols >= 3 else fallback_offset_y
    return target[0], target[1] - offset, row_cols


def _click_search_result_game(
    page,
    hybrid_locator,
    ui_scanner,
    game_config,
    artifact_handler,
):
    """Click game poster from JC search results; retry offsets if still on lobby.

    When search shows ≥2 game cards on the target row, click the second-row
    provider chip first (FA CHAI / JDB / …) so same-name titles resolve correctly.
    """
    label_key = f"{game_config['id']}_label"
    results_scan = ui_scanner(context="lobby")
    base_offset = int(game_config.get("icon_offset_y", LOBBY_DEFAULT_ICON_OFFSET_Y))
    row_cols = int(results_scan.get(f"{game_config['id']}_row_cols") or 0)

    if row_cols >= 2:
        if click_jc_search_provider_chip(
            page, hybrid_locator, game_config, artifact_handler
        ):
            results_scan = ui_scanner(context="lobby")
            row_cols = int(results_scan.get(f"{game_config['id']}_row_cols") or row_cols)

    if label_key in results_scan:
        click_x, click_y, row_cols = _resolve_poster_click_coords(
            page, results_scan, game_config, label_key, base_offset
        )
        offsets = [0, max(25, base_offset - 45)] if row_cols >= 3 else [0, 25]

        for attempt, extra_drop in enumerate(offsets):
            try_x = click_x
            try_y = click_y + extra_drop
            logger.info(
                "🎯 OCR Found Label '%s'. Clicking poster at (%.1f, %.1f) "
                "[row_cols=%s, extra_y=%s]",
                label_key,
                try_x,
                try_y,
                row_cols,
                extra_drop,
            )
            page = _click_open_game_page(page, try_x, try_y)
            time.sleep(2.5)
            if _unity_canvas_visible(page):
                return page
            verify_ocr = hybrid_locator.ocr.reader.readtext(page.screenshot())
            if _lobby_search_no_data(verify_ocr):
                logger.warning(
                    "⚠️ Search results show No Data after click (likely hit provider chip); retrying..."
                )
                if attempt < len(offsets) - 1:
                    continue
                artifact_handler.capture(
                    page,
                    "fail_search_no_data",
                    category="failures",
                    attach_to_allure=True,
                )
                return None
            if not _page_looks_like_jc_lobby(verify_ocr):
                return page
            if not _lobby_search_label_visible(ui_scanner, game_config):
                return page
            if attempt < len(offsets) - 1:
                log_retry(
                    logger,
                    attempt + 1,
                    len(offsets),
                    "Still on lobby search results after poster click; nudging down...",
                )
        return page

    pre_vlm_ocr = hybrid_locator.ocr.reader.readtext(page.screenshot())
    if _lobby_search_no_data(pre_vlm_ocr):
        logger.warning(
            "⚠️ Search results show No Data; skipping VLM (likely provider chip was hit earlier)."
        )
        artifact_handler.capture(
            page,
            "fail_search_no_data",
            category="failures",
            attach_to_allure=True,
        )
        return None
    if not _lobby_search_results_visible(pre_vlm_ocr, game_config):
        logger.warning(
            "⚠️ OCR label '%s' not found and page is not on search results; skipping VLM.",
            label_key,
        )
        artifact_handler.capture(
            page,
            "fail_icon_not_found",
            category="failures",
            attach_to_allure=True,
        )
        return None

    # Label miss but results visible: try provider filter once, then rescan before VLM.
    if click_jc_search_provider_chip(
        page, hybrid_locator, game_config, artifact_handler
    ):
        results_scan = ui_scanner(context="lobby")
        if label_key in results_scan:
            click_x, click_y, row_cols = _resolve_poster_click_coords(
                page, results_scan, game_config, label_key, base_offset
            )
            logger.info(
                "🎯 After provider filter, OCR label '%s' at poster (%.1f, %.1f)",
                label_key,
                click_x,
                click_y,
            )
            return _click_open_game_page(page, click_x, click_y)

    logger.warning(f"⚠️ OCR label '{label_key}' not found. Using VLM to find Game Icon...")
    provider = _infer_provider_key(game_config) or "provider"
    target = (
        f"leftmost {game_config['name']} {provider} game poster thumbnail in search results "
        f"below provider filter chips, not provider buttons"
    )
    target_coords = hybrid_locator.find_and_refine(
        page,
        target,
        keywords=[game_config["name"].lower()],
    )
    if target_coords and _lobby_vlm_poster_coords_valid(page, target_coords):
        logger.info(f"✅ VLM Found Icon at {target_coords}")
        return _click_open_game_page(page, *target_coords)
    if target_coords:
        logger.warning(
            "⚠️ VLM poster coords rejected (y=%.1f); not in game-card band.",
            target_coords[1],
        )

    logger.error("❌ Failed to find game icon via OCR or VLM.")
    artifact_handler.capture(
        page,
        "fail_icon_not_found",
        category="failures",
        attach_to_allure=True,
    )
    return None


def portrait_active_region(game_config: dict | None) -> dict:
    if not game_config:
        return PORTRAIT_DEFAULT_ACTIVE_REGION
    return game_config.get("portrait_active_region") or PORTRAIT_DEFAULT_ACTIVE_REGION


def portrait_footer_region(game_config: dict | None, page=None) -> dict:
    if not game_config:
        return PORTRAIT_FOOTER_REGION
    if game_config.get("portrait_footer_region"):
        return game_config["portrait_footer_region"]
    if use_fc_portrait_footer_strip(game_config, page):
        return dict(FC_PORTRAIT_FOOTER_REGION)
    if use_jdb_portrait_footer_strip(game_config, page):
        return dict(FC_PORTRAIT_FOOTER_REGION)
    return PORTRAIT_FOOTER_REGION


def map_footer_region_to_viewport(page, base_region: dict) -> dict:
    """Map a footer fraction region through Unity canvas when pillarboxed."""
    canvas = sample_canvas_viewport_rect(page)
    if canvas and not canvas_fills_viewport_width(canvas, min_width_frac=0.92):
        return map_region_to_viewport(base_region, canvas)
    return base_region


def _footer_region_tuple(region: dict) -> tuple:
    keys = ("x_start", "x_end", "y_start", "y_end")
    return tuple(round(float(region.get(k, 0)), 4) for k in keys)


def footer_ocr_regions_to_try(page, game_config: dict | None) -> list[dict]:
    """Primary footer region plus a conservative fallback strip."""
    if not game_config:
        return [map_footer_region_to_viewport(page, PORTRAIT_FOOTER_REGION)]
    regions: list[dict] = []
    seen: set[tuple] = set()
    primary = resolve_footer_ocr_region(page, game_config)
    regions.append(primary)
    seen.add(_footer_region_tuple(primary))
    if use_fc_portrait_footer_strip(game_config, page) or use_jdb_portrait_footer_strip(
        game_config, page
    ):
        extra_bases: tuple[dict, ...] = (
            FC_PORTRAIT_BALANCE_REGION,
            FC_PORTRAIT_BOTTOM_BALANCE_REGION,
        )
        if use_jdb_portrait_footer_strip(game_config, page):
            # Prefer center icon strip first — full-width crops often miss tiny bet/win.
            extra_bases = (
                JDB_PORTRAIT_ICON_STRIP_REGION,
                JDB_PORTRAIT_ICON_STRIP_BOTTOM_REGION,
                FC_PORTRAIT_BALANCE_REGION,
                FC_PORTRAIT_BOTTOM_BALANCE_REGION,
            )
        for base in extra_bases:
            mapped = map_footer_region_to_viewport(page, base)
            sig = _footer_region_tuple(mapped)
            if sig not in seen:
                if base in (
                    JDB_PORTRAIT_ICON_STRIP_REGION,
                    FC_PORTRAIT_BALANCE_REGION,
                ):
                    regions.insert(0, mapped)
                else:
                    regions.append(mapped)
                seen.add(sig)
        fallback_base = PORTRAIT_FOOTER_REGION
    else:
        fallback_base = FC_PORTRAIT_FOOTER_REGION
    fallback = map_footer_region_to_viewport(page, fallback_base)
    sig = _footer_region_tuple(fallback)
    if sig not in seen:
        regions.append(fallback)
    return regions


def portrait_intro_click_region(game_config: dict | None) -> dict:
    if not game_config:
        return PORTRAIT_INTRO_CLICK_REGION
    if game_config.get("portrait_intro_click_region"):
        return game_config["portrait_intro_click_region"]
    # JDB START sits lower than COMBO Continue.
    if _game_config_is_jdb(game_config):
        return {
            "x_start": 0.25,
            "x_end": 0.75,
            "y_start": 0.55,
            "y_end": 0.95,
        }
    return PORTRAIT_INTRO_CLICK_REGION


def resolve_spin_button_config(
    game_config: dict,
    page=None,
    hybrid_locator=None,
) -> dict:
    """Return spin_button config with ``_layout`` for click-offset selection."""
    if page is not None:
        resolve_game_layout(
            game_config,
            page,
            hybrid_locator,
            refresh=True,
            footer_first=True,
        )
    spin_data = dict(game_config.get("spin_button") or {})
    layout = game_config.get(_RESOLVED_LAYOUT_KEY) or game_config.get("layout", LAYOUT_LANDSCAPE)
    if layout in (LAYOUT_AUTO, None):
        layout = LAYOUT_LANDSCAPE
    if layout == LAYOUT_PORTRAIT:
        portrait_override = spin_data.pop("portrait", None)
        if portrait_override:
            spin_data = {**spin_data, **portrait_override}
            if "region" in portrait_override:
                spin_data["region"] = portrait_override["region"]
        elif spin_data.get("region", {}).get("x_start", 0) >= 0.6:
            if game_config.get(_COMBOBURST_PORTAL_KEY):
                spin_data["region"] = dict(PORTRAIT_COMBO_SPIN_REGION)
                spin_data["portal_chrome_exclusion"] = dict(COMBOBURST_PORTAL_CHROME_EXCLUSION)
            else:
                spin_data["region"] = PORTRAIT_DEFAULT_SPIN_REGION
            spin_data["prompt"] = (
                "the largest circular main spin button at the exact bottom center, "
                "bigger than auto-play and turbo icons on its sides, "
                "round circle with spiral arrow, not auto-spin or turbo"
            )
            spin_data["idle_prompt"] = spin_data["prompt"]
        if game_config.get("portrait_intro_click_region"):
            spin_data["portrait_intro_click_region"] = game_config["portrait_intro_click_region"]
        for key in ("portrait_active_region", "portrait_footer_region"):
            if game_config.get(key):
                spin_data[key] = game_config[key]
    spin_data["_layout"] = layout
    spin_data[_RESOLVED_LAYOUT_KEY] = layout
    if game_config.get(_COMBOBURST_PORTAL_KEY):
        spin_data[_COMBOBURST_PORTAL_KEY] = True
        if layout == LAYOUT_PORTRAIT and "portal_chrome_exclusion" not in spin_data:
            spin_data["portal_chrome_exclusion"] = dict(COMBOBURST_PORTAL_CHROME_EXCLUSION)

    for passthrough in (
        "id",
        "provider_key",
        "_provider_key",
        _OVERLAY_DISMISS_COUNT_KEY,
        _OVERLAY_PROBE_COUNT_KEY,
    ):
        if passthrough in game_config:
            spin_data[passthrough] = game_config[passthrough]

    if page is not None and spin_data.get("region"):
        probe_host = game_config.get(_LAYOUT_PROBE_HOST_KEY)
        canvas_rect = sample_canvas_viewport_rect(page, probe_host)
        spin_data["region"] = apply_canvas_relative_region(
            spin_data["region"], canvas_rect, label="Spin"
        )
        if canvas_rect:
            spin_data["_canvas_rect"] = canvas_rect

    return spin_data


def _ocr_results_in_fraction_region(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    region_frac: dict,
) -> list:
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    dpr = 1.0
    try:
        if screenshot_bytes:
            img = Image.open(io.BytesIO(screenshot_bytes))
            dpr = img.width / vp_w if vp_w > 0 else 1.0
    except Exception:
        dpr = 1.0
    x0 = region_frac["x_start"] * vp_w
    x1 = region_frac["x_end"] * vp_w
    y0 = region_frac["y_start"] * vp_h
    y1 = region_frac["y_end"] * vp_h
    filtered = []
    for res in ocr_results:
        cx = (res[0][0][0] + res[0][2][0]) / 2 / dpr
        cy = (res[0][0][1] + res[0][2][1]) / 2 / dpr
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            filtered.append(res)
    return filtered


def _bbox_center_viewport(btn_bbox, screenshot_bytes: bytes, page) -> tuple[float, float]:
    vp_w = page.viewport_size["width"]
    if screenshot_bytes:
        splash_img = Image.open(io.BytesIO(screenshot_bytes))
        dpr = splash_img.width / vp_w if vp_w > 0 else 1.0
    else:
        dpr = 1.0
    cx = (btn_bbox[0][0] + btn_bbox[2][0]) / 2 / dpr
    cy = (btn_bbox[0][1] + btn_bbox[2][1]) / 2 / dpr
    return cx, cy


def _pick_continue_click(
    continue_btns: list,
    screenshot_bytes: bytes,
    page,
    *,
    portrait: bool,
) -> tuple[float, float]:
    if portrait:
        vp_w = page.viewport_size["width"]
        vp_h = page.viewport_size["height"]
        target_x, target_y = vp_w * 0.5, vp_h * PORTRAIT_SPLASH_CONTINUE_FY
        best = min(
            continue_btns,
            key=lambda res: (
                (_bbox_center_viewport(res[0], screenshot_bytes, page)[0] - target_x) ** 2
                + (_bbox_center_viewport(res[0], screenshot_bytes, page)[1] - target_y) ** 2
            ),
        )
        return _bbox_center_viewport(best[0], screenshot_bytes, page)
    return _bbox_center_viewport(continue_btns[0][0], screenshot_bytes, page)


def _normalize_intro_label(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _is_continue_promo_label(text: str) -> bool:
    """Intro splash Continue button text (exact); does not match autoplay Play."""
    norm = _normalize_intro_label(text)
    if not norm:
        return False
    if norm == "continue":
        return True
    return norm.startswith("continue ") and len(norm) <= 24


def _is_weak_intro_label(text: str) -> bool:
    """Start / Play on intro slides only — excludes autoplay and long sentences."""
    norm = _normalize_intro_label(text)
    if not norm or "auto" in norm:
        return False
    if norm in ("start", "play", "tap to play", "press start"):
        return True
    return (norm.startswith("start ") or norm.startswith("play ")) and len(norm) <= 20


def _ocr_center_fraction(
    ocr_result,
    screenshot_bytes: bytes,
    page,
) -> tuple[float, float]:
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    cx, cy = _bbox_center_viewport(ocr_result[0], screenshot_bytes, page)
    return cx / vp_w if vp_w else 0.0, cy / vp_h if vp_h else 0.0


def _point_in_fraction_region(fx: float, fy: float, region_frac: dict) -> bool:
    return (
        region_frac["x_start"] <= fx <= region_frac["x_end"]
        and region_frac["y_start"] <= fy <= region_frac["y_end"]
    )


def _portrait_continue_promo_visible(ocr_results) -> bool:
    """True when intro Continue promo is on screen (blocks ready / spin)."""
    return any(_is_continue_promo_label(res[1]) for res in ocr_results)


def _is_loose_continue_label(text: str) -> bool:
    """Landscape splash: OCR substring match (legacy behaviour)."""
    if _is_continue_promo_label(text):
        return True
    lowered = text.lower().strip()
    if not lowered or len(lowered) > 24:
        return False
    return bool(re.search(r"\bcontinue\b", lowered))


def _splash_continue_visible(ocr_results) -> bool:
    """True when any splash Continue label is visible (strict or loose)."""
    return any(_is_loose_continue_label(res[1]) for res in ocr_results)


def resolve_footer_ocr_region(page, game_config: dict | None) -> dict:
    """Footer OCR region mapped through Unity canvas when pillarboxed."""
    base = portrait_footer_region(game_config, page)
    canvas = sample_canvas_viewport_rect(page)
    if canvas and not canvas_fills_viewport_width(canvas, min_width_frac=0.92):
        return map_region_to_viewport(base, canvas)
    return base


def _loading_phase_detected(all_text: str) -> bool:
    """True during bundle/progress loading (1–99% or InitWaiting) before splash Continue."""
    lowered = all_text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if LOADING_PROGRESS_PERCENT_RE.search(lowered):
        return True
    if "initwaiting" in compact:
        return True
    return any(k in lowered for k in PORTRAIT_LOADING_KEYWORDS)


def _landscape_footer_ready(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    game_config: dict | None = None,
) -> bool:
    """True when footer strip shows balance UI (not version/splash noise)."""
    return portrait_game_ui_detected(
        ocr_results,
        screenshot_bytes,
        page,
        game_config=game_config,
        footer_region=resolve_footer_ocr_region(page, game_config),
    )


def _portrait_intro_dismissable(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    game_config: dict | None = None,
) -> bool:
    """True when we should try to advance an intro slide (click), not block on autoplay Play."""
    if _portrait_continue_promo_visible(ocr_results):
        return True
    region = portrait_intro_click_region(game_config)
    for res in ocr_results:
        if not _is_weak_intro_label(res[1]):
            continue
        fx, fy = _ocr_center_fraction(res, screenshot_bytes, page)
        if _point_in_fraction_region(fx, fy, region):
            return True
    return False


def _collect_portrait_intro_click_targets(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    game_config: dict | None = None,
) -> list:
    continue_targets = [res for res in ocr_results if _is_continue_promo_label(res[1])]
    if continue_targets:
        return continue_targets
    region = portrait_intro_click_region(game_config)
    weak_targets = []
    for res in ocr_results:
        if not _is_weak_intro_label(res[1]):
            continue
        fx, fy = _ocr_center_fraction(res, screenshot_bytes, page)
        if _point_in_fraction_region(fx, fy, region):
            weak_targets.append(res)
    return weak_targets


def extract_balance(ocr_results):
    """從 OCR 結果中提取所有符合金額格式的數字。
    支援格式: 1,234.56, 100.00, 50 00
    """
    all_text = " ".join([res[1] for res in ocr_results])
    matches = re.findall(r"([\d,]+[.\s]?\d{2})", all_text)

    valid_balances = []
    for val_str in matches:
        try:
            clean_str = val_str.replace(" ", ".")
            if "," in clean_str and "." not in clean_str:
                clean_str = clean_str.replace(",", ".")
            else:
                clean_str = clean_str.replace(",", "")

            valid_balances.append(float(clean_str))
        except ValueError:
            continue
    return sorted(valid_balances)


def try_rescue_click(page, hybrid_locator, game_id, artifact_handler):
    """[救援模式] 當找不到 Spin 按鈕時的急救措施。"""
    logger.info("🚑 Emergency: Spin button missing. Attempting rescue click...")

    artifact_handler.capture(page, f"debug_rescue_start_{int(time.time())}", category="debug")

    # 1. 優先點擊 Cache (上次成功的位置)
    cache_key = f"{game_id}_spin_button"
    cached = hybrid_locator.get_cached_coords(cache_key) or get_spin_coord(game_id)
    if cached:
        logger.info(f"⏩ Rescue: Clicking cached Spin Button at {cached}")
        click_with_marker(
            page,
            artifact_handler,
            f"rescue_click_{game_id}_cached",
            cached[0],
            cached[1],
            label=f"rescue cache ({cached[0]:.0f}, {cached[1]:.0f})",
        )
        time.sleep(1.2)
        return True

    # 2. 找關鍵字按鈕點 (OCR)
    screenshot = page.screenshot()
    ocr_results = hybrid_locator.ocr.reader.readtext(screenshot)
    rescue_keywords = ["start", "free", "collect", "feature", "confirm", "spin"]

    for res in ocr_results:
        if any(k in res[1].lower() for k in rescue_keywords):
            logger.info(f"✅ Rescue: Found text button '{res[1]}', clicking it!")
            bbox = res[0]
            vp_w = page.viewport_size["width"]
            img = Image.open(io.BytesIO(screenshot))
            dpr = img.width / vp_w if vp_w > 0 else 1.0
            cx = (bbox[0][0] + bbox[2][0]) / 2 / dpr
            cy = (bbox[0][1] + bbox[2][1]) / 2 / dpr
            click_with_marker(
                page,
                artifact_handler,
                f"rescue_click_{game_id}_ocr",
                cx,
                cy,
                label=f"rescue '{res[1]}'",
                screenshot_bytes=screenshot,
            )
            time.sleep(1.7)
            return True

    # 3. Fallback: 點擊螢幕正中間
    logger.info("⏩ Rescue: Clicking center screen (Fallback).")
    w = page.viewport_size["width"]
    h = page.viewport_size["height"]
    click_with_marker(
        page,
        artifact_handler,
        f"rescue_click_{game_id}_center",
        w / 2,
        h / 2,
        label="rescue center",
    )
    time.sleep(0.7)
    return True


def _vlm_bbox_to_viewport_rect(
    spin_coords: list, screenshot_bytes: bytes, page
) -> tuple[float, float, float, float, float, float]:
    """Map VLM bbox (0-1000 full image) to viewport CSS rect and center."""
    img = Image.open(io.BytesIO(screenshot_bytes))
    w, h = img.size
    vp_w = page.viewport_size["width"]
    dpr = w / vp_w if vp_w > 0 else 1.0

    def axis_to_vp(coord_1000: float, img_axis: int) -> float:
        return coord_1000 / 1000.0 * img_axis / dpr

    x1 = axis_to_vp(spin_coords[0], w)
    y1 = axis_to_vp(spin_coords[1], h)
    x2 = axis_to_vp(spin_coords[2], w)
    y2 = axis_to_vp(spin_coords[3], h)
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    return cx, cy, x1, y1, x2, y2


def _compute_spin_delta(bw: float, bh: float, *, loose: bool = False) -> float:
    short = min(bw, bh)
    if loose:
        return max(SPIN_LOOSE_DELTA_MIN, min(SPIN_LOOSE_DELTA_MAX, short * 0.12))
    return max(SPIN_DELTA_MIN, min(SPIN_DELTA_MAX, short * 0.12))


def _is_loose_bbox_in_region(spin_coords: list, spin_config: dict) -> bool:
    """True when VLM box fills too much of the search region (unreliable center)."""
    region = spin_config["region"]
    reg_w = max(region["x_end"] - region["x_start"], 1e-6)
    reg_h = max(region["y_end"] - region["y_start"], 1e-6)
    box_w = (spin_coords[2] - spin_coords[0]) / 1000.0
    box_h = (spin_coords[3] - spin_coords[1]) / 1000.0
    return (box_w / reg_w > SPIN_MAX_BBOX_RATIO) or (box_h / reg_h > SPIN_MAX_BBOX_RATIO)


def build_spin_click_candidates(
    cx: float,
    cy: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    page,
    spin_config: dict | None = None,
    spin_coords_0_1000: list | None = None,
) -> tuple[list[tuple[str, float, float]], float]:
    """Center + directional offsets; loose VLM boxes alternate left/right before down/up."""
    bw = max(x2 - x1, 1.0)
    bh = max(y2 - y1, 1.0)
    loose = bool(
        spin_config
        and spin_coords_0_1000
        and _is_loose_bbox_in_region(spin_coords_0_1000, spin_config)
    )
    delta = _compute_spin_delta(bw, bh, loose=loose)
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    portrait = spin_config and spin_config.get("_layout") == "portrait"
    if portrait:
        offsets = SPIN_PORTRAIT_LOOSE_CLICK_OFFSET_ORDER if loose else SPIN_PORTRAIT_CLICK_OFFSET_ORDER
    else:
        offsets = SPIN_LOOSE_CLICK_OFFSET_ORDER if loose else SPIN_CLICK_OFFSET_ORDER

    candidates: list[tuple[str, float, float]] = []
    for name, dx_mul, dy_mul in offsets:
        x = max(2.0, min(vp_w - 2, cx + dx_mul * delta))
        y = max(2.0, min(vp_h - 2, cy + dy_mul * delta))
        x, y = _clamp_click_outside_portal_chrome(x, y, page, spin_config)
        candidates.append((name, x, y))
    return candidates, delta


def _portal_chrome_exclusions(spin_config: dict | None) -> list[dict]:
    if not spin_config:
        return []
    exc = spin_config.get("portal_chrome_exclusion")
    if exc:
        return [exc]
    if spin_config.get(_COMBOBURST_PORTAL_KEY):
        return [COMBOBURST_PORTAL_CHROME_EXCLUSION]
    return []


def _clamp_click_outside_portal_chrome(
    x: float,
    y: float,
    page,
    spin_config: dict | None,
) -> tuple[float, float]:
    """Keep clicks above COMBO portal orientation bar (desktop/mobile toggle)."""
    exclusions = _portal_chrome_exclusions(spin_config)
    if not exclusions:
        return x, y
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    for exc in exclusions:
        x0 = exc["x_start"] * vp_w
        x1 = exc["x_end"] * vp_w
        y0 = exc["y_start"] * vp_h
        if x0 <= x <= x1 and y >= y0 - PORTAL_CHROME_CLICK_MARGIN_PX:
            y = min(y, y0 - PORTAL_CHROME_CLICK_MARGIN_PX)
    return x, max(2.0, y)


def _spin_region_center_viewport(page, spin_config: dict) -> tuple[float, float]:
    return _spin_region_click_anchor(page, spin_config)


def _spin_region_click_anchor(page, spin_config: dict) -> tuple[float, float]:
    """Portrait spin anchor: horizontal center of region, above portal chrome when present."""
    region = spin_config.get("region") or PORTRAIT_DEFAULT_SPIN_REGION
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    cx = (region["x_start"] + region["x_end"]) / 2 * vp_w
    y_span = region["y_end"] - region["y_start"]
    cy = (region["y_start"] + y_span * PORTRAIT_SPIN_ANCHOR_Y_FRAC) * vp_h
    exclusions = _portal_chrome_exclusions(spin_config)
    if exclusions:
        y_cap = exclusions[0]["y_start"] * vp_h - PORTAL_CHROME_CLICK_MARGIN_PX
        cy = min(cy, y_cap)
        cy = max(region["y_start"] * vp_h, cy)
    return cx, cy


def _landscape_spin_region_anchor(page, spin_config: dict) -> tuple[float, float]:
    """Bottom-right anchor inside the (canvas-mapped) spin search region."""
    region = spin_config.get("region") or {}
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    span_x = region.get("x_end", 1.0) - region.get("x_start", 0.0)
    span_y = region.get("y_end", 1.0) - region.get("y_start", 0.0)
    cx = (region["x_start"] + span_x * LANDSCAPE_SPIN_ANCHOR_X_FRAC) * vp_w
    cy = (region["y_start"] + span_y * LANDSCAPE_SPIN_ANCHOR_Y_FRAC) * vp_h
    return _clamp_click_outside_portal_chrome(cx, cy, page, spin_config)


def _vlm_snap_click_anchor(
    page,
    spin_config: dict,
    vlm_cx: float,
    vlm_cy: float,
    *,
    loose: bool,
) -> tuple[float, float, bool]:
    """Snap unreliable VLM centers to configured region anchors (portrait or landscape)."""
    layout = spin_config.get("_layout")
    canvas_rect = spin_config.get("_canvas_rect")

    if layout == LAYOUT_PORTRAIT and loose:
        rcx, rcy = _spin_region_click_anchor(page, spin_config)
        logger.warning(
            f"⚠️ Portrait loose VLM bbox; snapping click anchor "
            f"from ({vlm_cx:.1f}, {vlm_cy:.1f}) to ({rcx:.1f}, {rcy:.1f})"
        )
        return rcx, rcy, True

    if layout == LAYOUT_LANDSCAPE:
        outside_canvas = not point_inside_canvas_rect(
            vlm_cx, vlm_cy, canvas_rect, page
        )
        if loose or outside_canvas:
            rcx, rcy = _landscape_spin_region_anchor(page, spin_config)
            reason = "outside canvas" if outside_canvas else "loose bbox"
            logger.warning(
                f"⚠️ Landscape VLM {reason}; snapping click anchor "
                f"from ({vlm_cx:.1f}, {vlm_cy:.1f}) to ({rcx:.1f}, {rcy:.1f})"
            )
            return rcx, rcy, True

    return vlm_cx, vlm_cy, False


def _portrait_loose_snap_click_anchor(
    page,
    spin_config: dict,
    vlm_cx: float,
    vlm_cy: float,
    *,
    loose: bool,
) -> tuple[float, float, bool]:
    """Backward-compatible wrapper."""
    return _vlm_snap_click_anchor(page, spin_config, vlm_cx, vlm_cy, loose=loose)


def _portrait_spin_fallback_candidates(page, spin_config: dict) -> tuple[list[tuple[str, float, float]], float]:
    """When VLM fails on portrait games, click around the configured region center."""
    cx, cy = _spin_region_center_viewport(page, spin_config)
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    pad_x = max(24.0, vp_w * 0.02)
    pad_y = max(24.0, vp_h * 0.02)
    return build_spin_click_candidates(
        cx,
        cy,
        cx - pad_x,
        cy - pad_y,
        cx + pad_x,
        cy + pad_y,
        page,
        spin_config,
        None,
    )


def _detect_spin_bbox(vision, screenshot_bytes: bytes, spin_config: dict) -> list | None:
    """VLM grid-region detect only; loose bbox is OK — multi-point clicks compensate."""
    region = spin_config["region"]
    coords = vision.detect_in_grid_region(
        screenshot_bytes,
        spin_config["prompt"],
        x_start=region["x_start"],
        x_end=region["x_end"],
        y_start=region["y_start"],
        y_end=region["y_end"],
    )
    if not coords:
        return []
    if _is_loose_bbox_in_region(coords, spin_config):
        if spin_config.get("_layout") == LAYOUT_PORTRAIT:
            logger.info("⚠️ VLM bbox loose (portrait); will snap to region bottom-center")
        else:
            logger.info("⚠️ VLM bbox loose (landscape); will snap to region bottom-right")
    else:
        logger.info("✓ VLM bbox from grid region")
    return coords


def resolve_spin_success_check_timeout(spin_config: dict | None) -> float:
    """FC portrait spin uses a longer OCR ack window (spin_config has ``_layout``, not yaml layout)."""
    if _game_config_is_fc(spin_config) and spin_config and spin_config.get("_layout") == LAYOUT_PORTRAIT:
        return FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC
    if _game_config_is_jdb(spin_config) and spin_config and spin_config.get("_layout") == LAYOUT_PORTRAIT:
        return FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC
    return SPIN_MULTI_CLICK_TIMEOUT_SEC


def resolve_spin_post_click_grace(spin_config: dict | None) -> float:
    if spin_config and spin_config.get("_layout") == LAYOUT_PORTRAIT and (
        _game_config_is_fc(spin_config) or _game_config_is_jdb(spin_config)
    ):
        return FC_SPIN_POST_CLICK_GRACE_SEC
    return SPIN_POST_CLICK_GRACE_SEC


def _poll_spin_acknowledged(
    success_check,
    timeout_sec: float,
    *,
    grace_sec: float = SPIN_POST_CLICK_GRACE_SEC,
) -> bool:
    """Wait for spin_triggered / bet deduction, then short grace for delayed game events."""
    if success_check(timeout_sec=timeout_sec):
        return True
    if grace_sec > 0 and success_check(timeout_sec=grace_sec):
        logger.info("✅ Spin acknowledged during post-click grace period")
        return True
    return False


def _spin_already_started_before_click(
    success_check,
    *,
    page=None,
    game_config: dict | None = None,
    reel_before=None,
) -> bool:
    """True when primary spin evidence exists (and reels moved if assist is on)."""
    if success_check is None:
        return False
    # One OCR attempt; keep window short so the happy path does not stall.
    if not bool(success_check(timeout_sec=0.25)):
        return False
    if page is not None and game_config is not None:
        from core.reel_motion import reel_motion_vetoes_spin

        if reel_motion_vetoes_spin(page, game_config, before=reel_before):
            return False
    return True


def _cache_spin_coords(hybrid_locator, cache_key: str, game_id: str, x: float, y: float) -> None:
    hybrid_locator.set_cached_coords(cache_key, (x, y))
    save_spin_coord(game_id, x, y)


def _spin_click_retry_enabled(game_config: dict | None, game_id: str) -> bool:
    if game_config and game_config.get("spin_click_retry") is False:
        return False
    gid = str(game_id)
    return gid.startswith("FC-") or gid.startswith("JDB-")


def _balance_unchanged_for_spin_retry(
    page,
    hybrid_locator,
    game_config: dict | None,
    before_primary: float | None,
) -> bool:
    if before_primary is None:
        return False
    from core.balance_audit import (
        primary_balance_spin_delta,
        read_in_game_footer_primary,
        resolve_spin_delta_min_bet,
    )

    current = read_in_game_footer_primary(page, hybrid_locator, game_config)
    if current is None:
        return False
    delta_min = resolve_spin_delta_min_bet(None, game_config)
    return primary_balance_spin_delta(before_primary, current, min_bet=delta_min) is None


def _reels_static_for_spin_retry(
    page,
    game_config: dict | None,
    reel_before,
) -> bool:
    from core.reel_motion import (
        get_reel_post_click_moved,
        probe_reel_motion_after_click,
        reel_motion_assist_enabled,
    )

    if not reel_motion_assist_enabled(game_config):
        return False
    moved = get_reel_post_click_moved(game_config)
    if moved is True:
        return False
    if moved is False:
        return True
    probe = probe_reel_motion_after_click(
        page, game_config, before=reel_before, delay_sec=0.25
    )
    return probe is False


def _spin_retry_allowed(
    page,
    hybrid_locator,
    game_config: dict | None,
    game_id: str,
    success_check,
    before_primary: float | None,
    reel_before,
) -> bool:
    if not _spin_click_retry_enabled(game_config, game_id):
        return False
    if success_check and _spin_already_started_before_click(
        success_check,
        page=page,
        game_config=game_config,
        reel_before=reel_before,
    ):
        return False
    if not _balance_unchanged_for_spin_retry(
        page, hybrid_locator, game_config, before_primary
    ):
        return False
    if not _reels_static_for_spin_retry(page, game_config, reel_before):
        return False
    return True


def _maybe_retry_spin_click(
    page,
    artifact_handler,
    hybrid_locator,
    game_id: str,
    attempt_idx: int,
    name: str,
    x: float,
    y: float,
    success_check,
    success_check_timeout: float,
    grace_sec: float,
    game_config: dict | None,
    reel_before,
    before_primary: float | None,
    *,
    spin_coords=None,
    screenshot_bytes=None,
) -> bool:
    """One conditional re-click at the same coords. Returns True if ack succeeds."""
    from core.reel_motion import probe_reel_motion_after_click, reel_probe_snapshot
    from core.run_evidence import record_spin_click_attempt, update_spin_click_summary

    if not _spin_retry_allowed(
        page,
        hybrid_locator,
        game_config,
        game_id,
        success_check,
        before_primary,
        reel_before,
    ):
        return False

    logger.info(
        "🔁 Spin click retry: balance unchanged and reels static; "
        "waiting %.1fs before re-click at (%.0f, %.0f)",
        SPIN_CLICK_RETRY_PRE_CLICK_SEC,
        x,
        y,
    )
    time.sleep(SPIN_CLICK_RETRY_PRE_CLICK_SEC)
    if success_check and success_check(timeout_sec=0.25):
        logger.info("✅ Spin acknowledged during retry pre-wait; skipping re-click")
        update_spin_click_summary(game_config, after_retry_ack_ok=True, retry_used=True)
        return True

    retry_name = f"{name}_retry1"
    click_with_marker(
        page,
        artifact_handler,
        f"spin_click_{game_id}_attempt{attempt_idx}_{retry_name}",
        x,
        y,
        bbox_0_1000=spin_coords if name == "center" else None,
        label=f"spin {retry_name} ({x:.0f},{y:.0f})",
        screenshot_bytes=screenshot_bytes if name == "center" else None,
        capture_after=False,
    )
    probe_reel_motion_after_click(page, game_config, before=reel_before)
    record_spin_click_attempt(
        game_config,
        {
            "label": retry_name,
            "coords": [round(x, 1), round(y, 1)],
            "is_retry": True,
            "retry_reason": "balance_unchanged_and_reels_static",
            "reel": reel_probe_snapshot(game_config),
        },
    )
    retry_timeout = min(success_check_timeout, SPIN_CLICK_RETRY_ACK_TIMEOUT_SEC)
    retry_grace = min(grace_sec, SPIN_CLICK_RETRY_GRACE_SEC)
    if _poll_spin_acknowledged(success_check, retry_timeout, grace_sec=retry_grace):
        logger.info("✅ Spin triggered on retry click at (%.1f, %.1f)", x, y)
        update_spin_click_summary(
            game_config,
            after_retry_ack_ok=True,
            retry_used=True,
            coords=[round(x, 1), round(y, 1)],
        )
        artifact_handler.capture(
            page,
            f"spin_click_{game_id}_attempt{attempt_idx}_{retry_name}_after",
            "debug",
        )
        return True

    still_static = _reels_static_for_spin_retry(page, game_config, reel_before)
    update_spin_click_summary(
        game_config,
        after_retry_ack_ok=False,
        retry_used=True,
        retry_still_static=still_static,
    )
    logger.warning(
        "⚠️ Spin retry at (%.1f, %.1f) did not trigger within %.1fs (+%.1fs grace)",
        x,
        y,
        retry_timeout,
        retry_grace,
    )
    return False


def _try_spin_click_candidates(
    page,
    artifact_handler,
    hybrid_locator,
    cache_key: str,
    game_id: str,
    attempt_idx: int,
    candidates: list[tuple[str, float, float]],
    spin_coords: list,
    screenshot_bytes: bytes,
    success_check,
    success_check_timeout: float,
    *,
    grace_sec: float = SPIN_POST_CLICK_GRACE_SEC,
    game_config: dict | None = None,
    reel_before=None,
    before_primary: float | None = None,
) -> tuple[tuple[float, float] | None, bool]:
    """Click each candidate; stop on first success_check pass. Cache winning coords."""
    from core.reel_motion import probe_reel_motion_after_click, reel_probe_snapshot
    from core.run_evidence import record_spin_click_attempt, update_spin_click_summary

    multi = success_check is not None
    to_try = candidates if multi else candidates[:1]
    if multi and (
        str(game_id).startswith("FC-") or str(game_id).startswith("JDB-")
    ):
        to_try = candidates[:FC_SPIN_MAX_SUCCESS_CANDIDATES]

    for i, (name, x, y) in enumerate(to_try):
        if multi and i > 0 and success_check(timeout_sec=0.1):
            prev_name, prev_x, prev_y = to_try[i - 1]
            logger.info(
                f"⚠️ Spin already acknowledged before '{name}'; "
                f"crediting prior candidate '{prev_name}'"
            )
            _cache_spin_coords(hybrid_locator, cache_key, game_id, prev_x, prev_y)
            artifact_handler.capture(
                page,
                f"spin_click_{game_id}_attempt{attempt_idx}_{prev_name}_delayed_after",
                "debug",
            )
            return (prev_x, prev_y), False

        # Overlay / VLM wait may have already spun — do not click again.
        if multi and _spin_already_started_before_click(
            success_check,
            page=page,
            game_config=game_config,
            reel_before=reel_before,
        ):
            logger.warning(
                "⚠️ Spin already reflected before click '%s'; skipping further spin clicks",
                name,
            )
            _cache_spin_coords(hybrid_locator, cache_key, game_id, x, y)
            artifact_handler.capture(
                page,
                f"spin_click_{game_id}_attempt{attempt_idx}_{name}_skipped_already_spun",
                "debug",
            )
            return (x, y), False

        logger.debug(f"🎯 Spin click candidate '{name}' at ({x:.1f}, {y:.1f})")
        click_with_marker(
            page,
            artifact_handler,
            f"spin_click_{game_id}_attempt{attempt_idx}_{name}",
            x,
            y,
            bbox_0_1000=spin_coords if name == "center" else None,
            label=f"spin {name} ({x:.0f},{y:.0f})",
            screenshot_bytes=screenshot_bytes if name == "center" else None,
            capture_after=False,
        )
        probe_reel_motion_after_click(page, game_config, before=reel_before)
        if multi:
            record_spin_click_attempt(
                game_config,
                {
                    "label": name,
                    "coords": [round(x, 1), round(y, 1)],
                    "is_retry": False,
                    "reel": reel_probe_snapshot(game_config),
                },
            )
        if not multi:
            _cache_spin_coords(hybrid_locator, cache_key, game_id, x, y)
            artifact_handler.capture(page, f"spin_click_{game_id}_attempt{attempt_idx}_{name}_after", "debug")
            return (x, y), False

        if _poll_spin_acknowledged(
            success_check, success_check_timeout, grace_sec=grace_sec
        ):
            logger.info(f"✅ Spin triggered at candidate '{name}' ({x:.1f}, {y:.1f})")
            update_spin_click_summary(
                game_config,
                first_ack_ok=True,
                coords=[round(x, 1), round(y, 1)],
            )
            _cache_spin_coords(hybrid_locator, cache_key, game_id, x, y)
            artifact_handler.capture(
                page,
                f"spin_click_{game_id}_attempt{attempt_idx}_{name}_after",
                "debug",
            )
            return (x, y), False

        update_spin_click_summary(game_config, first_ack_ok=False, coords=[round(x, 1), round(y, 1)])
        logger.warning(
            f"⚠️ Candidate '{name}' did not trigger spin within "
            f"{success_check_timeout}s (+{grace_sec}s grace)"
        )
        if _maybe_retry_spin_click(
            page,
            artifact_handler,
            hybrid_locator,
            game_id,
            attempt_idx,
            name,
            x,
            y,
            success_check,
            success_check_timeout,
            grace_sec,
            game_config,
            reel_before,
            before_primary,
            spin_coords=spin_coords if name == "center" else None,
            screenshot_bytes=screenshot_bytes if name == "center" else None,
        ):
            _cache_spin_coords(hybrid_locator, cache_key, game_id, x, y)
            artifact_handler.capture(
                page,
                f"spin_click_{game_id}_attempt{attempt_idx}_{name}_after",
                "debug",
            )
            return (x, y), False

    return None, False


def perform_spin_action(
    page,
    hybrid_locator,
    spin_config,
    game_id,
    attempt_idx,
    artifact_handler,
    success_check=None,
    success_check_timeout: float | None = None,
    before_primary: float | None = None,
):
    """執行單次 Spin 動作。
    策略：持久 Cache → 記憶體 Cache → VLM grid region → 多點點擊（含防雙 spin）。
    """
    if success_check_timeout is None:
        success_check_timeout = resolve_spin_success_check_timeout(spin_config)
    grace_sec = resolve_spin_post_click_grace(spin_config)

    reel_before = None
    if spin_config:
        from core.reel_motion import (
            capture_reel_snapshot,
            reel_motion_assist_enabled,
            store_reel_before,
        )

        if reel_motion_assist_enabled(spin_config):
            reel_before = capture_reel_snapshot(page, spin_config)
            store_reel_before(spin_config, reel_before)

    if spin_config and spin_config.get("_layout") == "portrait":
        dismissed = dismiss_portrait_intro_carousel(
            page, hybrid_locator, artifact_handler, game_config=spin_config
        )
        if dismissed:
            logger.info(f"⏭️ Cleared {dismissed} intro slide(s) before spin detection.")

        # Extra Bet teaching overlay can re-appear right before spin.
        dismiss_extra_bet_teaching_overlay_if_present(
            page,
            hybrid_locator,
            artifact_handler,
            game_config=spin_config,
            tag=f"pre_spin_{game_id}_attempt{attempt_idx}",
            use_vlm_fallback=_overlay_vlm_fallback_allowed(spin_config),
        )
        # Overlay dismiss can punch through to spin — skip VLM/click if already spun.
        if _spin_already_started_before_click(
            success_check,
            page=page,
            game_config=spin_config,
            reel_before=reel_before,
        ):
            logger.warning(
                "⚠️ Spin already reflected after pre-spin dismiss; skipping spin click"
            )
            cx, cy = _spin_region_center_viewport(page, spin_config) if spin_config else (0.0, 0.0)
            _cache_spin_coords(hybrid_locator, f"{game_id}_spin_button", game_id, cx, cy)
            artifact_handler.capture(
                page,
                f"spin_click_{game_id}_attempt{attempt_idx}_skipped_already_spun",
                "debug",
            )
            return (cx, cy), False

    cache_key = f"{game_id}_spin_button"
    cached = hybrid_locator.get_cached_coords(cache_key)
    if not cached:
        persisted = get_spin_coord(game_id)
        if persisted:
            cached = persisted
            hybrid_locator.set_cached_coords(cache_key, cached)
            logger.info(f"💾 Loaded persisted spin coords for {game_id}: {cached}")

    if cached and spin_config:
        from core.balance_audit import is_cached_coord_stale

        if is_cached_coord_stale(cached[0], cached[1], page, spin_config):
            logger.warning(
                f"⚠️ Stale cached spin coords ({cached[0]:.1f}, {cached[1]:.1f}) "
                "in portal chrome; clearing and re-detecting."
            )
            hybrid_locator.clear_cache(cache_key)
            clear_spin_coord(game_id)
            cached = None

    if cached:
        if _spin_already_started_before_click(
            success_check,
            page=page,
            game_config=spin_config,
            reel_before=reel_before,
        ):
            logger.warning(
                "⚠️ Spin already reflected before cached click; skipping spin click"
            )
            artifact_handler.capture(
                page,
                f"spin_click_{game_id}_attempt{attempt_idx}_cached_skipped_already_spun",
                "debug",
            )
            return cached, True
        logger.info(f"⏩ Cached spin coords: {cached}")
        click_with_marker(
            page,
            artifact_handler,
            f"spin_click_{game_id}_attempt{attempt_idx}_cached",
            cached[0],
            cached[1],
            label=f"spin cache ({cached[0]:.0f}, {cached[1]:.0f})",
        )
        from core.reel_motion import probe_reel_motion_after_click, reel_probe_snapshot
        from core.run_evidence import record_spin_click_attempt, update_spin_click_summary

        probe_reel_motion_after_click(page, spin_config, before=reel_before)
        if success_check:
            record_spin_click_attempt(
                spin_config,
                {
                    "label": "cached",
                    "coords": [round(cached[0], 1), round(cached[1], 1)],
                    "is_retry": False,
                    "reel": reel_probe_snapshot(spin_config),
                },
            )
            if _poll_spin_acknowledged(
                success_check, success_check_timeout, grace_sec=grace_sec
            ):
                update_spin_click_summary(spin_config, first_ack_ok=True)
                return cached, True
            update_spin_click_summary(spin_config, first_ack_ok=False)
            if _maybe_retry_spin_click(
                page,
                artifact_handler,
                hybrid_locator,
                game_id,
                attempt_idx,
                "cached",
                cached[0],
                cached[1],
                success_check,
                success_check_timeout,
                grace_sec,
                spin_config,
                reel_before,
                before_primary,
            ):
                return cached, True
            logger.warning("⚠️ Cached spin coords did not trigger; re-detecting via VLM...")
            hybrid_locator.clear_cache(cache_key)
            clear_spin_coord(game_id)
        else:
            return cached, True

    logger.info(f"🔍 [Spin {attempt_idx}] Detecting Spin Button via VLM...")
    screenshot_bytes = page.screenshot()
    ocr_pre_spin = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
    if spin_config and spin_config.get("_layout") == "portrait" and _portrait_continue_promo_visible(
        ocr_pre_spin
    ):
        dismiss_portrait_intro_carousel(
            page, hybrid_locator, artifact_handler, game_config=spin_config
        )
        screenshot_bytes = page.screenshot()
        ocr_pre_spin = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
        if _portrait_continue_promo_visible(ocr_pre_spin):
            logger.warning("⚠️ Continue promo still visible; skipping spin VLM this attempt.")
            artifact_handler.capture(page, f"debug_spin_blocked_intro_{attempt_idx}", category="debug")
            return None, False

    spin_coords = _detect_spin_bbox(hybrid_locator.vision, screenshot_bytes, spin_config)

    if not spin_coords:
        if spin_config and spin_config.get("_layout") == LAYOUT_PORTRAIT:
            cx, cy = _spin_region_center_viewport(page, spin_config)
            logger.warning(
                f"⚠️ VLM failed to find Spin Button; portrait region-center fallback at ({cx:.1f}, {cy:.1f})"
            )
            artifact_handler.capture(page, f"debug_spin_vlm_fallback_{attempt_idx}", category="debug")
            candidates, delta = _portrait_spin_fallback_candidates(page, spin_config)
            logger.info(
                f"🎯 Portrait fallback center ({cx:.1f}, {cy:.1f}), offset Δ={delta:.1f}, "
                f"multi-point ({len(candidates)} pts)"
            )
            coords, from_cache = _try_spin_click_candidates(
                page,
                artifact_handler,
                hybrid_locator,
                cache_key,
                game_id,
                attempt_idx,
                candidates,
                [],
                screenshot_bytes,
                success_check,
                success_check_timeout,
                grace_sec=grace_sec,
                game_config=spin_config,
                reel_before=reel_before,
                before_primary=before_primary,
            )
            return coords, from_cache
        logger.warning("⚠️ VLM failed to find Spin Button.")
        artifact_handler.capture(page, f"debug_spin_not_found_{attempt_idx}", category="debug")
        return None, False

    cx, cy, x1, y1, x2, y2 = _vlm_bbox_to_viewport_rect(spin_coords, screenshot_bytes, page)
    loose = _is_loose_bbox_in_region(spin_coords, spin_config)
    cx, cy, snapped = _vlm_snap_click_anchor(
        page, spin_config, cx, cy, loose=loose
    )
    if snapped:
        vp_w = page.viewport_size["width"]
        vp_h = page.viewport_size["height"]
        pad_x = max(20.0, vp_w * 0.015)
        pad_y = max(20.0, vp_h * 0.015)
        x1, y1, x2, y2 = cx - pad_x, cy - pad_y, cx + pad_x, cy + pad_y
    candidates, delta = build_spin_click_candidates(
        cx, cy, x1, y1, x2, y2, page, spin_config, spin_coords if not snapped else None
    )
    logger.info(
        f"🎯 VLM bbox center ({cx:.1f}, {cy:.1f}), offset Δ={delta:.1f}, "
        f"loose_bbox={loose}, {'multi-point' if success_check else 'center-only'} "
        f"({len(candidates if success_check else candidates[:1])} pts)"
    )

    coords, from_cache = _try_spin_click_candidates(
        page,
        artifact_handler,
        hybrid_locator,
        cache_key,
        game_id,
        attempt_idx,
        candidates,
        spin_coords,
        screenshot_bytes,
        success_check,
        success_check_timeout,
        grace_sec=grace_sec,
        game_config=spin_config,
        reel_before=reel_before,
        before_primary=before_primary,
    )
    return coords, from_cache


def verify_spin_settlement(console_listener, tolerance: float = 0.01) -> tuple[bool, str, dict]:
    """Verify B1 = B0 - Bet + Win from console listener state."""
    summary = console_listener.get_settlement_summary()
    b0, b1, bet, win = summary["b0"], summary["b1"], summary["bet"], summary["win"]

    missing = [
        name
        for name, val in [
            ("balance_before_spin", b0),
            ("balance_after_settle", b1),
            ("bet_amount", bet),
        ]
        if val is None
    ]
    if missing:
        return False, f"Missing settlement fields: {', '.join(missing)}", summary

    if not console_listener.get_hint("spin_triggered"):
        return False, "Spin was not triggered (no SpinTriggerDispatchEvent)", summary
    if not console_listener.has_spin_acknowledged():
        return (
            False,
            "Missing spin server response (ReciviedSpinResponse or Spin response Code=0 with TxnId)",
            summary,
        )
    if not console_listener.get_hint("spin_response_ok"):
        return False, "Spin response Code != 0", summary

    after_bet = console_listener.get_hint("balance_after_bet")
    if after_bet is not None and b1 is not None and bet is not None:
        post_bet_drop = round(after_bet - b1, 4)
        if post_bet_drop > tolerance and abs(post_bet_drop - bet) <= tolerance:
            return (
                False,
                f"Possible double spin: balance dropped {post_bet_drop} after first bet "
                f"(single spin should not deduct bet twice)",
                summary,
            )

    if win is None:
        win = round(b1 - b0 + bet, 4)
        summary["win"] = win

    expected_b1 = round(b0 - bet + win, 4)
    if abs(b1 - expected_b1) > tolerance:
        return (
            False,
            f"Balance formula mismatch: B0={b0}, Bet={bet}, Win={win}, "
            f"expected B1={expected_b1}, actual B1={b1}",
            summary,
        )

    total_win_raw = summary.get("total_win_raw")
    if total_win_raw is not None:
        try:
            json_win = int(total_win_raw) / 10000
            if abs(json_win - win) > tolerance:
                logger.warning(
                    f"TotalWin/10000 ({json_win}) differs from formula win ({win}); "
                    "using balance formula as authority."
                )
        except (ValueError, TypeError):
            pass

    logger.info(
        f"✅ Settlement verified: B0={b0}, Bet={bet}, Win={win}, B1={b1}, "
        f"TxnId={summary.get('txn_id')}"
    )
    return True, "OK", summary


def verify_final_balance_integrity(
    page,
    hybrid_locator,
    target_balance,
    artifact_handler,
    round_idx="Check",
):
    """🔥 [嚴格查帳] 確認畫面上的餘額與 Log 完全一致。"""
    if target_balance is None:
        return True

    logger.info(f"🧾 Auditing Balance... Target: {target_balance}")

    screenshot = page.screenshot()
    with io.BytesIO(screenshot) as f:
        img = Image.open(f)
        w, h = img.size
        crop = io.BytesIO()
        img.crop((0, int(h * 0.8), w, h)).save(crop, format="PNG")
        ocr_res = hybrid_locator.ocr.reader.readtext(crop.getvalue())

    screen_nums = extract_balance(ocr_res)

    if any(abs(n - target_balance) < 0.1 for n in screen_nums):
        logger.info("✅ Audit Passed: Balance Matched.")
        return True

    logger.error(f"❌ Audit Failed! Target {target_balance} NOT found in {screen_nums}")
    artifact_handler.capture(
        page,
        f"audit_fail_{round_idx}",
        category="failures",
        attach_to_allure=True,
    )
    return False


def check_for_big_win_animation(page, hybrid_locator):
    """檢查畫面是否有 Big Win / Mega Win 動畫。"""
    screenshot = page.screenshot()
    ocr_res = hybrid_locator.ocr.reader.readtext(screenshot)
    text = " ".join([res[1].lower() for res in ocr_res])

    keywords = ["big win", "mega win", "super win", "epic win", "total win"]
    if any(k in text for k in keywords):
        logger.info("💰 Big Win Animation Detected! Clicking to skip...")
        w = page.viewport_size["width"]
        h = page.viewport_size["height"]
        page.mouse.click(w / 2, h / 2)
        time.sleep(3.5)
        return True
    return False


def _unity_canvas_visible(page, expected_host: str | None = None) -> bool:
    """True when any page/frame shows a Unity canvas with usable intrinsic size."""
    for ctx in iter_game_contexts(page, expected_host):
        if unity_canvas_ready(ctx):
            return True
    return False


def _page_looks_like_jc_lobby(ocr_results) -> bool:
    """True on JC platform lobby (balance in header/sidebar must not count as in-game)."""
    all_text = " ".join([res[1].lower() for res in ocr_results])
    if "jackpot combo" not in all_text:
        return False
    nav_hits = sum(1 for tab in JC_LOBBY_NAV_TABS if tab in all_text)
    marker_hits = sum(1 for marker in JC_LOBBY_MARKERS if marker in all_text)
    return nav_hits >= 3 and marker_hits >= 2


def _page_looks_like_external_redirect(page, ocr_results) -> bool:
    """True when navigation landed on an ad / travel site instead of the game."""
    url = (page.url or "").lower()
    if any(host in url for host in ("agoda.", "booking.com", "trip.com")):
        return True
    all_text = " ".join([res[1].lower() for res in ocr_results])
    return any(marker in all_text for marker in EXTERNAL_REDIRECT_MARKERS)


def _game_entry_context_ok(page, ocr_results) -> bool:
    """Hard gate: reject lobby false-positives and off-platform redirects."""
    if _page_looks_like_jc_lobby(ocr_results):
        logger.debug("Game load: still on JC lobby (rejecting ready gate).")
        return False
    if _page_looks_like_external_redirect(page, ocr_results):
        logger.warning("⚠️ Game load: external redirect detected (not in-game).")
        return False
    if not _unity_canvas_visible(page):
        logger.debug("Game load: Unity canvas not visible yet.")
        return False
    return True


def _click_open_game_page(page, x: float, y: float, *, timeout_sec: float = 8.0):
    """Click game icon; return a newly opened tab when JC opens the game in a popup."""
    pages_before = list(page.context.pages)
    page.mouse.click(x, y)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for candidate in page.context.pages:
            if candidate in pages_before or candidate.is_closed():
                continue
            try:
                candidate.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            logger.info("🪟 Game opened in new tab; switching automation to game page.")
            return candidate
        time.sleep(0.3)
    return page


def portrait_load_ui_footer_regions(page, game_config: dict | None) -> list[dict]:
    """Footer OCR regions for portrait-load ready detection.

    FC titles already entered the portrait load path — use mid-strip + bottom bar
    without requiring ``use_fc_portrait_footer_strip`` (layout may not be on yaml yet).
    """
    if _game_config_is_fc(game_config) or _game_config_is_jdb(game_config):
        if _game_config_is_jdb(game_config):
            bases = (
                JDB_PORTRAIT_ICON_STRIP_REGION,
                JDB_PORTRAIT_ICON_STRIP_BOTTOM_REGION,
                FC_PORTRAIT_BALANCE_REGION,
                FC_PORTRAIT_FOOTER_REGION,
                FC_PORTRAIT_BOTTOM_BALANCE_REGION,
                PORTRAIT_FOOTER_REGION,
            )
        else:
            bases = (
                FC_PORTRAIT_BALANCE_REGION,
                FC_PORTRAIT_FOOTER_REGION,
                FC_PORTRAIT_BOTTOM_BALANCE_REGION,
                PORTRAIT_FOOTER_REGION,
            )
    else:
        bases = (portrait_footer_region(game_config, page),)
    regions: list[dict] = []
    seen: set[tuple] = set()
    for base in bases:
        mapped = map_footer_region_to_viewport(page, base)
        sig = _footer_region_tuple(mapped)
        if sig in seen:
            continue
        seen.add(sig)
        regions.append(mapped)
    return regions


def _footer_region_has_load_ui(footer_ocr) -> bool:
    footer_text = " ".join([res[1].lower() for res in footer_ocr])
    if any(k in footer_text for k in PORTRAIT_LOAD_UI_KEYWORDS):
        return True
    if re.search(r"\b\d{1,3}(?:,\d{3})*\.\d{2,3}\b", footer_text):
        return True
    if extract_balance(footer_ocr):
        return True
    return False


def portrait_game_ui_detected(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    *,
    game_config: dict | None = None,
    all_text: str | None = None,
    footer_region: dict | None = None,
    footer_regions: list[dict] | None = None,
) -> bool:
    """True when portrait footer shows balance/bet UI (mid-strip and/or bottom bar)."""
    del all_text  # ready gate must use footer crop (avoid lobby sidebar false positives)
    if footer_regions is not None:
        regions = footer_regions
    elif footer_region is not None:
        regions = [footer_region]
    else:
        regions = [
            portrait_footer_region(game_config, page),
        ]
        # When page is available and FC portrait strip applies, also try load regions.
        if page is not None and (
            use_fc_portrait_footer_strip(game_config, page)
            or use_jdb_portrait_footer_strip(game_config, page)
            or _game_config_is_fc(game_config)
            or _game_config_is_jdb(game_config)
        ):
            # Prefer full FC mid+bottom set when caller did not pass regions
            # (portrait_footer_region alone may be narrow if layout gate fails).
            regions = portrait_load_ui_footer_regions(page, game_config)

    for region in regions:
        footer_ocr = _ocr_results_in_fraction_region(
            ocr_results, screenshot_bytes, page, region
        )
        if _footer_region_has_load_ui(footer_ocr):
            return True
    return False


def _portrait_intro_active(ocr_results) -> bool:
    """Deprecated alias: use _portrait_continue_promo_visible for ready gates."""
    return _portrait_continue_promo_visible(ocr_results)


def _try_click_landscape_splash_continue(
    page,
    hybrid_locator,
    artifact_handler,
    screenshot_bytes: bytes,
    ocr_results,
    *,
    tag: str,
) -> bool:
    """Click Continue on landscape intro splash (loose OCR + VLM, no portrait y-cap)."""
    continue_targets = [res for res in ocr_results if _is_loose_continue_label(res[1])]
    if continue_targets:
        cx, cy = _pick_continue_click(
            continue_targets,
            screenshot_bytes,
            page,
            portrait=False,
        )
        label = continue_targets[0][1]
        logger.info(
            f"✅ Landscape splash ({tag}): OCR '{label}' at ({cx:.0f}, {cy:.0f})"
        )
        page.mouse.click(cx, cy)
        artifact_handler.capture(page, f"landscape_splash_{tag}_ocr", category="setup")
        time.sleep(2)
        return True

    logger.info(f"🔍 Landscape splash ({tag}): trying VLM for Continue...")
    try:
        from core.vision_client import VisionClient

        vc = VisionClient()
        coords = vc.detect_ui_element(
            screenshot_bytes,
            "the Continue button on the game intro splash screen, not the spin button",
        )
        if coords:
            splash_img = Image.open(io.BytesIO(screenshot_bytes))
            vp_w = page.viewport_size["width"]
            dpr = splash_img.width / vp_w if vp_w > 0 else 1.0
            cx = ((coords[0] + coords[2]) / 2 / 1000.0) * splash_img.width / dpr
            cy = ((coords[1] + coords[3]) / 2 / 1000.0) * splash_img.height / dpr
            logger.info(f"✅ Landscape splash ({tag}): VLM Continue at ({cx:.0f}, {cy:.0f})")
            page.mouse.click(cx, cy)
            artifact_handler.capture(page, f"landscape_splash_{tag}_vlm", category="setup")
            time.sleep(2)
            return True
    except Exception as exc:
        logger.debug(f"Landscape splash VLM Continue failed: {exc}")
    return False


def dismiss_landscape_intro_carousel(
    page,
    hybrid_locator,
    artifact_handler,
    *,
    max_rounds: int = PORTRAIT_MAX_INTRO_ROUNDS,
) -> int:
    """Advance landscape intro slides until no Continue splash is visible."""
    clicks = 0
    for round_idx in range(max_rounds):
        screenshot_bytes = page.screenshot()
        ocr_results = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
        if not _splash_continue_visible(ocr_results):
            break
        if not _try_click_landscape_splash_continue(
            page,
            hybrid_locator,
            artifact_handler,
            screenshot_bytes,
            ocr_results,
            tag=f"round{round_idx + 1}",
        ):
            logger.warning(
                f"⚠️ Landscape intro slide {round_idx + 1} visible but not clicked."
            )
            break
        clicks += 1
        time.sleep(1.0)
    return clicks


def _try_click_portrait_continue(
    page,
    hybrid_locator,
    artifact_handler,
    screenshot_bytes: bytes,
    ocr_results,
    *,
    tag: str,
    game_config: dict | None = None,
) -> bool:
    """Click Continue on intro slides; Start/Play only inside intro click region."""
    targets = _collect_portrait_intro_click_targets(
        ocr_results, screenshot_bytes, page, game_config
    )
    if targets:
        cx, cy = _pick_continue_click(
            targets,
            screenshot_bytes,
            page,
            portrait=True,
        )
        label = targets[0][1]
        logger.info(
            f"✅ Portrait intro ({tag}): OCR '{label}' at ({cx:.0f}, {cy:.0f})"
        )
        page.mouse.click(cx, cy)
        artifact_handler.capture(page, f"portrait_intro_{tag}_ocr", category="setup")
        time.sleep(2)
        return True

    if not _portrait_intro_dismissable(ocr_results, screenshot_bytes, page, game_config):
        return False

    logger.info(f"🔍 Portrait intro ({tag}): trying VLM for Continue/START...")
    try:
        from core.vision_client import VisionClient

        vc = VisionClient()
        if _game_config_is_jdb(game_config):
            prompt = (
                "the large yellow or cream START button with the text START "
                "at the bottom center of the game splash screen, not the spin button"
            )
            y_max_frac = 0.95
        else:
            prompt = (
                "the Continue button with the text Continue on the intro splash screen, "
                "not the spin button"
            )
            y_max_frac = 0.78
        coords = vc.detect_ui_element(screenshot_bytes, prompt)
        if coords:
            splash_img = Image.open(io.BytesIO(screenshot_bytes))
            vp_w = page.viewport_size["width"]
            vp_h = page.viewport_size["height"]
            dpr = splash_img.width / vp_w if vp_w > 0 else 1.0
            cx = ((coords[0] + coords[2]) / 2 / 1000.0) * splash_img.width / dpr
            cy = ((coords[1] + coords[3]) / 2 / 1000.0) * splash_img.height / dpr
            if cy > vp_h * y_max_frac:
                logger.warning(
                    f"⚠️ Portrait intro VLM at ({cx:.0f},{cy:.0f}) too low; skip."
                )
                return False
            logger.info(f"✅ Portrait intro ({tag}): VLM at ({cx:.0f}, {cy:.0f})")
            page.mouse.click(cx, cy)
            artifact_handler.capture(page, f"portrait_intro_{tag}_vlm", category="setup")
            time.sleep(2)
            return True
    except Exception as exc:
        logger.debug(f"Portrait intro VLM failed: {exc}")
    return False


def dismiss_portrait_intro_carousel(
    page,
    hybrid_locator,
    artifact_handler,
    *,
    max_rounds: int = PORTRAIT_MAX_INTRO_ROUNDS,
    game_config: dict | None = None,
) -> int:
    """Advance portrait intro/promo slides until no Continue promo / weak intro in zone."""
    clicks = 0
    for round_idx in range(max_rounds):
        screenshot_bytes = page.screenshot()
        ocr_results = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
        if not _portrait_intro_dismissable(
            ocr_results, screenshot_bytes, page, game_config
        ):
            break
        if not _try_click_portrait_continue(
            page,
            hybrid_locator,
            artifact_handler,
            screenshot_bytes,
            ocr_results,
            tag=f"round{round_idx + 1}",
            game_config=game_config,
        ):
            logger.warning(
                f"⚠️ Portrait intro slide {round_idx + 1} detected but not clicked."
            )
            break
        clicks += 1
        time.sleep(1.0)
    if clicks:
        logger.info(f"✅ Dismissed {clicks} portrait intro slide(s).")
    return clicks


def _portrait_ready_for_gameplay(
    ocr_results,
    screenshot_bytes: bytes,
    page,
    all_text: str,
    game_config: dict | None,
    *,
    version_match,
    loading_detected: bool,
    stable_loops: int,
) -> bool:
    if loading_detected:
        return False
    if any(k in all_text for k in ("cmb", "switch environment")):
        return False
    if _portrait_continue_promo_visible(ocr_results):
        return False
    if not _game_entry_context_ok(page, ocr_results):
        return False
    load_regions = portrait_load_ui_footer_regions(page, game_config)
    if not portrait_game_ui_detected(
        ocr_results,
        screenshot_bytes,
        page,
        game_config=game_config,
        all_text=all_text,
        footer_regions=load_regions,
    ):
        return False
    if version_match:
        return True
    return stable_loops >= PORTRAIT_READY_STABLE_LOOPS


def _dismiss_error_dialog_if_present(
    page,
    temp_ocr_results,
    current_screenshot,
    artifact_handler,
) -> bool:
    all_text = " ".join([res[1].lower() for res in temp_ocr_results])
    error_keywords = [
        "system error",
        "error occurred",
        "something went wrong",
        "network error",
        *GAME_LAUNCH_ERROR_KEYWORDS,
    ]
    dismiss_keywords = ["ok", "close", "confirm", "retry", "dismiss", "yes"]
    if not any(k in all_text for k in error_keywords):
        return False

    logger.warning("⚠️ System error dialog detected! Attempting to dismiss...")
    artifact_handler.capture(
        page,
        "system_error_dialog",
        category="failures",
        attach_to_allure=True,
    )
    dismiss_btns = [
        res
        for res in temp_ocr_results
        if any(x in res[1].lower() for x in dismiss_keywords)
    ]
    if dismiss_btns:
        btn_bbox = dismiss_btns[0][0]
        splash_img = Image.open(io.BytesIO(current_screenshot))
        vp_w = page.viewport_size["width"]
        dpr = splash_img.width / vp_w if vp_w > 0 else 1.0
        cx = (btn_bbox[0][0] + btn_bbox[2][0]) / 2 / dpr
        cy = (btn_bbox[0][1] + btn_bbox[2][1]) / 2 / dpr
        logger.info(
            f"✅ Clicking dismiss button '{dismiss_btns[0][1]}' at ({cx:.0f}, {cy:.0f})",
        )
        page.mouse.click(cx, cy)
    else:
        w = page.viewport_size["width"]
        h = page.viewport_size["height"]
        page.mouse.click(w / 2, h / 2)
    time.sleep(2)
    return True


def _wait_for_portrait_unity_game_load(page, hybrid_locator, artifact_handler, game_config) -> bool:
    """Portrait load: dismiss intro, ready = footer UI + no Continue promo."""
    logger.info("⏳ Portrait game load started (max 120s)")
    time.sleep(3)
    start_time = time.time()
    stable_ready_loops = 0
    last_heartbeat = start_time

    while time.time() - start_time < 120:
        now = time.time()
        if now - last_heartbeat >= 15:
            logger.info("⏳ Portrait load… %.0fs", now - start_time)
            last_heartbeat = now
        current_screenshot = page.screenshot()
        temp_ocr_results = hybrid_locator.ocr.reader.readtext(current_screenshot)
        all_text = " ".join([res[1].lower() for res in temp_ocr_results])

        if _fatal_game_launch_error(temp_ocr_results):
            logger.error("❌ Game launch error detected; aborting portrait load wait.")
            artifact_handler.capture(
                page,
                "fail_game_launch_error",
                category="failures",
                attach_to_allure=True,
            )
            return False

        if _network_error_present(temp_ocr_results):
            logger.error("❌ Network error at game launch; aborting portrait load wait.")
            set_entry_error_reason(game_config, "network error")
            artifact_handler.capture(
                page,
                "fail_network_error",
                category="failures",
                attach_to_allure=True,
            )
            return False

        if _dismiss_error_dialog_if_present(
            page, temp_ocr_results, current_screenshot, artifact_handler
        ):
            stable_ready_loops = 0
            continue

        if _portrait_intro_dismissable(
            temp_ocr_results, current_screenshot, page, game_config
        ):
            _try_click_portrait_continue(
                page,
                hybrid_locator,
                artifact_handler,
                current_screenshot,
                temp_ocr_results,
                tag="load",
                game_config=game_config,
            )
            stable_ready_loops = 0
            time.sleep(1.5)
            continue

        # Extra Bet teaching overlays often block footer primary balance OCR.
        if dismiss_extra_bet_teaching_overlay_if_present(
            page,
            hybrid_locator,
            artifact_handler,
            game_config=game_config,
            tag="load_portrait",
            screenshot_bytes=current_screenshot,
            ocr_results=temp_ocr_results,
            use_vlm_fallback=False,
        ):
            stable_ready_loops = 0
            continue

        if _page_looks_like_external_redirect(page, temp_ocr_results):
            stable_ready_loops = 0
            time.sleep(2)
            continue

        loading_detected = any(k in all_text for k in PORTRAIT_LOADING_KEYWORDS)
        version_match = _game_version_detected(all_text)

        if _portrait_ready_for_gameplay(
            temp_ocr_results,
            current_screenshot,
            page,
            all_text,
            game_config,
            version_match=version_match,
            loading_detected=loading_detected,
            stable_loops=stable_ready_loops,
        ):
            dismiss_portrait_intro_carousel(
                page, hybrid_locator, artifact_handler, game_config=game_config
            )
            screenshot_after = page.screenshot()
            ocr_after = hybrid_locator.ocr.reader.readtext(screenshot_after)
            if _portrait_continue_promo_visible(ocr_after):
                logger.debug("Continue promo still visible after sweep; continuing...")
                stable_ready_loops = 0
                time.sleep(2)
                continue
            logger.info("✅ Portrait game loaded (%.0fs)", time.time() - start_time)
            artifact_handler.capture(
                page,
                "v_game_loaded_success",
                category="setup",
                attach_to_allure=True,
            )
            return True

        if portrait_game_ui_detected(
            temp_ocr_results,
            current_screenshot,
            page,
            game_config=game_config,
            all_text=all_text,
            footer_regions=portrait_load_ui_footer_regions(page, game_config),
        ) and not _portrait_continue_promo_visible(temp_ocr_results) and not loading_detected:
            stable_ready_loops += 1
        else:
            stable_ready_loops = 0

        if loading_detected or not version_match:
            _try_click_portrait_continue(
                page,
                hybrid_locator,
                artifact_handler,
                current_screenshot,
                temp_ocr_results,
                tag="bundle",
                game_config=game_config,
            )

        time.sleep(2)

    logger.warning("⚠️ Portrait game load wait timeout (120s).")
    artifact_handler.capture(
        page,
        "v_game_load_timeout",
        category="failures",
        attach_to_allure=True,
    )
    return False


def _wait_for_landscape_unity_game_load(
    page, hybrid_locator, artifact_handler, game_config=None
) -> bool:
    """Landscape load: wait for progress bar, dismiss splash Continue, then footer UI."""
    logger.info("⏳ Landscape game load started (max 120s)")
    time.sleep(3)

    start_time = time.time()
    stable_ready_loops = 0
    last_heartbeat = start_time
    while time.time() - start_time < 120:
        now = time.time()
        if now - last_heartbeat >= 15:
            logger.info("⏳ Landscape load… %.0fs", now - start_time)
            last_heartbeat = now
        current_screenshot = page.screenshot()
        temp_ocr_results = hybrid_locator.ocr.reader.readtext(current_screenshot)
        all_text = " ".join([res[1].lower() for res in temp_ocr_results])
        splash_continue = _splash_continue_visible(temp_ocr_results)

        if _network_error_present(temp_ocr_results):
            logger.error("❌ Network error at game launch; aborting landscape load wait.")
            set_entry_error_reason(game_config, "network error")
            artifact_handler.capture(
                page,
                "fail_network_error",
                category="failures",
                attach_to_allure=True,
            )
            return False

        if _dismiss_error_dialog_if_present(
            page, temp_ocr_results, current_screenshot, artifact_handler
        ):
            stable_ready_loops = 0
            continue

        if splash_continue:
            _try_click_landscape_splash_continue(
                page,
                hybrid_locator,
                artifact_handler,
                current_screenshot,
                temp_ocr_results,
                tag="load",
            )
            stable_ready_loops = 0
            time.sleep(1.5)
            continue

        # Landscape still may show teaching overlays.
        if dismiss_extra_bet_teaching_overlay_if_present(
            page,
            hybrid_locator,
            artifact_handler,
            game_config=game_config,
            tag="load_landscape",
            screenshot_bytes=current_screenshot,
            ocr_results=temp_ocr_results,
            use_vlm_fallback=_overlay_vlm_fallback_allowed(game_config),
        ):
            stable_ready_loops = 0
            continue

        if _loading_phase_detected(all_text):
            logger.debug("⏳ Landscape loading phase (progress / InitWaiting); waiting...")
            stable_ready_loops = 0
            time.sleep(2)
            continue

        if _landscape_footer_ready(
            temp_ocr_results, current_screenshot, page, game_config
        ):
            stable_ready_loops += 1
        else:
            stable_ready_loops = 0

        if stable_ready_loops >= PORTRAIT_READY_STABLE_LOOPS:
            if not _game_entry_context_ok(page, temp_ocr_results):
                stable_ready_loops = 0
                time.sleep(2)
                continue
            dismiss_landscape_intro_carousel(page, hybrid_locator, artifact_handler)
            logger.info("✅ Landscape game loaded (%.0fs)", time.time() - start_time)
            artifact_handler.capture(
                page,
                "v_game_loaded_success",
                category="setup",
                attach_to_allure=True,
            )
            return True

        time.sleep(2)

    logger.warning("⚠️ Landscape game load wait timeout (120s).")
    artifact_handler.capture(
        page,
        "v_game_load_timeout",
        category="failures",
        attach_to_allure=True,
    )
    return False


def wait_for_unity_game_load(page, hybrid_locator, artifact_handler, game_config=None):
    """動態等待 Unity 遊戲載入 (Max 120s)。直版與橫版分流，互不干擾。"""
    if game_config:
        provisional = _provisional_layout_for_load(game_config, page, hybrid_locator)
    else:
        provisional = LAYOUT_LANDSCAPE

    if provisional == LAYOUT_PORTRAIT:
        loaded = _wait_for_portrait_unity_game_load(
            page, hybrid_locator, artifact_handler, game_config
        )
    else:
        loaded = _wait_for_landscape_unity_game_load(
            page, hybrid_locator, artifact_handler, game_config
        )

    if loaded and game_config:
        previous = game_config.get(_RESOLVED_LAYOUT_KEY)
        layout = resolve_game_layout(
            game_config,
            page,
            hybrid_locator,
            refresh=True,
            footer_first=True,
        )
        if layout == LAYOUT_PORTRAIT and previous != LAYOUT_PORTRAIT:
            dismiss_portrait_intro_carousel(
                page, hybrid_locator, artifact_handler, game_config=game_config
            )
    return loaded


def _overlay_vlm_fallback_allowed(game_config: dict | None) -> bool:
    """VLM overlay probe — disabled for JDB (OCR-only; VLM false-positives common)."""
    if not game_config:
        return False
    if _game_config_is_jdb(game_config):
        return False
    probe = int(game_config.get(_OVERLAY_PROBE_COUNT_KEY) or 0)
    game_config[_OVERLAY_PROBE_COUNT_KEY] = probe + 1
    return probe < 2


def navigate_to_game(page, hybrid_locator, ui_scanner, game_config, artifact_handler):
    """[完整版] 進入遊戲流程：
    1. 點擊搜尋欄  2. 輸入關鍵字
    3. 點擊 Icon (OCR 優先 -> VLM Fallback)
    4. 等待載入
    """
    logger.info(f"🚀 Navigating to game: {game_config['name']}...")
    set_entry_error_reason(game_config, None)

    search_bar = _resolve_lobby_search_bar(page, ui_scanner, hybrid_locator)
    if not search_bar:
        artifact_handler.capture(
            page,
            "fail_search_bar_missing",
            category="failures",
            attach_to_allure=True,
        )
        return False

    logger.info("Clicking Search Bar...")
    page.mouse.click(*search_bar)
    time.sleep(2)

    overlay_scan = ui_scanner(context="lobby")
    real_input = overlay_scan.get("search_overlay_input")

    if not real_input:
        screenshot = page.screenshot()
        vlm_input = hybrid_locator.vision.detect_ui_element(
            screenshot,
            "white search input field text box with magnifying glass",
        )
        coords = _vlm_coords_to_viewport(page, vlm_input, screenshot)
        if _vlm_search_coords_valid(page, coords, vlm_input):
            real_input = coords

    if real_input:
        page.mouse.click(*real_input)
        time.sleep(0.5)

    logger.info(f"Typing: {game_config['search_keyword']}")
    page.keyboard.type(game_config["search_keyword"])
    time.sleep(0.5)
    artifact_handler.capture(page, f"setup_input_{game_config['search_keyword']}", category="setup")
    page.keyboard.press("Enter")
    time.sleep(5)

    page = _click_search_result_game(
        page, hybrid_locator, ui_scanner, game_config, artifact_handler
    )
    if page is None:
        return False

    game_config[_ACTIVE_GAME_PAGE_KEY] = page

    if not wait_for_unity_game_load(page, hybrid_locator, artifact_handler, game_config):
        return False

    verify_shot = page.screenshot()
    verify_ocr = hybrid_locator.ocr.reader.readtext(verify_shot)
    if not _game_entry_context_ok(page, verify_ocr):
        artifact_handler.capture(
            page,
            "fail_game_entry_verify",
            category="failures",
            attach_to_allure=True,
        )
        return False

    return True
