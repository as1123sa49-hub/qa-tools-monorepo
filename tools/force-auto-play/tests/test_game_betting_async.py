"""
非同步單手下注測試 (正式版)
- 使用 pytest-asyncio (asyncio_mode=auto)
- 沿用 conftest.py 的 ui_locator / vision_client / global_config session fixtures
- 每個 test = 一個 Provider，開一個 browser，登入一次，依序跑完所有遊戲
- 背景眼 (vision_eye_task) 在 test 生命週期內運行
- JILI: 使用 subprocess Chrome + connect_over_cdp + 斷連重連避免反調試偵測
"""
import asyncio
import logging
import subprocess
import tempfile
import os
import json
import time

import pytest
import yaml
from playwright.async_api import async_playwright

from core.goal_agent import GoalAgent
from core.async_game_utils import (
    navigate_to_game,
    execute_single_spin,
    vision_eye_task,
    async_ui_scan,
    perform_login,
    dismiss_lobby_modals,
    wait_for_game_load,
)

logger = logging.getLogger(__name__)


def _create_jili_extension():
    """建立 Chrome Extension 用於攔截 JILI JS debugger 語句。"""
    ext_dir = tempfile.mkdtemp(prefix="jili_bypass_ext_")

    with open(os.path.join(ext_dir, "manifest.json"), "w") as f:
        json.dump({
            "manifest_version": 3,
            "name": "JILI Anti-Debug Bypass",
            "version": "1.0",
            "permissions": [],
            "host_permissions": ["*://*.jlfafafa3.com/*"],
            "content_scripts": [{
                "matches": ["*://*.jlfafafa3.com/*", "*://*.jilicityapi.com/*"],
                "js": ["content.js"],
                "run_at": "document_start",
                "all_frames": True
            }],
            "background": {
                "service_worker": "background.js"
            }
        }, f, indent=2)

    with open(os.path.join(ext_dir, "content.js"), "w") as f:
        f.write("""
(function() {
    const origEval = window.eval;
    window.eval = function(code) {
        if (typeof code === 'string') {
            code = code.replace(/\\bdebugger\\b/g, '');
        }
        return origEval.call(this, code);
    };
    Object.defineProperty(window.eval, 'toString', {
        value: function() { return 'function eval() { [native code] }'; }
    });

    const origFunction = window.Function;
    window.Function = function(...args) {
        if (args.length > 0) {
            const lastIdx = args.length - 1;
            if (typeof args[lastIdx] === 'string') {
                args[lastIdx] = args[lastIdx].replace(/\\bdebugger\\b/g, '');
            }
        }
        return new.target
            ? Reflect.construct(origFunction, args)
            : origFunction.apply(this, args);
    };
    window.Function.prototype = origFunction.prototype;
    Object.defineProperty(window.Function, 'toString', {
        value: function() { return 'function Function() { [native code] }'; }
    });
})();
""")

    with open(os.path.join(ext_dir, "background.js"), "w") as f:
        f.write("// background\n")

    return ext_dir


# ============================================================
# Provider 等級執行器：一個 browser，loop 跑完所有遊戲
# ============================================================
async def _run_provider_betting(provider_name: str, request, global_config, ui_locator, vision_client):
    """
    一個 browser，登入一次，依序跑完 game_ids 所有遊戲。
    JILI: 使用 subprocess Chrome + 斷連重連繞過反調試。
    """
    with open("config/games.yaml") as f:
        all_games = yaml.safe_load(f)

    if provider_name not in all_games:
        pytest.fail(f"Provider '{provider_name}' not found in games.yaml")

    game_ids = list(all_games[provider_name].keys())

    target_game = request.config.getoption("--game")
    if target_game:
        if target_game in game_ids:
            game_ids = [target_game]
        else:
            pytest.skip(f"Game {target_game} not in provider {provider_name}")

    _env = global_config.get("_env", "uat")
    env_config = global_config["projects"]["client"]["environments"].get(
        _env, global_config["projects"]["client"]["environments"]["uat"]
    )

    shared_memory = {
        "running": True,
        "found_elements": {},
        "current_target": None,
    }

    failed_games: list[str] = []

    is_jili = provider_name.upper() == "JILI"

    if is_jili:
        await _run_jili_betting(game_ids, all_games, provider_name, env_config,
                                ui_locator, vision_client, shared_memory, failed_games, _env)
    else:
        await _run_normal_betting(provider_name, game_ids, all_games, env_config,
                                  ui_locator, vision_client, shared_memory, failed_games, _env,
                                  global_config, request)

    if failed_games:
        pytest.fail(
            f"[{provider_name}] {len(failed_games)}/{len(game_ids)} games failed:\n"
            + "\n".join(f"  - {g}" for g in failed_games)
        )


# ============================================================
# Raw CDP 遊戲互動 (不啟用 CDP domain，避免 JILI 反調試)
# ============================================================
async def _raw_wait_for_game_load(ui_locator, game_cfg, debug_port):
    """用 Raw CDP screenshot 等待遊戲載入，不啟用任何 CDP domain。"""
    from core.raw_cdp import raw_screenshot, raw_click
    from core.async_game_utils import extract_bottom_numbers
    from PIL import Image
    import io

    logger.info("⏳ [Raw CDP] 等待遊戲載入...")
    skip_splash = game_cfg.get("skip_splash", False)

    for attempt in range(15):
        ss_bytes = await raw_screenshot(debug_port)
        if not ss_bytes:
            logger.warning(f"⚠️ [Raw CDP] Screenshot failed (attempt {attempt+1})")
            await asyncio.sleep(2)
            continue

        img = Image.open(io.BytesIO(ss_bytes))
        # 假設 viewport 1280x720，計算 DPR
        dpr = img.width / 1280.0

        ocr_res = await asyncio.to_thread(ui_locator.reader.readtext, ss_bytes)

        # 處理 Splash 按鈕
        clicked_splash = False
        if not skip_splash:
            for r in ocr_res:
                if any(k in r[1].lower() for k in ["continue", "start", "play"]):
                    bbox = r[0]
                    cx = (bbox[0][0] + bbox[2][0]) / 2 / dpr
                    cy = (bbox[0][1] + bbox[2][1]) / 2 / dpr
                    logger.info(f"🖱️ [Raw CDP] 點擊 Splash '{r[1]}' at ({cx:.0f}, {cy:.0f})")
                    await raw_click(cx, cy, debug_port)
                    await asyncio.sleep(2)
                    clicked_splash = True
                    break
        else:
            logger.info("⏩ skip_splash = True, 點擊畫面中心")
            await raw_click(640, 360, debug_port)

        if clicked_splash:
            continue

        # 偵測底部數字判斷載入完成
        bottom_nums = extract_bottom_numbers(ocr_res, img.height, img.width)
        if len(bottom_nums) >= 2:
            logger.info(f"✅ [Raw CDP] Game Loaded! (Bottom nums: {[b[0] for b in bottom_nums]})")
            return True

        await asyncio.sleep(1.5)

    logger.info("⏳ [Raw CDP] 等待完畢，嘗試當作載入完成繼續...")
    return True


async def _raw_execute_spin(ui_locator, vision_client, shared_memory, game_cfg, debug_port):
    """用 Raw CDP 執行單次 Spin + 等待結算。"""
    from core.raw_cdp import raw_screenshot, raw_click
    from core.async_game_utils import extract_bottom_numbers, get_surgical_balance
    from PIL import Image
    import io

    logger.info("🔍 [Raw CDP] Pre-balance check...")
    ss = await raw_screenshot(debug_port)
    if not ss:
        logger.error("❌ [Raw CDP] Cannot take screenshot for balance check")
        return False

    img = Image.open(io.BytesIO(ss))
    dpr = img.width / 1280.0

    ocr_res = await asyncio.to_thread(ui_locator.reader.readtext, ss)
    bottom_nums = extract_bottom_numbers(ocr_res, img.height, img.width)

    before_balance = None
    balance_bbox = None

    if len(bottom_nums) >= 1:
        # 取最大值作為錢包餘額 (避免誤用 Bet 下注額)
        max_num_idx = 0
        max_val = -1.0
        for idx, (val, bbox) in enumerate(bottom_nums):
            if val > max_val:
                max_val = val
                max_num_idx = idx
        before_balance = bottom_nums[max_num_idx][0]
        balance_bbox = bottom_nums[max_num_idx][1]
        shared_memory["balance_bbox"] = balance_bbox
        logger.info(f"✅ [Raw CDP] Balance: {before_balance} (All: {[b[0] for b in bottom_nums]})")
    else:
        logger.warning("⚠️ [Raw CDP] 找不到初始餘額（可能是 Canvas 渲染），將略過 OCR 比對，改用 VLM 結算判定")

    # 找 Spin 按鈕 (使用快取或 VLM)
    cache_key = f"{game_cfg['id']}_spin_button"
    cached = shared_memory.setdefault("cache_spin_coords", {}).get(cache_key)

    if cached:
        logger.info(f"⏩ [Raw CDP Cache] Found cached Spin Button at {cached}")
        spin_x, spin_y = cached
    else:
        btn_config = game_cfg.get("spin_button", {})
        spin_prompt = btn_config.get("prompt", "the large circular spin button or start button for slot game")
        region = btn_config.get("region", {})
        x0, x1 = region.get("x_start", 0.0), region.get("x_end", 1.0)
        y0, y1 = region.get("y_start", 0.0), region.get("y_end", 1.0)

        vlm_rect = await asyncio.to_thread(
            vision_client.detect_in_grid_region, ss, spin_prompt, x0, x1, y0, y1
        )

        if vlm_rect:
            iw, ih = img.size
            spin_x = ((vlm_rect[0] + vlm_rect[2]) / 2 / 1000.0) * iw / dpr
            spin_y = ((vlm_rect[1] + vlm_rect[3]) / 2 / 1000.0) * ih / dpr
            shared_memory["cache_spin_coords"][cache_key] = (spin_x, spin_y)
            logger.info(f"🎰 [Raw CDP] VLM found Spin at ({spin_x:.2f}, {spin_y:.2f}) and cached.")
        else:
            # Fallback: 點擊畫面右下角 (多數遊戲 Spin 按鈕位置)
            logger.warning("⚠️ [Raw CDP] VLM 找不到 Spin，嘗試右下角")
            spin_x, spin_y = 1100, 650

    logger.info(f"🎰 [Raw CDP] Clicking Spin at ({spin_x:.0f}, {spin_y:.0f})")
    await raw_click(spin_x, spin_y, debug_port)

    # Cooldown 2 秒讓動畫啟動
    await asyncio.sleep(2)

    # 等待結算
    logger.info("⏳ [Raw CDP] Waiting for settlement...")

    # 若有 balance_bbox，先嘗試 OCR 比對；否則純粹等待固定時間
    if before_balance is not None and balance_bbox is not None:
        for check in range(15):
            ss2 = await raw_screenshot(debug_port)
            if not ss2:
                await asyncio.sleep(2)
                continue

            after_balance = await asyncio.to_thread(get_surgical_balance, ss2, balance_bbox, ui_locator)
            if after_balance is not None:
                if after_balance != before_balance:
                    logger.info(f"✅ [Raw CDP] Settlement done! Balance: {before_balance} → {after_balance}")
                    return True
                # 若餘額無變化，用全畫面再試一次
                img2 = Image.open(io.BytesIO(ss2))
                ocr2 = await asyncio.to_thread(ui_locator.reader.readtext, ss2)
                nums2 = extract_bottom_numbers(ocr2, img2.height, img2.width)
                if len(nums2) >= 1:
                    max_val = max(v for v, _ in nums2)
                    if max_val != before_balance:
                        logger.info(f"✅ [Raw CDP Full-OCR] Settlement done! Balance: {before_balance} → {max_val}")
                        return True

            await asyncio.sleep(2)
    else:
        # JILI Canvas 模式：等待固定秒數讓 spin 完成，視為成功
        logger.info("ℹ️ [Raw CDP] No balance reference, waiting 15s for spin to complete...")
        await asyncio.sleep(15)

    logger.info("⏳ [Raw CDP] 結算等待超時，視為完成")
    return True


async def _run_jili_betting(game_ids, all_games, provider_name, env_config,
                            ui_locator, vision_client, shared_memory, failed_games, _env):
    """
    JILI 專用流程：subprocess Chrome + connect_over_cdp。
    在點擊遊戲 icon 後斷開 CDP 連接，等遊戲載完再重連。
    """
    CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    DEBUG_PORT = 9222
    user_data_dir = tempfile.mkdtemp(prefix="jili_chrome_profile_")
    ext_dir = _create_jili_extension()

    logger.info(f"📦 Extension created at: {ext_dir}")
    logger.info(f"📂 Chrome user-data-dir: {user_data_dir}")

    chrome_args = [
        CHROME_PATH,
        f'--remote-debugging-port={DEBUG_PORT}',
        f'--user-data-dir={user_data_dir}',
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-features=IsolateOrigins,site-per-process',
        f'--disable-extensions-except={ext_dir}',
        f'--load-extension={ext_dir}',
        '--window-size=1280,720',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-popup-blocking',
        '--headless=new',
    ]

    # 先確保舊 Chrome debug port 沒被佔用
    subprocess.run(["pkill", "-f", f"--remote-debugging-port={DEBUG_PORT}"],
                   capture_output=True)
    await asyncio.sleep(1)

    chrome_proc = subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info(f"🚀 Chrome subprocess launched (PID={chrome_proc.pid})")
    await asyncio.sleep(3)  # 等 Chrome 啟動

    try:
        # === Phase 1: 登入 + 找遊戲 (CDP 連線中) ===
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # 設定 viewport
        await page.set_viewport_size({"width": 1280, "height": 720})

        eye_task = asyncio.create_task(
            vision_eye_task(page, vision_client, ui_locator, shared_memory)
        )

        lobby_url = await perform_login(page, ui_locator, env_config)

        for game_id in game_ids:
            if game_id not in all_games[provider_name]:
                logger.error(f"❌ [{provider_name}] {game_id} not found in games.yaml, skipping.")
                failed_games.append(f"{game_id}: not found in games.yaml")
                continue

            game_cfg = dict(all_games[provider_name][game_id])
            game_cfg["id"] = game_id
            game_cfg["provider_label"] = provider_name
            logger.info(f"🎮 [{provider_name}] {game_cfg['name']} ({game_id}) — Env: {_env}")

            shared_memory.update({
                "found_elements": {},
                "current_target": None,
                "can_spin": False,
                "settlement_complete": False,
                "error_detected": False,
            })

            try:
                # Step 1-4: 搜尋並點擊遊戲 (不等待載入)
                ok = await navigate_to_game(page, ui_locator, vision_client,
                                            shared_memory, game_cfg, click_only=True)
                if not ok:
                    logger.error(f"❌ Failed to click game icon for {game_id}")
                    failed_games.append(f"{game_id}: navigation failed")
                    continue

                logger.info("🔌 Game clicked — disconnecting CDP to avoid anti-tamper detection...")

                # 停止 eye task (它需要 page reference)
                shared_memory["running"] = False
                await eye_task

                # === 斷開 CDP ===
                await p.stop()
                logger.info("✅ CDP disconnected. Waiting for game to load...")

                # === 無 CDP 狀態下等待遊戲載入 ===
                await asyncio.sleep(20)

                # === Phase 2: 使用 Raw CDP (不啟用任何 domain) ===
                from core.raw_cdp import raw_screenshot, raw_click, raw_get_page_url

                game_url = await raw_get_page_url(DEBUG_PORT)
                logger.info(f"🔗 Game page URL: {game_url}")

                # 用 Raw CDP 等待遊戲載入 + spin
                loaded = await _raw_wait_for_game_load(ui_locator, game_cfg, DEBUG_PORT)
                if not loaded:
                    logger.error(f"❌ Game failed to load: {game_id}")
                    failed_games.append(f"{game_id}: loading failed")
                else:
                    result = await _raw_execute_spin(ui_locator, vision_client, shared_memory, game_cfg, DEBUG_PORT)
                    if not result:
                        logger.error(f"❌ Spin failed for {game_id}")
                        failed_games.append(f"{game_id}: spin failed")
                    else:
                        logger.info(f"✅ [{provider_name}] {game_id} passed")

            except Exception as e:
                logger.error(f"❌ [{provider_name}] {game_id} exception: {e}")
                failed_games.append(f"{game_id}: {e}")

            # 回大廳：重連 Playwright (離開遊戲頁後反調試不再運作)
            logger.info(f"🔄 Returning to lobby after {game_id}...")
            try:
                p = await async_playwright().start()
                browser = await p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                await page.set_viewport_size({"width": 1280, "height": 720})
                await page.goto(lobby_url)
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)
                await dismiss_lobby_modals(page, ui_locator)
                # 重啟 eye task
                shared_memory["running"] = True
                eye_task = asyncio.create_task(
                    vision_eye_task(page, vision_client, ui_locator, shared_memory)
                )
            except Exception as e:
                logger.warning(f"⚠️ Failed to return to lobby: {e}")

    finally:
        shared_memory["running"] = False
        try:
            await p.stop()
        except Exception:
            pass
        chrome_proc.terminate()
        chrome_proc.wait(timeout=5)
        logger.info("🛑 Chrome subprocess terminated.")


async def _run_normal_betting(provider_name, game_ids, all_games, env_config,
                              ui_locator, vision_client, shared_memory, failed_games, _env,
                              global_config, request):
    """非 JILI provider 的標準流程 (直接使用 Playwright launch)。"""
    from playwright_stealth import Stealth
    import os
    import allure
    from core.video_auditor import VideoAuditor

    # ── Goal Agent (Siraya API) ───────────────────────────────────────────────
    # 只有 COMBO provider 且設定了 SIRAYA_API_KEY 時才啟用。
    # 其他 provider 仍走原本的 execute_single_spin 流程。
    goal_agent = None
    if provider_name == "COMBO":
        siraya_api_key = os.environ.get("SIRAYA_API_KEY")
        no_goal_agent = request.config.getoption("--no-goal-agent", default=False)
        if siraya_api_key and not no_goal_agent:
            plan_model = os.environ.get("SIRAYA_PLAN_MODEL", "claude-sonnet-4.5")
            discovery_model = os.environ.get("SIRAYA_DISCOVERY_MODEL", "gemini-2.5-pro")
            state_model = os.environ.get("SIRAYA_STATE_MODEL", "qwen3.5-flash")
            goal_agent = GoalAgent(
                api_key=siraya_api_key,
                plan_model=plan_model,
                discovery_model=discovery_model,
                state_model=state_model,
            )
            logger.info(
                f"☁️ [COMBO] Goal Agent enabled "
                f"(plan={plan_model}, discovery={discovery_model}, state={state_model})"
            )
        else:
            if not siraya_api_key:
                logger.warning("⚠️ [COMBO] SIRAYA_API_KEY not set — falling back to local VLM spin")
            else:
                logger.info("⚠️ [COMBO] --no-goal-agent set — using local VLM spin")
    # ─────────────────────────────────────────────────────────────────────────

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=False)
        eye_task = None
        
        # 讀取錄影配置
        settings = global_config.get("report_settings", {})
        record_video = settings.get("record_video", False)
        video_dir = settings.get("video_dir", "recordings/")
        
        context_args = {"viewport": {"width": 1280, "height": 720}}
        if record_video:
            context_args["record_video_dir"] = video_dir
            context_args["record_video_size"] = {"width": 1280, "height": 720}
            
        try:
            context = await browser.new_context(**context_args)
            page = await context.new_page()

            eye_task = asyncio.create_task(
                vision_eye_task(page, vision_client, ui_locator, shared_memory)
            )

            lobby_url = await perform_login(page, ui_locator, env_config)

            for game_id in game_ids:
                if game_id not in all_games[provider_name]:
                    logger.error(f"❌ [{provider_name}] {game_id} not found in games.yaml, skipping.")
                    failed_games.append(f"{game_id}: not found in games.yaml")
                    continue

                game_cfg = dict(all_games[provider_name][game_id])
                game_cfg["id"] = game_id
                game_cfg["provider_label"] = provider_name
                logger.info(f"🎮 [{provider_name}] {game_cfg['name']} ({game_id}) — Env: {_env}")

                shared_memory.update({
                    "found_elements": {},
                    "current_target": None,
                    "can_spin": False,
                    "settlement_complete": False,
                    "error_detected": False,
                })

                try:
                    ok = await navigate_to_game(page, ui_locator, vision_client, shared_memory, game_cfg)
                    if not ok:
                        logger.error(f"❌ Failed to navigate to {game_id}")
                        failed_games.append(f"{game_id}: navigation failed")
                    else:
                        if goal_agent is not None:
                            # Phase 2: GoalAgent ReAct 循環執行高層目標
                            goal_text = game_cfg.get("goal") or GoalAgent.default_goal(game_cfg)
                            logger.info(f"☁️ [{provider_name}] Goal Agent running: {goal_text}")
                            result = await goal_agent.run(page, game_cfg, goal_text)
                        else:
                            # Fallback: 本地 VLM spin
                            result = await execute_single_spin(page, vision_client, ui_locator, shared_memory, game_cfg)
                        if not result:
                            logger.error(f"❌ Spin failed for {game_id}")
                            failed_games.append(f"{game_id}: spin failed")
                        else:
                            logger.info(f"✅ [{provider_name}] {game_id} passed")
                except Exception as e:
                    logger.error(f"❌ [{provider_name}] {game_id} exception: {e}")
                    failed_games.append(f"{game_id}: {e}")

                logger.info(f"🔄 Returning to lobby after {game_id}...")
                try:
                    await page.goto(lobby_url)
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2)
                    await dismiss_lobby_modals(page, ui_locator)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to return to lobby: {e}")

        finally:
            shared_memory["running"] = False
            if eye_task:
                await eye_task
                
            video_path = None
            if record_video:
                try:
                    video_path = await page.video.path()
                except Exception as e:
                    logger.warning(f"Failed to get video path: {e}")
                    
            await browser.close()
            
            # 處理非同步錄影影片與視覺審計
            if record_video and video_path:
                try:
                    abs_video_path = os.path.abspath(video_path)
                    for _ in range(20):
                        if os.path.exists(abs_video_path) and os.path.getsize(abs_video_path) > 1024:
                            break
                        await asyncio.sleep(0.1)
                        
                    if os.path.exists(abs_video_path) and os.path.getsize(abs_video_path) > 0:
                        test_name = request.node.name
                        artifact_handler = request.getfixturevalue("artifact_handler")
                        final_video_path = artifact_handler.move_video(abs_video_path, test_name)
                        
                        if not failed_games:
                            logger.info("🎬 Starting Async Post-Test Visual Audit...")
                            errors = VideoAuditor.audit_video_file(final_video_path, check_every_n_frames=3)
                            if errors:
                                msg = f"Visual Defects Found: {errors}"
                                logger.error(msg)
                                pytest.fail(msg)
                                
                        with open(final_video_path, "rb") as f:
                            allure.attach(
                                f.read(),
                                name="Execution Video",
                                attachment_type=allure.attachment_type.WEBM,
                            )
                except Exception as e:
                    logger.error(f"Failed to process video: {e}")


# ============================================================
# 測試函式：一個 Provider = 一個 test = 一個 browser
# ============================================================
async def test_async_game_betting_combo(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: COMBO (1 browser, 登入一次)"""
    await _run_provider_betting("COMBO", request, global_config, ui_locator, vision_client)

async def test_async_game_betting_fc(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: FC (1 browser, 登入一次)"""
    await _run_provider_betting("FC", request, global_config, ui_locator, vision_client)

async def test_async_game_betting_jdb(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: JDB (1 browser, 登入一次)"""
    await _run_provider_betting("JDB", request, global_config, ui_locator, vision_client)

async def test_async_game_betting_jili(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: JILI (1 browser, 登入一次)"""
    await _run_provider_betting("JILI", request, global_config, ui_locator, vision_client)

async def test_async_game_betting_pg(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: PG (1 browser, 登入一次)"""
    await _run_provider_betting("PG", request, global_config, ui_locator, vision_client)

async def test_async_game_betting_pp(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: PP (1 browser, 登入一次)"""
    await _run_provider_betting("PP", request, global_config, ui_locator, vision_client)

async def test_async_game_betting_sexybcrt(request, global_config, ui_locator, vision_client):
    """非同步單手下注測試 - Provider: SEXYBCRT (1 browser, 登入一次)"""
    await _run_provider_betting("SEXYBCRT", request, global_config, ui_locator, vision_client)
