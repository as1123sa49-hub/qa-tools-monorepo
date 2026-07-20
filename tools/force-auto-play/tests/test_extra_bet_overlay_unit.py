from core.game_utils import (
    _center_tutorial_copy_visible,
    _is_teaching_overlay_present,
)


def test_center_tutorial_detects_activation_copy():
    class _Page:
        viewport_size = {"width": 1280, "height": 720}

    ocr = [
        (
            [[400, 280], [900, 280], [900, 380], [400, 380]],
            "Extra Bet is 1.5X of the original bet After activation unlocked reel",
            0.9,
        ),
    ]
    assert _center_tutorial_copy_visible(ocr, b"", _Page())


def test_center_tutorial_rejects_permanent_extra_bet_button_only():
    class _Page:
        viewport_size = {"width": 1280, "height": 720}

    ocr = [
        ([[500, 520], [780, 520], [780, 560], [500, 560]], "Extra Bet", 0.9),
        ([[500, 40], [780, 40], [780, 80], [500, 80]], "1024 WAYS", 0.9),
        ([[200, 650], [1080, 650], [1080, 700], [200, 700]], "BALANCE 10007369.92", 0.9),
    ]
    all_text = "extra bet 1024 ways balance total bets"
    assert not _is_teaching_overlay_present(ocr, all_text, b"", _Page())


def test_center_tutorial_rejects_mission_sidebar_with_ways():
    class _Page:
        viewport_size = {"width": 1280, "height": 720}

    ocr = [
        ([[50, 200], [120, 200], [120, 240], [50, 240]], "MISSION", 0.9),
        ([[50, 280], [120, 280], [120, 320], [50, 320]], "PROPS", 0.9),
        ([[500, 40], [780, 40], [780, 80], [500, 80]], "1024 WAYS", 0.9),
        ([[500, 520], [780, 520], [780, 560], [500, 560]], "Extra Bet", 0.9),
    ]
    all_text = "mission props 1024 ways extra bet balance"
    assert not _is_teaching_overlay_present(ocr, all_text, b"", _Page())
