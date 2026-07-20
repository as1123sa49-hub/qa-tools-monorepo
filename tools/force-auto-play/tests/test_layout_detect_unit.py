from unittest.mock import MagicMock

from core.game_frame_utils import iter_game_contexts
from core.layout_detect import (
    LAYOUT_LANDSCAPE,
    LAYOUT_PORTRAIT,
    auto_detect_layout,
    fuse_layout_signals,
    layout_from_canvas_metrics,
    layout_from_footer_ocr,
    sample_canvas_layout,
)


def test_layout_from_canvas_metrics_portrait_intrinsic():
    metrics = {"display_ratio": 0.47, "intrinsic_ratio": 1.78, "area": 1000}
    assert layout_from_canvas_metrics(metrics) == LAYOUT_PORTRAIT


def test_layout_from_canvas_metrics_landscape():
    metrics = {"display_ratio": 0.56, "intrinsic_ratio": 0.56, "area": 1000}
    assert layout_from_canvas_metrics(metrics) == LAYOUT_LANDSCAPE


def test_sample_canvas_layout_uses_frame_metrics(monkeypatch):
    page = MagicMock()
    frame = MagicMock()
    frame.url = "https://games-uat.comboburst.com/game"
    page.frames = [frame]

    def fake_metrics(ctx):
        if ctx is frame:
            return {"display_ratio": 0.47, "intrinsic_ratio": 1.78, "area": 5000}
        return None

    monkeypatch.setattr("core.layout_detect.canvas_layout_metrics", fake_metrics)
    assert sample_canvas_layout(page, "games-uat.comboburst.com") == LAYOUT_PORTRAIT


def test_layout_from_footer_ocr_portrait_letterbox():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    ocr = [
        (
            [[900, 850], [1020, 850], [1020, 890], [900, 890]],
            "Balance P 3,335,556.60",
            0.9,
        ),
        (
            [[940, 820], [980, 820], [980, 840], [940, 840]],
            "P 3.00",
            0.9,
        ),
    ]
    assert layout_from_footer_ocr(ocr, b"", page) == LAYOUT_PORTRAIT


def test_layout_from_footer_ocr_portrait_currency_only():
    """Golden Bass style: amounts without 'balance' label in the same OCR box."""
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    ocr = [
        (
            [[850, 820], [1070, 820], [1070, 860], [850, 860]],
            "P 3,335,554.65",
            0.9,
        ),
        (
            [[920, 790], [1000, 790], [1000, 815], [920, 815]],
            "P 3.00",
            0.9,
        ),
    ]
    assert layout_from_footer_ocr(ocr, b"", page) == LAYOUT_PORTRAIT


def test_layout_from_footer_ocr_landscape_full_width():
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    ocr = [
        (
            [[120, 850], [280, 850], [280, 890], [120, 890]],
            "Balance P 3,335,556.60",
            0.9,
        ),
        (
            [[1500, 850], [1850, 850], [1850, 900], [1500, 900]],
            "Bet P 3.00",
            0.9,
        ),
    ]
    assert layout_from_footer_ocr(ocr, b"", page) == LAYOUT_LANDSCAPE


def test_layout_from_footer_ocr_compact_landscape_inconclusive():
    """Magic Runes style: compact footer bar (span ~0.42) must not auto-classify portrait."""
    page = type("P", (), {"viewport_size": {"width": 1920, "height": 911}})()
    ocr = [
        (
            [[400, 850], [700, 850], [700, 890], [400, 890]],
            "Balance P 3,335,529.45",
            0.9,
        ),
        (
            [[900, 850], [1100, 850], [1100, 890], [900, 890]],
            "P 3.00",
            0.9,
        ),
        (
            [[1250, 850], [1550, 850], [1550, 890], [1250, 890]],
            "Win P 0.00",
            0.9,
        ),
    ]
    assert layout_from_footer_ocr(ocr, b"", page) is None


def test_fuse_layout_signals_letterbox_portrait():
    assert (
        fuse_layout_signals(LAYOUT_LANDSCAPE, LAYOUT_PORTRAIT) == LAYOUT_PORTRAIT
    )


def test_fuse_layout_signals_magic_runes_landscape_hint():
    assert (
        fuse_layout_signals(
            LAYOUT_LANDSCAPE,
            LAYOUT_PORTRAIT,
            landscape_hint=True,
        )
        == LAYOUT_LANDSCAPE
    )


def test_fuse_layout_signals_compact_footer_landscape_hint():
    assert (
        fuse_layout_signals(
            LAYOUT_LANDSCAPE,
            None,
            landscape_hint=True,
        )
        == LAYOUT_LANDSCAPE
    )


def test_auto_detect_layout_footer_overrides_canvas_landscape(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()
    hybrid.ocr.reader.readtext.return_value = [
        (
            [[900, 850], [1020, 850], [1020, 890], [900, 890]],
            "Balance P 3,335,556.60",
            0.9,
        ),
    ]
    monkeypatch.setattr(
        "core.layout_detect.detect_game_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    monkeypatch.setattr("core.layout_detect.time.sleep", lambda *_: None)
    page.screenshot.return_value = b""
    page.viewport_size = {"width": 1920, "height": 911}
    assert auto_detect_layout(page, hybrid) == LAYOUT_PORTRAIT


def test_auto_detect_layout_footer_first_fuses_with_canvas(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()
    hybrid.ocr.reader.readtext.return_value = [
        (
            [[900, 850], [1020, 850], [1020, 890], [900, 890]],
            "Balance P 3,335,556.60",
            0.9,
        ),
    ]
    page.screenshot.return_value = b""
    page.viewport_size = {"width": 1920, "height": 911}

    monkeypatch.setattr(
        "core.layout_detect.sample_canvas_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    monkeypatch.setattr("core.layout_detect.time.sleep", lambda *_: None)
    assert auto_detect_layout(page, hybrid, footer_first=True) == LAYOUT_PORTRAIT


def test_auto_detect_layout_footer_first_landscape_hint(monkeypatch):
    page = MagicMock()
    hybrid = MagicMock()
    hybrid.ocr.reader.readtext.return_value = [
        (
            [[900, 850], [1020, 850], [1020, 890], [900, 890]],
            "Balance P 3,335,556.60",
            0.9,
        ),
    ]
    page.screenshot.return_value = b""
    page.viewport_size = {"width": 1920, "height": 911}

    monkeypatch.setattr(
        "core.layout_detect.sample_canvas_layout",
        lambda *_args, **_kwargs: LAYOUT_LANDSCAPE,
    )
    monkeypatch.setattr("core.layout_detect.time.sleep", lambda *_: None)
    assert (
        auto_detect_layout(
            page,
            hybrid,
            footer_first=True,
            landscape_hint=True,
        )
        == LAYOUT_LANDSCAPE
    )


def test_iter_game_contexts_prioritizes_expected_host():
    page = MagicMock()
    game_frame = MagicMock()
    game_frame.url = "https://games-uat.comboburst.com/game"
    other_frame = MagicMock()
    other_frame.url = "https://other.example.com/"
    page.frames = [other_frame, game_frame]
    contexts = list(iter_game_contexts(page, "games-uat.comboburst.com"))
    assert contexts[0] is game_frame
    assert page in contexts
