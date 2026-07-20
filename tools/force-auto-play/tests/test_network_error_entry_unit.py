"""Unit tests for network-error detection at game entry (Lucky Fortunes-style)."""

from core.game_utils import (
    _network_error_present,
    get_entry_error_reason,
    set_entry_error_reason,
)


def _ocr(*texts):
    return [([[0, 0], [10, 0], [10, 10], [0, 10]], t, 0.9) for t in texts]


def test_network_error_present_detects_common_phrases():
    assert _network_error_present(_ocr("Network Error"))
    assert _network_error_present(_ocr("Connection lost, please try again"))
    assert _network_error_present(_ocr("網路錯誤"))


def test_network_error_present_ignores_normal_footer():
    assert not _network_error_present(_ocr("BALANCE", "10,007,374", "WIN", "0"))
    assert not _network_error_present(_ocr("TOTAL BETS", "2.00"))


def test_entry_error_reason_roundtrip_and_reset():
    conf: dict = {}
    assert get_entry_error_reason(conf) is None
    set_entry_error_reason(conf, "network error")
    assert get_entry_error_reason(conf) == "network error"
    set_entry_error_reason(conf, None)
    assert get_entry_error_reason(conf) is None


def test_get_entry_error_reason_handles_none_config():
    assert get_entry_error_reason(None) is None
