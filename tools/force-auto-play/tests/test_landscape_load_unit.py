"""Unit tests for landscape game load phase detection."""

from core.game_utils import (
    _is_loose_continue_label,
    _loading_phase_detected,
    _splash_continue_visible,
    _portrait_continue_promo_visible,
)


def test_loading_phase_detects_progress_percent():
    assert _loading_phase_detected("initwaiting 98% combo v.0.3.13.u")
    assert _loading_phase_detected("loading bundle 42%")
    assert not _loading_phase_detected("free game continue v.0.3.13.u")


def test_loading_phase_detects_initwaiting_without_percent():
    assert _loading_phase_detected("Init Waiting please wait")
    assert _loading_phase_detected("initializing assets")


def test_loading_phase_ignores_hundred_percent():
    assert not _loading_phase_detected("100% complete free game")


def test_loose_continue_label_matches_substring():
    assert _is_loose_continue_label("Continue")
    assert _is_loose_continue_label("  continue  ")
    assert _splash_continue_visible([([[0, 0], [1, 0], [1, 1], [0, 1]], "Continue", 0.9)])


def test_version_string_does_not_count_as_loose_continue():
    assert not _is_loose_continue_label("v.0.3.13.u")


def test_continue_promo_blocks_ready():
    ocr = [([[0, 0], [1, 0], [1, 1], [0, 1]], "Continue", 0.9)]
    assert _portrait_continue_promo_visible(ocr)
    assert _splash_continue_visible(ocr)
