"""Save comboburst lobby login state for Playwright storage_state.

Usage:
  .\\.venv\\Scripts\\python.exe tools\\save_comboburst_auth.py

Manual login in the opened browser, then press Enter in the terminal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.comboburst_auth import resolve_comboburst_auth_path  # noqa: E402


def _load_comboburst_cfg() -> dict:
    config_path = ROOT / "config" / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data["projects"]["client"]["environments"]["uat"].get("comboburst") or {}


def main() -> None:
    cfg = _load_comboburst_cfg()
    lobby_url = cfg.get("lobby_url", "https://games-dev.comboburst.com/home/index.html")
    viewport = cfg.get("viewport") or {"width": 1920, "height": 911}
    auth_path = resolve_comboburst_auth_path(cfg)

    Path(auth_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"Lobby URL: {lobby_url}")
    print(f"Auth will be saved to: {auth_path}")
    print("請在瀏覽器手動登入大廳，完成後回到終端機按 Enter…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport=viewport)
        page = context.new_page()
        page.goto(lobby_url, wait_until="domcontentloaded")
        input()
        context.storage_state(path=auth_path)
        browser.close()

    print(f"已儲存登入狀態：{auth_path}")


if __name__ == "__main__":
    main()
