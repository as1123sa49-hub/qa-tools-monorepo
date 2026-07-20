"""Click debug screenshots — operation layer only (not validation).

Annotates full-page screenshots with click position and optional VLM bbox.
"""

from __future__ import annotations

import io
import logging
import os
import time
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

MARKER_COLOR = (255, 40, 40)
BBOX_COLOR = (50, 255, 80)
LABEL_BG = (0, 0, 0, 180)


def viewport_to_image_coords(page, x: float, y: float, image: Image.Image) -> tuple[int, int]:
    """Convert Playwright viewport CSS pixels to screenshot pixel coordinates."""
    vp_w = page.viewport_size["width"] if page.viewport_size else image.width
    dpr = image.width / vp_w if vp_w > 0 else 1.0
    return int(round(x * dpr)), int(round(y * dpr))


def bbox_0_1000_to_pixels(
    bbox: Sequence[float], image: Image.Image
) -> tuple[int, int, int, int]:
    """Map [xmin, ymin, xmax, ymax] in 0–1000 full-image space to pixel rect."""
    w, h = image.size
    x1 = int(round(bbox[0] / 1000.0 * w))
    y1 = int(round(bbox[1] / 1000.0 * h))
    x2 = int(round(bbox[2] / 1000.0 * w))
    y2 = int(round(bbox[3] / 1000.0 * h))
    return x1, y1, x2, y2


def annotate_click(
    image: Image.Image,
    px_x: int,
    px_y: int,
    *,
    bbox_0_1000: Sequence[float] | None = None,
    label: str | None = None,
) -> Image.Image:
    """Draw crosshair, circle, optional bbox and label on a copy of the image."""
    out = image.convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if bbox_0_1000 and len(bbox_0_1000) >= 4:
        x1, y1, x2, y2 = bbox_0_1000_to_pixels(bbox_0_1000, out)
        draw.rectangle([x1, y1, x2, y2], outline=BBOX_COLOR + (255,), width=3)

    arm = 24
    draw.line([(px_x - arm, px_y), (px_x + arm, px_y)], fill=MARKER_COLOR + (255,), width=4)
    draw.line([(px_x, px_y - arm), (px_x, px_y + arm)], fill=MARKER_COLOR + (255,), width=4)
    r = 14
    draw.ellipse(
        [(px_x - r, px_y - r), (px_x + r, px_y + r)],
        outline=MARKER_COLOR + (255,),
        width=3,
    )

    text = label or f"click ({px_x}, {px_y})"
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    text_x = min(px_x + 18, max(0, out.width - 200))
    text_y = max(0, px_y - 36)
    if font:
        tb = draw.textbbox((text_x, text_y), text, font=font)
    else:
        tb = draw.textbbox((text_x, text_y), text)
    pad = 4
    draw.rectangle(
        [tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad],
        fill=LABEL_BG,
    )
    draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)

    return Image.alpha_composite(out, overlay).convert("RGB")


def capture_click_marker(
    page,
    output_dir: str,
    name: str,
    x: float,
    y: float,
    *,
    bbox_0_1000: Sequence[float] | None = None,
    label: str | None = None,
    screenshot_bytes: bytes | None = None,
) -> str | None:
    """Save full-page screenshot with click marker to output_dir/{name}.png."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"{name}.png")

    try:
        raw = screenshot_bytes if screenshot_bytes is not None else page.screenshot()
        image = Image.open(io.BytesIO(raw))
        px_x, px_y = viewport_to_image_coords(page, x, y, image)
        annotated = annotate_click(
            image,
            px_x,
            px_y,
            bbox_0_1000=bbox_0_1000,
            label=label,
        )
        annotated.save(filepath)
        logger.info(f"📍 Click marker saved: {filepath} (viewport=({x:.1f}, {y:.1f}), px=({px_x}, {px_y}))")
        return filepath
    except Exception as exc:
        logger.warning(f"⚠️ Click marker screenshot failed for {name}: {exc}")
        return None


def click_with_marker(
    page,
    artifact_handler,
    name: str,
    x: float,
    y: float,
    *,
    bbox_0_1000: Sequence[float] | None = None,
    label: str | None = None,
    screenshot_bytes: bytes | None = None,
    capture_after: bool = True,
    attach_after_to_allure: bool = False,
) -> None:
    """Mark click target, click, optionally capture post-click frame (operation layer)."""
    debug_dir = artifact_handler.dirs["debug"]
    capture_click_marker(
        page,
        debug_dir,
        name,
        x,
        y,
        bbox_0_1000=bbox_0_1000,
        label=label,
        screenshot_bytes=screenshot_bytes,
    )
    page.mouse.click(x, y)
    if capture_after:
        time.sleep(0.35)
        artifact_handler.capture(
            page,
            f"{name}_after",
            category="debug",
            attach_to_allure=attach_after_to_allure,
        )
