"""Reel-area motion assist: veto false spin acks when the board looks static."""

from __future__ import annotations

import io
import logging
import time

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Portrait reel / body band (exclude footer + top chrome).
DEFAULT_REEL_REGION = {
    "x_start": 0.12,
    "x_end": 0.88,
    "y_start": 0.22,
    "y_end": 0.68,
}
_REEL_BEFORE_KEY = "_reel_before_spin"
_REEL_POST_CLICK_MOVED_KEY = "_reel_post_click_moved"
_REEL_PROBE_MAD_KEY = "_reel_last_probe_mad"
# Mean absolute pixel diff on 0–255 gray; below → treat as static.
DEFAULT_STATIC_MAD = 6.5
_COMPARE_MAX_SIDE = 160
# Capture after-click frame while reels are still moving (not settle-idle).
POST_CLICK_REEL_PROBE_DELAY_SEC = 0.45


def reel_motion_assist_enabled(game_config: dict | None) -> bool:
    """Generic helper; default on for JDB, overridable per game."""
    if not game_config:
        return False
    flag = game_config.get("reel_motion_assist")
    if flag is False:
        return False
    if flag is True:
        return True
    provider = game_config.get("provider_key") or game_config.get("_provider_key")
    if provider and str(provider).upper() == "JDB":
        return True
    gid = str(game_config.get("id") or "")
    return gid.upper().startswith("JDB-")


def _reel_region_frac(game_config: dict | None) -> dict:
    if game_config and isinstance(game_config.get("reel_motion_region"), dict):
        return dict(game_config["reel_motion_region"])
    active = None
    if game_config and isinstance(game_config.get("portrait_active_region"), dict):
        active = game_config["portrait_active_region"]
    if active:
        return {
            "x_start": active.get("x_start", DEFAULT_REEL_REGION["x_start"]),
            "x_end": active.get("x_end", DEFAULT_REEL_REGION["x_end"]),
            "y_start": max(active.get("y_start", 0.0), DEFAULT_REEL_REGION["y_start"]),
            "y_end": min(active.get("y_end", 1.0), DEFAULT_REEL_REGION["y_end"]),
        }
    return dict(DEFAULT_REEL_REGION)


def capture_reel_snapshot(
    page,
    game_config: dict | None = None,
    screenshot_bytes: bytes | None = None,
) -> np.ndarray | None:
    """Return downscaled grayscale crop of the reel band, or None on failure."""
    try:
        raw = screenshot_bytes if screenshot_bytes is not None else page.screenshot()
        img = Image.open(io.BytesIO(raw)).convert("L")
        # Prefer screenshot pixel size for cropping; viewport may differ by DPR.
        w, h = img.size
        region = _reel_region_frac(game_config)
        x0 = int(max(0.0, min(1.0, float(region["x_start"]))) * w)
        x1 = int(max(0.0, min(1.0, float(region["x_end"]))) * w)
        y0 = int(max(0.0, min(1.0, float(region["y_start"]))) * h)
        y1 = int(max(0.0, min(1.0, float(region["y_end"]))) * h)
        if x1 <= x0 + 8 or y1 <= y0 + 8:
            return None
        crop = img.crop((x0, y0, x1, y1))
        crop.thumbnail((_COMPARE_MAX_SIDE, _COMPARE_MAX_SIDE), Image.Resampling.BILINEAR)
        return np.asarray(crop, dtype=np.float32)
    except Exception as exc:
        logger.debug("Reel snapshot failed: %s", exc)
        return None


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float | None:
    if a is None or b is None:
        return None
    if a.shape != b.shape:
        # Resize b to a via PIL for a fair compare.
        try:
            ib = Image.fromarray(b.astype(np.uint8), mode="L").resize(
                (a.shape[1], a.shape[0]), Image.Resampling.BILINEAR
            )
            b = np.asarray(ib, dtype=np.float32)
        except Exception:
            return None
    return float(np.mean(np.abs(a - b)))


def reels_appear_static(
    before: np.ndarray | None,
    after: np.ndarray | None,
    *,
    max_mad: float = DEFAULT_STATIC_MAD,
) -> bool:
    """True when before/after look the same (no meaningful reel motion)."""
    mad = mean_abs_diff(before, after)
    if mad is None:
        return False  # unknown → do not veto
    return mad <= max_mad


def reels_appear_moved(
    before: np.ndarray | None,
    after: np.ndarray | None,
    *,
    max_mad: float = DEFAULT_STATIC_MAD,
) -> bool:
    return not reels_appear_static(before, after, max_mad=max_mad)


def store_reel_before(game_config: dict | None, snapshot: np.ndarray | None) -> None:
    if game_config is not None and snapshot is not None:
        game_config[_REEL_BEFORE_KEY] = snapshot


def get_reel_before(game_config: dict | None) -> np.ndarray | None:
    if not game_config:
        return None
    snap = game_config.get(_REEL_BEFORE_KEY)
    return snap if isinstance(snap, np.ndarray) else None


def probe_reel_motion_after_click(
    page,
    game_config: dict | None,
    *,
    before: np.ndarray | None = None,
    delay_sec: float = POST_CLICK_REEL_PROBE_DELAY_SEC,
) -> bool | None:
    """Short post-click probe while reels should still be moving.

    Returns True if moved, False if static, None if assist off / unknown.
    Does not run at settlement — idle-vs-idle frames are unreliable.
    """
    if not reel_motion_assist_enabled(game_config):
        return None
    baseline = before if before is not None else get_reel_before(game_config)
    if baseline is None:
        return None
    if delay_sec > 0:
        time.sleep(delay_sec)
    after = capture_reel_snapshot(page, game_config)
    if after is None:
        return None
    mad = mean_abs_diff(baseline, after)
    moved = not reels_appear_static(baseline, after)
    if game_config is not None:
        game_config[_REEL_POST_CLICK_MOVED_KEY] = moved
        if mad is not None:
            game_config[_REEL_PROBE_MAD_KEY] = mad
    logger.info(
        "🎞️ Post-click reel probe: %s (mad=%.2f)",
        "moved" if moved else "static",
        mad if mad is not None else -1.0,
    )
    return moved


def get_reel_post_click_moved(game_config: dict | None) -> bool | None:
    if not game_config:
        return None
    val = game_config.get(_REEL_POST_CLICK_MOVED_KEY)
    return val if isinstance(val, bool) else None


def get_reel_last_probe_mad(game_config: dict | None) -> float | None:
    if not game_config:
        return None
    val = game_config.get(_REEL_PROBE_MAD_KEY)
    return float(val) if val is not None else None


def reel_probe_snapshot(game_config: dict | None) -> dict:
    """JSON-friendly reel probe fields for run_evidence."""
    moved = get_reel_post_click_moved(game_config)
    mad = get_reel_last_probe_mad(game_config)
    if moved is None and mad is None:
        return {}
    out: dict = {}
    if moved is not None:
        out["moved"] = moved
    if mad is not None:
        out["mad"] = round(mad, 2)
    return out


def reel_motion_vetoes_spin(
    page,
    game_config: dict | None,
    *,
    before: np.ndarray | None = None,
    screenshot_bytes: bytes | None = None,
) -> bool:
    """True when assist is on and reels still look static vs stored/before frame.

    Intended for pre-click / immediate post-click checks — not settlement idle frames.
    """
    if not reel_motion_assist_enabled(game_config):
        return False
    baseline = before if before is not None else get_reel_before(game_config)
    if baseline is None:
        return False
    after = capture_reel_snapshot(page, game_config, screenshot_bytes=screenshot_bytes)
    if after is None:
        return False
    if reels_appear_static(baseline, after):
        mad = mean_abs_diff(baseline, after)
        logger.info(
            "🎞️ Reel motion assist: static board (mad=%.2f) — not treating as spun",
            mad if mad is not None else -1.0,
        )
        return True
    return False
