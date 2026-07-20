"""Map spin/search regions from Unity canvas coordinates to viewport fractions."""

from __future__ import annotations

import logging

from core.game_frame_utils import iter_game_contexts

logger = logging.getLogger(__name__)

CANVAS_VIEWPORT_WIDTH_FULL = 0.92
LANDSCAPE_SPIN_ANCHOR_X_FRAC = 0.82
LANDSCAPE_SPIN_ANCHOR_Y_FRAC = 0.82


def sample_canvas_viewport_rect(page, expected_host: str | None = None) -> dict | None:
    """Largest visible Unity canvas as viewport fractions (Playwright page coordinates)."""
    vp_size = page.viewport_size or {}
    vp_w = vp_size.get("width") or 0
    vp_h = vp_size.get("height") or 0
    try:
        vp_w = float(vp_w)
        vp_h = float(vp_h)
    except (TypeError, ValueError):
        return None
    if vp_w <= 0 or vp_h <= 0:
        return None

    best_rect: dict | None = None
    best_area = 0.0
    for ctx in iter_game_contexts(page, expected_host):
        try:
            canvas = ctx.locator("#unity-canvas, canvas").first
            if not canvas.is_visible(timeout=400):
                continue
            box = canvas.bounding_box()
            if not box or box.get("width", 0) < 100:
                continue
            area = float(box["width"]) * float(box["height"])
            if area <= best_area:
                continue
            best_area = area
            best_rect = {
                "x_start": box["x"] / vp_w,
                "y_start": box["y"] / vp_h,
                "x_end": (box["x"] + box["width"]) / vp_w,
                "y_end": (box["y"] + box["height"]) / vp_h,
            }
        except Exception:
            continue

    if best_rect:
        logger.debug(
            "📐 Canvas viewport rect: x=%.2f–%.2f, y=%.2f–%.2f (w=%.0f%%)",
            best_rect["x_start"],
            best_rect["x_end"],
            best_rect["y_start"],
            best_rect["y_end"],
            (best_rect["x_end"] - best_rect["x_start"]) * 100,
        )
    return best_rect


def canvas_viewport_width_frac(canvas_rect: dict | None) -> float:
    if not canvas_rect:
        return 1.0
    return max(canvas_rect["x_end"] - canvas_rect["x_start"], 0.0)


def canvas_fills_viewport_width(
    canvas_rect: dict | None, *, min_width_frac: float = 0.85
) -> bool:
    """True when the game canvas spans most of the viewport (true full-width landscape)."""
    return canvas_viewport_width_frac(canvas_rect) >= min_width_frac


def map_region_to_viewport(region: dict, canvas_rect: dict) -> dict:
    """Convert region fractions (relative to canvas) into viewport fractions."""
    cw = canvas_rect["x_end"] - canvas_rect["x_start"]
    ch = canvas_rect["y_end"] - canvas_rect["y_start"]
    mapped = {
        "x_start": canvas_rect["x_start"] + region["x_start"] * cw,
        "x_end": canvas_rect["x_start"] + region["x_end"] * cw,
        "y_start": canvas_rect["y_start"] + region["y_start"] * ch,
        "y_end": canvas_rect["y_start"] + region["y_end"] * ch,
    }
    return mapped


def apply_canvas_relative_region(
    region: dict,
    canvas_rect: dict | None,
    *,
    label: str = "spin",
) -> dict:
    """Map yaml region through canvas when the game is pillarboxed / letterboxed."""
    if not canvas_rect:
        return dict(region)
    if canvas_fills_viewport_width(canvas_rect, min_width_frac=CANVAS_VIEWPORT_WIDTH_FULL):
        return dict(region)
    mapped = map_region_to_viewport(region, canvas_rect)
    logger.info(
        "📐 %s region via canvas: x %.2f–%.2f → %.2f–%.2f, y %.2f–%.2f → %.2f–%.2f",
        label,
        region["x_start"],
        region["x_end"],
        mapped["x_start"],
        mapped["x_end"],
        region["y_start"],
        region["y_end"],
        mapped["y_start"],
        mapped["y_end"],
    )
    return mapped


def point_inside_canvas_rect(
    cx: float,
    cy: float,
    canvas_rect: dict | None,
    page,
    *,
    margin_frac: float = 0.01,
) -> bool:
    if not canvas_rect:
        return True
    vp_w = (page.viewport_size or {}).get("width") or 1
    vp_h = (page.viewport_size or {}).get("height") or 1
    x = cx / vp_w
    y = cy / vp_h
    m = margin_frac
    return (
        canvas_rect["x_start"] - m <= x <= canvas_rect["x_end"] + m
        and canvas_rect["y_start"] - m <= y <= canvas_rect["y_end"] + m
    )
