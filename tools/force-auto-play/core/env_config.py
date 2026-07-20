"""Helpers for per-environment test settings (entry mode, comboburst portal, etc.)."""

from __future__ import annotations

from typing import Any

ENTRY_MODE_JC_LOBBY = "jc_lobby"
ENTRY_MODE_COMBOBURST_PORTAL = "comboburst_portal"


def get_client_env_config(global_config: dict) -> dict:
    env_name = global_config.get("_env", "uat")
    projects = global_config.get("projects") or {}
    client = projects.get("client") or {}
    environments = client.get("environments") or {}
    return environments.get(env_name) or environments.get("uat") or {}


def get_entry_mode(global_config: dict) -> str:
    return get_client_env_config(global_config).get("entry_mode", ENTRY_MODE_JC_LOBBY)


def resolve_entry_mode(global_config: dict, game_conf: dict | None = None) -> str:
    """Per-game entry_mode in games.yaml overrides environment default."""
    if game_conf:
        mode = game_conf.get("entry_mode")
        if mode and str(mode).strip():
            return str(mode).strip()
    return get_entry_mode(global_config)


def uses_comboburst_portal(global_config: dict, game_conf: dict | None = None) -> bool:
    return resolve_entry_mode(global_config, game_conf) == ENTRY_MODE_COMBOBURST_PORTAL


def get_comboburst_config(global_config: dict) -> dict:
    return get_client_env_config(global_config).get("comboburst") or {}
