"""Auto-detect portrait vs landscape game layout (canvas + OCR footer heuristics)."""

from __future__ import annotations

import io
import logging
import re
import time

from PIL import Image

from core.game_frame_utils import canvas_layout_metrics, iter_game_contexts
from core.canvas_region import canvas_fills_viewport_width

logger = logging.getLogger(__name__)

LAYOUT_PORTRAIT = "portrait"
LAYOUT_LANDSCAPE = "landscape"
PORTRAIT_CANVAS_ASPECT_THRESHOLD = 1.05
FOOTER_LAYOUT_Y_START = 0.62
FOOTER_LAYOUT_KEYWORDS = (
    "balance",
    "total bet",
    "total",
    "credit",
    "autospin",
    "auto spin",
    "win:",
    "win ",
)
# Portrait letterbox footers are a narrow centered column; compact landscape bars
# (span ~0.4) must not qualify — use fuse_layout_signals + yaml hints instead.
FOOTER_PORTRAIT_MAX_SPAN = 0.35
FOOTER_LANDSCAPE_MIN_SPAN = 0.62
FOOTER_PORTRAIT_CENTER_MIN = 0.22
FOOTER_PORTRAIT_CENTER_MAX = 0.78
FOOTER_CURRENCY_RE = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b")
FOOTER_BET_CURRENCY_RE = re.compile(r"\bP\s*[\d,]+(?:\.\d{2})?\b", re.I)
_LAYOUT_PROBE_HOST_KEY = "_layout_probe_host"


def layout_ratio_is_portrait(ratio: float) -> bool:
    return ratio >= PORTRAIT_CANVAS_ASPECT_THRESHOLD


def layout_from_canvas_metrics(metrics: dict | None) -> str | None:
    if not metrics:
        return None
    display_ratio = float(metrics.get("display_ratio") or 0)
    intrinsic_ratio = float(metrics.get("intrinsic_ratio") or 0)
    if layout_ratio_is_portrait(display_ratio):
        return LAYOUT_PORTRAIT
    if layout_ratio_is_portrait(intrinsic_ratio):
        return LAYOUT_PORTRAIT
    if display_ratio > 0 and display_ratio <= (1.0 / PORTRAIT_CANVAS_ASPECT_THRESHOLD):
        return LAYOUT_LANDSCAPE
    if intrinsic_ratio > 0:
        return LAYOUT_LANDSCAPE
    return None


def sample_canvas_layout(page, expected_host: str | None = None) -> str | None:
    """Detect layout from Unity canvas in page + frames (cross-origin iframe safe)."""
    best_metrics = None
    best_area = 0.0
    for ctx in iter_game_contexts(page, expected_host):
        metrics = canvas_layout_metrics(ctx)
        if not metrics:
            continue
        area = float(metrics.get("area") or 0)
        if area > best_area:
            best_area = area
            best_metrics = metrics
    return layout_from_canvas_metrics(best_metrics)


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


def _footer_keyword_match(text: str) -> bool:
    """Match footer UI labels without substring false positives (e.g. 'bet' in 'alphabet')."""
    lowered = text.lower()
    for keyword in FOOTER_LAYOUT_KEYWORDS:
        if keyword in ("total bet", "auto spin", "win:", "win "):
            if keyword in lowered:
                return True
        elif re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return True
    return False


def _is_footer_ui_text(text: str) -> bool:
    if _footer_keyword_match(text):
        return True
    if FOOTER_CURRENCY_RE.search(text):
        return True
    if FOOTER_BET_CURRENCY_RE.search(text):
        return True
    return False


def layout_from_footer_ocr(ocr_results, screenshot_bytes: bytes, page) -> str | None:
    """Portrait COMBO games: footer UI sits in a narrow centered column (letterboxed)."""
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    if not vp_w or not vp_h:
        return None
    footer_y_min = vp_h * FOOTER_LAYOUT_Y_START
    centers_x: list[float] = []
    below_threshold = 0
    for res in ocr_results:
        text = res[1]
        if not _is_footer_ui_text(text):
            continue
        _cx, cy = _bbox_center_viewport(res[0], screenshot_bytes, page)
        if cy < footer_y_min:
            below_threshold += 1
            continue
        centers_x.append(_cx / vp_w)

    if not centers_x:
        logger.info(
            f"📐 Footer OCR layout: no footer UI hits "
            f"(y>={FOOTER_LAYOUT_Y_START:.0%}, below_y={below_threshold})"
        )
        return None

    span = max(centers_x) - min(centers_x)
    mid = (max(centers_x) + min(centers_x)) / 2
    if (
        span <= FOOTER_PORTRAIT_MAX_SPAN
        and FOOTER_PORTRAIT_CENTER_MIN <= mid <= FOOTER_PORTRAIT_CENTER_MAX
    ):
        logger.info(
            f"📐 Footer OCR layout: portrait (span={span:.2f}, center_x={mid:.2f}, n={len(centers_x)})"
        )
        return LAYOUT_PORTRAIT
    if span >= FOOTER_LANDSCAPE_MIN_SPAN:
        logger.info(
            f"📐 Footer OCR layout: landscape (span={span:.2f}, center_x={mid:.2f}, n={len(centers_x)})"
        )
        return LAYOUT_LANDSCAPE
    logger.info(
        f"📐 Footer OCR layout: inconclusive (span={span:.2f}, center_x={mid:.2f}, "
        f"n={len(centers_x)})"
    )
    return None


def fuse_layout_signals(
    canvas_layout: str | None,
    footer_layout: str | None,
    *,
    portrait_hint: bool = False,
    landscape_hint: bool = False,
    canvas_rect: dict | None = None,
) -> str | None:
    """Combine canvas, footer OCR, and games.yaml spin-region hints.

    Letterboxed COMBO portrait: canvas=landscape + footer=portrait → portrait.
    Landscape with compact footer (Magic Runes): canvas=landscape + yaml bottom-right
    spin region → landscape even when footer OCR is inconclusive or wrong.
    Pillarboxed games (canvas width < 85% viewport): yaml bottom-right alone does not
    override footer portrait letterbox detection.
    """
    effective_landscape_hint = landscape_hint and (
        canvas_rect is None or canvas_fills_viewport_width(canvas_rect, min_width_frac=0.85)
    )

    if canvas_layout == LAYOUT_PORTRAIT:
        logger.info("📐 Fused layout: portrait (canvas)")
        return LAYOUT_PORTRAIT

    if canvas_layout == LAYOUT_LANDSCAPE and footer_layout == LAYOUT_PORTRAIT:
        if effective_landscape_hint and not portrait_hint:
            logger.info(
                "📐 Fused layout: landscape (canvas + yaml bottom-right spin; "
                "footer portrait ignored)"
            )
            return LAYOUT_LANDSCAPE
        logger.info(
            "📐 Fused layout: portrait (letterbox: canvas landscape + footer portrait)"
        )
        return LAYOUT_PORTRAIT

    if footer_layout == LAYOUT_LANDSCAPE:
        logger.info("📐 Fused layout: landscape (footer OCR)")
        return LAYOUT_LANDSCAPE

    if footer_layout == LAYOUT_PORTRAIT and not landscape_hint:
        logger.info("📐 Fused layout: portrait (footer OCR)")
        return LAYOUT_PORTRAIT

    if canvas_layout == LAYOUT_LANDSCAPE:
        if effective_landscape_hint:
            logger.info("📐 Fused layout: landscape (canvas + yaml bottom-right spin)")
        else:
            logger.info("📐 Fused layout: landscape (canvas)")
        return LAYOUT_LANDSCAPE

    if effective_landscape_hint and not portrait_hint:
        logger.info("📐 Fused layout: landscape (yaml bottom-right spin)")
        return LAYOUT_LANDSCAPE

    if portrait_hint:
        logger.info("📐 Fused layout: portrait (yaml center spin)")
        return LAYOUT_PORTRAIT

    return footer_layout or canvas_layout


def probe_footer_layout(page, hybrid_locator, *, screenshot_bytes: bytes | None = None) -> str | None:
    """OCR footer controls once; used after game load when UI is stable."""
    if hybrid_locator is None:
        return None
    try:
        screenshot_bytes = screenshot_bytes if screenshot_bytes is not None else page.screenshot()
        ocr_results = hybrid_locator.ocr.reader.readtext(screenshot_bytes)
        return layout_from_footer_ocr(ocr_results, screenshot_bytes, page)
    except Exception as exc:
        logger.warning(f"📐 Footer OCR layout probe failed: {exc}")
        return None


def detect_game_layout(
    page,
    hybrid_locator=None,
    *,
    expected_host: str | None = None,
    stable_reads: int = 2,
    interval_sec: float = 0.4,
) -> str | None:
    """Stable canvas layout probe across frames; None when canvas is not ready."""
    last_sample = None
    stable = 0
    for _ in range(16):
        sample = sample_canvas_layout(page, expected_host)
        if sample is None:
            stable = 0
            last_sample = None
            time.sleep(interval_sec)
            continue
        if sample == last_sample:
            stable += 1
        else:
            stable = 1
            last_sample = sample
        if stable >= stable_reads:
            return last_sample
        time.sleep(interval_sec)
    return last_sample


def auto_detect_layout(
    page,
    hybrid_locator=None,
    *,
    expected_host: str | None = None,
    footer_first: bool = False,
    portrait_hint: bool = False,
    landscape_hint: bool = False,
) -> str | None:
    """Fuse canvas aspect, footer OCR spread, and optional games.yaml spin-region hints.

    ``footer_first`` only selects a single footer OCR pass before canvas polling
    (post-load UI is stable); it does not let footer alone override canvas+yaml.
    """
    footer_layout = None
    if footer_first and hybrid_locator is not None:
        footer_layout = probe_footer_layout(page, hybrid_locator)

    canvas_rect = None
    try:
        from core.canvas_region import sample_canvas_viewport_rect

        canvas_rect = sample_canvas_viewport_rect(page, expected_host)
    except Exception:
        pass

    canvas_layout = None
    if footer_first:
        canvas_layout = sample_canvas_layout(page, expected_host)
    else:
        canvas_layout = detect_game_layout(page, hybrid_locator, expected_host=expected_host)
    if not canvas_layout:
        for _ in range(6):
            time.sleep(0.5)
            canvas_layout = sample_canvas_layout(page, expected_host)
            if canvas_layout:
                break

    if footer_layout is None and hybrid_locator is not None:
        footer_layout = probe_footer_layout(page, hybrid_locator)

    return fuse_layout_signals(
        canvas_layout,
        footer_layout,
        portrait_hint=portrait_hint,
        landscape_hint=landscape_hint,
        canvas_rect=canvas_rect,
    )
