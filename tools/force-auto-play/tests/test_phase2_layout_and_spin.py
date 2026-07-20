"""
Phase 2 — Layout Discovery & GoalAgent 簡單目標驗證 (pytest)

測試目標：COMBO 0001 Prosperous Tiger - 執行 "Spin 3 times"
環境：PP（Prepaid）
成本：~$0.0227 / 次

用法：
    export SIRAYA_API_KEY="sk-..."
    pytest scratch/test_phase2_layout_and_spin.py -v -s --env pp

觀察指標：
    ✅ Layout discovery 成功？座標合理嗎？
    ✅ Cache 寫入 config/specs/layout_cache/0001.json
    ✅ ReAct 循環執行 3 次 spin？
    ✅ complete(success=true) 被呼叫？
"""

import asyncio
import logging
import os
import time
from pathlib import Path

import pytest
import yaml
import allure
from playwright.async_api import async_playwright

from core.goal_agent import GoalAgent
from core.async_game_utils import perform_login, navigate_to_game
from core.video_auditor import VideoAuditor

logger = logging.getLogger(__name__)


# ============================================================
# Pytest Fixtures
# ============================================================
@pytest.fixture
def games_config():
    """載入 COMBO 遊戲設定"""
    games_path = Path("config/games.yaml")
    with open(games_path) as f:
        games = yaml.safe_load(f)
    return games.get("COMBO", {})


@pytest.fixture
def goal_agent():
    """建立 GoalAgent 實例"""
    api_key = os.environ.get("SIRAYA_API_KEY")
    if not api_key:
        pytest.skip("SIRAYA_API_KEY not set")
    return GoalAgent(api_key=api_key)


# ============================================================
# Test Cases
# ============================================================
@pytest.mark.asyncio
async def test_phase2_combo_0001_spin_3_times(
    request, global_config, ui_locator, vision_client, games_config, goal_agent
):
    """
    Phase 2: Layout Discovery & GoalAgent Simple Spin Test

    測試流程：
    1. 登入 PP 環境
    2. 進入 COMBO 0001 Prosperous Tiger
    3. 執行 "Spin 3 times" 目標
    4. 驗證 Layout cache 生成
    5. 驗證 GoalAgent 成功完成
    """
    env = global_config.get("_env", "pp")
    logger.info(f"🎮 Phase 2: GoalAgent Layout Discovery & Spin Test")
    logger.info(f"   環境: {env.upper()}")
    logger.info(f"   遊戲: COMBO 0001 Prosperous Tiger")
    logger.info(f"   目標: Click bet_increase once, verify bet changed, then spin 2 times")

    # ── 遊戲設定 ──────────────────────────────────────────
    game_cfg = dict(games_config.get("0001", {}))
    assert game_cfg, "COMBO 0001 not found in games.yaml"

    game_id = "0001"
    game_cfg["id"] = game_id
    game_cfg["provider_label"] = "COMBO"
    game_name = game_cfg.get("name", "Prosperous Tiger")
    logger.info(f"✅ 遊戲設定: {game_id} - {game_name}")

    # ── 環境設定 ──────────────────────────────────────────
    env_config = global_config["projects"]["client"]["environments"][env]
    shared_memory = {
        "found_elements": {},
        "current_target": None,
        "can_spin": False,
        "settlement_complete": False,
        "error_detected": False,
    }
    goal = "Click bet_increase to 50, verify bet changed, then spin 2 times"
    success = False
    elapsed = 0.0

    # 讀取錄影配置
    settings = global_config.get("report_settings", {})
    record_video = settings.get("record_video", False)
    video_dir = settings.get("video_dir", "recordings/")
    Path(video_dir).mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context_args = {"viewport": {"width": 1280, "height": 720}}
        if record_video:
            context_args["record_video_dir"] = video_dir
            context_args["record_video_size"] = {"width": 1280, "height": 720}
        context = await browser.new_context(**context_args)
        page = await context.new_page()

        try:
            # ── 登入 ──────────────────────────────────────────────
            logger.info(f"🔐 登入 {env.upper()} 環境...")
            lobby_url = await perform_login(page, ui_locator, env_config)
            assert lobby_url, "登入失敗"
            logger.info(f"✅ 登入成功: {lobby_url}")

            # ── 進遊戲 ────────────────────────────────────────────
            logger.info(f"🎮 進入 {game_name}...")
            ok = await navigate_to_game(page, ui_locator, vision_client, shared_memory, game_cfg)
            assert ok, "進遊戲失敗"
            logger.info(f"✅ 進遊戲成功")

            # 等待遊戲完全加載
            await asyncio.sleep(2)

            # ── 執行 GoalAgent ────────────────────────────────────
            logger.info(f"\n⚡ 執行目標: '{goal}'")
            logger.info(f"   成本估計: $0.023 per step")
            logger.info("")

            t_start = time.perf_counter()
            success = await goal_agent.run(page, game_cfg, goal)
            elapsed = time.perf_counter() - t_start
        finally:
            video_path = None
            if record_video:
                try:
                    video_path = await page.video.path()
                except Exception as e:
                    logger.warning(f"Failed to get video path: {e}")
            
            await context.close()
            await browser.close()
            
            # 處理錄影影片與視覺審計
            if record_video and video_path:
                try:
                    abs_video_path = os.path.abspath(video_path)
                    # 等待視頻檔案寫完
                    for _ in range(20):
                        if os.path.exists(abs_video_path) and os.path.getsize(abs_video_path) > 1024:
                            break
                        await asyncio.sleep(0.1)
                    
                    if os.path.exists(abs_video_path) and os.path.getsize(abs_video_path) > 0:
                        test_name = request.node.name
                        artifact_handler = request.getfixturevalue("artifact_handler")
                        final_video_path = artifact_handler.move_video(abs_video_path, test_name)
                        
                        # 如果成功，執行視覺審計
                        if success:
                            logger.info("🎬 Starting Post-Test Visual Audit...")
                            errors = VideoAuditor.audit_video_file(final_video_path, check_every_n_frames=3)
                            if errors:
                                msg = f"Visual Defects Found: {errors}"
                                logger.error(msg)
                                pytest.fail(msg)
                        
                        # 附加到 allure 報告
                        with open(final_video_path, "rb") as f:
                            allure.attach(
                                f.read(),
                                name="Execution Video",
                                attachment_type=allure.attachment_type.WEBM,
                            )
                        logger.info(f"🎥 錄影已儲存並附加: {final_video_path}")
                except Exception as e:
                    logger.error(f"Failed to process video: {e}")

    logger.info("")
    if success:
        logger.info(f"✅ 目標達成！耗時 {elapsed:.1f}s")
    else:
        logger.info(f"❌ 目標失敗。耗時 {elapsed:.1f}s")

    # ── 驗證結果 ──────────────────────────────────────────
    cache_path = Path("config/specs/layout_cache") / f"{game_id}.json"
    if cache_path.exists():
        logger.info(f"✅ Layout cache 已寫入: {cache_path}")
    else:
        logger.warning(f"⚠️  Layout cache 未找到: {cache_path}")

    # ── 斷言 ──────────────────────────────────────────────
    assert success, f"GoalAgent 未能完成目標 '{goal}'"
    assert cache_path.exists(), "Layout cache 未生成"
