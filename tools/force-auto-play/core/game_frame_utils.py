"""Playwright Page/Frame helpers for Unity games (cross-origin iframe safe)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def iter_game_contexts(page, expected_host: str | None = None):
    """Yield game host frames first, then page and remaining frames."""
    seen: set[int] = set()
    if expected_host:
        for frame in page.frames:
            if urlparse(frame.url).hostname == expected_host:
                seen.add(id(frame))
                yield frame
    yield page
    for frame in page.frames:
        if id(frame) not in seen:
            yield frame


def unity_canvas_ready(ctx) -> bool:
    """True when ctx shows a Unity canvas with intrinsic width > 100."""
    try:
        canvas = ctx.locator("#unity-canvas, canvas").first
        if not canvas.is_visible(timeout=400):
            return False
        width = canvas.evaluate("c => (c && c.width) || 0")
        return bool(width and int(width) > 100)
    except Exception:
        return False


def canvas_layout_metrics(ctx) -> dict | None:
    """Return display/intrinsic aspect metrics for the largest canvas in ctx."""
    try:
        canvas = ctx.locator("#unity-canvas, canvas").first
        if not canvas.is_visible(timeout=400):
            return None
        return canvas.evaluate(
            """c => {
                const r = c.getBoundingClientRect();
                const displayW = r.width;
                const displayH = r.height;
                const intrinsicW = c.width || displayW;
                const intrinsicH = c.height || displayH;
                return {
                    display_ratio: displayH / displayW,
                    intrinsic_ratio: intrinsicH / intrinsicW,
                    area: displayW * displayH,
                };
            }"""
        )
    except Exception:
        return None


def enable_game_debug(page, expected_host: str | None = None) -> int:
    """Set window.debug=true in game iframe(s) and page. Returns contexts updated."""
    count = 0
    for ctx in iter_game_contexts(page, expected_host):
        try:
            ctx.evaluate("() => { window.debug = true; }")
            count += 1
        except Exception as exc:
            logger.debug("enable_game_debug skipped for %s: %s", type(ctx).__name__, exc)
    return count
