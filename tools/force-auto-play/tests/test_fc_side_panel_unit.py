"""Unit tests for FC side-panel collapse helpers."""

from core.game_utils import (
    _FC_SIDE_PANEL_COLLAPSE_X_FRAC,
    _FC_SIDE_PANEL_COLLAPSE_Y_FRAC,
    fc_side_panel_open,
)


class _FakePage:
    viewport_size = {"width": 400, "height": 800}


def test_collapse_tab_fracs_are_left_mid():
    """Purple collapse tab sits on left drawer edge, mid-lower height."""
    assert 0.05 <= _FC_SIDE_PANEL_COLLAPSE_X_FRAC <= 0.15
    assert 0.55 <= _FC_SIDE_PANEL_COLLAPSE_Y_FRAC <= 0.80


def test_fc_side_panel_open_requires_two_left_labels(monkeypatch):
    page = _FakePage()
    # Two MISSION-band labels in left region → open.
    ocr = [
        ([[10, 100], [80, 100], [80, 120], [10, 120]], "MISSION", 0.9),
        ([[10, 200], [80, 200], [80, 220], [10, 220]], "PROPS", 0.9),
        ([[200, 700], [300, 700], [300, 720], [200, 720]], "BALANCE", 0.9),
    ]

    def _fake_region(ocr_results, screenshot_bytes, page, region):
        out = []
        for bbox, text, prob in ocr_results:
            cx = (bbox[0][0] + bbox[2][0]) / 2
            if cx < 120:
                out.append((bbox, text, prob))
        return out

    monkeypatch.setattr(
        "core.game_utils._ocr_results_in_fraction_region", _fake_region
    )
    assert (
        fc_side_panel_open(
            page,
            hybrid_locator=object(),
            screenshot_bytes=b"x",
            ocr_results=ocr,
        )
        is True
    )

    ocr_one = [ocr[0], ocr[2]]
    assert (
        fc_side_panel_open(
            page,
            hybrid_locator=object(),
            screenshot_bytes=b"x",
            ocr_results=ocr_one,
        )
        is False
    )
