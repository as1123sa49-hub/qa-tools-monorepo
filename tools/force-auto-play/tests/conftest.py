import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import allure
import pytest
import yaml

from core.artifact_handler import ArtifactHandler, cleanup_orphan_session_dirs
from core.comboburst_auth import resolve_comboburst_auth_path_for_load
from core.jc_lobby_auth import resolve_jc_lobby_auth_path_for_load
from core.env_config import (
    ENTRY_MODE_COMBOBURST_PORTAL,
    ENTRY_MODE_JC_LOBBY,
    get_client_env_config,
    get_comboburst_config,
    get_entry_mode,
    resolve_entry_mode,
)
from core.game_console_listener import GameConsoleListener
from core.hybrid_locator import HybridLocator
from core.log_format import install_category_logging
from core.ui_locator import UILocator
from core.video_auditor import VideoAuditor
from core.vision_client import VisionClient

try:
    from core.game_config import GameConfig
except ImportError:
    logging.warning("GameConfig class not found in core. Using generic dict wrapper.")

    class GameConfig:
        def __init__(self, game_id, data):
            self.game_id = game_id
            self.data = data
            self.name = data.get("name", "")
            self.search_keyword = data.get("search_keyword", "")


logger = logging.getLogger(__name__)

GAMES_YAML_PATH = "config/games.yaml"


def _lookup_game_config(game_id: str) -> dict | None:
    if not os.path.exists(GAMES_YAML_PATH):
        return None
    with open(GAMES_YAML_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for provider_games in data.values():
        if isinstance(provider_games, dict) and game_id in provider_games:
            entry = provider_games[game_id]
            if isinstance(entry, dict):
                return dict(entry)
    return None


def _entry_mode_for_request(request, global_config: dict) -> str:
    """Use per-game entry_mode from games.yaml when test is parametrized by game_id."""
    callspec = getattr(request.node, "callspec", None)
    if callspec and "game_id" in callspec.params:
        game_cfg = _lookup_game_config(callspec.params["game_id"])
        if game_cfg:
            return resolve_entry_mode(global_config, game_cfg)
    return get_entry_mode(global_config)


def _lookup_game_name(game_id: str) -> str | None:
    if not os.path.exists(GAMES_YAML_PATH):
        return None
    with open(GAMES_YAML_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for provider_games in data.values():
        if isinstance(provider_games, dict) and game_id in provider_games:
            entry = provider_games[game_id]
            if isinstance(entry, dict):
                return entry.get("name")
    return None


def _lookup_game_provider(game_id: str) -> str | None:
    if not os.path.exists(GAMES_YAML_PATH):
        return None
    with open(GAMES_YAML_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for provider, provider_games in data.items():
        if isinstance(provider_games, dict) and game_id in provider_games:
            return str(provider)
    return None


def _resolve_game_slug(request) -> str:
    callspec = getattr(request.node, "callspec", None)
    if callspec and "game_id" in callspec.params:
        game_id = callspec.params["game_id"]
        return _lookup_game_name(game_id) or str(game_id)
    return request.node.name


def _resolve_archive_meta(request) -> tuple[str, str | None, str | None]:
    """Return (game_slug, provider, game_id) for artifact archiving."""
    callspec = getattr(request.node, "callspec", None)
    if callspec and "game_id" in callspec.params:
        game_id = str(callspec.params["game_id"])
        return (
            _lookup_game_name(game_id) or game_id,
            _lookup_game_provider(game_id),
            game_id,
        )
    # Fallback: provider from test function name test_game_betting_fc
    provider = None
    name = getattr(request.node, "name", "") or ""
    if "game_betting_" in name:
        provider = name.split("game_betting_", 1)[-1].split("[", 1)[0].upper()
        if provider == "SEXYBCRT":
            provider = "SEXYBCRT"
    return _resolve_game_slug(request), provider, None


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


def pytest_configure(config):
    """Write each pytest run to logs/pytest_YYYYMMDD_HHMMSS.log (no overwrite)."""
    root = Path(__file__).resolve().parent.parent
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_name = f"pytest_{ts}.log"
    stamped_path = logs_dir / stamped_name
    config.option.log_file = str(stamped_path)
    if not getattr(config.option, "log_file_level", None):
        config.option.log_file_level = "DEBUG"
    (logs_dir / "latest.log").write_text(stamped_name + "\n", encoding="utf-8")


def pytest_sessionstart(session):
    install_category_logging()
    removed = cleanup_orphan_session_dirs()
    if removed:
        logging.getLogger("test.session").info(
            "🗑️ Cleaned %s orphan test_artifacts session dir(s)", removed
        )
    log_file = getattr(session.config.option, "log_file", None)
    if log_file:
        logging.getLogger("test.session").info("📄 Session log file: %s", log_file)


def pytest_addoption(parser):
    parser.addoption(
        "--env",
        action="store",
        default="uat",
        help="Test environment: uat (default) or pp",
    )
    parser.addoption(
        "--game",
        action="store",
        default=None,
        help="Specific game ID to run (e.g. 1006)",
    )
    parser.addoption(
        "--no-goal-agent",
        action="store_true",
        default=False,
        help="Disable GoalAgent (use local VLM instead), even if SIRAYA_API_KEY is set",
    )


@pytest.fixture(scope="session")
def global_config(request):
    """Loads the main global configuration."""
    config_path = "config/config.yaml"
    config = {}
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    config["_env"] = request.config.getoption("--env", default="uat")
    return config


@pytest.fixture(scope="session")
def ui_locator(global_config):
    """Provides a UILocator instance with registered game targets."""
    locator = UILocator()
    games_config_path = "config/games.yaml"

    if os.path.exists(games_config_path):
        logger.info(f"Loading game configurations from {games_config_path}...")
        with open(games_config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            for provider, games_map in data.items():
                for game_id, raw_data in games_map.items():
                    game = GameConfig(game_id, raw_data)

                    keywords = [game.search_keyword]

                    locator.register_game_target(game_id, keywords)
    else:
        logger.warning(f"⚠️ Games config not found at {games_config_path}. UILocator will be empty!")

    return locator


@pytest.fixture(scope="session")
def vision_client():
    """Provides a VisionClient instance."""
    return VisionClient()


@pytest.fixture(scope="function")
def hybrid_locator(vision_client, ui_locator):
    """Provides the orchestrated HybridLocator."""
    return HybridLocator(vision_client, ui_locator)


@pytest.fixture(scope="function")
def ui_scanner(page, ui_locator):
    """Returns a function that scans the UI for a specific context."""

    def _scan(context="all"):
        screenshot_bytes = page.screenshot()

        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(screenshot_bytes))
        vp_w = page.viewport_size["width"]
        dpr = img.width / vp_w if vp_w > 0 else 1.0

        raw_coords = ui_locator.scan_context(
            screenshot_bytes,
            context=context,
            dpr=dpr,
            viewport_height=page.viewport_size["height"],
        )
        return raw_coords

    return _scan


@pytest.fixture(scope="function")
def browser_context_args(browser_context_args, global_config, request):
    args = dict(browser_context_args)
    settings = global_config.get("report_settings", {})
    entry_mode = _entry_mode_for_request(request, global_config)

    if entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        comboburst = get_comboburst_config(global_config)
        viewport = comboburst.get("viewport") or {"width": 1920, "height": 911}
        args["viewport"] = viewport

        auth_path = resolve_comboburst_auth_path_for_load(comboburst)
        if os.path.isfile(auth_path):
            args["storage_state"] = auth_path
            logger.info(f"🔑 Comboburst auth loaded: {auth_path}")
        else:
            logger.warning(
                f"⚠️ Comboburst auth not found ({auth_path}). "
                "Run: .\\.venv\\Scripts\\python.exe tools\\save_comboburst_auth.py"
            )
    elif entry_mode == ENTRY_MODE_JC_LOBBY:
        auth_path = resolve_jc_lobby_auth_path_for_load(global_config)
        if os.path.isfile(auth_path):
            args["storage_state"] = auth_path
            logger.info(f"🔑 JC lobby auth loaded: {auth_path}")
        else:
            logger.info(
                "JC lobby auth not found (%s); will full-login. "
                "Optional: .\\.venv\\Scripts\\python.exe tools\\save_jc_lobby_auth.py",
                auth_path,
            )

    if settings.get("record_video", False):
        video_dir = settings.get("video_dir", "recordings/")
        args.update(
            {
                "record_video_dir": video_dir,
                "record_video_size": {"width": 1280, "height": 720},
            }
        )
    return args


@pytest.fixture(scope="function", autouse=True)
def attach_video_to_allure(global_config, request):
    # Async tests manage their own browser — skip video attachment entirely
    if asyncio.iscoroutinefunction(request.node.function):
        yield
        return

    # Pure unit tests: do not pull artifact_handler (avoids orphan timestamp dirs)
    if request.node.path.name.endswith("_unit.py"):
        yield
        return

    artifact_handler = request.getfixturevalue("artifact_handler")
    page = request.getfixturevalue("page")
    yield

    settings = global_config.get("report_settings", {})
    if settings.get("record_video", False):
        try:
            page.context.close()
        except:
            pass

        video_path = page.video.path()

        if video_path:
            abs_video_path = os.path.abspath(video_path)

            time.sleep(1.0)
            for _ in range(20):
                if os.path.exists(abs_video_path) and os.path.getsize(abs_video_path) > 1024:
                    break
                time.sleep(0.1)

            if os.path.exists(abs_video_path) and os.path.getsize(abs_video_path) > 0:
                test_name = request.node.name
                final_video_path = artifact_handler.move_video(abs_video_path, test_name)

                if getattr(request.node, "rep_call", None) and request.node.rep_call.passed:
                    logger.info("🎬 Starting Post-Test Visual Audit...")
                    errors = VideoAuditor.audit_video_file(final_video_path, check_every_n_frames=3)

                    if errors:
                        msg = f"Visual Defects Found: {errors}"
                        logger.error(msg)
                        pytest.fail(msg)

                try:
                    with open(final_video_path, "rb") as f:
                        allure.attach(
                            f.read(),
                            name="Execution Video",
                            attachment_type=allure.attachment_type.WEBM,
                        )
                except Exception as e:
                    logger.error(f"Failed to attach video: {e}")


@pytest.fixture(scope="function")
def login_to_lobby(page, ui_scanner, hybrid_locator, global_config, request):
    """Fixture: 登入 -> 大廳 -> Yield -> 回大廳（comboburst_portal 時跳過 JC 登入）"""
    env_config = get_client_env_config(global_config)
    entry_mode = _entry_mode_for_request(request, global_config)

    if entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        logger.info("🔒 Fixture: entry_mode=comboburst_portal — skipping JC lobby login")
        yield page
        comboburst = get_comboburst_config(global_config)
        teardown_url = comboburst.get(
            "lobby_url", "https://games-dev.comboburst.com/home/index.html"
        )
        logger.info(f"🔄 Teardown: Returning to comboburst lobby ({teardown_url})...")
        try:
            page.goto(teardown_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Teardown navigation failed: {e}")
        return

    logger.info("🔒 Fixture: Starting Login/Check Sequence (JC lobby)...")

    url = env_config["web_url"]
    username = env_config["accounts"]["player_vision"]["username"]
    password = env_config["accounts"]["player_vision"]["password"]

    # --- [SETUP] ---
    if url not in page.url:
        logger.info(f"Navigate to {url}")
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)

    # 處理 Guest Modal (登入前)
    logger.info("Step 1: Checking for Entry Modal (Pre-login)...")
    for i in range(3):
        scan = ui_scanner(context="guest")
        cb = scan.get("checkbox_label") or scan.get("checkbox")
        agree = scan.get("agree_button")

        if not cb and not agree:
            logger.info(f"OCR missed Entry Modal elements. Trying VLM check (attempt {i+1})...")
            try:
                cb = cb or hybrid_locator.find_and_refine(
                    page, "checkbox sentence", keywords=["agree", "confirm", "read"]
                )
                agree = agree or hybrid_locator.find_and_refine(
                    page, "Agree or Start button", keywords=["agree", "all", "start"]
                )
            except:
                pass

        if not cb and not agree:
            logger.info("No Entry Modal detected. Proceeding.")
            break

        if cb:
            logger.info(f"Clicking guest checkbox (label preferred) at {cb}")
            page.mouse.click(*cb)
            time.sleep(0.5)
        if agree:
            logger.info(f"Clicking guest agree button at {agree}")
            page.mouse.click(*agree)
            time.sleep(2)

    # 登入檢查
    login_btn_scan = ui_scanner(context="login")
    if "header_login_button" in login_btn_scan:
        logger.info("Not logged in. Performing Full Login...")
        page.mouse.click(*login_btn_scan["header_login_button"])
        time.sleep(2)

        login_form = ui_scanner(context="login")
        if "switch_to_password_btn" in login_form:
            page.mouse.click(*login_form["switch_to_password_btn"])
            time.sleep(1)
            login_form = ui_scanner(context="login")

        if "login_phone_field" in login_form:
            page.mouse.click(*login_form["login_phone_field"])
            page.keyboard.type(str(username))
            time.sleep(1)

        if "login_password_field" in login_form:
            page.mouse.click(*login_form["login_password_field"])
            page.keyboard.type(str(password))
            time.sleep(1)

        if "login_submit_button" in login_form:
            page.mouse.click(*login_form["login_submit_button"])
            logger.info("Login submitted.")
            time.sleep(5)
    else:
        logger.info("✅ Already logged in.")

    # 登入後公告檢查
    logger.info("Step 3: Checking for post-login modals...")
    for i in range(3):
        scan = ui_scanner(context="guest")
        cb = scan.get("checkbox_label") or scan.get("checkbox")
        agree = scan.get("agree_button")

        if not cb and not agree:
            logger.info(f"OCR missed post-login elements. Trying VLM check (attempt {i+1})...")
            try:
                cb = cb or hybrid_locator.find_and_refine(
                    page, "checkbox sentence", keywords=["agree", "confirm", "show again"]
                )
                agree = agree or hybrid_locator.find_and_refine(
                    page, "Close or Agree button", keywords=["agree", "all", "ok", "close"]
                )
            except:
                pass

        if not cb and not agree:
            logger.info("No post-login modal detected. Proceeding.")
            break

        if cb:
            logger.info(f"Clicking checkbox (label preferred) at {cb}")
            page.mouse.click(*cb)
            time.sleep(0.5)
        if agree:
            logger.info(f"Clicking agree button at {agree}")
            page.mouse.click(*agree)
            time.sleep(2)
        else:
            time.sleep(1)

    # --- [YIELD] ---
    yield page

    # --- [TEARDOWN] ---
    logger.info("🔄 Teardown: Returning to Lobby...")
    try:
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
    except Exception as e:
        logger.warning(f"Teardown navigation failed: {e}")


@pytest.fixture(scope="function")
def console_listener(page):
    """提供 Console 監聽器"""
    listener = GameConsoleListener()
    listener.start(page)
    return listener


@pytest.fixture(scope="function")
def artifact_handler(request):
    """為每個測試案例提供 ArtifactHandler；結束後搬到 test_artifacts/pass|fail/。"""
    from core.fail_codes import parse_fail_code, run_label

    handler = ArtifactHandler()
    handler.run_label = run_label()
    yield handler

    if request.node.path.name.endswith("_unit.py"):
        handler.discard_ephemeral()
        return

    rep = getattr(request.node, "rep_call", None)
    outcome = "pass" if rep is not None and rep.passed else "fail"
    if outcome == "fail" and not handler.fail_code and rep is not None:
        # Prefer explicit set_fail_code; else parse [CODE] from pytest.fail message.
        longrepr = getattr(rep, "longrepr", None)
        handler.set_fail_code(parse_fail_code(str(longrepr) if longrepr else None))
    game_slug, provider, game_id = _resolve_archive_meta(request)
    archived = handler.archive_session(
        outcome, game_slug, provider=provider, game_id=game_id
    )
    if archived is None:
        handler.discard_ephemeral()
