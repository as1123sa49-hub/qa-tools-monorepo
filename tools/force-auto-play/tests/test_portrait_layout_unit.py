from unittest.mock import MagicMock

import pytest

from core.game_utils import (
    FC_PORTRAIT_BALANCE_REGION,
    FC_PORTRAIT_FOOTER_REGION,
    LAYOUT_LANDSCAPE,
    LAYOUT_PORTRAIT,
    PORTRAIT_DEFAULT_SPIN_REGION,
    PORTRAIT_FOOTER_REGION,
    _game_config_is_fc,
    _game_config_landscape_hint,
    _game_config_portrait_hint,
    _layout_ratio_is_portrait,
    _is_continue_promo_label,
    _is_weak_intro_label,
    _portrait_continue_promo_visible,
    _portrait_intro_dismissable,
    _provisional_layout_for_load,
    build_spin_click_candidates,
    footer_ocr_regions_to_try,
    portrait_footer_region,
    portrait_game_ui_detected,
    resolve_game_layout,
    resolve_spin_button_config,
    wait_for_unity_game_load,
)
from core.game_utils import _game_version_detected


def test_resolve_game_layout_yaml_override():
    page = MagicMock()
    game = {"layout": LAYOUT_PORTRAIT}
    assert resolve_game_layout(game, page) == LAYOUT_PORTRAIT


def test_resolve_game_layout_auto_detect(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        "core.game_utils.auto_detect_layout",
        lambda *_args, **_kwargs: LAYOUT_PORTRAIT,
    )
    game = {"id": "probe"}
    assert resolve_game_layout(game, page, MagicMock()) == LAYOUT_PORTRAIT
    assert game["_resolved_layout"] == LAYOUT_PORTRAIT


def test_game_config_portrait_hint_from_regions():
    assert _game_config_portrait_hint({"portrait_footer_region": {"x_start": 0}})
    assert not _game_config_portrait_hint({})


def test_portrait_footer_region_fc_default():
    fc = {"id": "FC-SLOT-004", "name": "Night Market", "layout": "portrait"}
    assert portrait_footer_region(fc) == FC_PORTRAIT_FOOTER_REGION
    assert portrait_footer_region({"id": "JILI-SLOT-001"}) == PORTRAIT_FOOTER_REGION


def test_game_config_is_fc():
    assert _game_config_is_fc({"id": "FC-SLOT-004"})
    assert _game_config_is_fc({"provider_key": "fc"})
    assert not _game_config_is_fc({"id": "JILI-SLOT-001"})


def test_footer_ocr_regions_to_try_fc_fallback(monkeypatch):
    from core.game_utils import FC_PORTRAIT_BOTTOM_BALANCE_REGION

    page = MagicMock()
    monkeypatch.setattr(
        "core.game_utils.sample_canvas_viewport_rect",
        lambda *_args, **_kwargs: None,
    )
    regions = footer_ocr_regions_to_try(
        page, {"id": "FC-SLOT-004", "layout": "portrait"}
    )
    assert len(regions) == 4
    assert regions[0]["y_start"] == FC_PORTRAIT_BALANCE_REGION["y_start"]
    assert regions[1]["y_start"] == FC_PORTRAIT_FOOTER_REGION["y_start"]
    assert regions[2]["y_start"] == FC_PORTRAIT_BOTTOM_BALANCE_REGION["y_start"]
    assert regions[3]["y_start"] == PORTRAIT_FOOTER_REGION["y_start"]


def test_game_version_detected_fc_and_combo():
    assert _game_version_detected("footer ver. d90811d balance")
    assert _game_version_detected("build v.1.3.2.u ready")
    assert not _game_version_detected("loading bundle 42%")


def test_resolve_game_layout_portrait_hint_when_detect_landscape(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        "core.game_utils.auto_detect_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    game = {
        "spin_button": {
            "region": {"x_start": 0.42, "x_end": 0.58, "y_start": 0.84, "y_end": 0.98},
        },
    }
    assert resolve_game_layout(game, page) == LAYOUT_PORTRAIT


def test_resolve_spin_button_config_uses_resolved_layout():
    game = {
        "_resolved_layout": LAYOUT_PORTRAIT,
        "spin_button": {
            "prompt": "landscape prompt",
            "region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0},
        },
    }
    spin = resolve_spin_button_config(game)
    assert spin["_layout"] == LAYOUT_PORTRAIT
    assert spin["region"] == PORTRAIT_DEFAULT_SPIN_REGION


def test_resolve_spin_button_config_portrait_explicit():
    game = {
        "layout": "portrait",
        "spin_button": {
            "prompt": "bottom center spin",
            "region": {"x_start": 0.30, "x_end": 0.70, "y_start": 0.70, "y_end": 0.98},
        },
    }
    spin = resolve_spin_button_config(game)
    assert spin["_layout"] == "portrait"
    assert spin["region"]["x_start"] == 0.30


def test_resolve_spin_button_config_portrait_from_landscape_defaults():
    game = {
        "layout": "portrait",
        "spin_button": {
            "prompt": "landscape prompt",
            "region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0},
        },
    }
    spin = resolve_spin_button_config(game)
    assert spin["region"] == PORTRAIT_DEFAULT_SPIN_REGION
    assert "bottom center" in spin["prompt"]


def test_resolve_spin_button_config_combo_portrait_region():
    from core.game_utils import COMBOBURST_PORTAL_CHROME_EXCLUSION, PORTRAIT_COMBO_SPIN_REGION

    game = {
        "_comboburst_portal": True,
        "_resolved_layout": LAYOUT_PORTRAIT,
        "spin_button": {
            "prompt": "landscape prompt",
            "region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0},
        },
    }
    spin = resolve_spin_button_config(game)
    assert spin["region"] == PORTRAIT_COMBO_SPIN_REGION
    assert spin["portal_chrome_exclusion"] == COMBOBURST_PORTAL_CHROME_EXCLUSION


def test_resolve_spin_button_config_refreshes_layout_from_footer(monkeypatch):
    page = MagicMock()
    page.viewport_size = {"width": 1920, "height": 911}
    hybrid = MagicMock()
    game = {
        "_resolved_layout": LAYOUT_LANDSCAPE,
        "spin_button": {
            "prompt": "landscape prompt",
            "region": {"x_start": 0.42, "x_end": 0.58, "y_start": 0.84, "y_end": 0.98},
        },
    }

    def fake_resolve(gc, *_args, **_kwargs):
        gc["_resolved_layout"] = LAYOUT_PORTRAIT
        return LAYOUT_PORTRAIT

    monkeypatch.setattr("core.game_utils.resolve_game_layout", fake_resolve)
    spin = resolve_spin_button_config(game, page, hybrid)
    assert spin["_layout"] == LAYOUT_PORTRAIT
    assert spin["region"]["x_start"] == 0.42


def test_game_config_landscape_hint_from_spin_region():
    assert _game_config_landscape_hint(
        {"spin_button": {"region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0}}}
    )
    assert not _game_config_landscape_hint(
        {"spin_button": {"region": {"x_start": 0.42, "x_end": 0.58, "y_start": 0.84, "y_end": 0.98}}}
    )


def test_resolve_game_layout_landscape_hint_overrides_footer_portrait(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(
        "core.game_utils.auto_detect_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    game = {
        "spin_button": {
            "region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0},
        },
    }
    assert resolve_game_layout(game, page, MagicMock(), refresh=True) == LAYOUT_LANDSCAPE
    assert game["_resolved_layout"] == LAYOUT_LANDSCAPE


def test_provisional_layout_landscape_hint_with_footer_portrait(monkeypatch):
    page = MagicMock()
    page.viewport_size = {"width": 1920, "height": 911}
    hybrid = MagicMock()
    monkeypatch.setattr(
        "core.game_utils.sample_canvas_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    monkeypatch.setattr(
        "core.game_utils.sample_canvas_viewport_rect",
        lambda *_args, **_kwargs: {"x_start": 0.02, "x_end": 0.98, "y_start": 0.0, "y_end": 1.0},
    )
    monkeypatch.setattr(
        "core.game_utils.probe_footer_layout",
        lambda *_args, **_kwargs: LAYOUT_PORTRAIT,
    )
    game = {
        "spin_button": {
            "region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0},
        },
    }
    assert _provisional_layout_for_load(game, page, hybrid) == LAYOUT_LANDSCAPE
    assert "_resolved_layout" not in game


def test_provisional_layout_footer_portrait_letterbox(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()
    monkeypatch.setattr(
        "core.game_utils.sample_canvas_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    monkeypatch.setattr(
        "core.game_utils.probe_footer_layout",
        lambda *_args, **_kwargs: LAYOUT_PORTRAIT,
    )
    game = {
        "spin_button": {
            "region": {"x_start": 0.42, "x_end": 0.58, "y_start": 0.84, "y_end": 0.98},
        },
    }
    assert _provisional_layout_for_load(game, page, hybrid) == LAYOUT_PORTRAIT
    assert "_resolved_layout" not in game


def test_build_spin_click_candidates_portrait_order():
    page = type("P", (), {"viewport_size": {"width": 1280, "height": 720}})()
    spin_config = {"_layout": "portrait"}
    candidates, _ = build_spin_click_candidates(
        640, 650, 580, 610, 700, 690, page, spin_config
    )
    assert [name for name, _, _ in candidates[:3]] == ["center", "up", "down"]


def test_spin_region_click_anchor_bottom_center():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    from core.game_utils import (
        COMBOBURST_PORTAL_CHROME_EXCLUSION,
        PORTRAIT_COMBO_SPIN_REGION,
        _clamp_click_outside_portal_chrome,
        _spin_region_click_anchor,
    )

    cx, cy = _spin_region_click_anchor(page, {"region": PORTRAIT_DEFAULT_SPIN_REGION})
    assert 900 <= cx <= 1020
    assert 700 <= cy <= 820

    combo_cx, combo_cy = _spin_region_click_anchor(
        page,
        {
            "region": PORTRAIT_COMBO_SPIN_REGION,
            "portal_chrome_exclusion": COMBOBURST_PORTAL_CHROME_EXCLUSION,
        },
    )
    assert combo_cx == pytest.approx(960.0, abs=2)
    assert combo_cy < COMBOBURST_PORTAL_CHROME_EXCLUSION["y_start"] * 911
    assert 680 <= combo_cy <= 780

    _, clamped_y = _clamp_click_outside_portal_chrome(
        960.0,
        842.0,
        page,
        {"portal_chrome_exclusion": COMBOBURST_PORTAL_CHROME_EXCLUSION},
    )
    assert clamped_y < 842.0
    assert clamped_y < COMBOBURST_PORTAL_CHROME_EXCLUSION["y_start"] * 911


def test_landscape_spin_region_anchor():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    from core.game_utils import _landscape_spin_region_anchor

    region = {"x_start": 0.58, "x_end": 0.88, "y_start": 0.55, "y_end": 0.95}
    cx, cy = _landscape_spin_region_anchor(page, {"region": region})
    assert 1400 <= cx <= 1700
    assert 700 <= cy <= 850


def test_vlm_snap_landscape_outside_canvas():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    from core.game_utils import _vlm_snap_click_anchor

    spin_config = {
        "_layout": "landscape",
        "_canvas_rect": {"x_start": 0.12, "x_end": 0.88, "y_start": 0.05, "y_end": 0.95},
        "region": {"x_start": 0.58, "x_end": 0.88, "y_start": 0.55, "y_end": 0.95},
    }
    cx, cy, snapped = _vlm_snap_click_anchor(
        page, spin_config, 1736.0, 727.0, loose=False
    )
    assert snapped
    assert cx < 1700


def test_portrait_loose_snap_uses_region_anchor():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    from core.game_utils import (
        COMBOBURST_PORTAL_CHROME_EXCLUSION,
        PORTRAIT_COMBO_SPIN_REGION,
        _portrait_loose_snap_click_anchor,
    )

    spin_config = {
        "_layout": "portrait",
        "region": PORTRAIT_COMBO_SPIN_REGION,
        "portal_chrome_exclusion": COMBOBURST_PORTAL_CHROME_EXCLUSION,
    }
    cx, cy, snapped = _portrait_loose_snap_click_anchor(
        page, spin_config, 1094.0, 842.0, loose=True
    )
    assert snapped
    assert cx == pytest.approx(960.0, abs=2)
    assert cy < 842.0
    assert cy < COMBOBURST_PORTAL_CHROME_EXCLUSION["y_start"] * 911


def test_portrait_game_ui_detected_footer_balance():
    page = type("P", (), {"viewport_size": {"width": 1280, "height": 720}})()
    ocr = [
        ([[0, 650], [200, 650], [200, 700], [0, 700]], "Balance P 3,335,677.80", 0.9),
    ]
    assert portrait_game_ui_detected(ocr, b"", page, all_text="balance p 3,335,677.80")


def test_portrait_load_fc_mid_strip_balance_without_yaml_layout(monkeypatch):
    """FC portrait load must see BALANCE above spin even when yaml has no layout."""
    from core.game_utils import portrait_load_ui_footer_regions

    page = MagicMock()
    page.viewport_size = {"width": 1280, "height": 720}
    monkeypatch.setattr(
        "core.game_utils.sample_canvas_viewport_rect",
        lambda *_a, **_k: None,
    )
    # Mid-strip y ~0.72 (above spin row) — outside generic PORTRAIT_FOOTER 0.82–1.0
    ocr = [
        (
            [[80, 520], [400, 520], [400, 560], [80, 560]],
            "BALANCE 10,007,426.55",
            0.9,
        ),
        (
            [[500, 520], [700, 520], [700, 560], [500, 560]],
            "TOTAL BETS 1.00",
            0.9,
        ),
    ]
    game = {"id": "FC-SLOT-032", "name": "Night Market 2"}
    regions = portrait_load_ui_footer_regions(page, game)
    assert any(r["y_start"] <= 0.60 for r in regions)
    assert portrait_game_ui_detected(
        ocr,
        b"",
        page,
        game_config=game,
        footer_regions=regions,
    )
    # Narrow bottom-only region would miss mid-strip (regression guard)
    assert not portrait_game_ui_detected(
        ocr,
        b"",
        page,
        game_config=game,
        footer_region=PORTRAIT_FOOTER_REGION,
    )


def test_portrait_game_ui_detected_rejects_empty():
    page = type("P", (), {"viewport_size": {"width": 1280, "height": 720}})()
    assert not portrait_game_ui_detected([], b"", page)


def test_portrait_game_ui_detected_rejects_lobby_balance_outside_footer():
    """JC lobby has balance in sidebar; must not count as in-game footer UI."""
    page = type("P", (), {"viewport_size": {"width": 1280, "height": 720}})()
    ocr = [
        ([[40, 120], [220, 120], [220, 180], [40, 180]], "Balance P 10,007,366.12", 0.9),
        ([[40, 620], [200, 620], [200, 680], [40, 680]], "Teen Patti", 0.9),
    ]
    assert not portrait_game_ui_detected(
        ocr,
        b"",
        page,
        all_text="jackpot combo balance p 10,007,366.12 arcade slot fish",
    )


def test_continue_promo_label_exact():
    assert _is_continue_promo_label("Continue")
    assert _is_continue_promo_label("CONTINUE")
    assert not _is_continue_promo_label("Autoplay")


def test_continue_promo_visible_ignores_autoplay_play():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    ocr = [
        (
            [[1100, 820], [1180, 820], [1180, 880], [1100, 880]],
            "Play",
            0.9,
        ),
    ]
    assert not _portrait_continue_promo_visible(ocr)
    assert not _is_continue_promo_label("Play")


def test_weak_intro_label_excludes_autoplay():
    assert _is_weak_intro_label("Start")
    assert not _is_weak_intro_label("Autoplay")


def test_portrait_intro_dismissable_play_only_in_intro_zone():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    # Autoplay Play at bottom-right — outside intro click region
    ocr_autoplay = [
        (
            [[1100, 820], [1180, 820], [1180, 880], [1100, 880]],
            "Play",
            0.9,
        ),
    ]
    assert not _portrait_intro_dismissable(ocr_autoplay, b"", page)

    # Start centered in intro zone
    ocr_start = [
        (
            [[860, 620], [1060, 620], [1060, 700], [860, 700]],
            "Start",
            0.9,
        ),
    ]
    assert _portrait_intro_dismissable(ocr_start, b"", page)


def test_wait_for_unity_game_load_dispatches_portrait(monkeypatch):
    called = {"portrait": False, "landscape": False, "refresh": 0}

    def fake_portrait(page, hybrid_locator, artifact_handler, game_config):
        called["portrait"] = True
        return True

    def fake_landscape(page, hybrid_locator, artifact_handler, game_config=None):
        called["landscape"] = True
        return True

    def fake_resolve(*_args, refresh=False, footer_first=False, **_kwargs):
        called["refresh"] += 1
        return LAYOUT_LANDSCAPE

    monkeypatch.setattr("core.game_utils._wait_for_portrait_unity_game_load", fake_portrait)
    monkeypatch.setattr("core.game_utils._wait_for_landscape_unity_game_load", fake_landscape)
    monkeypatch.setattr("core.game_utils.resolve_game_layout", fake_resolve)
    monkeypatch.setattr("core.game_utils.dismiss_portrait_intro_carousel", lambda *_a, **_k: 0)

    page = MagicMock()
    hybrid = MagicMock()
    artifacts = MagicMock()

    wait_for_unity_game_load(page, hybrid, artifacts, {"layout": "portrait"})
    assert called["portrait"] and not called["landscape"]
    assert called["refresh"] == 1

    called["portrait"] = False
    called["landscape"] = False
    called["refresh"] = 0
    monkeypatch.setattr(
        "core.game_utils._provisional_layout_for_load",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    wait_for_unity_game_load(page, hybrid, artifacts, {"id": "probe"})
    assert called["landscape"] and not called["portrait"]
    assert called["refresh"] == 1