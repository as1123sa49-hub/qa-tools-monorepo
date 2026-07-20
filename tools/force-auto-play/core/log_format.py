"""Pytest live-log category formatter with optional ANSI colors."""

from __future__ import annotations

import logging
import os
import re
import sys

CATEGORY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"📐|layout_detect|Footer OCR|Resolved layout|Layout from|Layout updated", re.I), "LAYOUT"),
    (re.compile(r"🎯|🔍|Spin click|VLM|spin_button|Grid crop|Vision Response", re.I), "SPIN"),
    (re.compile(r"comboburst|Entered|lobby|navigat|game card|Unity canvas", re.I), "ENTRY"),
    (re.compile(r"Game Loaded|v_game_loaded|intro|portrait intro|Waiting for game load", re.I), "LOAD"),
    (re.compile(r"balance|settlement|console|spin_ack|Initial balance|Auditing Balance", re.I), "SETTLE"),
    (re.compile(r"Artifact|Screenshot|Video archived|📦|📁|🎥", re.I), "ARTIFACT"),
    (re.compile(r"Teardown|Returning to", re.I), "TEARDOWN"),
    (re.compile(r"conftest|Fixture|auth loaded|Login|EasyOCR|Registered Game", re.I), "SETUP"),
    (re.compile(r"^=+$|==========", re.I), "PHASE"),
]

CATEGORY_LOG_FORMAT = "%(asctime)s [%(levelname)-5s] [%(category)-8s] %(message)s"
CATEGORY_LOG_DATEFMT = "%H:%M:%S"

# ANSI styles (category tag colors)
_RESET = "\033[0m"
_BOLD = "\033[1m"
_CATEGORY_COLORS: dict[str, str] = {
    "PHASE": "\033[1m\033[96m",   # bold cyan
    "ENTRY": "\033[36m",          # cyan
    "LOAD": "\033[34m",           # blue
    "SPIN": "\033[35m",           # magenta
    "SETTLE": "\033[32m",         # green
    "LAYOUT": "\033[90m",         # gray
    "ARTIFACT": "\033[90m",
    "SETUP": "\033[90m",
    "TEARDOWN": "\033[90m",
    "OTHER": "\033[0m",
}
_LEVEL_COLORS: dict[int, str] = {
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}


def use_log_color() -> bool:
    """Color terminal output when interactive; respect NO_COLOR / CI defaults."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("FAP_LOG_COLOR") == "1":
        return True
    if os.environ.get("CI") and os.environ.get("FAP_LOG_COLOR") != "1":
        return False
    stream = sys.stderr
    return hasattr(stream, "isatty") and stream.isatty()


def _resolve_category(logger_name: str, message: str) -> str:
    for pattern, category in CATEGORY_RULES:
        if pattern.search(message) or pattern.search(logger_name):
            return category
    return "OTHER"


class CategoryFormatter(logging.Formatter):
    """Map logger name + message to a short category tag."""

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "category", None):
            record.category = _resolve_category(record.name, record.getMessage())
        return super().format(record)


class ColoredCategoryFormatter(CategoryFormatter):
    """CategoryFormatter with ANSI colors for terminal (category + level)."""

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "category", None):
            record.category = _resolve_category(record.name, record.getMessage())

        category = record.category
        level = record.levelno
        cat_color = _CATEGORY_COLORS.get(category, _CATEGORY_COLORS["OTHER"])
        level_color = _LEVEL_COLORS.get(level, "")

        if level_color:
            record.levelname = f"{level_color}{record.levelname}{_RESET}"
        record.category = f"{cat_color}{category:8s}{_RESET}"

        msg = record.getMessage()
        if category == "PHASE" or (category in ("ENTRY", "LOAD", "SPIN", "SETTLE") and msg.startswith("=")):
            record.msg = f"{_BOLD}{msg}{_RESET}"
            record.args = ()

        formatted = super().format(record)
        record.levelname = logging.getLevelName(level)
        record.category = category
        return formatted


def log_retry(
    logger: logging.Logger,
    attempt: int,
    max_attempts: int,
    msg: str,
    *,
    level: int = logging.WARNING,
    final_level: int | None = None,
) -> None:
    """Log retry: first and last at INFO/WARNING; middle attempts at DEBUG."""
    if attempt == 1:
        logger.log(level, msg)
    elif attempt >= max_attempts:
        logger.log(final_level or level, msg)
    else:
        logger.debug(msg)


def install_category_logging() -> None:
    """Apply formatters: colored for streams, plain for log files."""
    root = logging.getLogger()
    plain = CategoryFormatter(CATEGORY_LOG_FORMAT, datefmt=CATEGORY_LOG_DATEFMT)
    colored = ColoredCategoryFormatter(CATEGORY_LOG_FORMAT, datefmt=CATEGORY_LOG_DATEFMT)

    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.setFormatter(plain)
        elif use_log_color():
            handler.setFormatter(colored)
        else:
            handler.setFormatter(plain)

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(colored if use_log_color() else plain)
        root.addHandler(handler)
        root.setLevel(logging.INFO)


def log_phase(phase: str, title: str) -> None:
    """Emit a visible section divider in live logs."""
    logging.getLogger("test.phase").info(
        f"========== {title} ==========",
        extra={"category": phase},
    )
