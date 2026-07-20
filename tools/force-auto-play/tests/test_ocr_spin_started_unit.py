"""Unit tests for strict footer-primary spin detection."""

from unittest.mock import MagicMock

from core.balance_audit import ocr_spin_started_primary, pick_primary_balance


def test_pick_primary_from_footer_style_ocr():
    ocr = [
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "P 3,335,538.45", 0.9),
        ([[0, 0], [1, 0], [1, 1], [0, 1]], "P 3.00", 0.9),
    ]
    assert pick_primary_balance(ocr) == 3335538.45


def test_ocr_spin_started_requires_meaningful_delta(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()

    calls = {"n": 0}

    def fake_read(page_, hybrid_, game_config=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return 3335538.45
        return 3335538.45

    monkeypatch.setattr("core.balance_audit.read_in_game_footer_primary", fake_read)
    monkeypatch.setattr("core.balance_audit.detect_in_game_win_banner", lambda *a, **k: False)
    monkeypatch.setattr(
        "core.balance_audit.use_fc_portrait_footer_strip", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "core.balance_audit.dismiss_fc_side_panel_if_open", lambda *a, **k: False
    )
    assert ocr_spin_started_primary(page, hybrid, 3335538.45) is False


def test_ocr_spin_started_detects_bet_deduction(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()

    calls = {"n": 0}

    def fake_read(page_, hybrid_, game_config=None, **kwargs):
        calls["n"] += 1
        return 3335535.45

    monkeypatch.setattr("core.balance_audit.read_in_game_footer_primary", fake_read)
    monkeypatch.setattr("core.balance_audit.detect_in_game_win_banner", lambda *a, **k: False)
    monkeypatch.setattr(
        "core.balance_audit.use_fc_portrait_footer_strip", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "core.balance_audit.dismiss_fc_side_panel_if_open", lambda *a, **k: False
    )
    assert ocr_spin_started_primary(page, hybrid, 3335538.45) is True


def test_ocr_spin_started_rejects_implausible_fragment(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()

    monkeypatch.setattr(
        "core.balance_audit.read_in_game_footer_primary",
        lambda *a, **k: 7399.82,
    )
    monkeypatch.setattr("core.balance_audit.detect_in_game_win_banner", lambda *a, **k: False)
    monkeypatch.setattr(
        "core.balance_audit.use_fc_portrait_footer_strip", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "core.balance_audit.dismiss_fc_side_panel_if_open", lambda *a, **k: False
    )
    assert ocr_spin_started_primary(page, hybrid, 10_007_381.02) is False


def test_wallet_spin_formula_ok_win_and_loss():
    from core.balance_audit import wallet_spin_formula_ok

    b0 = 10_007_433.63
    # Net -0.36 with bet 1.20 → win 0.84
    assert wallet_spin_formula_ok(b0, 10_007_433.27, 1.20, 0.84)
    # Pure loss
    assert wallet_spin_formula_ok(10_007_433.27, 10_007_432.07, 1.20, 0.0)
    # Bad WIN OCR must not pass
    assert not wallet_spin_formula_ok(b0, b0 - 1.20, 1.20, 9_000_000.0)
    # Delta too far from formula
    assert not wallet_spin_formula_ok(b0, b0 - 5.0, 1.20, 0.0)
    # win ≈ bet → B1 near B0 still counts as spun (must not treat as OCR noise)
    assert wallet_spin_formula_ok(10_000.00, 9_999.80, 1.20, 1.00)
    # Flat balance + win≈0 must not pass (low-bet false positive)
    assert not wallet_spin_formula_ok(10_007_403.75, 10_007_403.75, 0.20, 0.0)
    # Break-even: flat balance but win≈bet
    assert wallet_spin_formula_ok(10_007_403.75, 10_007_403.75, 0.20, 0.20)


def test_resolve_spin_success_check_timeout_fc_portrait():
    from core.game_utils import (
        FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC,
        SPIN_MULTI_CLICK_TIMEOUT_SEC,
        resolve_spin_success_check_timeout,
    )

    assert resolve_spin_success_check_timeout(
        {"id": "FC-SLOT-007", "_layout": "portrait"}
    ) == FC_SPIN_SUCCESS_CHECK_TIMEOUT_SEC
    assert resolve_spin_success_check_timeout(
        {"id": "FC-SLOT-007", "layout": "portrait"}
    ) == SPIN_MULTI_CLICK_TIMEOUT_SEC
    assert resolve_spin_success_check_timeout(
        {"id": "JILI-SLOT-001", "_layout": "portrait"}
    ) == SPIN_MULTI_CLICK_TIMEOUT_SEC
