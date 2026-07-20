"""COMBO internal portal lobby (games-dev.comboburst.com) navigation.

Mirrors qa-tools-monorepo/tools/l10n-capture/lib/lobby-flow.js for betting tests.
JC platform (jackpot-uat.combo.ph) remains in game_utils.navigate_to_game + conftest.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from urllib.parse import urlparse

from core.balance_audit import capture_lobby_wallet_b0
from core.env_config import ENTRY_MODE_COMBOBURST_PORTAL
from core.game_frame_utils import iter_game_contexts, unity_canvas_ready
from core.game_utils import _COMBOBURST_PORTAL_KEY, wait_for_unity_game_load
from core.layout_detect import _LAYOUT_PROBE_HOST_KEY

logger = logging.getLogger(__name__)

DEFAULT_LOBBY_URL = "https://games-dev.comboburst.com/home/index.html"
DEFAULT_PORTAL_ENV = "COMBO_UAT"
DEFAULT_LANG_LABEL = "英文"
DEFAULT_GAME_HOST = "games-uat.comboburst.com"
LOBBY_TIMEOUT_MS = 45_000
GAME_LOAD_TIMEOUT_MS = 90_000
LOBBY_READY_TIMEOUT_MS = 45_000

_ENV_BUTTON_PATTERNS = [
    "Switch environment",
    re.compile(r"switch environment", re.I),
    "切換環境",
    re.compile(r"切换环境"),
]

_LANG_BUTTON_PATTERNS = [
    "Change language",
    re.compile(r"change language", re.I),
    "切換語言",
    re.compile(r"切换语言"),
]


def _get_current_portal_env(page) -> str | None:
    try:
        btn = page.locator("button, [role='button']").filter(
            has_text=re.compile(r"COMBO_", re.I)
        ).first
        if btn.is_visible(timeout=2_000):
            text = btn.inner_text(timeout=2_000).strip()
            match = re.search(r"COMBO_\w+", text, re.I)
            if match:
                return match.group(0).upper()
    except Exception:
        pass
    return None


def _click_first_visible(page, getters, action: str, timeout_ms: int = 10_000) -> None:
    last_error = None
    for get_locator in getters:
        try:
            loc = get_locator().first
            loc.wait_for(state="visible", timeout=3_000)
            loc.click(timeout=timeout_ms)
            return
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"{action} 失敗：{last_error}")


def _wait_for_lobby_ready(page, timeout_ms: int = LOBBY_READY_TIMEOUT_MS) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            if _get_current_portal_env(page):
                logger.info("✅ Comboburst lobby ready (env dropdown visible).")
                return
        except Exception:
            pass
        for pattern in _ENV_BUTTON_PATTERNS:
            try:
                if page.get_by_role("button", name=pattern).first.is_visible(timeout=400):
                    logger.info("✅ Comboburst lobby ready (env switch visible).")
                    return
            except Exception:
                pass
        try:
            search = page.locator(
                'input[type="search"], input[placeholder*="Search"], input[placeholder*="搜"]'
            ).first
            if search.is_visible(timeout=400):
                logger.info("✅ Comboburst lobby ready (search visible).")
                return
        except Exception:
            pass
        time.sleep(0.5)

    _raise_login_hint(page)


def _raise_login_hint(page) -> None:
    url = page.url
    body_snippet = ""
    try:
        body_snippet = page.locator("body").inner_text(timeout=2_000)[:300]
    except Exception:
        pass
    if any(k in body_snippet.lower() for k in ("login", "sign in", "登入", "登录")):
        raise RuntimeError(
            "Comboburst 大廳需要登入。請先執行："
            ".\\.venv\\Scripts\\python.exe tools\\save_comboburst_auth.py"
        )
    raise RuntimeError(
        "大廳未就緒：找不到「Switch environment / 切換環境」或搜尋欄。"
        "若未登入請執行 tools/save_comboburst_auth.py"
        f"（目前 URL: {url}）"
    )


def _select_environment(page, portal_env: str) -> None:
    _wait_for_lobby_ready(page)

    current = _get_current_portal_env(page)
    if current and current.upper() == portal_env.upper():
        logger.info(f"✅ Portal environment already {portal_env}")
        return

    env_openers = [
        lambda: page.locator("button, [role='button']").filter(
            has_text=re.compile(r"COMBO_", re.I)
        ),
        lambda: page.get_by_role("button", name=re.compile(r"COMBO_|switch environment", re.I)),
    ]
    env_openers.extend(
        lambda pattern=pattern: page.get_by_role("button", name=pattern)
        for pattern in _ENV_BUTTON_PATTERNS
    )
    env_openers.extend(
        [
            lambda: page.get_by_text("Switch environment", exact=False),
            lambda: page.get_by_text("切換環境", exact=False),
        ]
    )
    _click_first_visible(page, env_openers, "開啟環境選單")
    time.sleep(0.5)

    page.get_by_role("menuitem", name=portal_env).click(timeout=15_000)
    time.sleep(1.0)

    selected = _get_current_portal_env(page)
    if selected and selected.upper() != portal_env.upper():
        raise RuntimeError(f"環境切換後仍為 {selected}，預期 {portal_env}")
    logger.info(f"✅ Portal environment selected: {portal_env}")


def _select_language(page, portal_label: str) -> None:
    try:
        lang_btn = page.locator("button, [role='button']").filter(
            has_text=re.compile(rf"^{re.escape(portal_label)}$|{portal_label}", re.I)
        ).first
        if lang_btn.is_visible(timeout=1_500):
            logger.info(f"✅ Portal language already {portal_label}")
            return
    except Exception:
        pass

    lang_openers = [
        lambda: page.get_by_role("button", name=pattern)
        for pattern in _LANG_BUTTON_PATTERNS
    ]
    lang_openers.append(
        lambda: page.locator('header button, [class*="header"] button, nav button').filter(
            has_text=re.compile(r"文|语|English|語言|Language", re.I)
        )
    )

    try:
        _click_first_visible(page, lang_openers, "開啟語系選單", timeout_ms=8_000)
    except RuntimeError:
        logger.warning("語系按鈕未找到，可能已是目標語系，繼續…")
        return

    time.sleep(0.4)

    lang_pickers = [
        lambda: page.get_by_role("menuitem", name=portal_label, exact=True),
        lambda: page.get_by_role("button", name=portal_label, exact=True),
        lambda: page.get_by_text(portal_label, exact=True),
    ]
    try:
        _click_first_visible(page, lang_pickers, f"選擇語系 {portal_label}", timeout_ms=8_000)
    except RuntimeError as exc:
        logger.warning(f"語系選項未點擊（{exc}），繼續…")
        return

    time.sleep(0.8)
    logger.info(f"✅ Portal language selected: {portal_label}")


def _prepare_lobby(page, comboburst_cfg: dict) -> None:
    lobby_url = comboburst_cfg.get("lobby_url", DEFAULT_LOBBY_URL)
    portal_env = comboburst_cfg.get("portal_env", DEFAULT_PORTAL_ENV)
    lang_label = comboburst_cfg.get("lang_label", DEFAULT_LANG_LABEL)

    logger.info(f"🌐 Comboburst lobby: {lobby_url} → {portal_env} / {lang_label}")
    page.goto(lobby_url, wait_until="domcontentloaded", timeout=LOBBY_TIMEOUT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except Exception:
        logger.debug("networkidle timeout; continuing with domcontentloaded")
    time.sleep(2.0)
    _select_environment(page, portal_env)
    _select_language(page, lang_label)


def resolve_portal_click_id(game_conf: dict) -> str | None:
    """Optional Slot id (e.g. Slot002) used to click the game tile after name search."""
    value = game_conf.get("portal_slot_id")
    if value and str(value).strip():
        return str(value).strip()
    return None


def _exclude_form_fields(page, locator):
    """Ignore text nodes inside search boxes and other inputs."""
    return locator.filter(
        has_not=page.locator("input, textarea, [contenteditable='true']")
    )


def _click_locator(locator, *, timeout_ms: int = 20_000) -> None:
    """Click element; if it is small text, prefer the poster image in the same card."""
    locator.wait_for(state="visible", timeout=8_000)
    try:
        img = locator.locator(
            "xpath=ancestor::li[1]//img | ancestor::article[1]//img"
            " | ancestor::*[contains(@class,'card')][1]//img"
        ).first
        if img.is_visible(timeout=1_500):
            img.click(timeout=timeout_ms)
            return
    except Exception:
        pass
    locator.click(timeout=timeout_ms)


def _click_game_card_after_search(page, query: str, portal_slot_id: str | None) -> str:
    """Click the filtered game tile (poster image preferred). Returns strategy name."""
    query_variants = _expand_search_query_variants(query)
    last_error: Exception | None = None

    strategies: list[tuple[str, Callable[[], None]]] = []

    if portal_slot_id:
        slot_pattern = re.compile(re.escape(portal_slot_id), re.I)

        def _click_slot_badge():
            tile = page.locator("li, article").filter(has_text=slot_pattern).first
            tile.wait_for(state="visible", timeout=8_000)
            img = tile.locator("img").first
            if img.is_visible(timeout=2_000):
                img.click(timeout=20_000)
            else:
                _exclude_form_fields(page, page.get_by_text(portal_slot_id, exact=False)).first.click(
                    timeout=20_000
                )

        strategies.append((f"portal_slot_id={portal_slot_id!r}", _click_slot_badge))

    def _click_single_search_result():
        cards = page.locator("li, article").filter(has=page.locator("img"))
        if cards.count() != 1:
            raise RuntimeError(f"expected 1 search result, found {cards.count()}")
        cards.first.locator("img").first.click(timeout=20_000)

    strategies.append(("single_search_result_image", _click_single_search_result))

    for variant in query_variants:
        query_pattern = re.compile(re.escape(variant), re.I)

        def _click_card_image(q=variant, pattern=query_pattern):
            card = (
                page.locator("li, article")
                .filter(has_text=pattern)
                .filter(has=page.locator("img"))
                .first
            )
            card.wait_for(state="visible", timeout=8_000)
            card.locator("img").first.click(timeout=20_000)

        strategies.append((f"card_image for {variant!r}", _click_card_image))

        def _click_query_text(q=variant):
            text_el = _exclude_form_fields(page, page.get_by_text(q, exact=False)).first
            _click_locator(text_el)

        strategies.append((f"text_ancestor for {variant!r}", _click_query_text))

    def _click_normalized_match():
        cards = page.locator("li, article").filter(has=page.locator("img"))
        target_keys = {_normalize_for_card_match(v) for v in query_variants}
        for idx in range(cards.count()):
            card = cards.nth(idx)
            try:
                card_text = card.inner_text(timeout=2_000)
            except Exception:
                continue
            card_key = _normalize_for_card_match(card_text)
            if any(key in card_key or card_key in key for key in target_keys if key):
                card.locator("img").first.click(timeout=20_000)
                return
        raise RuntimeError(f"no normalized card match for {query_variants!r}")

    strategies.append((f"normalized_match for {query!r}", _click_normalized_match))

    for strategy_name, action in strategies:
        try:
            action()
            return strategy_name
        except Exception as exc:
            last_error = exc
            logger.debug("Portal card click %s failed: %s", strategy_name, exc)
            continue

    raise RuntimeError(
        f"無法點擊遊戲卡片（搜尋={query!r}, slot={portal_slot_id!r}）：{last_error}"
    )


def _search_and_enter_game(page, game_conf: dict) -> None:
    """Search comboburst lobby by game name, then click the matching tile (image / Slot badge)."""
    queries = resolve_portal_search_queries(game_conf)
    portal_slot_id = resolve_portal_click_id(game_conf)

    search = page.locator(
        'input[type="search"], input[placeholder*="搜"], input[placeholder*="Search"], input[type="text"]'
    ).first
    search.wait_for(state="visible", timeout=20_000)

    last_error: Exception | None = None
    for query in queries:
        search.click(timeout=5_000)
        search.fill("")
        search.fill(query)
        time.sleep(2.0)
        try:
            strategy = _click_game_card_after_search(page, query, portal_slot_id)
            logger.info(f"🎯 Clicked game card ({strategy}) after search: {query!r}")
            return
        except Exception as exc:
            last_error = exc
            logger.debug("Portal search %r failed: %s", query, exc)

    raise RuntimeError(
        f"無法點擊遊戲卡片（queries={queries!r}, slot={portal_slot_id!r}）：{last_error}"
    )


def _wait_for_game_entry(page, expected_host: str, timeout_ms: int = GAME_LOAD_TIMEOUT_MS):
    """Wait until game runs on expected host, in iframe, or as embedded canvas overlay."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if urlparse(page.url).hostname == expected_host:
            logger.info(f"✅ Game host matched: {expected_host}")
            return page

        for frame in page.frames:
            if urlparse(frame.url).hostname == expected_host:
                logger.info(f"✅ Game host matched in frame: {expected_host}")
                return frame

        try:
            canvas = page.locator("#unity-canvas, canvas").first
            if canvas.is_visible(timeout=500):
                logger.info("✅ Game entry: Unity canvas visible on portal page")
                return page
        except Exception:
            pass

        try:
            if page.locator("text=/v\\.\\d+\\.\\d+/i").first.is_visible(timeout=400):
                logger.info("✅ Game entry: loading screen detected")
                return page
        except Exception:
            pass

        time.sleep(0.5)

    actual = urlparse(page.url).hostname
    raise RuntimeError(
        f"遊戲未進入：預期 {expected_host} 或內嵌 canvas，"
        f"實際 URL host={actual}（{page.url}）"
    )


def _wait_for_unity_canvas(
    page,
    expected_host: str | None = None,
    timeout_ms: int = GAME_LOAD_TIMEOUT_MS,
) -> None:
    """Wait for Unity canvas using Playwright frame locators (works for cross-origin iframes)."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        for ctx in iter_game_contexts(page, expected_host):
            if unity_canvas_ready(ctx):
                ctx_url = getattr(ctx, "url", page.url)
                logger.info(f"✅ Unity canvas ready in {ctx_url}")
                time.sleep(2)
                return
        time.sleep(0.5)

    frame_urls = [f.url for f in page.frames]
    raise TimeoutError(
        f"Unity canvas not ready within {timeout_ms}ms "
        f"(page={page.url}, frames={frame_urls})"
    )


def _normalize_search_text(value: str) -> str:
    return (
        value.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .strip()
    )


def _expand_search_query_variants(query: str) -> list[str]:
    """Apostrophe / underscore variants for lobby search and card matching."""
    variants: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        normalized = _normalize_search_text(value).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            variants.append(normalized)

    _add(query)
    curly = query.replace("'", "\u2019")
    straight = query.replace("\u2019", "'").replace("\u2018", "'")
    _add(curly)
    _add(straight)
    _add(re.sub(r"[''\u2018\u2019`]", "", query))
    _add(re.sub(r"[''\u2018\u2019`]", " ", query))
    if " " in query:
        _add(query.replace(" ", "_"))
    if "_" in query:
        _add(query.replace("_", " "))
    _add(re.sub(r"[\s_]+", "", query))
    return variants


def _normalize_for_card_match(value: str) -> str:
    lowered = value.lower()
    for ch in "'\u2018\u2019`":
        lowered = lowered.replace(ch, "")
    return re.sub(r"[\s_]+", "", lowered)


def resolve_portal_search_queries(game_conf: dict) -> list[str]:
    """Ordered lobby search strings: slot id → keyword → name → aliases (with variants)."""
    seen: set[str] = set()
    queries: list[str] = []

    def _add(value: str) -> None:
        for variant in _expand_search_query_variants(str(value)):
            key = variant.lower()
            if key not in seen:
                seen.add(key)
                queries.append(variant)

    slot_id = game_conf.get("portal_slot_id")
    if slot_id:
        _add(str(slot_id))
    for key in ("search_keyword", "name"):
        value = game_conf.get(key)
        if value:
            _add(str(value))
    for alias in game_conf.get("search_aliases") or []:
        _add(str(alias))
    if not queries:
        raise ValueError(
            f"Game '{game_conf.get('name', game_conf.get('id'))}' missing search_keyword or name "
            "(required for comboburst_portal entry_mode)"
        )
    return queries


def resolve_portal_search_query(game_conf: dict) -> str:
    """Lobby search text: first entry from resolve_portal_search_queries."""
    return resolve_portal_search_queries(game_conf)[0]


def resolve_portal_slot_id(game_conf: dict) -> str:
    """Deprecated alias — use resolve_portal_search_query."""
    return resolve_portal_search_query(game_conf)


def navigate_via_comboburst_portal(
    page,
    game_conf: dict,
    comboburst_cfg: dict,
    hybrid_locator,
    artifact_handler,
    global_config: dict | None = None,
) -> bool:
    """Open comboburst dev lobby, switch to UAT + English, search game name, wait for Unity."""
    try:
        search_query = resolve_portal_search_query(game_conf)
        expected_host = comboburst_cfg.get("game_host", DEFAULT_GAME_HOST)

        _prepare_lobby(page, comboburst_cfg)
        artifact_handler.capture(page, "comboburst_lobby_ready", category="setup", attach_to_allure=True)
        capture_lobby_wallet_b0(
            page,
            hybrid_locator,
            global_config or {},
            ENTRY_MODE_COMBOBURST_PORTAL,
            game_conf,
        )

        _search_and_enter_game(page, game_conf)
        _wait_for_game_entry(page, expected_host)
        _wait_for_unity_canvas(page, expected_host=expected_host)
        game_conf[_LAYOUT_PROBE_HOST_KEY] = expected_host
        game_conf[_COMBOBURST_PORTAL_KEY] = True
        safe_name = re.sub(r"[^\w.-]+", "_", search_query)[:40]
        artifact_handler.capture(page, f"comboburst_entered_{safe_name}", category="setup", attach_to_allure=True)

        if not wait_for_unity_game_load(page, hybrid_locator, artifact_handler, game_conf):
            return False

        logger.info(f"✅ Entered {search_query!r} via comboburst portal ({expected_host})")
        return True
    except Exception as exc:
        logger.error(f"❌ Comboburst portal navigation failed: {exc}")
        artifact_handler.capture(page, "fail_comboburst_nav", category="failures", attach_to_allure=True)
        return False
