"""Stable fail codes for pytest summary / artifact folder names."""

from __future__ import annotations

import os
import re

# Environment variable set by full-run / rerun scripts.
RUN_ROUND_ENV = "FORCE_AUTO_PLAY_RUN"

FAIL_ENTRY_NETWORK = "ENTRY_NETWORK"
FAIL_ENTRY_SEARCH = "ENTRY_SEARCH"
FAIL_ENTRY_LOAD = "ENTRY_LOAD"
FAIL_ENTRY_VERIFY = "ENTRY_VERIFY"
FAIL_ENTRY_UNKNOWN = "ENTRY_UNKNOWN"
FAIL_PRE_BALANCE = "PRE_BALANCE"
FAIL_SPIN_ACK = "SPIN_ACK"
FAIL_SPIN_NETWORK = "SPIN_NETWORK"
FAIL_SETTLE = "SETTLE"
FAIL_AUDIT = "AUDIT"
FAIL_TIMEOUT = "SETTLE_TIMEOUT"
FAIL_VISUAL = "VISUAL"

_CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]\s*(.*)$", re.S)


def format_fail(code: str, message: str) -> str:
    """Prefix a pytest.fail message with ``[CODE]``."""
    msg = (message or "").strip()
    return f"[{code}] {msg}" if msg else f"[{code}]"


def parse_fail_code(message: str | None) -> str | None:
    if not message:
        return None
    match = _CODE_RE.match(str(message).strip())
    return match.group(1) if match else None


def resolve_run_round(default: int = 1) -> int:
    """Return 1-based run round from env (full run=1, --lf rerun=2, …)."""
    raw = (os.environ.get(RUN_ROUND_ENV) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


def run_label(round_num: int | None = None) -> str:
    n = resolve_run_round() if round_num is None else max(1, int(round_num))
    return f"run{n}"
