"""Unit tests for balance_audit helpers."""

from core.balance_audit import (
    COMBO_LOBBY_WALLET_REFRESH_REGION,
    audit_cross_venue_wallet,
    collect_footer_amount_candidates,
    is_plausible_ingame_balance,
    match_footer_to_lobby_b0,
    parse_amounts_from_text,
    pick_primary_balance,
    primary_balance_spin_delta,
    resolve_lobby_wallet_refresh_regions,
)
from core.env_config import ENTRY_MODE_COMBOBURST_PORTAL, ENTRY_MODE_JC_LOBBY


class _Ocr:
    def __init__(self, text: str):
        self.text = text


def test_parse_amounts_requires_decimal():
    assert parse_amounts_from_text("49217694-9af2-483d") == []
    assert parse_amounts_from_text("3,335,535.45") == [3335535.45]


def test_parse_amounts_peso_and_commas():
    amounts = parse_amounts_from_text("₱ 10,104.30 refresh")
    assert 10104.30 in amounts


def test_pick_primary_balance_excludes_jackpots():
    ocr = [
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "P 3.00", 0.9),
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "P 75.00", 0.9),
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "P 3,335,538.45", 0.9),
    ]
    assert pick_primary_balance(ocr) == 3335538.45


def test_match_footer_to_lobby_b0_picks_closest():
    ocr = [
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "WIN 0.00", 0.9),
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "TOTAL BETS 1.00", 0.9),
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "10,007,365.62", 0.9),
    ]
    lobby_b0 = 10_007_366.62
    assert match_footer_to_lobby_b0(ocr, lobby_b0) == 10_007_365.62
    assert collect_footer_amount_candidates(ocr) == [10007365.62]


def test_primary_balance_spin_delta_requires_min_bet():
    assert primary_balance_spin_delta(3335538.45, 3335535.45, min_bet=3.0) == -3.0
    assert primary_balance_spin_delta(3335538.45, 3335538.40, min_bet=3.0) is None


def test_primary_balance_spin_delta_rejects_flat_with_low_jdb_floor():
    # Regression: min_bet 0.05 + tolerance 0.15 used to accept Δ=0.
    flat = 10_007_400.84
    assert primary_balance_spin_delta(flat, flat, min_bet=0.05) is None
    assert primary_balance_spin_delta(flat, flat + 0.01, min_bet=0.05) is None
    assert primary_balance_spin_delta(flat, flat - 0.20, min_bet=0.05) == -0.20


def test_is_plausible_ingame_balance_rejects_small_fragment():
    assert not is_plausible_ingame_balance(361.02, 10_007_361.02)
    assert is_plausible_ingame_balance(10_007_350.00, 10_007_361.02)


def test_audit_cross_venue_rejects_unchanged_lobby():
    ok, reason = audit_cross_venue_wallet(
        1000.0,
        998.0,
        998.0,
        require_lobby_change=True,
        min_bet=3.0,
    )
    assert not ok
    assert "unchanged" in reason.lower()


def test_audit_cross_venue_accepts_console_small_win():
    ok, reason = audit_cross_venue_wallet(
        3335534.85,
        3335535.45,
        3335535.45,
        require_lobby_change=True,
        min_bet=3.0,
        console_summary={
            "b0": 3335534.85,
            "b1": 3335535.45,
            "bet": 3.0,
            "win": 3.6,
        },
    )
    assert ok, reason


def test_audit_cross_venue_accepts_console_when_lobby_b0_stale():
    """CallOfThor-style: entry lobby B0 OCR stale but B1 matches console after spin."""
    ok, reason = audit_cross_venue_wallet(
        3335458.45,
        3335458.45,
        3335458.45,
        require_lobby_change=True,
        min_bet=3.0,
        console_summary={
            "b0": 3335461.45,
            "b1": 3335458.45,
            "bet": 3.0,
            "win": 0.0,
        },
    )
    assert ok, reason


def test_audit_cross_venue_accepts_matching_wallet():
    ok, reason = audit_cross_venue_wallet(
        3335538.45,
        3335535.45,
        3335535.45,
        require_lobby_change=True,
        min_bet=3.0,
    )
    assert ok, reason


def test_audit_cross_venue_rejects_mismatch():
    ok, reason = audit_cross_venue_wallet(
        3335538.45,
        3335535.45,
        3335530.00,
        tolerance=0.5,
        require_lobby_change=False,
    )
    assert not ok
    assert "mismatch" in reason.lower()


def test_resolve_refresh_regions_combo_and_jc():
    combo = resolve_lobby_wallet_refresh_regions({}, ENTRY_MODE_COMBOBURST_PORTAL)
    assert combo == [COMBO_LOBBY_WALLET_REFRESH_REGION]
    jc = resolve_lobby_wallet_refresh_regions({}, ENTRY_MODE_JC_LOBBY)
    assert len(jc) == 2
