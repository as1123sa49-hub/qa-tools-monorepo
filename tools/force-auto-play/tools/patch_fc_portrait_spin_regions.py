"""Patch FC slot spin regions in games.yaml without reformatting the whole file."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAMES_PATH = ROOT / "config" / "games.yaml"

OLD_REGION = """      region:
        x_start: 0.6
        x_end: 1.0
        y_start: 0.6
        y_end: 1.0"""

NEW_REGION = """      region:
        x_start: 0.38
        x_end: 0.62
        y_start: 0.78
        y_end: 0.88"""

PORTRAIT_PROMPT = (
    "the largest circular main spin button at the exact bottom center, "
    "bigger than auto-play and turbo icons on its sides, "
    "round circle with spiral arrow, not auto-spin or turbo"
)


def main() -> None:
    text = GAMES_PATH.read_text(encoding="utf-8")
    fc_block, _, tail = text.partition("JDB:")
    if not fc_block.startswith("FC:"):
        raise SystemExit("FC section not found")
    updated = fc_block.count(OLD_REGION)
    fc_block = fc_block.replace(OLD_REGION, NEW_REGION)
    fc_block = fc_block.replace(
        "      prompt: the large circular spin button with spiral arrow\n"
        "      idle_prompt: the large circular yellow/purple spin button",
        f"      prompt: {PORTRAIT_PROMPT}\n"
        f"      idle_prompt: {PORTRAIT_PROMPT}",
    )
    GAMES_PATH.write_text(fc_block + "JDB:" + tail, encoding="utf-8")
    print(f"Patched {updated} FC spin region block(s).")


if __name__ == "__main__":
    main()
