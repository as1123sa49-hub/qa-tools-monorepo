from core.balance_audit import is_plausible_ingame_balance
from core.ui_locator import (
    count_cards_on_label_row,
    poster_click_from_label_bbox,
)


def test_count_cards_on_label_row_three_up():
    hits = [
        (200, 500, "Chinese New Year"),
        (500, 505, "Chinese New Year 2"),
        (800, 498, "Chinese New Year Moreways"),
        (300, 420, "FA CHAI"),
    ]
    assert count_cards_on_label_row(hits, 500) == 3


def test_poster_click_3col_stays_below_label_above_provider_safe():
    bbox = (180, 620, 420, 650)
    cx, cy = poster_click_from_label_bbox(bbox, viewport_height=720, row_cols=3)
    assert 520 <= cy <= 610
    assert cx == 300


def test_poster_click_rejects_provider_row_when_label_high():
    """Misplaced label in provider band nudges click into card grid, not provider chips."""
    bbox = (680, 360, 760, 390)
    _cx, cy = poster_click_from_label_bbox(bbox, viewport_height=720, row_cols=3)
    assert cy >= 720 * 0.53 + 12


def test_poster_click_2col_uses_larger_offset():
    bbox = (200, 620, 500, 650)
    _cx, cy_3 = poster_click_from_label_bbox(bbox, viewport_height=720, row_cols=3)
    _cx, cy_2 = poster_click_from_label_bbox(bbox, viewport_height=720, row_cols=2)
    assert cy_2 <= cy_3


def test_is_plausible_rejects_footer_fragment():
    lobby_b0 = 10_007_361.02
    assert not is_plausible_ingame_balance(361.02, lobby_b0)
    assert is_plausible_ingame_balance(10_007_358.02, lobby_b0)
