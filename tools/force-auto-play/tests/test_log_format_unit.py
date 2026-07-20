from core.log_format import (
    CategoryFormatter,
    ColoredCategoryFormatter,
    _resolve_category,
    log_retry,
)


def test_resolve_category_layout():
    assert _resolve_category("core.layout_detect", "📐 Footer OCR layout: portrait") == "LAYOUT"


def test_resolve_category_spin():
    assert _resolve_category("core.game_utils", "🎯 Spin click candidate 'center'") == "SPIN"


def test_resolve_category_phase():
    assert _resolve_category("test.phase", "========== Enter game ==========") == "PHASE"


def test_resolve_category_other():
    assert _resolve_category("random", "hello") == "OTHER"


def test_category_formatter_sets_field():
    import logging

    formatter = CategoryFormatter("%(category)s %(message)s")
    record = logging.LogRecord("core.game_utils", logging.INFO, "", 0, "Grid crop saved", (), None)
    assert formatter.format(record) == "SPIN Grid crop saved"


def test_plain_formatter_no_escape():
    import logging

    formatter = CategoryFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
    assert "\033[" not in formatter.format(record)


def test_colored_formatter_adds_escape_when_enabled(monkeypatch):
    import logging

    monkeypatch.setattr("core.log_format.use_log_color", lambda: True)
    formatter = ColoredCategoryFormatter("%(category)s %(message)s")
    record = logging.LogRecord("core.game_utils", logging.INFO, "", 0, "Spin click candidate 'center'", (), None)
    out = formatter.format(record)
    assert "\033[" in out
    assert "SPIN" in out


def test_log_retry_first_and_last_only():
    import logging
    from unittest.mock import MagicMock

    logger = MagicMock()
    log_retry(logger, 1, 5, "retry msg")
    log_retry(logger, 3, 5, "retry msg")
    log_retry(logger, 5, 5, "retry msg")

    assert logger.log.call_count == 2
    assert logger.debug.call_count == 1
