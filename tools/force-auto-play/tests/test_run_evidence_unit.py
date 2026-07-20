"""Unit tests for run_evidence JSON helpers."""

import json
from pathlib import Path

from core.run_evidence import (
    format_evidence_summary,
    init_run_evidence,
    record_console_settlement_to_evidence,
    record_footer_strip_to_evidence,
    record_spin_click_attempt,
    set_balance_fields,
    write_run_evidence,
)
from core.artifact_handler import ArtifactHandler
from core.balance_audit import FcFooterStrip, JdbFooterStrip


def test_init_and_write_run_evidence(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    game_conf = {}
    init_run_evidence(
        game_conf,
        provider="JDB",
        game_id="JDB-SLOT-123",
        game_name="Piggy Bank",
    )
    set_balance_fields(
        game_conf,
        lobby_b0=10007361.28,
        before_primary=10007361.28,
        after_primary=10007360.28,
    )
    record_footer_strip_to_evidence(
        game_conf, JdbFooterStrip(balance=10007360.28, bet=1.0, win=0.0)
    )
    record_spin_click_attempt(
        game_conf,
        {
            "label": "center",
            "coords": [640.0, 606.2],
            "is_retry": False,
            "reel": {"moved": False, "mad": 2.63},
        },
    )
    path = write_run_evidence(handler, game_conf, "pass", settle_path="visual")
    assert path is not None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["outcome"] == "pass"
    assert data["game_id"] == "JDB-SLOT-123"
    assert data["balances"]["before_primary"] == 10007361.28
    assert data["balances"]["bet"] == 1.0
    assert data["balances"]["win"] == 0.0
    assert data["spin_click"]["first_reel"]["mad"] == 2.63


def test_record_footer_strip_fc_uses_total_bets_as_bet():
    game_conf = {}
    init_run_evidence(
        game_conf,
        provider="FC",
        game_id="FC-SLOT-005",
        game_name="Pong Pong Hu",
    )
    record_footer_strip_to_evidence(
        game_conf,
        FcFooterStrip(balance=1000.0, win=2.5, total_bets=1.2),
    )
    bal = game_conf["_run_evidence"]["balances"]
    assert bal["bet"] == 1.2
    assert bal["win"] == 2.5


def test_record_console_settlement_to_evidence():
    game_conf = {}
    init_run_evidence(
        game_conf,
        provider="COMBO",
        game_id="CMB_COMBO_Example",
        game_name="Example",
    )
    record_console_settlement_to_evidence(
        game_conf, {"bet": 2.0, "win": 5.5, "b0": 100.0, "b1": 103.5}
    )
    bal = game_conf["_run_evidence"]["balances"]
    assert bal["bet"] == 2.0
    assert bal["win"] == 5.5


def test_format_evidence_summary_includes_bet_win():
    game_conf = {}
    init_run_evidence(
        game_conf,
        provider="JDB",
        game_id="JDB-SLOT-123",
        game_name="Piggy Bank",
    )
    set_balance_fields(
        game_conf,
        lobby_b0=10007432.3,
        before_primary=10007432.3,
        after_primary=10007431.3,
        bet=1.0,
        win=0.0,
    )
    summary = format_evidence_summary(game_conf)
    assert "bet=1.0" in summary
    assert "win=0.0" in summary


def test_format_evidence_summary():
    game_conf = {}
    init_run_evidence(
        game_conf,
        provider="FC",
        game_id="FC-SLOT-004",
        game_name="Night Market",
    )
    set_balance_fields(game_conf, lobby_b0=1000.0, before_primary=999.0)
    summary = format_evidence_summary(game_conf, "PRE_BALANCE")
    assert "lobby_b0=1000.0" in summary
    assert "before=999.0" in summary
    assert "code=PRE_BALANCE" in summary
