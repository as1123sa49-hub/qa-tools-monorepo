"""Unit tests for canvas-relative spin region mapping."""

import pytest

from core.canvas_region import (
    apply_canvas_relative_region,
    canvas_fills_viewport_width,
    map_region_to_viewport,
    point_inside_canvas_rect,
)
from core.layout_detect import (
    LAYOUT_LANDSCAPE,
    LAYOUT_PORTRAIT,
    fuse_layout_signals,
)


def test_map_region_to_viewport_pillarbox_landscape():
    """Gummy-style: yaml bottom-right mapped inside centered canvas."""
    canvas = {"x_start": 0.12, "x_end": 0.88, "y_start": 0.05, "y_end": 0.95}
    yaml_region = {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0}
    mapped = map_region_to_viewport(yaml_region, canvas)
    assert mapped["x_start"] == pytest.approx(0.576, abs=0.01)
    assert mapped["x_end"] == pytest.approx(0.88, abs=0.01)
    assert mapped["x_end"] < 0.90


def test_map_region_to_viewport_full_canvas_is_identity():
    canvas = {"x_start": 0.0, "x_end": 1.0, "y_start": 0.0, "y_end": 1.0}
    region = {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0}
    assert apply_canvas_relative_region(region, canvas) == region


def test_apply_skips_mapping_when_canvas_fills_viewport():
    canvas = {"x_start": 0.02, "x_end": 0.98, "y_start": 0.0, "y_end": 1.0}
    region = {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0}
    assert apply_canvas_relative_region(region, canvas) == region


def test_canvas_fills_viewport_width():
    assert canvas_fills_viewport_width({"x_start": 0.05, "x_end": 0.95})
    assert not canvas_fills_viewport_width({"x_start": 0.12, "x_end": 0.88})


def test_point_inside_canvas_rect():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    canvas = {"x_start": 0.12, "x_end": 0.88, "y_start": 0.05, "y_end": 0.95}
    assert not point_inside_canvas_rect(1736, 727, canvas, page)
    assert point_inside_canvas_rect(1500, 727, canvas, page)


def test_fuse_pillarbox_footer_portrait_not_overridden_by_yaml_landscape():
    canvas = {"x_start": 0.20, "x_end": 0.80, "y_start": 0.0, "y_end": 1.0}
    assert (
        fuse_layout_signals(
            LAYOUT_LANDSCAPE,
            LAYOUT_PORTRAIT,
            landscape_hint=True,
            canvas_rect=canvas,
        )
        == LAYOUT_PORTRAIT
    )


def test_fuse_full_width_yaml_landscape_hint_still_wins():
    canvas = {"x_start": 0.02, "x_end": 0.98, "y_start": 0.0, "y_end": 1.0}
    assert (
        fuse_layout_signals(
            LAYOUT_LANDSCAPE,
            LAYOUT_PORTRAIT,
            landscape_hint=True,
            canvas_rect=canvas,
        )
        == LAYOUT_LANDSCAPE
    )
