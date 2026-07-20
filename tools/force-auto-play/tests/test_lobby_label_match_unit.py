from core.ui_locator import (
    lobby_poster_click_y_ok,
    lobby_search_label_y_ok,
    score_lobby_label_match,
    should_replace_lobby_label_match,
)


def test_exact_match_night_market():
    assert score_lobby_label_match("Night Market", "Night Market") > 0


def test_night_market_does_not_match_sequel():
    assert score_lobby_label_match("Night Market", "Night Market 2") == 0


def test_night_market_2_matches_sequel():
    assert score_lobby_label_match("Night Market 2", "Night Market 2") > 0


def test_chinese_new_year_sequel_boundary():
    assert score_lobby_label_match("Chinese New Year", "Chinese New Year 2") == 0
    assert score_lobby_label_match("Chinese New Year 2", "Chinese New Year 2") > 0


def test_chinese_new_year_prefix_match():
    exact = score_lobby_label_match("Chinese New Year", "Chinese New Year")
    prefix = score_lobby_label_match("Chinese New Year", "Chinese New")
    assert prefix > 0
    assert exact > prefix
    assert score_lobby_label_match("Chinese New Year", "inewyearl") == 0


def test_tie_break_prefers_leftmost_on_same_row():
    """Same score on one result row picks the leftmost game card."""
    score = score_lobby_label_match("Chinese New Year", "Chinese New")
    assert should_replace_lobby_label_match(score, 698.0, 523.0, score, 698.0, 375.0)
    assert not should_replace_lobby_label_match(score, 698.0, 375.0, score, 698.0, 523.0)


def test_tie_break_prefers_lowest_label_on_different_rows():
    """Different rows: prefer the label lower on screen (larger cy)."""
    score = score_lobby_label_match("Sugar Bang Bang", "Sugar Bang Bang")
    assert should_replace_lobby_label_match(score, 500.0, 200.0, score, 650.0, 200.0)
    assert not should_replace_lobby_label_match(score, 650.0, 200.0, score, 500.0, 200.0)


def test_lobby_search_label_y_ok_excludes_provider_row():
    assert not lobby_search_label_y_ok(150, 720)
    assert not lobby_search_label_y_ok(350, 720)
    assert lobby_search_label_y_ok(420, 720)


def test_lobby_vlm_y_guard_rejects_provider_band():
    assert not lobby_poster_click_y_ok(356.0, 720.0)
    assert lobby_poster_click_y_ok(520.0, 720.0)
