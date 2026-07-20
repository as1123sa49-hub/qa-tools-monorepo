import logging
import re

import easyocr

logger = logging.getLogger(__name__)

_SEQUEL_TAIL_RE = re.compile(r"^[2-9]\d*|^more|^plus|^deluxe|^max", re.I)
# JC search-results: provider chips sit above game cards; card title labels are lower.
LOBBY_SEARCH_LABEL_MIN_CY_FRAC = 0.58
LOBBY_POSTER_CLICK_MIN_CY_FRAC = 0.52
LOBBY_HEADER_MAX_CY = 200
LOBBY_PROVIDER_SAFE_Y_FRAC = 0.53
LOBBY_SEARCH_ROW_Y_TOLERANCE = 45
LOBBY_POSTER_OFFSET_MIN = 50.0
LOBBY_POSTER_OFFSET_MAX = 120.0
_PROVIDER_NAME_BLOCKLIST = (
    "fa chai",
    "jdb",
    "jili",
    "pg soft",
    "pragmatic",
    "sexy",
    "combo",
    "feature",
    "slot",
    "fish",
    "arcade",
    "live",
    "egame",
    "promo",
    "search",
    "deposit",
    "withdraw",
    "balance",
    "casino",
    "provider",
)


def _normalize_label(text: str) -> str:
    norm = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", norm).strip()


def score_lobby_label_match(keyword: str, ocr_text: str) -> int:
    """Score OCR card title against games.yaml search_keyword (exact > sequel-safe)."""
    kw = _normalize_label(keyword)
    text = _normalize_label(ocr_text)
    if not kw or not text:
        return 0
    if text == kw:
        return 1000 + len(kw)
    if text.startswith(kw):
        tail = text[len(kw) :].strip()
        if not tail:
            return 1000 + len(kw)
        if _SEQUEL_TAIL_RE.match(tail):
            return 0
    # OCR often splits titles ("Chinese New" without "Year"); accept safe prefix only.
    if kw.startswith(text):
        words = text.split()
        if len(words) >= 2 and len(text) >= max(8, int(len(kw) * 0.45)):
            return 500 + len(text)
    return 0


def lobby_search_label_y_ok(cy: float, viewport_height: float | None) -> bool:
    """Reject header and provider-chip rows; keep game-card title labels."""
    if cy <= LOBBY_HEADER_MAX_CY:
        return False
    if viewport_height and viewport_height > 0:
        return cy >= LOBBY_SEARCH_LABEL_MIN_CY_FRAC * viewport_height
    return cy >= 380


def _is_provider_or_nav_label(text: str) -> bool:
    norm = _normalize_label(text)
    if len(norm) < 3:
        return True
    return any(block in norm for block in _PROVIDER_NAME_BLOCKLIST)


def count_cards_on_label_row(
    row_hits: list[tuple[float, float, str]],
    target_cy: float,
    *,
    y_tolerance: float = LOBBY_SEARCH_ROW_Y_TOLERANCE,
) -> int:
    """Count game-card title rows sharing the same result row as the target label."""
    return sum(
        1
        for _cx, cy, text in row_hits
        if abs(cy - target_cy) <= y_tolerance and not _is_provider_or_nav_label(text)
    )


def poster_click_from_label_bbox(
    bbox: tuple[float, float, float, float],
    *,
    viewport_height: float,
    row_cols: int = 2,
) -> tuple[float, float]:
    """Map title OCR bbox to a poster click on the card image (above title, below providers)."""
    x_left, y_top, x_right, y_bottom = bbox
    cx = (x_left + x_right) / 2
    label_h = max(y_bottom - y_top, 8.0)
    mult = 2.0 if row_cols >= 3 else 2.5
    poster_offset = max(LOBBY_POSTER_OFFSET_MIN, min(LOBBY_POSTER_OFFSET_MAX, label_h * mult))
    provider_floor = viewport_height * LOBBY_PROVIDER_SAFE_Y_FRAC + 12
    poster_ceiling = y_top - 12
    click_y = y_top - poster_offset
    if poster_ceiling >= provider_floor:
        click_y = max(provider_floor, min(click_y, poster_ceiling))
    else:
        # Misread label in provider band: nudge into the card grid below chips.
        click_y = provider_floor + 36
    return cx, click_y


def lobby_poster_click_y_ok(cy: float, viewport_height: float) -> bool:
    """Reject provider-chip row clicks; poster body sits above card titles."""
    if viewport_height <= 0:
        return cy >= 380
    return cy >= LOBBY_POSTER_CLICK_MIN_CY_FRAC * viewport_height


def should_replace_lobby_label_match(
    prev_score: float,
    prev_cy: float,
    prev_x: float,
    match_score: float,
    cy: float,
    cx: float,
) -> bool:
    """Prefer higher score; same row → leftmost card; else lowest title (largest cy)."""
    if match_score > prev_score:
        return True
    if match_score < prev_score:
        return False
    if abs(cy - prev_cy) <= LOBBY_SEARCH_ROW_Y_TOLERANCE:
        return cx < prev_x
    if cy > prev_cy:
        return True
    if cy < prev_cy:
        return False
    return cx < prev_x


class UILocator:
    """通用 UI 定位器 (基於 EasyOCR)
    支援動態註冊遊戲目標，徹底移除 Hardcode。
    """

    def __init__(self, languages=["en"], gpu=False):
        logger.info("Initializing EasyOCR...")
        self.reader = easyocr.Reader(languages, gpu=gpu)
        self.coordinates = {}
        # {game_id: primary search_keyword}
        self.dynamic_targets = {}

    def register_game_target(self, game_id: str, keywords: list):
        """註冊要監控的遊戲關鍵字（primary keyword = search_keyword）。"""
        clean_keywords = [k.lower().strip() for k in keywords if k and str(k).strip()]
        if not clean_keywords:
            return
        self.dynamic_targets[game_id] = clean_keywords[0]
        logger.debug(f"Registered dynamic target [{game_id}]: {clean_keywords[0]}")

    def scan_context(self, screenshot_bytes, context="guest", dpr=1.0, viewport_height=None):
        """Scan a screenshot for anchors relevant to a specific context.
        context: 'guest', 'lobby', 'login', 'all'
        dpr: 轉換係數。預設 1.0。若 dpr > 1，會在做 offset 操作"前"將物理座標轉為 CSS 座標。
        viewport_height: CSS viewport height for search-result label Y filtering.
        """
        results = self.reader.readtext(screenshot_bytes)

        if dpr > 1.01:
            scaled_results = []
            for bbox, text, prob in results:
                scaled_bbox = [[x / dpr, y / dpr] for [x, y] in bbox]
                scaled_results.append((scaled_bbox, text, prob))
            results = scaled_results

        found_coords = {}
        card_row_hits: list[tuple[float, float, str]] = []

        for bbox, text, prob in results:
            clean_text = text.lower().strip()
            logger.debug(f"OCR Seen: [{clean_text}]")

            if len(clean_text) < 2:
                continue

            # =========================================
            # 1. GUEST / ENTRY MODAL (固定錨點)
            # =========================================
            if context in ["guest", "all"]:
                cb_keywords = [
                    "have read and agree", "acknowledge and", "confirm:", "acknowledge", "i agree",
                    "read and agr", "agroo", "acknow", "onfirm", "thave read", "acknowledgc", "read and"
                ]
                if any(x in clean_text for x in cb_keywords):
                    tl, bl = bbox[0], bbox[3]
                    text_mid_y = (tl[1] + bl[1]) / 2
                    text_left_x = tl[0]
                    found_coords["checkbox"] = (float(text_left_x - 50), float(text_mid_y))
                    found_coords["checkbox_label"] = (float(text_left_x + 60), float(text_mid_y))
                    logger.info(f"Found Checkbox Anchor: '{clean_text}' at {found_coords['checkbox']}")

                agree_keywords = [
                    "agree all", "agree", "start", "ok", "confirm", "close",
                    "connrm", "onfirm", "agroo", "agree or"
                ]
                if any(x in clean_text for x in agree_keywords):
                    if any(bad in clean_text for bad in ["provider", "support", "about", "games", "all rights"]):
                        continue

                    tl, br = bbox[0], bbox[2]
                    center_x, center_y = (tl[0] + br[0]) / 2, (tl[1] + br[1]) / 2

                    if 100 < center_x < 1180:
                        found_coords["agree_button"] = (float(center_x), float(center_y))
                        logger.info(f"Found Agree Button: '{clean_text}' at {found_coords['agree_button']}")

            # =========================================
            # 2. LOBBY (Logged-in)
            # =========================================
            if context in ["lobby", "all"]:
                if "deposit" in clean_text:
                    tl, br = bbox[0], bbox[2]
                    found_coords["deposit_button"] = (
                        float((tl[0] + br[0]) / 2),
                        float((tl[1] + br[1]) / 2),
                    )

                if "withdraw" in clean_text:
                    tl, br = bbox[0], bbox[2]
                    found_coords["withdraw_button"] = (
                        float((tl[0] + br[0]) / 2),
                        float((tl[1] + br[1]) / 2),
                    )

                if "search" in clean_text:
                    tl, br = bbox[0], bbox[2]
                    if (tl[1] + br[1]) / 2 < 250:
                        found_coords["search_overlay_input"] = (
                            float((tl[0] + br[0]) / 2),
                            float((tl[1] + br[1]) / 2),
                        )
                    else:
                        found_coords["search_bar_placeholder"] = (
                            float((tl[0] + br[0]) / 2),
                            float((tl[1] + br[1]) / 2),
                        )

                for game_id, keyword in self.dynamic_targets.items():
                    match_score = score_lobby_label_match(keyword, text)
                    if match_score <= 0:
                        continue
                    tl, br = bbox[0], bbox[2]
                    cx, cy = (tl[0] + br[0]) / 2, (tl[1] + br[1]) / 2

                    if not lobby_search_label_y_ok(cy, viewport_height):
                        continue

                    if not _is_provider_or_nav_label(text):
                        card_row_hits.append((float(cx), float(cy), text))

                    key = f"{game_id}_label"
                    prev_score = found_coords.get(f"{key}_score", 0)
                    prev_cy = found_coords.get(f"{key}_y", -1.0)
                    prev_x = found_coords.get(f"{key}_x", float("inf"))
                    if should_replace_lobby_label_match(
                        prev_score, prev_cy, prev_x, match_score, cy, cx
                    ):
                        found_coords[key] = (float(cx), float(cy))
                        found_coords[f"{key}_bbox"] = (
                            float(tl[0]),
                            float(tl[1]),
                            float(br[0]),
                            float(br[1]),
                        )
                        found_coords[f"{key}_score"] = match_score
                        found_coords[f"{key}_y"] = float(cy)
                        found_coords[f"{key}_x"] = float(cx)
                        row_cols = count_cards_on_label_row(card_row_hits, cy)
                        found_coords[f"{game_id}_row_cols"] = max(row_cols, 1)
                        logger.info(
                            f"🎯 Dynamic Match [{game_id}]: '{text}' at ({cx:.0f}, {cy:.0f}) "
                            f"[score={match_score}, row_cols={row_cols}]"
                        )

            # =========================================
            # 3. LOGIN MODAL (固定錨點)
            # =========================================
            if context in ["login", "all"]:
                if "phone" in clean_text:
                    tl, br = bbox[0], bbox[2]
                    found_coords["login_phone_field"] = (
                        float((tl[0] + br[0]) / 2),
                        float((tl[1] + br[1]) / 2),
                    )

                if "password" in clean_text and clean_text != "login by password":
                    tl, br = bbox[0], bbox[2]
                    found_coords["login_password_field"] = (
                        float((tl[0] + br[0]) / 2),
                        float((tl[1] + br[1]) / 2),
                    )

                if "login" in clean_text:
                    tl, br = bbox[0], bbox[2]
                    cx, cy = (tl[0] + br[0]) / 2, (tl[1] + br[1]) / 2
                    if cy > 200:
                        found_coords["login_submit_button"] = (float(cx), float(cy))
                    elif cy < 100:
                        found_coords["header_login_button"] = (float(cx), float(cy))

                if "login by password" in clean_text:
                    tl, br = bbox[0], bbox[2]
                    found_coords["switch_to_password_btn"] = (
                        float((tl[0] + br[0]) / 2),
                        float((tl[1] + br[1]) / 2),
                    )

        found_coords = {
            k: v
            for k, v in found_coords.items()
            if not k.endswith("_score") and not k.endswith("_x") and not k.endswith("_y")
        }
        self.coordinates.update(found_coords)
        return found_coords

    def get_coordinate(self, name):
        """Get coordinate by name."""
        return self.coordinates.get(name)

    def clear(self):
        """Reset coordinates mapping."""
        self.coordinates = {}
