"""Unit tests for fail codes and run labels."""

from core.fail_codes import (
    FAIL_PRE_BALANCE,
    FAIL_SPIN_NETWORK,
    RUN_ROUND_ENV,
    format_fail,
    parse_fail_code,
    resolve_run_round,
    run_label,
)


def test_format_fail_prefixes_code():
    assert format_fail(FAIL_PRE_BALANCE, "No balance") == "[PRE_BALANCE] No balance"
    assert format_fail(FAIL_SPIN_NETWORK, "") == "[SPIN_NETWORK]"


def test_parse_fail_code_from_message():
    assert parse_fail_code("[PRE_BALANCE] No footer") == "PRE_BALANCE"
    assert parse_fail_code("plain message") is None
    assert parse_fail_code(None) is None


def test_run_label_from_env(monkeypatch):
    monkeypatch.delenv(RUN_ROUND_ENV, raising=False)
    assert resolve_run_round() == 1
    assert run_label() == "run1"
    monkeypatch.setenv(RUN_ROUND_ENV, "2")
    assert run_label() == "run2"
    monkeypatch.setenv(RUN_ROUND_ENV, "0")
    assert resolve_run_round() == 1
