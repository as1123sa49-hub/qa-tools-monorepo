"""Persistent spin button coordinates learned from successful clicks."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "config" / ".cache" / "spin_coords.json"

_lock = threading.Lock()


def _cache_path() -> Path:
    return DEFAULT_CACHE_PATH


def _load_all_unlocked() -> dict:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"⚠️ Failed to read spin coord cache ({path}): {exc}")
        return {}


def _save_all_unlocked(data: dict) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_spin_coord(game_id: str) -> tuple[float, float] | None:
    with _lock:
        entry = _load_all_unlocked().get(game_id)
    if not entry:
        return None
    try:
        return float(entry["x"]), float(entry["y"])
    except (KeyError, TypeError, ValueError):
        return None


def save_spin_coord(game_id: str, x: float, y: float) -> None:
    with _lock:
        data = _load_all_unlocked()
        data[game_id] = {"x": round(x, 2), "y": round(y, 2)}
        _save_all_unlocked(data)
    logger.info(f"💾 Spin coord cached for {game_id}: ({x:.1f}, {y:.1f})")


def clear_spin_coord(game_id: str) -> None:
    with _lock:
        data = _load_all_unlocked()
        if game_id in data:
            del data[game_id]
            _save_all_unlocked(data)
            logger.info(f"🗑️ Cleared stale spin coord cache for {game_id}")
