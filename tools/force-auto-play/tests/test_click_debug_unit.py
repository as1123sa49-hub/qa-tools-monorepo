"""Unit tests for click_debug annotation helpers."""

from PIL import Image

from core.click_debug import annotate_click, bbox_0_1000_to_pixels
from core.game_utils import _detect_spin_bbox, build_spin_click_candidates

SPIN_CONFIG = {
    "prompt": "spin",
    "region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0},
}
LOOSE_BBOX = [120, 130, 1000, 870]
TIGHT_BBOX = [700, 750, 850, 900]


class _FakeVision:
    def __init__(self, primary):
        self.primary = primary
        self.grid_search_called = False

    def detect_in_grid_region(self, *_args, **_kwargs):
        return self.primary

    def detect_with_grid_search(self, *_args, **_kwargs):
        self.grid_search_called = True
        return []


def test_detect_spin_bbox_returns_grid_region_result():
    vision = _FakeVision(primary=TIGHT_BBOX)
    assert _detect_spin_bbox(vision, b"", SPIN_CONFIG) == TIGHT_BBOX
    assert vision.grid_search_called is False


def test_detect_spin_bbox_accepts_loose_bbox_without_grid_search():
    vision = _FakeVision(primary=LOOSE_BBOX)
    assert _detect_spin_bbox(vision, b"", SPIN_CONFIG) == LOOSE_BBOX
    assert vision.grid_search_called is False


def test_detect_spin_bbox_empty_when_vlm_misses():
    vision = _FakeVision(primary=[])
    assert _detect_spin_bbox(vision, b"", SPIN_CONFIG) == []


class _FakeViewport:
    def __init__(self, width: int, height: int):
        self.viewport_size = {"width": width, "height": height}


def test_bbox_0_1000_to_pixels():
    img = Image.new("RGB", (1000, 500))
    assert bbox_0_1000_to_pixels([100, 50, 300, 250], img) == (100, 25, 300, 125)


def test_annotate_click_returns_rgb_image():
    img = Image.new("RGB", (200, 100), color=(30, 30, 30))
    out = annotate_click(img, 150, 80, bbox_0_1000=[800, 600, 950, 900], label="test")
    assert out.mode == "RGB"
    assert out.size == (200, 100)
    # marker pixel should differ from flat background
    assert out.getpixel((150, 80)) != (30, 30, 30)


def test_build_spin_click_candidates_center_and_directions():
    page = _FakeViewport(1920, 911)
    cx, cy, x1, y1, x2, y2 = 1000.0, 800.0, 900.0, 720.0, 1100.0, 840.0
    candidates, delta = build_spin_click_candidates(cx, cy, x1, y1, x2, y2, page)
    names = [n for n, _, _ in candidates]
    assert names == ["center", "right", "left", "down", "up"]
    assert candidates[0] == ("center", cx, cy)
    assert candidates[1][1] > cx
    assert candidates[2][1] < cx
    assert candidates[3][2] > cy
    assert candidates[4][2] < cy
    assert 28 <= delta <= 48


def test_build_spin_click_candidates_loose_bbox_uses_widened_offsets():
    page = _FakeViewport(1920, 911)
    cx, cy = 1200.0, 750.0
    x1, y1, x2, y2 = 400.0, 580.0, 1900.0, 800.0
    spin_config = {"region": {"x_start": 0.6, "x_end": 1.0, "y_start": 0.6, "y_end": 1.0}}
    spin_coords = [120, 130, 1000, 870]
    candidates, delta = build_spin_click_candidates(
        cx, cy, x1, y1, x2, y2, page, spin_config, spin_coords
    )
    names = [n for n, _, _ in candidates]
    assert names == [
        "center",
        "left",
        "right",
        "left2",
        "right2",
        "left3",
        "right3",
        "down",
        "down2",
        "up",
    ]
    assert 40 <= delta <= 72
    by_name = {n: (x, y) for n, x, y in candidates}
    assert by_name["left"][0] < cx < by_name["right"][0]
    assert by_name["left2"][0] < by_name["left"][0]
    assert by_name["right2"][0] > by_name["right"][0]
    assert by_name["down2"][1] > by_name["down"][1] > cy
