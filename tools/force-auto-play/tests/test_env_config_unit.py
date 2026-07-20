"""Unit tests for env_config and comboburst portal helpers."""

from unittest.mock import MagicMock

import pytest

from core.comboburst_auth import resolve_comboburst_auth_path, resolve_comboburst_auth_path_for_load
from core.comboburst_lobby import (
    _wait_for_unity_canvas,
    resolve_portal_click_id,
    resolve_portal_search_query,
    resolve_portal_slot_id,
)
from core.game_frame_utils import iter_game_contexts, unity_canvas_ready
from core.env_config import (
    ENTRY_MODE_COMBOBURST_PORTAL,
    ENTRY_MODE_JC_LOBBY,
    get_entry_mode,
    resolve_entry_mode,
)


def test_get_entry_mode_defaults_to_jc_lobby():
    assert get_entry_mode({"projects": {"client": {"environments": {"uat": {}}}}}) == ENTRY_MODE_JC_LOBBY


def test_get_entry_mode_comboburst():
    cfg = {
        "projects": {
            "client": {
                "environments": {
                    "uat": {"entry_mode": ENTRY_MODE_COMBOBURST_PORTAL},
                }
            }
        },
        "_env": "uat",
    }
    assert get_entry_mode(cfg) == ENTRY_MODE_COMBOBURST_PORTAL


def test_resolve_entry_mode_game_override():
    global_cfg = {
        "projects": {"client": {"environments": {"uat": {"entry_mode": ENTRY_MODE_JC_LOBBY}}}},
        "_env": "uat",
    }
    game_cfg = {"entry_mode": ENTRY_MODE_COMBOBURST_PORTAL}
    assert resolve_entry_mode(global_cfg, game_cfg) == ENTRY_MODE_COMBOBURST_PORTAL
    assert resolve_entry_mode(global_cfg, {}) == ENTRY_MODE_JC_LOBBY


def test_resolve_portal_search_query_prefers_search_keyword():
    conf = {
        "search_keyword": "Magic Runes",
        "name": "Magic Runes Full",
        "portal_slot_id": "Slot002",
    }
    assert resolve_portal_search_query(conf) == "Magic Runes"


def test_resolve_portal_search_query_falls_back_to_name():
    assert resolve_portal_search_query({"name": "Wild Buffalo"}) == "Wild Buffalo"


def test_resolve_portal_search_query_falls_back_to_portal_slot_id():
    assert resolve_portal_search_query({"portal_slot_id": "Slot056"}) == "Slot056"


def test_resolve_portal_search_query_missing():
    with pytest.raises(ValueError, match="search_keyword or name"):
        resolve_portal_search_query({"id": "CMB_COMBO_X"})


def test_resolve_portal_slot_id_alias():
    assert resolve_portal_slot_id({"search_keyword": "Magic Runes"}) == "Magic Runes"


def test_resolve_portal_click_id_returns_slot_when_set():
    assert resolve_portal_click_id({"portal_slot_id": "Slot002"}) == "Slot002"


def test_resolve_portal_click_id_none_when_missing():
    assert resolve_portal_click_id({"search_keyword": "Magic Runes"}) is None


def test_resolve_comboburst_auth_path_relative():
    path = resolve_comboburst_auth_path({"auth_file": "config/.auth/comboburst_lobby.json"})
    assert path.endswith("config\\.auth\\comboburst_lobby.json") or path.endswith(
        "config/.auth/comboburst_lobby.json"
    )


def test_unity_canvas_ready_checks_intrinsic_width():
    canvas = MagicMock()
    canvas.is_visible.return_value = True
    canvas.evaluate.return_value = 720
    ctx = MagicMock()
    ctx.locator.return_value.first = canvas
    assert unity_canvas_ready(ctx) is True
    canvas.evaluate.return_value = 50
    assert unity_canvas_ready(ctx) is False


def test_iter_game_contexts_prioritizes_expected_host():
    page = MagicMock()
    page.url = "https://games-dev.comboburst.com/home/index.html"
    game_frame = MagicMock()
    game_frame.url = "https://games-uat.comboburst.com/game"
    other_frame = MagicMock()
    other_frame.url = "https://other.example.com/"
    page.frames = [other_frame, game_frame]
    contexts = list(iter_game_contexts(page, "games-uat.comboburst.com"))
    assert contexts[0] is game_frame
    assert page in contexts


def test_wait_for_unity_canvas_finds_canvas_in_cross_origin_frame(monkeypatch):
    page = MagicMock()
    page.url = "https://games-dev.comboburst.com/home/index.html"
    game_frame = MagicMock()
    game_frame.url = "https://games-uat.comboburst.com/game"
    page.frames = [game_frame]

    calls = {"n": 0}

    def fake_ready(ctx):
        calls["n"] += 1
        return ctx is game_frame and calls["n"] >= 1

    monkeypatch.setattr("core.comboburst_lobby.unity_canvas_ready", fake_ready)
    monkeypatch.setattr("core.comboburst_lobby.time.sleep", lambda *_: None)
    _wait_for_unity_canvas(page, expected_host="games-uat.comboburst.com", timeout_ms=5_000)
