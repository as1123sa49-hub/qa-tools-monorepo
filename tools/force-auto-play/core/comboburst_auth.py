"""Resolve comboburst portal auth storage path."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUTH_REL = "config/.auth/comboburst_lobby.json"

# Optional shared auth from l10n-capture (sibling repo)
_L10N_AUTH_CANDIDATES = [
    PROJECT_ROOT.parent / "qa-tools-monorepo" / "tools" / "l10n-capture" / "data" / "default" / ".auth" / "lobby.json",
    PROJECT_ROOT.parent / "qa-tools-monorepo" / "tools" / "l10n-capture" / ".auth" / "lobby.json",
]


def resolve_comboburst_auth_path(comboburst_cfg: dict | None) -> str:
    """Return absolute path to Playwright storage_state JSON, or empty if unset."""
    cfg = comboburst_cfg or {}
    raw = cfg.get("auth_file") or os.environ.get("COMBOBURST_AUTH_FILE") or DEFAULT_AUTH_REL
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


def resolve_comboburst_auth_path_for_load(comboburst_cfg: dict | None) -> str:
    """Primary auth path, or first existing fallback (e.g. l10n-capture lobby.json)."""
    primary = resolve_comboburst_auth_path(comboburst_cfg)
    if os.path.isfile(primary):
        return primary
    for candidate in _L10N_AUTH_CANDIDATES:
        if candidate.is_file():
            return str(candidate.resolve())
    return primary
