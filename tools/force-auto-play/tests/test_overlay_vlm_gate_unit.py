"""Unit tests for JDB overlay VLM gate."""

from core.game_utils import _overlay_vlm_fallback_allowed


def test_jdb_disables_overlay_vlm_fallback():
    cfg = {"id": "JDB-SLOT-101", "provider_key": "JDB"}
    assert _overlay_vlm_fallback_allowed(cfg) is False
    # Probe counter must not advance when blocked for JDB.
    assert cfg.get("_overlay_probe_count") in (None, 0)


def test_fc_allows_limited_overlay_vlm_fallback():
    cfg = {"id": "FC-SLOT-004", "provider_key": "FC"}
    assert _overlay_vlm_fallback_allowed(cfg) is True
    assert cfg["_overlay_probe_count"] == 1
    assert _overlay_vlm_fallback_allowed(cfg) is True
    assert cfg["_overlay_probe_count"] == 2
    assert _overlay_vlm_fallback_allowed(cfg) is False
