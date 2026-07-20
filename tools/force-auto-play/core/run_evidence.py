"""Lightweight pass/fail evidence JSON written into each artifact session folder."""

from __future__ import annotations

import json
import os
from typing import Any

from core.fail_codes import run_label as resolve_run_label

_RUN_EVIDENCE_KEY = "_run_evidence"


def evidence_store(game_conf: dict | None) -> dict:
    if game_conf is None:
        return {}
    if _RUN_EVIDENCE_KEY not in game_conf:
        game_conf[_RUN_EVIDENCE_KEY] = {}
    return game_conf[_RUN_EVIDENCE_KEY]


def init_run_evidence(
    game_conf: dict,
    *,
    provider: str,
    game_id: str,
    game_name: str,
) -> None:
    """Reset per-test evidence bucket on game_conf."""
    game_conf[_RUN_EVIDENCE_KEY] = {
        "provider": provider,
        "game_id": game_id,
        "game_name": game_name,
        "run": resolve_run_label(),
        "balances": {},
        "spin": {},
        "spin_click": {"attempts": 0, "retry_used": False},
        "audit": {},
    }


def set_balance_fields(game_conf: dict | None, **fields: Any) -> None:
    store = evidence_store(game_conf)
    bucket = store.setdefault("balances", {})
    for key, val in fields.items():
        if val is not None:
            bucket[key] = float(val) if isinstance(val, (int, float)) else val


def record_footer_strip_to_evidence(game_conf: dict | None, strip) -> None:
    """Copy bet/win from FC/JDB footer strip into ``balances`` when present."""
    if game_conf is None or strip is None:
        return
    bet = getattr(strip, "total_bets", None)
    if bet is None:
        bet = getattr(strip, "bet", None)
    win = getattr(strip, "win", None)
    fields: dict[str, float] = {}
    if bet is not None:
        fields["bet"] = float(bet)
    if win is not None:
        fields["win"] = float(win)
    if fields:
        set_balance_fields(game_conf, **fields)


def record_console_settlement_to_evidence(game_conf: dict | None, summary: dict) -> None:
    """Copy bet/win from COMBO console settlement summary when present."""
    if game_conf is None or not summary:
        return
    fields: dict[str, float] = {}
    if summary.get("bet") is not None:
        fields["bet"] = float(summary["bet"])
    if summary.get("win") is not None:
        fields["win"] = float(summary["win"])
    if fields:
        set_balance_fields(game_conf, **fields)


def enrich_balances_from_footer(page, hybrid_locator, game_conf: dict | None) -> None:
    """Best-effort footer strip read to fill bet/win in evidence."""
    if page is None or hybrid_locator is None or game_conf is None:
        return
    from core.balance_audit import (
        read_in_game_fc_footer_strip,
        read_in_game_jdb_footer_strip,
    )
    from core.game_utils import use_fc_portrait_footer_strip, use_jdb_portrait_footer_strip

    strip = None
    if use_fc_portrait_footer_strip(game_conf, page, hybrid_locator):
        strip = read_in_game_fc_footer_strip(page, hybrid_locator, game_conf)
    elif use_jdb_portrait_footer_strip(game_conf, page, hybrid_locator):
        strip = read_in_game_jdb_footer_strip(page, hybrid_locator, game_conf)
    record_footer_strip_to_evidence(game_conf, strip)


def set_spin_fields(game_conf: dict | None, **fields: Any) -> None:
    store = evidence_store(game_conf)
    bucket = store.setdefault("spin", {})
    for key, val in fields.items():
        if val is not None:
            bucket[key] = val


def set_audit_fields(game_conf: dict | None, **fields: Any) -> None:
    store = evidence_store(game_conf)
    bucket = store.setdefault("audit", {})
    for key, val in fields.items():
        if val is not None:
            bucket[key] = val


def update_spin_click_summary(game_conf: dict | None, **fields: Any) -> None:
    sc = evidence_store(game_conf).setdefault("spin_click", {})
    for key, val in fields.items():
        if val is not None:
            sc[key] = val
    details = sc.get("attempts_detail") or []
    if details:
        details[-1].update({k: v for k, v in fields.items() if v is not None})


def record_spin_click_attempt(game_conf: dict | None, attempt: dict[str, Any]) -> None:
    """Append one spin click attempt (first click, retry, cached, …)."""
    store = evidence_store(game_conf)
    sc = store.setdefault("spin_click", {})
    details = sc.setdefault("attempts_detail", [])
    details.append(attempt)
    sc["attempts"] = len(details)
    if attempt.get("is_retry"):
        sc["retry_used"] = True
    for key in (
        "coords",
        "first_ack_ok",
        "after_retry_ack_ok",
        "retry_reason",
        "retry_still_static",
    ):
        if key in attempt and attempt[key] is not None:
            sc[key] = attempt[key]
    first = details[0] if details else {}
    reel = first.get("reel") or {}
    if isinstance(reel, dict) and "mad" in reel:
        sc["first_reel"] = reel
    if len(details) > 1:
        retry_reel = details[-1].get("reel") or {}
        if isinstance(retry_reel, dict) and "mad" in retry_reel:
            sc["second_reel"] = retry_reel


def build_evidence_payload(
    game_conf: dict | None,
    outcome: str,
    fail_code: str | None = None,
    *,
    settle_path: str | None = None,
) -> dict[str, Any]:
    store = dict(evidence_store(game_conf))
    store["outcome"] = outcome
    store["fail_code"] = fail_code
    if settle_path:
        store["settle_path"] = settle_path
    return store


def format_evidence_summary(game_conf: dict | None, fail_code: str | None = None) -> str:
    """Compact one-line summary for pytest.fail / logs."""
    store = evidence_store(game_conf)
    parts: list[str] = []
    bal = store.get("balances") or {}
    sc = store.get("spin_click") or {}
    if bal.get("lobby_b0") is not None:
        parts.append(f"lobby_b0={bal['lobby_b0']}")
    if bal.get("before_primary") is not None:
        parts.append(f"before={bal['before_primary']}")
    if bal.get("after_primary") is not None:
        parts.append(f"after={bal['after_primary']}")
    if bal.get("bet") is not None:
        parts.append(f"bet={bal['bet']}")
    if bal.get("win") is not None:
        parts.append(f"win={bal['win']}")
    if bal.get("lobby_b1") is not None:
        parts.append(f"lobby_b1={bal['lobby_b1']}")
    if sc.get("retry_used"):
        parts.append("retry_used=true")
    first_reel = sc.get("first_reel") or {}
    if isinstance(first_reel, dict) and first_reel.get("mad") is not None:
        parts.append(f"first_mad={first_reel['mad']}")
    if fail_code:
        parts.append(f"code={fail_code}")
    return " | ".join(parts)


def write_run_evidence(
    artifact_handler,
    game_conf: dict | None,
    outcome: str,
    fail_code: str | None = None,
    *,
    settle_path: str | None = None,
) -> str | None:
    if artifact_handler is None or game_conf is None:
        return None
    payload = build_evidence_payload(
        game_conf, outcome, fail_code, settle_path=settle_path
    )
    if not payload.get("game_id"):
        return None
    artifact_handler._ensure_dirs()
    path = os.path.join(artifact_handler.base_dir, "run_evidence.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path
