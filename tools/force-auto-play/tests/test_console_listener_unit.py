"""Unit tests for GameConsoleListener spin settlement logic."""

from core.game_console_listener import GameConsoleListener
from core.game_utils import verify_spin_settlement


class _Msg:
    def __init__(self, text: str):
        self.text = text


def _feed(listener: GameConsoleListener, lines: list[str]):
    for line in lines:
        listener._handle_console_message(_Msg(line))


def test_losing_spin_settlement():
    listener = GameConsoleListener()
    listener._latest_data["current_balance"] = 3335747.85
    _feed(
        listener,
        [
            "SpinTriggerDispatchEvent triggered",
            "SendCommend: cmd: Slot056, requestId: x",
            "OnChangeBalance balance:3335744.85",
            "Spin response: Code=0, TxnId=abc-123",
            'ReciviedSpinResponse { "MGResult": {}, "FGResult": {}, "GameMode": 1 }',
            "OnChangeBalance balance:3335744.85",
            "OnUIBottomNormalEvent: Published UIBottomNormalDispatchEvent",
        ],
    )
    assert listener.is_spin_settled()
    summary = listener.get_settlement_summary()
    assert summary["b0"] == 3335747.85
    assert summary["bet"] == 3
    assert summary["win"] == 0
    assert summary["b1"] == 3335744.85
    ok, reason, _ = verify_spin_settlement(listener)
    assert ok, reason


def test_winning_spin_settlement():
    listener = GameConsoleListener()
    listener._latest_data["current_balance"] = 3335735.85
    _feed(
        listener,
        [
            "SpinTriggerDispatchEvent triggered",
            "OnChangeBalance balance:3335732.85",
            "Spin response: Code=0, TxnId=def-456",
            'ReciviedSpinResponse { "TotalWin": "4500", "MGResult": {}, "FGResult": {}, "GameMode": 1 }',
            "OnChangeBalance balance:3335733.3",
            "OnUIBottomNormalEvent",
        ],
    )
    assert listener.is_spin_settled()
    summary = listener.get_settlement_summary()
    assert abs(summary["win"] - 0.45) < 0.01
    ok, reason, _ = verify_spin_settlement(listener)
    assert ok, reason


def test_big_win_b1_greater_than_b0():
    listener = GameConsoleListener()
    listener._latest_data["current_balance"] = 3335705.7
    _feed(
        listener,
        [
            "SpinTriggerDispatchEvent triggered",
            "OnChangeBalance balance:3335702.7",
            "Spin response: Code=0, TxnId=ghi-789",
            'ReciviedSpinResponse { "TotalWin": "36000", "MGResult": {}, "FGResult": {}, "GameMode": 1 }',
            "OnChangeBalance balance:3335706.3",
            "OnUIBottomNormalEvent",
        ],
    )
    summary = listener.get_settlement_summary()
    assert summary["b1"] > summary["b0"]
def test_magic_runes_bet_before_spin_trigger():
    """Magic Runes: bet OnChangeBalance arrives before SpinTriggerDispatchEvent."""
    listener = GameConsoleListener()
    listener._latest_data["current_balance"] = 3335695.5
    _feed(
        listener,
        [
            "OnChangeBalance balance:3335695.5",
            "SendCommend: cmd: Slot002, requestId: x",
            "OnChangeBalance balance:3335692.5",
            "OnSpinTriggerEvent: Published SpinTriggerDispatchEvent.",
            "Spin response: Code=0, TxnId=3dca96b0-c9ce-4d58-91a5-4cff52815571",
            'ReciviedSpinResponse { "MGResult": { "MainWin": "22500" }, "FGResult": {}, '
            '"TotalWin": "22500", "GameMode": 1 }',
            "OnChangeBalance balance:3335694.75",
            "OnUIBottomNormalEvent: Published UIBottomNormalDispatchEvent.",
        ],
    )
    assert listener.is_spin_settled()
    summary = listener.get_settlement_summary()
    assert summary["b0"] == 3335695.5
    assert summary["bet"] == 3
    assert abs(summary["win"] - 2.25) < 0.01
    assert summary["b1"] == 3335694.75
    ok, reason, _ = verify_spin_settlement(listener)
    assert ok, reason


def test_gem_bonanza_style_settlement_without_recivied_spin_response():
    """Some COMBO H5 builds emit Spin response + UIBottomNormal but not ReciviedSpinResponse."""
    listener = GameConsoleListener()
    listener._latest_data["current_balance"] = 3335698.35
    _feed(
        listener,
        [
            "SpinTriggerDispatchEvent triggered",
            "OnChangeBalance balance:3335695.35",
            "Spin response: Code=0, TxnId=66c5f2d1-d7f9-45e3-8a51-3e30c1126102",
            "[BottomBarManager] OnSetWin: 0 -> 21",
            "[BottomBarUIMediator] OnUIBottomNormalDispatchEvent triggered",
            "OnChangeBalance balance:3335716.35",
        ],
    )
    assert listener.has_spin_acknowledged()
    assert listener.is_spin_settled()
    summary = listener.get_settlement_summary()
    assert summary["b0"] == 3335698.35
    assert summary["bet"] == 3
    assert abs(summary["win"] - 21) < 0.01
    assert summary["b1"] == 3335716.35
    ok, reason, _ = verify_spin_settlement(listener)
    assert ok, reason


def test_free_game_settlement():
    listener = GameConsoleListener()
    listener._latest_data["current_balance"] = 3335965.95
    _feed(
        listener,
        [
            "SpinTriggerDispatchEvent triggered",
            "OnChangeBalance balance:3335665.95",
            "Spin response: Code=0, TxnId=fg-txn",
            'ReciviedSpinResponse { "MGResult": {}, "FGResult": {}, "GameMode": 1 }',
            "OnFreeGameEnterEvent",
            "OnFreeGameLeaveEvent",
            "OnChangeBalance balance:3335747.85",
        ],
    )
    assert listener.is_spin_settled()
    summary = listener.get_settlement_summary()
    assert summary["bet"] == 300
    assert abs(summary["win"] - 81.90) < 0.01
    ok, reason, _ = verify_spin_settlement(listener)
    assert ok, reason
