"""Unit tests for multi-frame GameConsoleListener attachment."""

from unittest.mock import MagicMock

from core.game_console_listener import GameConsoleListener


def test_listener_attaches_to_page_and_frames():
    listener = GameConsoleListener()
    page = MagicMock()
    frame = MagicMock()
    page.frames = [frame]

    listener.start(page)

    page.on.assert_any_call("frameattached", listener._on_frame_attached)
    page.on.assert_any_call("console", listener._handle_console_message)
    frame.on.assert_called_once_with("console", listener._handle_console_message)


def test_refresh_frames_attaches_new_frame():
    listener = GameConsoleListener()
    page = MagicMock()
    frame1 = MagicMock()
    frame2 = MagicMock()
    page.frames = [frame1]
    listener.start(page)
    frame1.on.reset_mock()

    page.frames = [frame1, frame2]
    added = listener.refresh_frames()

    assert added == 1
    frame2.on.assert_called_once_with("console", listener._handle_console_message)


def test_note_visual_spin_started():
    listener = GameConsoleListener()
    listener.note_visual_spin_started()
    assert listener.get_hint("visual_spin_started") is True
    assert listener.get_hint("spin_triggered") is True


def test_console_dedup_skips_duplicate_messages():
    listener = GameConsoleListener()
    msg = MagicMock()
    msg.text = "SpinTriggerDispatchEvent triggered"
    msg.type = "log"

    listener._handle_console_message(msg)
    assert listener.get_hint("spin_triggered") is True

    listener._handle_console_message(msg)
    assert listener.get_hint("spin_triggered") is True
