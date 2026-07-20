"""Unit tests for game_frame_utils."""

from unittest.mock import MagicMock

from core.game_frame_utils import enable_game_debug, iter_game_contexts


def test_enable_game_debug_iterates_contexts():
    page = MagicMock()
    game_frame = MagicMock()
    game_frame.url = "https://games-uat.comboburst.com/game"
    page.frames = [game_frame]
    page.evaluate = MagicMock()

    count = enable_game_debug(page, "games-uat.comboburst.com")

    assert count >= 2
    game_frame.evaluate.assert_called_once()
    page.evaluate.assert_called_once()


def test_iter_game_contexts_prioritizes_expected_host():
    page = MagicMock()
    other_frame = MagicMock()
    other_frame.url = "https://games-dev.comboburst.com/home"
    game_frame = MagicMock()
    game_frame.url = "https://games-uat.comboburst.com/game"
    page.frames = [other_frame, game_frame]
    contexts = list(iter_game_contexts(page, "games-uat.comboburst.com"))
    assert contexts[0] is game_frame
