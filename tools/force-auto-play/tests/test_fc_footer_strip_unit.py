"""Unit tests for FC footer strip parsing (balance / win / total bets)."""

import pytest
from unittest.mock import MagicMock

from core.balance_audit import (
    is_cached_coord_stale,
    is_plausible_ingame_balance,
    parse_amounts_from_text,
    parse_fc_footer_from_ocr,
    parse_footer_amounts_from_text,
    primary_balance_spin_delta,
    reconcile_fc_balance_with_b0,
    resolve_spin_min_bet,
)


def _page(w=1280, h=720):
    page = MagicMock()
    page.viewport_size = {"width": w, "height": h}
    return page


def _ocr_box(text: str, x: float, y: float, w: float = 80, h: float = 20):
    return (
        [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        text,
        0.9,
    )


def test_parse_amounts_fixes_comma_decimal_ocr():
    assert parse_amounts_from_text("10,007,352,02") == [10_007_352.02]
    assert parse_footer_amounts_from_text("10,007,352,02") == [10_007_352.02]


def test_parse_amounts_fixes_spaced_digit_ocr():
    """FC-SLOT-040 style: OCR inserts spaces inside the amount token."""
    assert parse_footer_amounts_from_text("10, 007 , 422 . 03") == [10_007_422.03]
    assert parse_footer_amounts_from_text("0 . 00") == [0.0]
    assert parse_footer_amounts_from_text("2 .00") == [2.0]
    assert parse_amounts_from_text("BALANCE 10, 007 , 422 . 03") == [10_007_422.03]


def test_ocr_text_has_spaced_amount():
    from core.balance_audit import ocr_text_has_spaced_amount

    assert ocr_text_has_spaced_amount("10, 007 , 422 . 03")
    assert ocr_text_has_spaced_amount("0 . 00")
    assert not ocr_text_has_spaced_amount("10,007,422.83")


def test_choose_fc_footer_strip_keeps_spun_primary_over_upscaled_toward_b0():
    """win≈bet can leave B1 near B0; upscaled must not undo a formula-ok spin."""
    from core.balance_audit import FcFooterStrip, _choose_fc_footer_strip

    b0 = 10_000.00
    primary = FcFooterStrip(balance=9_999.80, win=1.00, total_bets=1.20)
    # Upscaled wrongly "corrects" back toward B0 / loses win
    refined = FcFooterStrip(balance=10_000.00, win=0.0, total_bets=1.20)
    chosen = _choose_fc_footer_strip(primary, refined, ref_b0=b0, min_bet=1.0)
    assert chosen is primary


def test_choose_fc_footer_strip_prefers_upscaled_when_primary_not_spun():
    from core.balance_audit import FcFooterStrip, _choose_fc_footer_strip

    b0 = 10_007_422.83
    primary = FcFooterStrip(balance=10_007_422.03, win=0.0, total_bets=2.0)
    refined = FcFooterStrip(balance=10_007_422.83, win=0.0, total_bets=2.0)
    chosen = _choose_fc_footer_strip(primary, refined, ref_b0=b0, min_bet=1.7)
    assert chosen is refined


def test_parse_fc_footer_spaced_amount_ocr_fc040():
    """Pre-balance must accept spaced OCR amounts on the value row."""
    ocr = [
        _ocr_box("BALANCE", 100, 600),
        _ocr_box("WIN", 500, 600),
        _ocr_box("TDTAL Bets", 900, 600),
        _ocr_box("10, 007 , 422 . 03", 100, 650),
        _ocr_box("0 . 00", 500, 650),
        _ocr_box("2 .00", 900, 650),
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=10_007_422.03)
    assert strip is not None
    assert strip.balance == 10_007_422.03
    assert strip.win == 0.0
    assert strip.total_bets == 2.0


def test_parse_amounts_fixes_dot_thousands_ocr():
    assert parse_amounts_from_text("10.007.381.02") == [10_007_381.02]
    assert parse_footer_amounts_from_text("10.007.381.02") == [10_007_381.02]
    assert parse_amounts_from_text("BALANCE 10.007.381.02 WIN") == [10_007_381.02]


def test_parse_fc_footer_three_value_columns():
    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("WIN", 520, 600),
        _ocr_box("TOTAL BETS", 920, 600),
        _ocr_box("10,007,352.02", 120, 640),
        _ocr_box("0.00", 520, 640),
        _ocr_box("2.00", 920, 640),
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=10_007_352.02)
    assert strip is not None
    assert strip.balance == 10_007_352.02
    assert strip.win == 0.0
    assert strip.total_bets == 2.0
    assert strip.balance_x_frac == pytest.approx(160 / 1280, rel=1e-3)
    assert strip.value_row_y_frac == pytest.approx(650 / 720, rel=1e-3)


def test_parse_fc_footer_uses_rightmost_as_total_bets():
    ocr = [
        _ocr_box("10,007,356.02", 100, 650),
        _ocr_box("0.00", 500, 650),
        _ocr_box("1.00", 900, 650),
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=10_007_356.02)
    assert strip is not None
    assert strip.balance == 10_007_356.02
    assert strip.win == 0.0
    assert strip.total_bets == 1.0


def test_reconcile_fc_balance_truncated_leading_digits():
    assert reconcile_fc_balance_with_b0(7352.02, 10_007_352.02) == 10_007_352.02


def test_reconcile_fc_balance_truncated_after_spin():
    """OCR drops leading '1' after bet deduction — return real B1, not B0."""
    b0 = 10_007_429.51
    # OCR '0,007,428.39' → 7428.39; reconstructed post-spin balance
    assert reconcile_fc_balance_with_b0(7428.39, b0) == 10_007_428.39


def test_reconcile_fc_balance_rejects_unrelated_fragment():
    assert reconcile_fc_balance_with_b0(7399.82, 10_007_381.02) is None
    assert reconcile_fc_balance_with_b0(381.02, 10_007_352.02) is None
    assert reconcile_fc_balance_with_b0(5555.55, 10_007_381.02) is None


def test_parse_fc_footer_recovers_truncated_ocr_balance():
    """OCR '0,007,352.02' parses as 7352.02 but reconstructs to lobby B0."""
    ocr = [
        _ocr_box("0,007,352.02", 120, 640),
        _ocr_box("0.00", 520, 640),
        _ocr_box("1.20", 920, 640),
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=10_007_352.02)
    assert strip is not None
    assert strip.balance == 10_007_352.02
    assert strip.win == 0.0
    assert strip.total_bets == 1.2


def test_parse_fc_footer_recovers_truncated_post_spin_balance():
    """FC-SLOT-007 style: B0=…429.51, OCR 0,007,428.39 after −1.20 loss."""
    from core.balance_audit import wallet_spin_formula_ok

    b0 = 10_007_429.51
    ocr = [
        _ocr_box("BAI ANCF", 120, 600),
        _ocr_box("WIN", 520, 600),
        _ocr_box("TOTAI RFTS", 920, 600),
        _ocr_box("0,007,428.39", 120, 640),
        _ocr_box("0.00", 520, 640),
        _ocr_box("1.20", 920, 640),
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=b0)
    assert strip is not None
    assert strip.balance == 10_007_428.39
    assert strip.win == 0.0
    assert strip.total_bets == 1.2
    assert wallet_spin_formula_ok(b0, strip.balance, strip.total_bets, strip.win)


def test_parse_fc_footer_falls_back_when_x_anchor_hits_win_column():
    """anchor_x near WIN must not miss when truncated balance is still in row."""
    b0 = 10_007_429.51
    ocr = [
        _ocr_box("0,007,428.39", 120, 640),
        _ocr_box("0.00", 520, 640),
        _ocr_box("1.20", 920, 640),
    ]
    strip = parse_fc_footer_from_ocr(
        ocr,
        _page(),
        b"",
        lobby_b0=b0,
        balance_x_frac=520 / 1280,  # WIN column
        value_row_y_frac=650 / 720,
    )
    assert strip is not None
    assert strip.balance == 10_007_428.39
    assert strip.total_bets == 1.2


def test_parse_fc_footer_rejects_balance_far_from_b0_on_calibration():
    ocr = [
        _ocr_box("10,007,352.02", 100, 650),
        _ocr_box("0.00", 500, 650),
        _ocr_box("2.00", 900, 650),
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=10_008_500.00)
    assert strip is None


def test_parse_fc_footer_uses_balance_x_anchor_after_calibration():
    ocr = [
        _ocr_box("10,007,350.02", 100, 650),
        _ocr_box("0.00", 500, 650),
        _ocr_box("2.00", 900, 650),
    ]
    strip = parse_fc_footer_from_ocr(
        ocr,
        _page(),
        b"",
        balance_x_frac=100 / 1280,
        value_row_y_frac=650 / 720,
    )
    assert strip is not None
    assert strip.balance == 10_007_350.02
    assert strip.total_bets == 2.0


def test_parse_fc_footer_rejects_fragment_with_x_anchor_and_b0():
    """Post-spin OCR fragment at balance column must not pass when far from B0."""
    ocr = [
        _ocr_box("7,399.82", 100, 650),
        _ocr_box("20.00", 500, 650),
        _ocr_box("2.00", 900, 650),
    ]
    strip = parse_fc_footer_from_ocr(
        ocr,
        _page(),
        b"",
        lobby_b0=10_007_381.02,
        balance_x_frac=100 / 1280,
        value_row_y_frac=650 / 720,
    )
    assert strip is None


def test_resolve_spin_min_bet_from_fc_total_bets():
    game_conf = {"_audit_fc_total_bets": 2.0}
    assert resolve_spin_min_bet(game_conf) == 1.7


def test_parse_fc_footer_rescues_nonzero_bet_when_rightmost_is_zero():
    """Row has 0.00 and 1.20 — do not keep total_bets=0."""
    ocr = [
        _ocr_box("10,007,421.63", 100, 650),
        _ocr_box("0.00", 500, 650),
        _ocr_box("1.20", 700, 650),
        _ocr_box("0.00", 900, 650),  # rightmost OCR noise
    ]
    strip = parse_fc_footer_from_ocr(ocr, _page(), b"", lobby_b0=10_007_421.63)
    assert strip is not None
    assert strip.balance == 10_007_421.63
    assert strip.total_bets == 1.20


def test_store_fc_footer_anchor_skips_zero_total_bets():
    from core.balance_audit import (
        FcFooterStrip,
        _store_fc_footer_anchor,
        audit_fc_total_bets_key,
    )

    conf = {audit_fc_total_bets_key(): 2.0}
    _store_fc_footer_anchor(
        conf,
        FcFooterStrip(balance=100.0, win=0.0, total_bets=0.0, balance_x_frac=0.2),
    )
    assert conf[audit_fc_total_bets_key()] == 2.0


def test_resolve_spin_delta_min_bet_unknown_uses_floor():
    from core.balance_audit import (
        UNKNOWN_BET_DELTA_FLOOR,
        primary_balance_spin_delta,
        resolve_spin_delta_min_bet,
    )

    assert resolve_spin_delta_min_bet(0.0, {"_audit_fc_total_bets": 0.0}) == UNKNOWN_BET_DELTA_FLOOR
    assert resolve_spin_delta_min_bet(None, None) == UNKNOWN_BET_DELTA_FLOOR
    # 022-style: bet OCR 0 but wallet dropped 1.20
    assert (
        primary_balance_spin_delta(
            10_007_421.63,
            10_007_420.43,
            min_bet=resolve_spin_delta_min_bet(0.0, None),
        )
        == -1.20
    )
    # 040-style settlement: bet n/a, delta -2.00 must settle (not blocked by DEFAULT 2.5)
    assert (
        primary_balance_spin_delta(
            10_007_412.03,
            10_007_410.03,
            min_bet=resolve_spin_delta_min_bet(None, {}),
        )
        == -2.00
    )
    assert (
        primary_balance_spin_delta(
            10_007_412.03,
            10_007_410.03,
            min_bet=2.5,
        )
        is None
    )


def test_primary_balance_spin_delta_with_dynamic_bet():
    assert primary_balance_spin_delta(10_007_352.02, 10_007_350.02, min_bet=1.7) == -2.0


def test_primary_balance_spin_delta_rejects_footer_fragment():
    assert primary_balance_spin_delta(10_007_381.02, 7399.82, min_bet=1.7) is None


def test_is_plausible_ingame_balance_rejects_fragment():
    assert not is_plausible_ingame_balance(7399.82, 10_007_381.02)


def test_fc_footer_integer_balance_accepts_no_decimal_near_b0():
    """Robin Hood style: OCR reads '10,007,383' with no decimals — accept via B0."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("WIN", 520, 600),
        _ocr_box("TOTAL BETS", 920, 600),
        _ocr_box("10,007,383", 120, 640),
    ]
    strip = parse_fc_footer_integer_balance(
        ocr, _page(), b"", lobby_b0=10_007_383.02
    )
    assert strip is not None
    assert strip.balance == pytest.approx(10_007_383.0)
    assert strip.win is None
    assert strip.total_bets is None


def test_fc_footer_integer_balance_requires_balance_label():
    """No BALANCE label → do not gamble on a bare integer."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("10,007,383", 120, 640),
    ]
    assert (
        parse_fc_footer_integer_balance(ocr, _page(), b"", lobby_b0=10_007_383.02)
        is None
    )


def test_fc_footer_integer_balance_rejects_unrelated_integer():
    """Integer far from B0 (e.g. a TxnId) must be rejected even with BALANCE label."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("889912345", 120, 640),
    ]
    assert (
        parse_fc_footer_integer_balance(ocr, _page(), b"", lobby_b0=10_007_383.02)
        is None
    )


def test_fc_footer_integer_balance_needs_lobby_b0():
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("10,007,383", 120, 640),
    ]
    assert parse_fc_footer_integer_balance(ocr, _page(), b"", lobby_b0=None) is None


def test_fc_footer_integer_balance_recovers_truncated_integer():
    """OCR dropped the leading digit AND the decimals: '0,007,383' ≈ B0."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("0,007,383", 120, 640),
    ]
    strip = parse_fc_footer_integer_balance(
        ocr, _page(), b"", lobby_b0=10_007_383.02
    )
    assert strip is not None
    assert strip.balance == pytest.approx(10_007_383.0)


def test_fc_footer_integer_balance_ignores_small_bet_integers():
    """Bare small integers (bet/win like '2') must never be taken as balance."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("2", 920, 640),
    ]
    assert (
        parse_fc_footer_integer_balance(ocr, _page(), b"", lobby_b0=10_007_383.02)
        is None
    )


def test_fc_footer_integer_bet_win_disabled_by_default():
    """Robin Hood integer bet/win must stay n/a unless explicitly allowed."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("WIN", 520, 600),
        _ocr_box("TOTAL BETS", 920, 600),
        _ocr_box("10,007,374", 120, 640),
        _ocr_box("0", 520, 640),
        _ocr_box("1", 920, 640),
    ]
    strip = parse_fc_footer_integer_balance(ocr, _page(), b"", lobby_b0=10_007_374.0)
    assert strip is not None
    assert strip.balance == pytest.approx(10_007_374.0)
    assert strip.win is None
    assert strip.total_bets is None


def test_fc_footer_integer_bet_win_by_label_when_allowed():
    """FC-SLOT-020 integer-credit UI: read integer WIN / TOTAL BETS by column."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("WIN", 520, 600),
        _ocr_box("TOTAL BETS", 920, 600),
        _ocr_box("10,007,374", 120, 640),
        _ocr_box("0", 520, 640),
        _ocr_box("1", 920, 640),
    ]
    strip = parse_fc_footer_integer_balance(
        ocr, _page(), b"", lobby_b0=10_007_374.0, allow_integer_bet_win=True
    )
    assert strip is not None
    assert strip.balance == pytest.approx(10_007_374.0)
    assert strip.win == pytest.approx(0.0)
    assert strip.total_bets == pytest.approx(1.0)


def test_fc_footer_integer_bet_win_ignores_out_of_column_digits():
    """Digits not under WIN / TOTAL BETS labels must not be taken as bet/win."""
    from core.balance_audit import parse_fc_footer_integer_balance

    ocr = [
        _ocr_box("BALANCE", 120, 600),
        _ocr_box("WIN", 520, 600),
        _ocr_box("TOTAL BETS", 920, 600),
        _ocr_box("10,007,374", 120, 640),
        _ocr_box("1credit=1", 120, 560),  # left/above, not under a value label
    ]
    strip = parse_fc_footer_integer_balance(
        ocr, _page(), b"", lobby_b0=10_007_374.0, allow_integer_bet_win=True
    )
    assert strip is not None
    assert strip.balance == pytest.approx(10_007_374.0)
    assert strip.win is None
    assert strip.total_bets is None


def test_is_cached_coord_stale_outside_portrait_spin_region():
    page = _page(1280, 720)
    spin_config = {
        "_layout": "portrait",
        "region": {
            "x_start": 0.38,
            "x_end": 0.62,
            "y_start": 0.72,
            "y_end": 0.88,
        },
    }
    assert is_cached_coord_stale(1188.0, 668.0, page, spin_config)
    cx = (0.38 + 0.62) / 2 * 1280
    cy = (0.72 + 0.88) / 2 * 720
    assert not is_cached_coord_stale(cx, cy, page, spin_config)
