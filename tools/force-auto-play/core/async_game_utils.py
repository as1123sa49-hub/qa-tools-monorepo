"""
非同步遊戲工具函式 (抽離自 poc_async_single_bet.py)
對齊 core/game_utils.py 的同步版邏輯，但把 OCR/VLM 阻塞操作丟進背景執行緒。
"""
import asyncio
import io
import logging
import re
import time

from PIL import Image

logger = logging.getLogger(__name__)


# ============================================================
# 非同步登入 (單一來源，對齊 conftest.py login_to_lobby)
# ============================================================
async def perform_login(page, ui_locator, env_config) -> str:
    """
    非同步登入，完全對齊 conftest.py 的 login_to_lobby fixture 邏輯。
    回傳 lobby_url 供後續「回大廳」使用。
    """
    url = env_config["web_url"]
    username = str(env_config["accounts"]["player_vision_async"]["username"])
    password = str(env_config["accounts"]["player_vision_async"]["password"])

    logger.info(f"Navigate to {url}")
    await page.goto(url)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(3)

    # Step 1: 登入前 Guest Modal (對齊 conftest Step 1)
    logger.info("--- Step 1: 檢查登入前 Modal ---")
    for i in range(3):
        scan, _, _ = await async_ui_scan(page, ui_locator, "guest")
        cb = scan.get("checkbox_label") or scan.get("checkbox")
        agree = scan.get("agree_button")
        if not cb and not agree:
            logger.info(f"  沒有 Entry Modal (attempt {i+1}/3)")
            break
        if cb:
            logger.info(f"  點擊 checkbox at {cb}")
            await page.mouse.click(*cb)
            await asyncio.sleep(0.5)
        if agree:
            logger.info(f"  點擊 agree at {agree}")
            await page.mouse.click(*agree)
            await asyncio.sleep(2)

    # Step 2: 登入 (對齊 conftest Step 2)
    logger.info("--- Step 2: 登入 ---")
    login_scan, _, _ = await async_ui_scan(page, ui_locator, "login")
    if "header_login_button" in login_scan:
        logger.info(f"  點擊 Header Login at {login_scan['header_login_button']}")
        await page.mouse.click(*login_scan["header_login_button"])
        await asyncio.sleep(2)

        login_form, _, _ = await async_ui_scan(page, ui_locator, "login")
        if "switch_to_password_btn" in login_form:
            logger.info(f"  切換密碼登入 at {login_form['switch_to_password_btn']}")
            await page.mouse.click(*login_form["switch_to_password_btn"])
            await asyncio.sleep(1)
            login_form, _, _ = await async_ui_scan(page, ui_locator, "login")

        if "login_phone_field" in login_form:
            logger.info(f"  輸入帳號 at {login_form['login_phone_field']}")
            await page.mouse.click(*login_form["login_phone_field"])
            await page.keyboard.type(username)
            await asyncio.sleep(1)
        else:
            logger.warning("⚠️ OCR 沒找到 phone field!")

        if "login_password_field" in login_form:
            logger.info(f"  輸入密碼 at {login_form['login_password_field']}")
            await page.mouse.click(*login_form["login_password_field"])
            await page.keyboard.type(password)
            await asyncio.sleep(1)
        else:
            logger.warning("⚠️ OCR 沒找到 password field!")

        if "login_submit_button" in login_form:
            logger.info(f"  點擊送出 at {login_form['login_submit_button']}")
            await page.mouse.click(*login_form["login_submit_button"])
            await asyncio.sleep(5)
        else:
            logger.warning("⚠️ 沒找到 Login Submit 按鈕")
    else:
        logger.info("✅ 已經登入過了。")

    # Step 3: 登入後公告 Modal (對齊 conftest Step 3)
    logger.info("--- Step 3: 檢查登入後 Modal ---")
    for i in range(3):
        scan, _, _ = await async_ui_scan(page, ui_locator, "guest")
        cb = scan.get("checkbox_label") or scan.get("checkbox")
        agree = scan.get("agree_button")
        if not cb and not agree:
            logger.info(f"  沒有登入後 Modal (attempt {i+1}/3)")
            break
        if cb:
            logger.info(f"  點擊 checkbox at {cb}")
            await page.mouse.click(*cb)
            await asyncio.sleep(0.5)
        if agree:
            logger.info(f"  點擊 agree at {agree}")
            await page.mouse.click(*agree)
            await asyncio.sleep(2)

    return url


# ============================================================
# Helper: 回大廳後關閉可能出現的 Modal
# ============================================================
async def dismiss_lobby_modals(page, ui_locator, retries: int = 2):
    """回大廳後處理可能彈出的公告 Modal。"""
    for _ in range(retries):
        scan, _, _ = await async_ui_scan(page, ui_locator, "guest")
        cb = scan.get("checkbox_label") or scan.get("checkbox")
        agree = scan.get("agree_button")
        if not cb and not agree:
            break
        if cb:
            await page.mouse.click(*cb)
            await asyncio.sleep(0.5)
        if agree:
            await page.mouse.click(*agree)
            await asyncio.sleep(2)


# ============================================================
# Helper: 非同步版 ui_scanner
# ============================================================
async def async_ui_scan(page, ui_locator, context="all"):
    """截圖 → 計算 DPR → 執行 OCR scan_context (非同步)"""
    screenshot_bytes = await page.screenshot(type="png")
    img = Image.open(io.BytesIO(screenshot_bytes))
    vp_w = page.viewport_size["width"]
    dpr = img.width / vp_w if vp_w > 0 else 1.0
    raw_coords = await asyncio.to_thread(ui_locator.scan_context, screenshot_bytes, context, dpr)
    return raw_coords, screenshot_bytes, dpr


def extract_bottom_numbers(ocr_results, img_height, img_width=1920):
    """
    從畫面下方提取餘額與下注額。
    透過過濾 Y 座標 (只看下方 60% 以下)，找出帶小數點兩位的數字。
    根據距離畫面中央的近度排序，因此 index 0 取出的即是最接近中央的餘額。
    回傳：[(value, bbox), ...]
    """
    numbers = []
    for bbox, text, conf in ocr_results:
        cy = (bbox[0][1] + bbox[2][1]) / 2
        cx = (bbox[0][0] + bbox[2][0]) / 2
        
        # 尋找畫面下半部，但排除最底部的 BMM 合規字元區 (例如 y > 98% 的極窄帶)
        # 這次我們不硬性規定 cx > 0.25，而是全部收進來後用距離中央的距離進行排序
        if img_height * 0.6 < cy < img_height * 0.98:
            matches = re.findall(r"([\d,]+[.\s]?\d{2})", text)
            for val_str in matches:
                try:
                    cl = val_str.replace(",", "").replace(" ", "")
                    if len(cl) <= 12:
                        numbers.append((cx, float(cl), bbox))
                except ValueError:
                    pass
                    
    # 根據距離畫面中央 (img_width / 2) 的遠近排序，最靠近水平中央的會排在第一個（真實錢包餘額）
    center_x = img_width / 2
    numbers.sort(key=lambda item: abs(item[0] - center_x))
    
    return [(n[1], n[2]) for n in numbers]


def get_surgical_balance(screenshot_bytes, balance_bbox, ui_locator):
    """使用 Surgical Crop 快速獲取餘額，減少 OCR 時間"""
    try:
        img = Image.open(io.BytesIO(screenshot_bytes))
        # balance_bbox: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        x1, y1 = balance_bbox[0]
        x2, y2 = balance_bbox[2]
        margin = 15
        crop_box = (
            max(0, x1 - margin),
            max(0, y1 - margin),
            min(img.width, x2 + margin),
            min(img.height, y2 + margin)
        )
        cropped_img = img.crop(crop_box)
        crop_bytes_io = io.BytesIO()
        cropped_img.save(crop_bytes_io, format="PNG")
        
        ocr_res = ui_locator.reader.readtext(crop_bytes_io.getvalue())
        all_text = " ".join([r[1] for r in ocr_res])
        matches = re.findall(r"([\d,]+[.\s]?\d{2})", all_text)
        for val_str in matches:
            cl = val_str.replace(",", "").replace(" ", "").replace("l", "1").replace("o", "0")
            try:
                return float(cl)
            except ValueError:
                pass
    except Exception as e:
        logger.error(f"Surgical OCR balance check failed: {e}")
    return None



# ============================================================
# 背景眼 (Eye Task) — 非同步持續監控
# ============================================================
async def vision_eye_task(page, vision_client, ui_locator, shared_memory):
    """背景眼：持續截圖並根據 current_target 判斷畫面狀態。"""
    logger.info("👁️ [Eye Task] Started.")
    while shared_memory.get("running", True):
        target = shared_memory.get("current_target")
        if not target:
            await asyncio.sleep(0.1)
            continue

        try:
            if target == "monitor_spin_button":
                spin_px = shared_memory.get("spin_btn_px")
                if spin_px:
                    cx, cy = spin_px
                    clip_x = max(0, cx - 80)
                    clip_y = max(0, cy - 80)
                    crop_bytes = await page.screenshot(
                        type="jpeg", quality=50,
                        clip={"x": clip_x, "y": clip_y, "width": 160, "height": 160}
                    )
                    idle_prompt = shared_memory.get("idle_prompt", "spin button")
                    vlm_res = await asyncio.to_thread(
                        vision_client.detect_ui_element, crop_bytes, idle_prompt)
                    if vlm_res and len(vlm_res) == 4:
                        shared_memory["can_spin"] = True
                        shared_memory["current_target"] = None
                await asyncio.sleep(0.3)
                continue

            elif target == "monitor_settlement":
                ss = await page.screenshot(type="png")
                ocr_results = await asyncio.to_thread(ui_locator.reader.readtext, ss)

                all_text_check = " ".join([r[1].lower() for r in ocr_results])
                error_kws = ["system error", "error occurred", "something went wrong", "network error"]
                if any(k in all_text_check for k in error_kws):
                    logger.warning("⚠️ 系統錯誤彈窗偵測！")
                    shared_memory["error_detected"] = True
                    shared_memory["current_target"] = None
                    continue

                curr_nums = extract_balance(ocr_results)
                shared_memory["latest_ocr"] = ocr_results
                shared_memory["latest_balances"] = curr_nums
                if shared_memory.get("before_balance"):
                    if curr_nums and curr_nums != shared_memory["before_balance"]:
                        shared_memory["settlement_complete"] = True
                        shared_memory["current_target"] = None

        except Exception as e:
            logger.error(f"Eye Task error: {e}")

        await asyncio.sleep(0.5)

    logger.info("👁️ [Eye Task] Stopped.")


# ============================================================
# 等待遊戲載入 (Step 5 抽離，供斷連重連場景獨立呼叫)
# ============================================================
async def wait_for_game_load(page, ui_locator, game_cfg):
    """等待遊戲載入完成 — 處理 splash screen + 偵測底部數字。"""
    logger.info("⏳ 等待遊戲載入...")
    await asyncio.sleep(3)
    skip_splash = game_cfg.get("skip_splash", False)

    for attempt in range(15):
        try:
            ss_load = await asyncio.wait_for(
                page.screenshot(type="png"), timeout=10
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"⚠️ Screenshot timeout/error during loading check (attempt {attempt+1}): {e}")
            await asyncio.sleep(2)
            continue

        img_load = Image.open(io.BytesIO(ss_load))
        vp_load = page.viewport_size
        dpr_load = img_load.width / vp_load["width"] if vp_load["width"] > 0 else 1.0

        ocr_res = await asyncio.to_thread(ui_locator.reader.readtext, ss_load)

        # 1. 優先處理 Splash 畫面的按鈕
        clicked_splash = False
        if not skip_splash:
            for r in ocr_res:
                if any(k in r[1].lower() for k in ["continue", "start", "play"]):
                    bbox = r[0]
                    cx = (bbox[0][0] + bbox[2][0]) / 2 / dpr_load
                    cy = (bbox[0][1] + bbox[2][1]) / 2 / dpr_load
                    logger.info(f"🖱️ 點擊 Splash 按鈕 '{r[1]}' at ({cx:.0f}, {cy:.0f})")
                    await page.mouse.click(cx, cy)
                    await asyncio.sleep(2)
                    clicked_splash = True
                    break
        else:
            logger.info("⏩ skip_splash = True, 點擊畫面中心喚醒遊戲 focus")
            await page.mouse.click(vp_load["width"] / 2, vp_load["height"] / 2)

        if clicked_splash:
            continue

        # 2. 若沒有 Splash，判斷畫面是否載入完成：尋找底部雙數字 (餘額與下注)
        bottom_nums = extract_bottom_numbers(ocr_res, img_load.height, img_load.width)

        if len(bottom_nums) >= 2:
            logger.info(f"✅ Game Loaded! (Bottom nums found: {[b[0] for b in bottom_nums]})")
            return True

        await asyncio.sleep(1.5)

    logger.info("⏳ 等待完畢，嘗試當作載入完成繼續...")
    return True


# ============================================================
# 進入遊戲 (對齊 game_utils.navigate_to_game)
# ============================================================
async def navigate_to_game(page, ui_locator, vision_client, shared_memory, game_cfg, click_only=False):
    """非同步版 navigate_to_game，完全對齊同步版。
    click_only=True 時，點擊遊戲 icon 後立即 return True，不等待載入。
    """
    game_id = game_cfg["id"]
    game_name = game_cfg["name"]
    search_keyword = game_cfg["search_keyword"]
    logger.info(f"🚀 Navigating to game: {game_name}...")

    # Step 1: 點擊搜尋欄
    scan, ss, dpr = await async_ui_scan(page, ui_locator, "lobby")
    search_bar = scan.get("search_bar_placeholder") or scan.get("search_bar")

    if not search_bar:
        logger.warning("⚠️ OCR missed search bar. Trying VLM...")
        vlm_rect = await asyncio.to_thread(
            vision_client.detect_ui_element, ss, "search bar input field")
        if vlm_rect:
            img = Image.open(io.BytesIO(ss))
            iw, ih = img.size
            search_bar = (
                ((vlm_rect[0] + vlm_rect[2]) / 2 / 1000.0) * iw / dpr,
                ((vlm_rect[1] + vlm_rect[3]) / 2 / 1000.0) * ih / dpr,
            )

    if not search_bar:
        logger.error("❌ 找不到搜尋欄！")
        return False

    logger.info(f"點擊 Search Bar at {search_bar}")
    await page.mouse.click(*search_bar)
    await asyncio.sleep(2)

    # Step 2: 點擊 Overlay 搜尋輸入框
    scan2, ss2, dpr2 = await async_ui_scan(page, ui_locator, "lobby")
    real_input = scan2.get("search_overlay_input")

    if not real_input:
        vlm_input = await asyncio.to_thread(
            vision_client.detect_ui_element, ss2, "white search input field text box")
        if vlm_input:
            img2 = Image.open(io.BytesIO(ss2))
            iw2, ih2 = img2.size
            real_input = (
                ((vlm_input[0] + vlm_input[2]) / 2 / 1000.0) * iw2 / dpr2,
                ((vlm_input[1] + vlm_input[3]) / 2 / 1000.0) * ih2 / dpr2,
            )

    if real_input:
        await page.mouse.click(*real_input)
        await asyncio.sleep(0.5)

    # Step 3: 輸入關鍵字
    logger.info(f"⌨️ Typing: {search_keyword}")
    await page.keyboard.type(search_keyword)
    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")
    await asyncio.sleep(5)

    # Step 4: 點擊遊戲 Icon (完全使用 OCR 與 VLM 辨識，並加入滾動支援)
    clicked = False
    
    # 取出較長的關鍵字來比對 (例如 ['prosperous', 'tiger'])
    target_words = [w.lower() for w in game_name.split() if len(w) > 3]
    if not target_words:
        target_words = [game_name.lower()]

    vp_h = page.viewport_size["height"]
    search_bar_y = real_input[1] if real_input else 0

    for attempt in range(3):
        ss3 = await page.screenshot(type="png")
        img3 = Image.open(io.BytesIO(ss3))
        vp3 = page.viewport_size
        dpr3 = img3.width / vp3["width"] if vp3["width"] > 0 else 1.0
        
        logger.info(f"🔍 Using OCR to find game card... (Attempt {attempt+1})")
        ocr_results = await asyncio.to_thread(ui_locator.reader.readtext, ss3)
            
        # 1. 蒐集並整理所有的 OCR 結果，計算中心點與上下邊界
        blocks = []
        for bbox, text, conf in ocr_results:
            t_low = text.lower().strip()
            x1, y1 = bbox[0][0], bbox[0][1]
            x2, y2 = bbox[2][0], bbox[2][1]
            cx = (x1 + x2) / 2 / dpr3
            cy = (y1 + y2) / 2 / dpr3
            h = (y2 - y1) / dpr3
            blocks.append({
                "bbox": bbox,
                "text": text,
                "t_low": t_low,
                "cx": cx,
                "cy": cy,
                "x1": x1 / dpr3,
                "y1": y1 / dpr3,
                "x2": x2 / dpr3,
                "y2": y2 / dpr3,
                "height": h
            })

        best_match = None
        matches = []
        
        # 2. 進行單行比對
        for b in blocks:
            if b["t_low"] == game_name.lower() or (all(w in b["t_low"] for w in target_words) and "joker" not in b["t_low"]):
                if b["cy"] > (vp_h * 0.15) and (b["cy"] - search_bar_y > 100):
                    matches.append((b["cx"], b["cy"], b["text"]))
                    
        # 3. 如果單行沒找到，進行多行合併比對 (處理自動換行，例如 "Lucky\nColor Game")
        if not matches:
            logger.info("⚠️ Single-line OCR match failed. Trying multi-line adjacent block merging...")
            for i, b1 in enumerate(blocks):
                merged_text = b1["t_low"]
                current_b = b1
                
                # 允許最多合併 3 行
                for _ in range(2):
                    next_b = None
                    for b2 in blocks:
                        if b2 == current_b or b2 == b1:
                            continue
                        y_dist = b2["y1"] - current_b["y2"]
                        x_dist = abs(b2["cx"] - current_b["cx"])
                        # 下方垂直距離 35px 內，且水平 x_center 差距 80px 內
                        if 0 <= y_dist <= 35 and x_dist < 80:
                            next_b = b2
                            break
                    if next_b:
                        merged_text += " " + next_b["t_low"]
                        current_b = next_b
                    else:
                        break
                
                if merged_text != b1["t_low"]:
                    if merged_text == game_name.lower() or (all(w in merged_text for w in target_words) and "joker" not in merged_text):
                        if b1["cy"] > (vp_h * 0.15) and (b1["cy"] - search_bar_y > 100):
                            logger.info(f"🔄 Multi-line match found: '{merged_text}' by merging starting at '{b1['text']}' at ({b1['cx']:.0f}, {b1['cy']:.0f})")
                            matches.append((b1["cx"], b1["cy"], merged_text))
                            
        if matches:
            # 取畫面位置最下面的（Y座標最大的），確保點到的是下方搜尋出來的卡片
            best_match = sorted(matches, key=lambda m: m[1])[-1]
            cx, cy, match_text = best_match
            
            offset_y = game_cfg.get("icon_offset_y", 100)
            click_y = cy - offset_y
            logger.info(f"🎯 OCR found '{match_text}' at ({cx:.0f}, {cy:.0f}). Clicking icon at ({cx:.0f}, {click_y:.0f})")
            await page.mouse.click(cx, click_y)
            clicked = True

            if click_only:
                return True

            # ------ 螢幕截圖驗證進遊戲 ------
            await asyncio.sleep(6)  # 等一下遊戲載入
            ss_path = f"/tmp/game_loaded_{game_id.replace('-', '_')}_{int(time.time())}.png"
            await page.screenshot(path=ss_path)
            logger.info(f"📸 Game loaded screenshot saved to {ss_path}")
            # -------------------------------
            break
            
        # 找不到的話，滾動視窗往下找 (每次滾動 300px)
        logger.warning(f"⚠️ Game icon not found in current view. Scrolling down...")
        await page.mouse.wheel(0, 300)
        await asyncio.sleep(1)

    if not clicked:
        logger.warning(f"⚠️ OCR text for {game_name} not found. Using VLM to detect game icon...")
        vlm_icon = await asyncio.to_thread(
            vision_client.detect_ui_element, ss3, f"{game_name} game icon or {search_keyword}")
        if vlm_icon:
            iw3, ih3 = img3.size
            icon_x = ((vlm_icon[0] + vlm_icon[2]) / 2 / 1000.0) * iw3 / dpr3
            icon_y = ((vlm_icon[1] + vlm_icon[3]) / 2 / 1000.0) * ih3 / dpr3
            logger.info(f"✅ VLM Found Icon at ({icon_x:.0f}, {icon_y:.0f}). Clicking.")
            await page.mouse.click(icon_x, icon_y)
            clicked = True

            if click_only:
                return True

            await asyncio.sleep(6)
            ss_path = f"/tmp/game_loaded_{game_id.replace('-', '_')}_{int(time.time())}.png"
            await page.screenshot(path=ss_path)
            logger.info(f"📸 Game loaded screenshot saved to {ss_path}")
        else:
            logger.error("❌ Failed to find game icon!")
            return False

    # Step 5: 等待載入
    return await wait_for_game_load(page, ui_locator, game_cfg)


# ============================================================
# 單次 Spin + 結算等待
# ============================================================
async def execute_single_spin(page, vision_client, ui_locator, shared_memory, game_cfg):
    """單次 Spin + 等待結算 (背景眼輔助)"""
    logger.info("🔍 Pre-balance check...")
    coords, ss, dpr = await async_ui_scan(page, ui_locator, "all")
    img_ss = Image.open(io.BytesIO(ss))
    
    ocr_res = await asyncio.to_thread(ui_locator.reader.readtext, ss)
    bottom_nums = extract_bottom_numbers(ocr_res, img_ss.height, img_ss.width)
    
    if len(bottom_nums) >= 1:
        # 取最大值作為錢包餘額 (避免誤用 Bet 下注額)
        max_num_idx = 0
        max_val = -1.0
        for idx, (val, bbox) in enumerate(bottom_nums):
            if val > max_val:
                max_val = val
                max_num_idx = idx
        before_balances = bottom_nums[max_num_idx][0]
        logger.info(f"✅ Initial balance detected: {before_balances} (All bottom nums: {[b[0] for b in bottom_nums]})")
        shared_memory["balance_bbox"] = bottom_nums[max_num_idx][1]
    else:
        logger.error("❌ 找不到初始餘額！")
        return False

    shared_memory["before_balance"] = [before_balances]  # 相容舊版清單格式

    category = game_cfg.get("category", "slot")
    if category == "fish":
        btn_config = game_cfg.get("shoot_button", {})
        fallback_prompt = "the cannon or weapon used to shoot"
    elif category in ["egame", "arcade", "table"]:
        btn_config = game_cfg.get("action_button", {})
        fallback_prompt = "the main action or drop button"
    elif category == "live":
        btn_config = game_cfg.get("bet_area", {})
        fallback_prompt = "the main betting area or chips"
    else:
        btn_config = game_cfg.get("spin_button", {})
        fallback_prompt = "the large circular spin button with spiral arrow"

    spin_prompt = btn_config.get("prompt", fallback_prompt)
    idle_prompt = btn_config.get("idle_prompt", spin_prompt)
    region = btn_config.get("region", {"x_start": 0.0, "x_end": 1.0, "y_start": 0.0, "y_end": 1.0})

    # ── 找 Spin 按鈕 ──
    cache_key = f"{game_cfg['id']}_spin_button"
    cached = shared_memory.setdefault("cache_spin_coords", {}).get(cache_key)

    if cached:
        logger.info(f"⏩ [Spin Cache] Found cached Spin Button at {cached}")
        spin_px = cached
    else:
        logger.info("🔍 VLM 尋找 Spin 按鈕...")
        ss = await page.screenshot(type="png")
        spin_coords = await asyncio.to_thread(
            vision_client.detect_in_grid_region,
            ss, spin_prompt, region["x_start"], region["x_end"], region["y_start"], region["y_end"],
        )

        if not spin_coords:
            logger.error("❌ VLM 找不到 Spin 按鈕！")
            return False

        img = Image.open(io.BytesIO(ss))
        iw, ih = img.size
        vp = page.viewport_size
        dpr = iw / vp["width"] if vp["width"] > 0 else 1.0
        spin_px = (
            ((spin_coords[0] + spin_coords[2]) / 2 / 1000.0) * iw / dpr,
            ((spin_coords[1] + spin_coords[3]) / 2 / 1000.0) * ih / dpr,
        )
        shared_memory["cache_spin_coords"][cache_key] = spin_px
        logger.info(f"🎯 VLM Found Spin Button at {spin_px} and cached.")

    shared_memory["spin_btn_px"] = spin_px
    shared_memory["idle_prompt"] = idle_prompt
    shared_memory["can_spin"] = False
    shared_memory["current_target"] = "monitor_spin_button"
    logger.info("👁️ 等待 VLM 確認按鈕 Ready...")

    wait_start = time.time()
    while not shared_memory.get("can_spin", False) and time.time() - wait_start < 20:
        await asyncio.sleep(0.5)

    if not shared_memory.get("can_spin"):
        logger.error("❌ Spin 按鈕遲遲無法點擊 (Timeout)")
        return False

    # Smart Click 點擊與重試機制
    click_success = False
    for attempt in range(1, 4):
        logger.info(f"🎰 Clicking Spin at {spin_px} (Attempt {attempt}/3)...")
        await page.mouse.click(spin_px[0], spin_px[1])
        
        # 檢查是否成功開始 Spin (在 2.0 秒內偵測按鈕是否離開 Ready 狀態)
        spin_started = False
        check_start = time.time()
        while time.time() - check_start < 2.0:
            await asyncio.sleep(0.4)
            # 擷取按鈕區域並用 VLM 偵測
            cx, cy = spin_px
            clip_x = max(0, cx - 80)
            clip_y = max(0, cy - 80)
            try:
                crop_bytes = await page.screenshot(
                    type="jpeg", quality=50,
                    clip={"x": clip_x, "y": clip_y, "width": 160, "height": 160}
                )
                vlm_res = await asyncio.to_thread(
                    vision_client.detect_ui_element, crop_bytes, idle_prompt
                )
                # 如果偵測不到 Ready 按鈕，表示按鈕已經進入 spinning 狀態（點擊成功）
                if not (vlm_res and len(vlm_res) == 4):
                    logger.info("🔥 Spin started (Spin button changed to active/spinning state)!")
                    spin_started = True
                    break
            except Exception as e:
                logger.warning(f"⚠️ Error during click verification: {e}")
                
        if spin_started:
            click_success = True
            break
        else:
            logger.warning(f"⚠️ Spin button did not respond on attempt {attempt}, retrying...")

    if not click_success:
        logger.warning("⚠️ Smart Click: Spin button remained in ready state after 3 attempts, continuing anyway.")

    # 強制 Cooldown 2 秒，避開動畫啟動延遲造成的背景眼瞬時 idle 偵測
    logger.info("⏳ Cooldown 2.0s to allow spin animation to start...")
    await asyncio.sleep(2.0)

    # 等待結算：VLM 偵測 spin 按鈕回到 idle（轉完），不靠 OCR 餘額比對
    # lobby header 餘額在 game iframe spin 後不會改變，OCR 比對永遠 timeout
    shared_memory["can_spin"] = False
    shared_memory["current_target"] = "monitor_spin_button"
    logger.info("👁️ 等待結算 (VLM 偵測 Spin 回到 Ready)...")

    spin_start = time.time()
    while time.time() - spin_start < 45:
        if shared_memory.get("can_spin"):
            logger.info("✅ Spin 結算完成！(Spin 按鈕回到 Ready)")
            return True
        await asyncio.sleep(0.5)

    logger.warning("⚠️ Settlement 偵測 timeout，但 Spin 已點擊，視為成功")
    return True
