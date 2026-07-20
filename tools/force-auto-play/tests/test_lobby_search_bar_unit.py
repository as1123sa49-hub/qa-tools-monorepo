from unittest.mock import MagicMock

from core.game_utils import (
    _resolve_lobby_search_bar,
    _vlm_rect_height_frac,
    _vlm_rect_top_frac,
    _vlm_search_box_plausible,
    _vlm_search_coords_valid,
)


def _page(vp_h=911):
    page = MagicMock()
    page.viewport_size = {"height": vp_h, "width": 1920}
    return page


def test_vlm_search_coords_accepts_feature_home_search_bar():
    page = _page()
    assert _vlm_search_coords_valid(page, (960.0, 403.0), [120, 350, 880, 420])


def test_vlm_search_coords_accepts_top_overlay():
    page = _page()
    assert _vlm_search_coords_valid(page, (960.0, 120.0), [80, 60, 920, 160])


def test_vlm_search_coords_rejects_hot_games_center_panel():
    page = _page()
    huge = [120, 650, 1000, 870]
    assert not _vlm_search_box_plausible(huge)
    assert _vlm_rect_top_frac(huge) > 0.52
    assert _vlm_rect_height_frac(huge) > 0.14
    assert not _vlm_search_coords_valid(page, (692.0, 692.0), huge)


def test_vlm_search_coords_rejects_mid_screen_without_overlay():
    page = _page()
    assert not _vlm_search_coords_valid(page, (500.0, 600.0), [200, 550, 800, 650])


def test_resolve_lobby_search_bar_uses_placeholder_without_y_cap():
    page = _page()
    ui_scanner = MagicMock(
        return_value={"search_bar_placeholder": (960.0, 403.0)},
    )
    hybrid = MagicMock()
    assert _resolve_lobby_search_bar(page, ui_scanner, hybrid) == (960.0, 403.0)
    hybrid.vision.detect_ui_element.assert_not_called()


def test_resolve_lobby_search_bar_prefers_overlay_input():
    page = _page()
    ui_scanner = MagicMock(
        return_value={
            "search_overlay_input": (960.0, 95.0),
            "search_bar_placeholder": (960.0, 403.0),
        },
    )
    assert _resolve_lobby_search_bar(page, ui_scanner, MagicMock()) == (960.0, 95.0)
