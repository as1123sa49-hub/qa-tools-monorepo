"""Unit tests for conditional spin click retry gates."""

from core.game_utils import (
    _balance_unchanged_for_spin_retry,
    _reels_static_for_spin_retry,
    _spin_click_retry_enabled,
    _spin_retry_allowed,
)


def test_spin_click_retry_enabled_fc_jdb():
    assert _spin_click_retry_enabled({}, "FC-SLOT-004") is True
    assert _spin_click_retry_enabled({}, "JDB-SLOT-123") is True
    assert _spin_click_retry_enabled({}, "JILI-SLOT-001") is False
    assert _spin_click_retry_enabled({"spin_click_retry": False}, "JDB-SLOT-123") is False


def test_reels_static_uses_last_probe():
    game_conf = {"_reel_post_click_moved": False, "id": "JDB-SLOT-123", "provider_key": "JDB"}
    assert _reels_static_for_spin_retry(None, game_conf, None) is True
    game_conf["_reel_post_click_moved"] = True
    assert _reels_static_for_spin_retry(None, game_conf, None) is False


def test_spin_retry_blocked_when_reels_moved(monkeypatch):
    game_conf = {
        "id": "JDB-SLOT-123",
        "provider_key": "JDB",
        "_reel_post_click_moved": True,
    }

    def _noop(*_a, **_k):
        return True

    monkeypatch.setattr(
        "core.game_utils._balance_unchanged_for_spin_retry",
        lambda *a, **k: True,
    )
    monkeypatch.setattr("core.game_utils._spin_already_started_before_click", _noop)
    assert (
        _spin_retry_allowed(None, None, game_conf, "JDB-SLOT-123", None, 100.0, None)
        is False
    )


def test_balance_unchanged_when_delta_none(monkeypatch):
    game_conf = {"id": "JDB-SLOT-123"}

    monkeypatch.setattr(
        "core.balance_audit.read_in_game_footer_primary",
        lambda *a, **k: 100.0,
    )
    monkeypatch.setattr(
        "core.balance_audit.resolve_spin_delta_min_bet",
        lambda *a, **k: 0.5,
    )
    monkeypatch.setattr(
        "core.balance_audit.primary_balance_spin_delta",
        lambda b, a, min_bet: None,
    )
    assert _balance_unchanged_for_spin_retry(None, None, game_conf, 100.0) is True

    monkeypatch.setattr(
        "core.balance_audit.primary_balance_spin_delta",
        lambda b, a, min_bet: -1.0,
    )
    assert _balance_unchanged_for_spin_retry(None, None, game_conf, 100.0) is False
