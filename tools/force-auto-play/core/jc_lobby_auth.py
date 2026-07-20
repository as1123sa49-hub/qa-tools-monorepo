"""Resolve JC lobby Playwright storage_state path."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUTH_REL = "config/.auth/jc_lobby_{env}.json"


def resolve_jc_lobby_auth_path(
    global_config: dict | None = None,
    *,
    env_name: str | None = None,
) -> str:
    """Return absolute path for JC lobby storage_state JSON."""
    cfg = global_config or {}
    env = env_name or cfg.get("_env") or "uat"
    env_cfg = {}
    try:
        from core.env_config import get_client_env_config

        env_cfg = get_client_env_config(cfg) if cfg else {}
    except Exception:
        env_cfg = {}

    raw = (
        env_cfg.get("jc_lobby_auth_file")
        or os.environ.get("JC_LOBBY_AUTH_FILE")
        or DEFAULT_AUTH_REL.format(env=env)
    )
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


def resolve_jc_lobby_auth_path_for_load(global_config: dict | None = None) -> str:
    """Primary JC auth path (may not exist yet)."""
    return resolve_jc_lobby_auth_path(global_config)
