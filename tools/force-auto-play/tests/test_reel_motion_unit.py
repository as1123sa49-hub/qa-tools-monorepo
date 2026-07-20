"""Unit tests for reel motion assist."""

import numpy as np

from core.reel_motion import (
    mean_abs_diff,
    probe_reel_motion_after_click,
    reel_motion_assist_enabled,
    reels_appear_moved,
    reels_appear_static,
    store_reel_before,
)


def test_reel_motion_assist_default_jdb_only():
    assert reel_motion_assist_enabled({"id": "JDB-SLOT-101"})
    assert reel_motion_assist_enabled({"provider_key": "JDB", "id": "X"})
    assert not reel_motion_assist_enabled({"id": "FC-SLOT-004"})
    assert not reel_motion_assist_enabled({"id": "JDB-SLOT-101", "reel_motion_assist": False})
    assert reel_motion_assist_enabled({"id": "FC-SLOT-004", "reel_motion_assist": True})


def test_reels_appear_static_on_identical():
    a = np.zeros((40, 60), dtype=np.float32)
    b = np.zeros((40, 60), dtype=np.float32)
    assert reels_appear_static(a, b)
    assert not reels_appear_moved(a, b)


def test_reels_appear_moved_on_large_diff():
    a = np.zeros((40, 60), dtype=np.float32)
    b = np.full((40, 60), 40.0, dtype=np.float32)
    assert mean_abs_diff(a, b) == 40.0
    assert reels_appear_moved(a, b)
    assert not reels_appear_static(a, b)


def test_probe_reel_motion_after_click_detects_move(monkeypatch):
    import core.reel_motion as rm

    before = np.zeros((40, 60), dtype=np.float32)
    after = np.full((40, 60), 40.0, dtype=np.float32)
    cfg = {"id": "JDB-SLOT-101"}
    store_reel_before(cfg, before)

    class _Page:
        viewport_size = {"width": 1280, "height": 720}

        def screenshot(self):
            return b"fake"

    monkeypatch.setattr(rm, "capture_reel_snapshot", lambda *a, **k: after)
    monkeypatch.setattr(rm.time, "sleep", lambda *a, **k: None)
    assert probe_reel_motion_after_click(_Page(), cfg, before=before, delay_sec=0.01) is True
    assert cfg.get("_reel_post_click_moved") is True


def test_jdb_settle_timeout_constant():
    from tests.test_game_betting import (
        JDB_VISUAL_SETTLE_TIMEOUT_SEC,
        VISUAL_SETTLE_TIMEOUT_SEC,
    )

    assert JDB_VISUAL_SETTLE_TIMEOUT_SEC > VISUAL_SETTLE_TIMEOUT_SEC
