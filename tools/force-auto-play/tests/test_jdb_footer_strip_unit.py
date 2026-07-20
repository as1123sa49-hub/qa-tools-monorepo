"""Unit tests for JDB icon-only footer strip (Balance | Bet | Win)."""

from unittest.mock import MagicMock

from core.balance_audit import (
    JDB_UNKNOWN_BET_DELTA_FLOOR,
    UNKNOWN_BET_DELTA_FLOOR,
    parse_footer_amounts_from_text,
    parse_jdb_footer_from_ocr,
    primary_balance_spin_delta,
    resolve_spin_delta_min_bet,
)
from core.game_utils import _game_config_is_jdb, use_jdb_portrait_footer_strip


def test_parse_footer_amounts_supports_three_decimals():
    assert 27399.995 in parse_footer_amounts_from_text("₱27,399.995")
    assert 0.5 in parse_footer_amounts_from_text("₱0.5")
    assert 0.2 in parse_footer_amounts_from_text("0.2")


def test_parse_jdb_footer_balance_bet_win_order():
    page = MagicMock()
    page.viewport_size = {"width": 1000, "height": 1000}
    # Synthetic OCR boxes: left balance, mid bet, right win (with currency markers).
    footer_ocr = [
        ([[100, 800], [220, 800], [220, 840], [100, 840]], "P27,399.995", 0.9),
        ([[400, 800], [470, 800], [470, 840], [400, 840]], "P0.50", 0.9),
        ([[700, 800], [780, 800], [780, 840], [700, 840]], "P0.00", 0.9),
    ]
    strip = parse_jdb_footer_from_ocr(
        footer_ocr,
        page,
        b"",
        lobby_b0=27399.995,
    )
    assert strip is not None
    assert abs(strip.balance - 27399.995) < 0.001
    assert strip.bet == 0.5
    assert strip.win == 0.0


def test_parse_jdb_footer_augments_nearby_small_bet_win():
    """Balance-only cluster still picks up bet/win slightly off the same OCR row."""
    page = MagicMock()
    page.viewport_size = {"width": 1000, "height": 1000}
    footer_ocr = [
        ([[100, 800], [240, 800], [240, 840], [100, 840]], "P10,007,406.95", 0.9),
        # Bet/win a bit lower — would miss a tight single-row cluster alone.
        ([[420, 860], [480, 860], [480, 900], [420, 900]], "P0.10", 0.9),
        ([[620, 860], [700, 860], [700, 900], [620, 900]], "P0.00", 0.9),
    ]
    strip = parse_jdb_footer_from_ocr(
        footer_ocr,
        page,
        b"",
        lobby_b0=10_007_406.95,
    )
    assert strip is not None
    assert abs(strip.balance - 10_007_406.95) < 0.01
    assert strip.bet == 0.1
    assert strip.win == 0.0


def test_parse_jdb_footer_ignores_version_noise_for_bet():
    """Version line v1.24.0 must not become bet when real stake is P0.1."""
    page = MagicMock()
    page.viewport_size = {"width": 1000, "height": 1000}
    footer_ocr = [
        ([[100, 800], [280, 800], [280, 840], [100, 840]], "P10,007,406.85", 0.9),
        ([[350, 760], [620, 760], [620, 790], [350, 790]], "v1.24.0 / v1c44da4", 0.9),
        ([[400, 820], [480, 820], [480, 860], [400, 860]], "P0.1", 0.9),
        ([[620, 820], [720, 820], [720, 860], [620, 860]], "P0.00", 0.9),
    ]
    strip = parse_jdb_footer_from_ocr(
        footer_ocr,
        page,
        b"",
        lobby_b0=10_007_406.85,
    )
    assert strip is not None
    assert abs(strip.balance - 10_007_406.85) < 0.01
    assert strip.bet == 0.1
    assert strip.win == 0.0
    assert strip.bet != 94.24


def test_parse_jdb_currency_amounts_from_text():
    from core.balance_audit import parse_jdb_currency_amounts_from_text

    assert parse_jdb_currency_amounts_from_text("P0.1") == [0.1]
    assert parse_jdb_currency_amounts_from_text("₱0.00") == [0.0]
    assert parse_jdb_currency_amounts_from_text("v1.24.0 / v1c44da4") == []
    assert 10_007_406.85 in parse_jdb_currency_amounts_from_text("P10,007,406.85")


def test_jdb_unknown_bet_delta_floor_accepts_point_one_stake():
    jdb = {"id": "JDB-SLOT-128", "provider_key": "JDB"}
    assert resolve_spin_delta_min_bet(None, jdb) == JDB_UNKNOWN_BET_DELTA_FLOOR
    assert resolve_spin_delta_min_bet(0.1, jdb) == max(
        0.1 * 0.85, JDB_UNKNOWN_BET_DELTA_FLOOR
    )
    # FC unchanged
    assert resolve_spin_delta_min_bet(None, {"id": "FC-SLOT-004"}) == UNKNOWN_BET_DELTA_FLOOR
    delta = primary_balance_spin_delta(
        10_007_406.95,
        10_007_406.85,
        min_bet=resolve_spin_delta_min_bet(None, jdb),
    )
    assert delta == -0.1


def test_game_config_is_jdb():
    assert _game_config_is_jdb({"id": "JDB-SLOT-001"})
    assert _game_config_is_jdb({"provider_key": "jdb"})
    assert not _game_config_is_jdb({"id": "FC-SLOT-001"})


def test_use_jdb_portrait_footer_strip_requires_portrait(monkeypatch):
    import core.game_utils as gu

    monkeypatch.setattr(gu, "is_portrait_layout", lambda *a, **k: True)
    assert use_jdb_portrait_footer_strip({"id": "JDB-SLOT-001"}, MagicMock())
    monkeypatch.setattr(gu, "is_portrait_layout", lambda *a, **k: False)
    assert not use_jdb_portrait_footer_strip({"id": "JDB-SLOT-001"}, MagicMock())
