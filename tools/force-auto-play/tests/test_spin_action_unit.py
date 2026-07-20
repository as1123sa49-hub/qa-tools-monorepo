from unittest.mock import MagicMock, patch

from core.game_utils import perform_spin_action, _try_spin_click_candidates


def test_perform_spin_portrait_overlay_uses_spin_config():
    """Regression: spin_config was wrongly referenced as game_config (NameError)."""
    page = MagicMock()
    page.viewport_size = {"width": 1920, "height": 911}
    hybrid = MagicMock()
    hybrid.get_cached_coords.return_value = None
    hybrid.ocr.reader.readtext.return_value = []
    artifacts = MagicMock()
    spin_config = {"_layout": "portrait", "id": "FC-SLOT-004", "spin_button": {"region": {}}}

    with patch("core.game_utils.dismiss_portrait_intro_carousel", return_value=0):
        with patch(
            "core.game_utils.dismiss_extra_bet_teaching_overlay_if_present",
            return_value=False,
        ) as dismiss_overlay:
            with patch("core.game_utils.get_spin_coord", return_value=None):
                with patch("core.game_utils._portrait_continue_promo_visible", return_value=False):
                    with patch("core.game_utils._detect_spin_bbox", return_value=None):
                        with patch(
                            "core.game_utils._portrait_spin_fallback_candidates",
                            return_value=([("center", 500.0, 800.0)], 0.0),
                        ):
                            with patch(
                                "core.game_utils._try_spin_click_candidates",
                                return_value=((500.0, 800.0), True),
                            ):
                                coords, ok = perform_spin_action(
                                    page,
                                    hybrid,
                                    spin_config,
                                    "FC-SLOT-004",
                                    1,
                                    artifacts,
                                    success_check=None,
                                )

    dismiss_overlay.assert_called_once()
    assert dismiss_overlay.call_args.kwargs["game_config"] is spin_config
    assert coords == (500.0, 800.0)
    assert ok is True


def test_perform_spin_skips_click_when_already_spun_after_overlay():
    """Overlay dismiss may trigger a spin; do not click spin again."""
    page = MagicMock()
    page.viewport_size = {"width": 1280, "height": 720}
    hybrid = MagicMock()
    hybrid.get_cached_coords.return_value = None
    artifacts = MagicMock()
    spin_config = {
        "_layout": "portrait",
        "id": "FC-SLOT-022",
        "spin_button": {
            "region": {
                "x_start": 0.38,
                "x_end": 0.62,
                "y_start": 0.72,
                "y_end": 0.88,
            }
        },
    }

    with patch("core.game_utils.dismiss_portrait_intro_carousel", return_value=0):
        with patch(
            "core.game_utils.dismiss_extra_bet_teaching_overlay_if_present",
            return_value=True,
        ):
            with patch("core.game_utils.get_spin_coord", return_value=None):
                with patch(
                    "core.game_utils._try_spin_click_candidates",
                ) as try_click:
                    coords, from_cache = perform_spin_action(
                        page,
                        hybrid,
                        spin_config,
                        "FC-SLOT-022",
                        1,
                        artifacts,
                        success_check=lambda timeout_sec=None: True,
                    )

    try_click.assert_not_called()
    assert coords is not None
    assert from_cache is False


def test_try_spin_click_skips_when_already_acknowledged():
    page = MagicMock()
    artifacts = MagicMock()
    hybrid = MagicMock()
    clicked = []

    def fake_click(*args, **kwargs):
        clicked.append(True)

    with patch("core.game_utils.click_with_marker", side_effect=fake_click):
        with patch("core.game_utils._cache_spin_coords"):
            coords, _ = _try_spin_click_candidates(
                page,
                artifacts,
                hybrid,
                "k",
                "FC-SLOT-022",
                1,
                [("center", 640.0, 606.0)],
                [],
                b"",
                success_check=lambda timeout_sec=None: True,
                success_check_timeout=14.0,
            )

    assert coords == (640.0, 606.0)
    assert clicked == []
