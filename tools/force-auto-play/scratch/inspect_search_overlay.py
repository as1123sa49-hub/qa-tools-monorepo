"""
登入後搜尋 Prosperous Tiger，用 JS 一次抓搜尋 overlay 內所有文字元素的 tag/class/y/text
"""
import asyncio
import sys
import yaml
from playwright.async_api import async_playwright

sys.path.insert(0, ".")
from core.async_game_utils import perform_login, dismiss_lobby_modals
from core.ui_locator import UILocator


async def main():
    with open("config/config.yaml") as f:
        cfg = yaml.safe_load(f)
    env = cfg["projects"]["client"]["environments"]["pp"]

    ui_locator = UILocator()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        await perform_login(page, ui_locator, env)
        await dismiss_lobby_modals(page, ui_locator)

        # 點搜尋 bar
        await page.get_by_placeholder("Search").first.click()
        await page.wait_for_timeout(1000)
        await page.keyboard.type("Prosperous Tiger")
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)

        await page.screenshot(path="/tmp/search_overlay.png")
        print("Screenshot: /tmp/search_overlay.png")

        # 用 JS 一次抓 y < 400 的所有 leaf text nodes 的父元素
        results = await page.evaluate("""() => {
            const out = [];
            const seen = new Set();
            document.querySelectorAll('*').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.y > 400 || rect.height < 8 || rect.width < 10) return;
                const txt = el.innerText ? el.innerText.trim() : '';
                if (!txt || txt.length > 80 || seen.has(txt)) return;
                // 只要 leaf-ish (直接子文字較多)
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('').trim();
                if (!directText) return;
                seen.add(txt);
                out.push({
                    tag: el.tagName,
                    cls: el.className.toString().slice(0, 60),
                    y: Math.round(rect.y),
                    h: Math.round(rect.height),
                    text: txt.slice(0, 80)
                });
            });
            return out.sort((a, b) => a.y - b.y);
        }""")

        print(f"\n=== {len(results)} elements ===")
        for r in results:
            print(f"  y={r['y']:4d} h={r['h']:3d}  <{r['tag']}>  cls='{r['cls']}'  '{r['text']}'")

        await browser.close()


asyncio.run(main())
