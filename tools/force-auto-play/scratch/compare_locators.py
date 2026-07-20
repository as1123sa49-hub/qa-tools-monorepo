import asyncio
import sys
import yaml
from playwright.async_api import async_playwright

sys.path.insert(0, ".")
from core.async_game_utils import perform_login, dismiss_lobby_modals
from core.ui_locator import UILocator

async def test_env(env_name, p):
    with open("config/config.yaml") as f:
        cfg = yaml.safe_load(f)
    env = cfg["projects"]["client"]["environments"][env_name]
    ui_locator = UILocator()

    print(f"\n=================== Testing {env_name.upper()} ===================")
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={"width": 1280, "height": 720})

    try:
        await perform_login(page, ui_locator, env)
    except Exception as e:
        print(f"Login failed: {e}")
        
    try:
        await dismiss_lobby_modals(page, ui_locator)
    except:
        pass

    await page.get_by_placeholder("Search").first.click()
    await page.wait_for_timeout(1000)
    await page.keyboard.type("Prosperous Tiger")
    await page.wait_for_timeout(3000)

    # 1. 舊版 exact=False
    try:
        old_loc = page.get_by_text("Prosperous Tiger", exact=False).first
        await old_loc.wait_for(timeout=3000, state="visible")
        box = await old_loc.bounding_box()
        tag = await old_loc.evaluate("e => e.tagName")
        cls = await old_loc.evaluate("e => e.className")
        print(f"[舊版 get_by_text(exact=False)] 抓到了 <{tag} class='{cls[:30]}'>")
        print(f"    - Bounding box Y: {box['y']:.0f}, Height: {box['height']:.0f}")
    except Exception as e:
        print(f"[舊版 get_by_text(exact=False)] Failed: {e}")

    # 2. 新版 CSS line-clamp
    try:
        new_loc = page.locator('p[class*="line-clamp"]').filter(has_text="Prosperous Tiger").first
        await new_loc.wait_for(timeout=3000, state="visible")
        box = await new_loc.bounding_box()
        tag = await new_loc.evaluate("e => e.tagName")
        cls = await new_loc.evaluate("e => e.className")
        print(f"[新版 CSS p[class*=\"line-clamp\"]] 抓到了 <{tag} class='{cls[:30]}'>")
        print(f"    - Bounding box Y: {box['y']:.0f}, Height: {box['height']:.0f}")
    except Exception as e:
        print(f"[新版 CSS selector] Failed: {e}")

    await browser.close()

async def main():
    async with async_playwright() as p:
        await test_env("uat", p)
        await test_env("pp", p)

asyncio.run(main())
