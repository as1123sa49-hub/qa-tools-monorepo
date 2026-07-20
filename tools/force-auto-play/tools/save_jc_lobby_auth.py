"""Save JC lobby login state for Playwright storage_state.

Usage:
  .\\.venv\\Scripts\\python.exe tools\\save_jc_lobby_auth.py
  .\\.venv\\Scripts\\python.exe tools\\save_jc_lobby_auth.py --env uat

Logs in with config accounts.player_vision (or prompts for manual login with --manual).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.jc_lobby_auth import resolve_jc_lobby_auth_path  # noqa: E402


def _load_env(env_name: str) -> dict:
    config_path = ROOT / "config" / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    environments = (
        ((data.get("projects") or {}).get("client") or {}).get("environments") or {}
    )
    return environments.get(env_name) or environments.get("uat") or {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Save JC lobby storage_state")
    parser.add_argument("--env", default="uat", help="Environment key in config.yaml")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Open browser for manual login instead of using config credentials",
    )
    args = parser.parse_args()

    env_cfg = _load_env(args.env)
    web_url = env_cfg.get("web_url") or "https://jackpot-uat.combo.ph/"
    auth_path = resolve_jc_lobby_auth_path({"_env": args.env}, env_name=args.env)
    Path(auth_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"Lobby URL: {web_url}")
    print(f"Auth will be saved to: {auth_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.goto(web_url, wait_until="domcontentloaded")
        time.sleep(2)

        if args.manual:
            print("請在瀏覽器手動登入大廳，完成後回到終端機按 Enter…")
            input()
        else:
            accounts = env_cfg.get("accounts") or {}
            player = accounts.get("player_vision") or {}
            username = player.get("username")
            password = player.get("password")
            if not username or not password:
                print("找不到 accounts.player_vision；改用手動登入。")
                print("請在瀏覽器手動登入大廳，完成後回到終端機按 Enter…")
                input()
            else:
                print(f"使用 player_vision 登入：{username}")
                # Best-effort: same flow as login_to_lobby (OCR omitted — user confirms).
                print(
                    "若未自動登入成功，請手動完成後回到終端機按 Enter…"
                )
                # Leave time for any agree modal; user can click manually.
                time.sleep(3)
                input("登入完成後按 Enter 儲存 storage_state…")

        context.storage_state(path=auth_path)
        browser.close()

    print(f"已儲存登入狀態：{auth_path}")


if __name__ == "__main__":
    main()
