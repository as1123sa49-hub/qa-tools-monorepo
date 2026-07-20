"""Lobby ↔ in-game wallet OCR and cross-venue balance audit.

JC platform (jackpot-uat.combo.ph): header pill + left sidebar Balance card.
COMBO portal (games-dev.comboburst.com): top-right wallet bar.
"""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass

from PIL import Image

from core.env_config import (
    ENTRY_MODE_COMBOBURST_PORTAL,
    ENTRY_MODE_JC_LOBBY,
    get_client_env_config,
    get_comboburst_config,
)
from core.game_utils import (
    _ocr_results_in_fraction_region,
    collapse_fc_side_panel_after_balance_miss,
    dismiss_fc_side_panel_if_open,
    footer_ocr_regions_to_try,
    portrait_footer_region,
    resolve_footer_ocr_region,
    use_fc_portrait_footer_strip,
    use_jdb_portrait_footer_strip,
    _game_config_is_jdb,
)
from core.game_frame_utils import iter_game_contexts, unity_canvas_ready

logger = logging.getLogger(__name__)

PRIMARY_BALANCE_MIN = 1000.0
WALLET_BALANCE_MIN = 100.0
DEFAULT_CROSS_VENUE_TOLERANCE = 1.0
DEFAULT_MIN_BET_DELTA = 2.5
# When TOTAL BETS OCR is missing/zero, still ack a real single-spin deduction.
UNKNOWN_BET_DELTA_FLOOR = 0.5
# JDB often uses 0.1 stakes; keep a lower floor only for that provider.
JDB_UNKNOWN_BET_DELTA_FLOOR = 0.05
# JDB footer amounts are prefixed with ₱ / P; version strings (v1.24.0) are not.
_JDB_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:₱|PHP|(?<![A-Za-z])P)\s*"
    r"(\d{1,3}(?:,\d{3})*\.\d{1,3}|\d+\.\d{1,3})",
    re.I,
)
_JDB_VERSION_TEXT_RE = re.compile(
    r"(?:\bv\.?\d|\bver\.|/[\da-f]{5,}|\bv\d+\.\d+)",
    re.I,
)
_JDB_LONE_CURRENCY_RE = re.compile(r"^(?:₱|P|PHP)$", re.I)
SPIN_WALLET_FORMULA_TOLERANCE = 0.25
# Flat balance (OCR noise) — not the same as formula tolerance; blocks false
# ack when B0≈B1, bet≤0.25, win≈0.
SPIN_BALANCE_UNCHANGED_EPS = 0.05
# Reject WIN OCR that is implausibly large vs wallet / bet (not absolute trust).
SPIN_WALLET_MAX_WIN_VS_B0_FRAC = 0.25
SPIN_WALLET_MAX_WIN_VS_BET = 80.0
LOBBY_WALLET_SYNC_TIMEOUT_SEC = 25.0
LOBBY_WALLET_SYNC_POLL_SEC = 2.0

# JC: top-right header pill (₱ 10,104.30)
JC_LOBBY_WALLET_HEADER_REGION = {
    "x_start": 0.80,
    "x_end": 0.99,
    "y_start": 0.02,
    "y_end": 0.12,
}
# JC: left sidebar Balance card
JC_LOBBY_WALLET_SIDEBAR_REGION = {
    "x_start": 0.02,
    "x_end": 0.24,
    "y_start": 0.13,
    "y_end": 0.32,
}
# COMBO portal: wallet amount OCR (left part of header bar, excludes refresh icon)
COMBO_LOBBY_WALLET_REGION = {
    "x_start": 0.66,
    "x_end": 0.90,
    "y_start": 0.0,
    "y_end": 0.10,
}
# COMBO portal: circular ↻ refresh beside "(PHP)"
COMBO_LOBBY_WALLET_REFRESH_REGION = {
    "x_start": 0.895,
    "x_end": 0.928,
    "y_start": 0.018,
    "y_end": 0.072,
}
# JC header pill: ↻ between balance and yellow wallet button
JC_LOBBY_WALLET_HEADER_REFRESH_REGION = {
    "x_start": 0.855,
    "x_end": 0.895,
    "y_start": 0.038,
    "y_end": 0.088,
}
# JC sidebar Balance card: ↻ right of ₱ amount
JC_LOBBY_WALLET_SIDEBAR_REFRESH_REGION = {
    "x_start": 0.185,
    "x_end": 0.235,
    "y_start": 0.188,
    "y_end": 0.248,
}

_WALLET_AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{1,3}|\d+\.\d{1,3})")
# Integer (no-decimals) amount tokens — comma-grouped (≥1,000) or a long digit run
# (≥4 digits). NARROW use only: FC balance fallback validated against lobby B0.
# Never fed into the generic amount parsers (would let TxnId / bet / win integers slip).
_FC_INTEGER_AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{4,})(?![\d.,])")
# Permissive integer token (incl. small values like 0 / 1) for the integer-credit
# footer UI. NARROW use only: FC-SLOT-020 (Robin Hood) bet/win, assigned by label
# column. Never fed into the generic amount parsers.
_FC_INTEGER_TOKEN_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})*|\d+)(?![\d.,])")
# OCR period→comma: 10,007,352,02 — not US thousands+period like 27,399.995
_COMMA_DECIMAL_TAIL_RE = re.compile(r"(\d{1,3}(?:,\d{3})*),(\d{2})(?![.\d])")
# OCR may use dots as thousands: 10.007.381.02 → 10,007,381.02
_DOT_GROUPED_AMOUNT_RE = re.compile(r"\b(\d{1,3}(?:\.\d{3})+\.\d{1,3})\b")
# Dirty OCR: spaces inside amount tokens (e.g. "10, 007 , 422 . 03")
# Require real whitespace — do not match clean "422.83".
_SPACED_AMOUNT_HINT_RE = re.compile(
    r"(?:\d[\d,]*\s+[\d,]|\d\s+[.,]\s*\d|\d[.,]\s+\d)"
)
_FC_RECONCILE_MIN_SUFFIX_DIGITS = 6
# Truncated OCR recovery: allow one-spin drift (bet/win), reject unrelated fragments.
_FC_RECONCILE_MAX_ABS_DELTA = 15.0
_FC_FOOTER_WIN_LABEL_RE = re.compile(r"\bwin\b", re.I)
FC_FOOTER_ROW_Y_TOLERANCE_PX = 28.0
FC_FOOTER_COLUMN_X_TOLERANCE_FRAC = 0.14
FC_FOOTER_UPSCALE_FACTOR = 2

_AUDIT_B0_LOBBY_KEY = "_audit_lobby_b0"
_AUDIT_B1_INGAME_KEY = "_audit_in_game_b1"
_AUDIT_CONSOLE_SUMMARY_KEY = "_audit_console_summary"
_AUDIT_FC_BALANCE_X_FRAC_KEY = "_audit_fc_balance_x_frac"
_AUDIT_FC_VALUE_ROW_Y_FRAC_KEY = "_audit_fc_value_row_y_frac"
_AUDIT_FC_TOTAL_BETS_KEY = "_audit_fc_total_bets"


@dataclass(frozen=True)
class FcFooterStrip:
    balance: float | None
    win: float | None
    total_bets: float | None
    balance_x_frac: float | None = None
    value_row_y_frac: float | None = None


@dataclass(frozen=True)
class JdbFooterStrip:
    """JDB portrait strip: icon-only columns Balance | Bet | Win (left → right)."""

    balance: float | None
    bet: float | None
    win: float | None
    balance_x_frac: float | None = None
    value_row_y_frac: float | None = None


def audit_lobby_b0_key() -> str:
    return _AUDIT_B0_LOBBY_KEY


def audit_in_game_b1_key() -> str:
    return _AUDIT_B1_INGAME_KEY


def audit_console_summary_key() -> str:
    return _AUDIT_CONSOLE_SUMMARY_KEY


def audit_fc_total_bets_key() -> str:
    return _AUDIT_FC_TOTAL_BETS_KEY


def audit_fc_balance_x_frac_key() -> str:
    return _AUDIT_FC_BALANCE_X_FRAC_KEY


def audit_fc_value_row_y_frac_key() -> str:
    return _AUDIT_FC_VALUE_ROW_Y_FRAC_KEY


def _expand_dot_grouped_amounts(text: str) -> str:
    """Normalize dot-as-thousands OCR (10.007.381.02) to comma-free decimal form."""

    def _repl(match: re.Match) -> str:
        token = match.group(1)
        whole, cents = token.rsplit(".", 1)
        return f"{whole.replace('.', '')}.{cents}"

    return _DOT_GROUPED_AMOUNT_RE.sub(_repl, text)


def _normalize_amount_ocr_text(text: str) -> str:
    """Strip currency noise and OCR gaps inside amounts (e.g. '10, 007 , 422 . 03')."""
    cleaned = text.replace("₱", " ").replace("PHP", " ").replace("P ", " ")
    # Join digit/separator runs split by spaces: "0 . 00" → "0.00"
    cleaned = re.sub(r"(?<=[\d.,])\s+(?=[\d.,])", "", cleaned)
    return _expand_dot_grouped_amounts(cleaned)


def ocr_text_has_spaced_amount(text: str) -> bool:
    """True when OCR split digits/separators with spaces (dirty amount token)."""
    return bool(_SPACED_AMOUNT_HINT_RE.search(text or ""))


def footer_ocr_has_spaced_amount(footer_ocr) -> bool:
    return any(ocr_text_has_spaced_amount(res[1]) for res in (footer_ocr or []))


def parse_amounts_from_text(text: str) -> list[float]:
    """Extract monetary amounts from OCR text (requires .XX — avoids TxnId digit runs)."""
    cleaned = _normalize_amount_ocr_text(text)
    amounts: list[float] = []
    seen: set[float] = set()

    def _add(val: float, *, min_value: float = WALLET_BALANCE_MIN) -> None:
        if val >= min_value and val not in seen:
            amounts.append(val)
            seen.add(val)

    for match in _WALLET_AMOUNT_RE.findall(cleaned):
        try:
            _add(float(match.replace(",", "")))
        except ValueError:
            continue
    for whole, cents in _COMMA_DECIMAL_TAIL_RE.findall(cleaned):
        if "." in whole:
            continue
        try:
            _add(float(whole.replace(",", "") + "." + cents))
        except ValueError:
            continue
    return amounts


def parse_footer_amounts_from_text(text: str) -> list[float]:
    """Footer amounts including win/bet (0.00–999.99)."""
    cleaned = _normalize_amount_ocr_text(text)
    amounts: list[float] = []
    seen: set[float] = set()

    def _add(val: float) -> None:
        if val < 0 or val in seen:
            return
        amounts.append(val)
        seen.add(val)

    for match in _WALLET_AMOUNT_RE.findall(cleaned):
        try:
            _add(float(match.replace(",", "")))
        except ValueError:
            continue
    for whole, cents in _COMMA_DECIMAL_TAIL_RE.findall(cleaned):
        if "." in whole:
            continue
        try:
            _add(float(whole.replace(",", "") + "." + cents))
        except ValueError:
            continue
    return amounts


def parse_jdb_currency_amounts_from_text(text: str) -> list[float]:
    """JDB amounts that carry a currency marker (₱ / P / PHP) — skips version tokens."""
    amounts: list[float] = []
    seen: set[float] = set()
    for match in _JDB_CURRENCY_AMOUNT_RE.finditer(text or ""):
        try:
            val = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if val < 0 or val in seen:
            continue
        amounts.append(val)
        seen.add(val)
    return amounts


def _collect_jdb_footer_amount_items(
    footer_ocr,
    dpr: float,
) -> list[tuple[float, float, float]]:
    """Collect (value, cx, cy); prefer currency-tagged OCR, ignore version lines."""
    currency_items: list[tuple[float, float, float]] = []
    fallback_items: list[tuple[float, float, float]] = []
    symbol_centers: list[tuple[float, float]] = []

    for res in footer_ocr or []:
        text = res[1] or ""
        cx, cy = _ocr_viewport_center(res, dpr)
        curr = parse_jdb_currency_amounts_from_text(text)
        if curr:
            for val in curr:
                currency_items.append((val, cx, cy))
            continue
        if _JDB_LONE_CURRENCY_RE.match(text.strip()):
            symbol_centers.append((cx, cy))
            continue
        if _JDB_VERSION_TEXT_RE.search(text):
            continue
        for val in parse_footer_amounts_from_text(text):
            fallback_items.append((val, cx, cy))

    # Symbol and digits split across boxes: P | 0.1
    if symbol_centers and fallback_items:
        for val, cx, cy in fallback_items:
            for sx, sy in symbol_centers:
                if abs(cy - sy) <= FC_FOOTER_ROW_Y_TOLERANCE_PX * 1.5 and 0 <= (cx - sx) <= 140:
                    currency_items.append((val, cx, cy))
                    break

    if currency_items:
        return currency_items
    return fallback_items


def _screenshot_dpr(screenshot_bytes: bytes, page) -> float:
    vp_w = page.viewport_size["width"]
    if not screenshot_bytes or not vp_w:
        return 1.0
    try:
        img = Image.open(io.BytesIO(screenshot_bytes))
        return img.width / vp_w
    except Exception:
        return 1.0


def _ocr_viewport_center(res, dpr: float) -> tuple[float, float]:
    cx = (res[0][0][0] + res[0][2][0]) / 2 / dpr
    cy = (res[0][0][1] + res[0][2][1]) / 2 / dpr
    return cx, cy


def _classify_fc_footer_label(text: str) -> str | None:
    norm = re.sub(r"[^\w\s]", " ", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    if "balance" in norm:
        return "balance"
    # OCR often mangled: TDTAL / TOTAI / TOTAL
    if "total bet" in norm or "tdtal" in norm or "totai" in norm:
        return "total_bets"
    if _FC_FOOTER_WIN_LABEL_RE.search(norm) and "balance" not in norm:
        return "win"
    return None


def _pick_footer_value_row(
    amounts: list[tuple[float, float, float]],
    labels: list[tuple[str, float, float]],
    *,
    value_row_y_frac: float | None,
    vp_h: float,
) -> list[tuple[float, float, float]]:
    if not amounts:
        return []
    if value_row_y_frac is not None:
        target_y = value_row_y_frac * vp_h
        row = [
            item
            for item in amounts
            if abs(item[2] - target_y) <= FC_FOOTER_ROW_Y_TOLERANCE_PX * 1.5
        ]
        if row:
            return row
    if labels:
        label_y = sum(cy for _, _, cy in labels) / len(labels)
        below = [item for item in amounts if item[2] > label_y + 6]
        if len(below) >= 2:
            amounts = below
    clusters: dict[int, list[tuple[float, float, float]]] = {}
    for val, cx, cy in amounts:
        bucket = round(cy / FC_FOOTER_ROW_Y_TOLERANCE_PX)
        clusters.setdefault(bucket, []).append((val, cx, cy))
    return max(clusters.values(), key=len)


def _best_reconciled_footer_balance(
    row: list[tuple[float, float, float]],
    lobby_b0: float,
) -> tuple[float, float, float] | None:
    """Pick row amount that reconcilies closest to lobby B0 (real B1, not B0 itself)."""
    best: tuple[float, float, float] | None = None
    best_dist: float | None = None
    for val, cx, cy in row:
        recovered = reconcile_fc_balance_with_b0(val, lobby_b0)
        if recovered is None:
            continue
        dist = abs(recovered - lobby_b0)
        if best is None or dist < best_dist:
            best = (recovered, cx, cy)
            best_dist = dist
    return best


def _assign_fc_footer_columns(
    row: list[tuple[float, float, float]],
    *,
    lobby_b0: float | None,
    balance_x_frac: float | None,
    vp_w: float,
    vp_h: float,
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    if not row:
        return None, None, None, None, None
    row = sorted(row, key=lambda item: item[1])
    balance_item = None
    source_item: tuple[float, float, float] | None = None
    if balance_x_frac is not None:
        target_x = balance_x_frac * vp_w
        source_item = min(row, key=lambda item: abs(item[1] - target_x))
        if lobby_b0 is not None:
            recovered = reconcile_fc_balance_with_b0(source_item[0], lobby_b0)
            if recovered is not None:
                balance_item = (recovered, source_item[1], source_item[2])
            else:
                # Bad x-anchor (e.g. WIN/BET column) → fall back to best B0 match.
                balance_item = _best_reconciled_footer_balance(row, lobby_b0)
                if balance_item is not None:
                    source_item = next(
                        (
                            item
                            for item in row
                            if abs(item[1] - balance_item[1]) < 1e-6
                            and abs(item[2] - balance_item[2]) < 1e-6
                        ),
                        source_item,
                    )
        else:
            balance_item = source_item
    elif lobby_b0 is not None:
        balance_item = _best_reconciled_footer_balance(row, lobby_b0)
        if balance_item is not None:
            source_item = next(
                (
                    item
                    for item in row
                    if abs(item[1] - balance_item[1]) < 1e-6
                    and abs(item[2] - balance_item[2]) < 1e-6
                ),
                None,
            )
    else:
        wallet = [item for item in row if item[0] >= PRIMARY_BALANCE_MIN]
        balance_item = wallet[0] if wallet else row[0]
        source_item = balance_item
    if balance_item is None:
        return None, None, None, None, None
    remaining = [
        item
        for item in row
        if source_item is None
        or abs(item[1] - source_item[1]) > 1e-6
        or abs(item[2] - source_item[2]) > 1e-6
        or abs(item[0] - source_item[0]) > 1e-6
    ]
    small = sorted(
        [item for item in remaining if item[0] < PRIMARY_BALANCE_MIN],
        key=lambda item: item[1],
    )
    if len(small) >= 2:
        win_val, bet_val = small[0][0], small[-1][0]
    elif len(small) == 1:
        win_val, bet_val = 0.0, small[0][0]
    else:
        win_val, bet_val = None, None
    # TOTAL BETS OCR often lands on 0.00 while a real stake (1.20 / 2.00 / …) is
    # still in the row — prefer rightmost nonzero small amount; never keep bet=0.
    if bet_val is not None and bet_val <= 0:
        nonzero = [item for item in small if item[0] > 0]
        if nonzero:
            bet_val = nonzero[-1][0]
            logger.debug(
                "FC footer bet rescued from nonzero column amount: %.2f", bet_val
            )
        else:
            bet_val = None
    balance_cx = balance_item[1]
    value_y = balance_item[2]
    return (
        balance_item[0],
        win_val,
        bet_val,
        balance_cx / vp_w if vp_w else None,
        value_y / vp_h if vp_h else None,
    )


def parse_fc_footer_from_ocr(
    footer_ocr,
    page,
    screenshot_bytes: bytes,
    *,
    lobby_b0: float | None = None,
    balance_x_frac: float | None = None,
    value_row_y_frac: float | None = None,
) -> FcFooterStrip | None:
    """Parse FC portrait footer: BALANCE | WIN | TOTAL BETS on one value row."""
    if not footer_ocr:
        return None
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    dpr = _screenshot_dpr(screenshot_bytes, page)
    labels: list[tuple[str, float, float]] = []
    amounts: list[tuple[float, float, float]] = []
    for res in footer_ocr:
        text = res[1]
        cx, cy = _ocr_viewport_center(res, dpr)
        label_kind = _classify_fc_footer_label(text)
        if label_kind:
            labels.append((label_kind, cx, cy))
        for val in parse_footer_amounts_from_text(text):
            amounts.append((val, cx, cy))
    row = _pick_footer_value_row(
        amounts,
        labels,
        value_row_y_frac=value_row_y_frac,
        vp_h=vp_h,
    )
    if len(row) < 2 and labels:
        for kind, lx, ly in labels:
            below = [
                item
                for item in amounts
                if item[2] > ly + 4 and abs(item[1] - lx) <= vp_w * FC_FOOTER_COLUMN_X_TOLERANCE_FRAC
            ]
            if below:
                row.append(min(below, key=lambda item: item[2]))
        row = sorted(set(row), key=lambda item: item[1])
    balance, win, bet, bx_frac, by_frac = _assign_fc_footer_columns(
        row,
        lobby_b0=lobby_b0,
        balance_x_frac=balance_x_frac,
        vp_w=vp_w,
        vp_h=vp_h,
    )
    if balance is None:
        return None
    if lobby_b0 is not None:
        recovered = reconcile_fc_balance_with_b0(balance, lobby_b0)
        if recovered is not None:
            balance = recovered
        elif balance_x_frac is None:
            tol = lobby_balance_match_tolerance(lobby_b0)
            if abs(balance - lobby_b0) > tol:
                logger.debug(
                    "FC footer balance %.2f rejected (lobby B0=%.2f, tol=%.2f)",
                    balance,
                    lobby_b0,
                    tol,
                )
                return None
        elif not is_plausible_ingame_balance(
            balance,
            lobby_b0,
            min_bet=resolve_spin_min_bet(None),
        ):
            logger.debug(
                "FC footer balance %.2f rejected as fragment (lobby B0=%.2f)",
                balance,
                lobby_b0,
            )
            return None
    return FcFooterStrip(
        balance=balance,
        win=win,
        total_bets=bet,
        balance_x_frac=bx_frac,
        value_row_y_frac=by_frac if by_frac else (row[0][2] / vp_h if row and vp_h else None),
    )


def _fc_integer_balance_candidates(
    footer_ocr,
    page,
    screenshot_bytes: bytes,
) -> list[tuple[float, float, float]]:
    """Integer (no-decimal) amount tokens with viewport centers — B0 fallback only."""
    if not footer_ocr:
        return []
    dpr = _screenshot_dpr(screenshot_bytes, page)
    items: list[tuple[float, float, float]] = []
    seen: set[tuple[float, float, float]] = set()
    for res in footer_ocr:
        cleaned = _normalize_amount_ocr_text(res[1] or "")
        cx, cy = _ocr_viewport_center(res, dpr)
        for match in _FC_INTEGER_AMOUNT_RE.findall(cleaned):
            try:
                val = float(match.replace(",", ""))
            except ValueError:
                continue
            key = (val, round(cx, 1), round(cy, 1))
            if key in seen:
                continue
            seen.add(key)
            items.append((val, cx, cy))
    return items


def _fc_integer_bet_win_by_label(
    footer_ocr,
    page,
    screenshot_bytes: bytes,
    *,
    balance_cx: float | None,
) -> tuple[float | None, float | None]:
    """Read integer WIN / TOTAL BETS by label column (integer-credit UI only).

    Returns ``(win, total_bets)``; each is None when its column has no integer token.
    Only tokens below the label and within the column x-tolerance are considered, so
    reel digits and the balance amount are not mistaken for bet/win.
    """
    if not footer_ocr:
        return None, None
    dpr = _screenshot_dpr(screenshot_bytes, page)
    vp_w = page.viewport_size["width"]
    labels: dict[str, tuple[float, float]] = {}
    tokens: list[tuple[float, float, float]] = []
    for res in footer_ocr:
        text = res[1] or ""
        cx, cy = _ocr_viewport_center(res, dpr)
        kind = _classify_fc_footer_label(text)
        if kind in ("win", "total_bets") and kind not in labels:
            labels[kind] = (cx, cy)
        cleaned = _normalize_amount_ocr_text(text)
        for match in _FC_INTEGER_TOKEN_RE.findall(cleaned):
            try:
                val = float(match.replace(",", ""))
            except ValueError:
                continue
            tokens.append((val, cx, cy))

    x_tol = vp_w * FC_FOOTER_COLUMN_X_TOLERANCE_FRAC if vp_w else 0.0

    def _pick(kind: str) -> float | None:
        if kind not in labels:
            return None
        lx, ly = labels[kind]
        below = [
            item
            for item in tokens
            if item[2] > ly + 4
            and abs(item[1] - lx) <= x_tol
            and (balance_cx is None or abs(item[1] - balance_cx) > x_tol)
        ]
        if not below:
            return None
        return min(below, key=lambda item: item[2])[0]

    return _pick("win"), _pick("total_bets")


def parse_fc_footer_integer_balance(
    footer_ocr,
    page,
    screenshot_bytes: bytes,
    *,
    lobby_b0: float | None,
    balance_x_frac: float | None = None,
    allow_integer_bet_win: bool = False,
) -> FcFooterStrip | None:
    """Narrow fallback: accept an integer (no-decimals) balance ONLY when a BALANCE
    label is present and the value reconciles to lobby B0. Sets balance only, unless
    ``allow_integer_bet_win`` (FC-SLOT-020 integer-credit UI) also permits integer
    WIN / TOTAL BETS by label column. Used when the strict decimal parser (incl.
    upscale) missed the balance.
    """
    if lobby_b0 is None or not footer_ocr:
        return None
    has_balance_label = any(
        _classify_fc_footer_label(res[1] or "") == "balance" for res in footer_ocr
    )
    if not has_balance_label:
        return None
    candidates = _fc_integer_balance_candidates(footer_ocr, page, screenshot_bytes)
    if not candidates:
        return None
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    best: tuple[float, float, float] | None = None
    best_dist: float | None = None
    for val, cx, cy in candidates:
        recovered = reconcile_fc_balance_with_b0(val, lobby_b0)
        if recovered is None:
            continue
        dist = abs(recovered - lobby_b0)
        # Bias toward the known balance column on near-ties.
        if balance_x_frac is not None and vp_w:
            dist += abs(cx - balance_x_frac * vp_w) / vp_w
        if best is None or dist < best_dist:
            best = (recovered, cx, cy)
            best_dist = dist
    if best is None:
        return None
    balance, cx, cy = best
    win_val: float | None = None
    bet_val: float | None = None
    if allow_integer_bet_win:
        win_val, bet_val = _fc_integer_bet_win_by_label(
            footer_ocr, page, screenshot_bytes, balance_cx=cx
        )
    logger.info(
        "💰 FC footer integer balance fallback: %.2f ≈ lobby B0 %.2f "
        "(BALANCE label present, no decimals in OCR) win=%s total_bets=%s",
        balance,
        lobby_b0,
        f"{win_val:.2f}" if win_val is not None else "n/a",
        f"{bet_val:.2f}" if bet_val is not None else "n/a",
    )
    return FcFooterStrip(
        balance=balance,
        win=win_val,
        total_bets=bet_val,
        balance_x_frac=(cx / vp_w) if vp_w else None,
        value_row_y_frac=(cy / vp_h) if vp_h else None,
    )


def _store_fc_footer_anchor(game_config: dict | None, strip: FcFooterStrip) -> None:
    if not game_config:
        return
    if strip.balance_x_frac is not None:
        game_config[audit_fc_balance_x_frac_key()] = float(strip.balance_x_frac)
    if strip.value_row_y_frac is not None:
        game_config[audit_fc_value_row_y_frac_key()] = float(strip.value_row_y_frac)
    # Never persist 0 / negative — that poisons min_bet and spin ack.
    if strip.total_bets is not None and float(strip.total_bets) > 0:
        game_config[audit_fc_total_bets_key()] = float(strip.total_bets)


def _assign_jdb_footer_columns(
    row: list[tuple[float, float, float]],
    *,
    lobby_b0: float | None,
    balance_x_frac: float | None,
    vp_w: float,
    vp_h: float,
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Assign JDB icon strip: Balance | Bet | Win left→right."""
    if not row:
        return None, None, None, None, None
    row = sorted(row, key=lambda item: item[1])
    balance_item = None
    source_item: tuple[float, float, float] | None = None
    if balance_x_frac is not None:
        target_x = balance_x_frac * vp_w
        source_item = min(row, key=lambda item: abs(item[1] - target_x))
        if lobby_b0 is not None:
            recovered = reconcile_fc_balance_with_b0(source_item[0], lobby_b0)
            balance_item = (
                (recovered, source_item[1], source_item[2])
                if recovered is not None
                else _best_reconciled_footer_balance(row, lobby_b0)
            )
            if balance_item is not None and recovered is None:
                source_item = next(
                    (
                        item
                        for item in row
                        if abs(item[1] - balance_item[1]) < 1e-6
                        and abs(item[2] - balance_item[2]) < 1e-6
                    ),
                    source_item,
                )
        else:
            balance_item = source_item
    elif lobby_b0 is not None:
        balance_item = _best_reconciled_footer_balance(row, lobby_b0)
        if balance_item is not None:
            source_item = next(
                (
                    item
                    for item in row
                    if abs(item[1] - balance_item[1]) < 1e-6
                    and abs(item[2] - balance_item[2]) < 1e-6
                ),
                None,
            )
    else:
        wallet = [item for item in row if item[0] >= PRIMARY_BALANCE_MIN]
        balance_item = wallet[0] if wallet else row[0]
        source_item = balance_item
    if balance_item is None:
        return None, None, None, None, None
    remaining = sorted(
        [
            item
            for item in row
            if source_item is None
            or abs(item[1] - source_item[1]) > 1e-6
            or abs(item[2] - source_item[2]) > 1e-6
            or abs(item[0] - source_item[0]) > 1e-6
        ],
        key=lambda item: item[1],
    )
    # Prefer small stake/win columns to the right of balance.
    small = [item for item in remaining if item[0] < PRIMARY_BALANCE_MIN]
    if len(small) >= 2:
        bet_val, win_val = small[0][0], small[-1][0]
    elif len(small) == 1:
        bet_val, win_val = small[0][0], 0.0
    elif len(remaining) >= 2:
        bet_val, win_val = remaining[0][0], remaining[-1][0]
    elif len(remaining) == 1:
        bet_val, win_val = remaining[0][0], 0.0
    else:
        bet_val, win_val = None, None
    if bet_val is not None and bet_val <= 0:
        nonzero = [item for item in small if item[0] > 0]
        bet_val = nonzero[0][0] if nonzero else None
    return (
        balance_item[0],
        bet_val,
        win_val,
        balance_item[1] / vp_w if vp_w else None,
        balance_item[2] / vp_h if vp_h else None,
    )


def _augment_jdb_row_with_nearby_small_amounts(
    row: list[tuple[float, float, float]],
    amounts: list[tuple[float, float, float]],
    *,
    vp_h: float,
) -> list[tuple[float, float, float]]:
    """If OCR only kept the wallet amount, pull bet/win from nearby small amounts."""
    if not row or not amounts:
        return row
    row_sorted = sorted(row, key=lambda item: item[1])
    # Prefer the leftmost wallet-sized amount as balance anchor.
    wallet = [item for item in row_sorted if item[0] >= PRIMARY_BALANCE_MIN]
    anchor = wallet[0] if wallet else row_sorted[0]
    ax, ay = anchor[1], anchor[2]
    y_tol = FC_FOOTER_ROW_Y_TOLERANCE_PX * 2.5
    merged = { (round(item[1], 1), round(item[2], 1), round(item[0], 4)): item for item in row_sorted }
    for val, cx, cy in amounts:
        if val >= PRIMARY_BALANCE_MIN:
            continue
        if cx <= ax + 8:
            continue
        if abs(cy - ay) > y_tol:
            continue
        key = (round(cx, 1), round(cy, 1), round(val, 4))
        merged[key] = (val, cx, cy)
    return sorted(merged.values(), key=lambda item: item[1])


def parse_jdb_footer_from_ocr(
    footer_ocr,
    page,
    screenshot_bytes: bytes,
    *,
    lobby_b0: float | None = None,
    balance_x_frac: float | None = None,
    value_row_y_frac: float | None = None,
) -> JdbFooterStrip | None:
    """Parse JDB portrait footer: icon-only Balance | Bet | Win on one value row."""
    if not footer_ocr:
        return None
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    dpr = _screenshot_dpr(screenshot_bytes, page)
    amounts = _collect_jdb_footer_amount_items(footer_ocr, dpr)
    row = _pick_footer_value_row(
        amounts,
        labels=[],
        value_row_y_frac=value_row_y_frac,
        vp_h=vp_h,
    )
    # Prefer a row that includes the wallet amount (small bet/win clusters can win max()).
    if not any(val >= PRIMARY_BALANCE_MIN for val, _, _ in row):
        wallet_hits = [item for item in amounts if item[0] >= PRIMARY_BALANCE_MIN]
        if wallet_hits:
            row = list(wallet_hits)
    row = _augment_jdb_row_with_nearby_small_amounts(row, amounts, vp_h=vp_h)
    balance, bet, win, bx_frac, by_frac = _assign_jdb_footer_columns(
        row,
        lobby_b0=lobby_b0,
        balance_x_frac=balance_x_frac,
        vp_w=vp_w,
        vp_h=vp_h,
    )
    if balance is None:
        return None
    if lobby_b0 is not None:
        recovered = reconcile_fc_balance_with_b0(balance, lobby_b0)
        if recovered is not None:
            balance = recovered
        elif balance_x_frac is None:
            tol = lobby_balance_match_tolerance(lobby_b0)
            if abs(balance - lobby_b0) > tol:
                return None
        elif not is_plausible_ingame_balance(
            balance,
            lobby_b0,
            min_bet=resolve_spin_min_bet(None),
        ):
            return None
    return JdbFooterStrip(
        balance=balance,
        bet=bet,
        win=win,
        balance_x_frac=bx_frac,
        value_row_y_frac=by_frac
        if by_frac
        else (row[0][2] / vp_h if row and vp_h else None),
    )


def _store_jdb_footer_anchor(game_config: dict | None, strip: JdbFooterStrip) -> None:
    if not game_config:
        return
    if strip.balance_x_frac is not None:
        game_config[audit_fc_balance_x_frac_key()] = float(strip.balance_x_frac)
    if strip.value_row_y_frac is not None:
        game_config[audit_fc_value_row_y_frac_key()] = float(strip.value_row_y_frac)
    if strip.bet is not None and float(strip.bet) > 0:
        game_config[audit_fc_total_bets_key()] = float(strip.bet)


def _choose_jdb_footer_strip(
    primary: JdbFooterStrip | None,
    refined: JdbFooterStrip | None,
    *,
    ref_b0: float | None,
    min_bet: float,
) -> JdbFooterStrip | None:
    if refined is None:
        return primary
    if primary is None:
        return refined
    if primary.balance is None:
        return refined
    if refined.balance is None:
        return primary
    # Prefer a strip that recovered bet/win columns.
    p_bet = primary.bet is not None and primary.bet > 0
    r_bet = refined.bet is not None and refined.bet > 0
    if r_bet and not p_bet:
        return refined
    # Prefer strip that satisfies wallet formula / closer to B0 when dirty OCR.
    if ref_b0 is not None:
        p_ok = wallet_spin_formula_ok(
            ref_b0, primary.balance, primary.bet or min_bet, primary.win
        ) if primary.bet else False
        r_ok = wallet_spin_formula_ok(
            ref_b0, refined.balance, refined.bet or min_bet, refined.win
        ) if refined.bet else False
        if r_ok and not p_ok:
            return refined
        if abs(refined.balance - ref_b0) + 1e-6 < abs(primary.balance - ref_b0):
            # Only when refined still looks like same wallet class.
            if is_plausible_ingame_balance(refined.balance, ref_b0, min_bet=min_bet):
                return refined
    return primary


def resolve_spin_min_bet(game_config: dict | None) -> float:
    floor = (
        JDB_UNKNOWN_BET_DELTA_FLOOR
        if _game_config_is_jdb(game_config)
        else UNKNOWN_BET_DELTA_FLOOR
    )
    if game_config:
        total_bets = game_config.get(audit_fc_total_bets_key())
        if total_bets is not None and float(total_bets) > 0:
            return max(float(total_bets) * 0.85, floor)
    return DEFAULT_MIN_BET_DELTA


def resolve_effective_spin_bet(
    strip_total_bets: float | None,
    game_config: dict | None,
) -> float | None:
    """Per-game stake when OCR is valid; None when unknown (do not invent a fixed bet)."""
    if strip_total_bets is not None and float(strip_total_bets) > 0:
        return float(strip_total_bets)
    if game_config:
        stored = game_config.get(audit_fc_total_bets_key())
        if stored is not None and float(stored) > 0:
            return float(stored)
    return None


def resolve_spin_delta_min_bet(
    strip_total_bets: float | None,
    game_config: dict | None,
) -> float:
    """Min |Δbalance| to treat as a spin — uses game bet when known, else a low floor."""
    floor = (
        JDB_UNKNOWN_BET_DELTA_FLOOR
        if _game_config_is_jdb(game_config)
        else UNKNOWN_BET_DELTA_FLOOR
    )
    bet = resolve_effective_spin_bet(strip_total_bets, game_config)
    if bet is not None:
        return max(float(bet) * 0.85, floor)
    return floor


def _fc_strip_indicates_spin(
    ref_b0: float | None,
    strip: FcFooterStrip | None,
    *,
    min_bet: float,
) -> bool:
    """True when strip looks like a completed spin vs ref (delta and/or B0-bet+win)."""
    if ref_b0 is None or strip is None or strip.balance is None:
        return False
    delta_min = min_bet if min_bet > 0 else UNKNOWN_BET_DELTA_FLOOR
    if strip.total_bets is not None and strip.total_bets > 0:
        delta_min = max(float(strip.total_bets) * 0.85, UNKNOWN_BET_DELTA_FLOOR)
    if primary_balance_spin_delta(ref_b0, strip.balance, min_bet=delta_min) is not None:
        return True
    bet = strip.total_bets if strip.total_bets and strip.total_bets > 0 else None
    if bet is None:
        return False
    return wallet_spin_formula_ok(ref_b0, strip.balance, bet, strip.win)


def _choose_fc_footer_strip(
    primary: FcFooterStrip | None,
    refined: FcFooterStrip | None,
    *,
    ref_b0: float | None,
    min_bet: float,
) -> FcFooterStrip | None:
    """Prefer upscaled refine on dirty OCR, but never undo a clear spin toward B0."""
    if refined is None:
        return primary
    if primary is None:
        return refined
    if _fc_strip_indicates_spin(ref_b0, primary, min_bet=min_bet):
        if not _fc_strip_indicates_spin(ref_b0, refined, min_bet=min_bet):
            if (
                ref_b0 is not None
                and primary.balance is not None
                and refined.balance is not None
                and abs(refined.balance - ref_b0) + 0.01 < abs(primary.balance - ref_b0)
            ):
                logger.info(
                    "Keeping primary FC footer (spin formula/delta); "
                    "upscaled moved closer to B0"
                )
                return primary
    return refined


def ocr_upscaled_fraction_region(
    hybrid_locator,
    screenshot_bytes: bytes,
    page,
    region_frac: dict,
    *,
    scale: int = FC_FOOTER_UPSCALE_FACTOR,
):
    """Crop region, upscale, OCR, remap boxes into full-screenshot pixel space."""
    if not screenshot_bytes or scale < 2:
        return []
    try:
        img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
    except Exception:
        return []
    w, h = img.size
    x0 = max(0, int(region_frac.get("x_start", 0.0) * w))
    x1 = min(w, int(region_frac.get("x_end", 1.0) * w))
    y0 = max(0, int(region_frac.get("y_start", 0.0) * h))
    y1 = min(h, int(region_frac.get("y_end", 1.0) * h))
    if x1 <= x0 or y1 <= y0:
        return []
    crop = img.crop((x0, y0, x1, y1))
    up = crop.resize((max(1, crop.width * scale), max(1, crop.height * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    up.save(buf, format="PNG")
    try:
        raw = hybrid_locator.ocr.reader.readtext(buf.getvalue())
    except Exception as exc:
        logger.debug("Upscaled footer OCR failed: %s", exc)
        return []
    remapped = []
    for item in raw or []:
        box, text = item[0], item[1]
        conf = item[2] if len(item) > 2 else 0.0
        new_box = [[pt[0] / scale + x0, pt[1] / scale + y0] for pt in box]
        remapped.append((new_box, text, conf))
    return remapped


def read_in_game_fc_footer_strip(
    page,
    hybrid_locator,
    game_config: dict | None,
    *,
    collapse_side_panel_on_miss: bool = True,
) -> FcFooterStrip | None:
    """Read FC portrait footer strip (balance / win / total bets) with B0 column calibration.

    Full-frame OCR first. On miss (A) or dirty spaced-amount OCR (B), retry with an
    upscaled footer crop. Never treat B1≈B0 alone as dirty — formula/delta decide spin.

    Side panel is collapsed only after a strip miss when ``collapse_side_panel_on_miss``.
    """
    if not use_fc_portrait_footer_strip(game_config, page, hybrid_locator):
        return None
    canvas_visible = any(unity_canvas_ready(ctx) for ctx in iter_game_contexts(page))
    if not canvas_visible:
        return None

    def _attempt() -> FcFooterStrip | None:
        return _read_in_game_fc_footer_strip_once(page, hybrid_locator, game_config)

    strip = _attempt()
    if strip is not None:
        return strip
    if collapse_side_panel_on_miss and collapse_fc_side_panel_after_balance_miss(
        page,
        hybrid_locator,
        game_config=game_config,
        tag="fc_footer_miss",
    ):
        return _attempt()
    return None


def _read_in_game_fc_footer_strip_once(
    page,
    hybrid_locator,
    game_config: dict | None,
) -> FcFooterStrip | None:
    lobby_b0 = game_config.get(audit_lobby_b0_key()) if game_config else None
    balance_x_frac = game_config.get(audit_fc_balance_x_frac_key()) if game_config else None
    value_row_y_frac = game_config.get(audit_fc_value_row_y_frac_key()) if game_config else None
    min_bet = resolve_spin_min_bet(game_config)
    # Robin Hood (FC-SLOT-020) is the only FC game with an integer-credit footer
    # (BALANCE / WIN / TOTAL BETS shown without decimals). Allow integer bet/win only
    # for it so ordinary FC games keep the strict decimal contract.
    integer_bet_win = bool(game_config and game_config.get("id") == "FC-SLOT-020")
    screenshot = page.screenshot()
    ocr = hybrid_locator.ocr.reader.readtext(screenshot)
    miss_snippets: list[str] = []
    for idx, footer in enumerate(footer_ocr_regions_to_try(page, game_config)):
        footer_ocr = _ocr_results_in_fraction_region(ocr, screenshot, page, footer)
        up_ocr = None
        strip = parse_fc_footer_from_ocr(
            footer_ocr,
            page,
            screenshot,
            lobby_b0=lobby_b0,
            balance_x_frac=balance_x_frac,
            value_row_y_frac=value_row_y_frac,
        )
        dirty = footer_ocr_has_spaced_amount(footer_ocr)
        need_upscale = strip is None or dirty
        if need_upscale:
            up_ocr = ocr_upscaled_fraction_region(
                hybrid_locator, screenshot, page, footer
            )
            up_strip = parse_fc_footer_from_ocr(
                up_ocr,
                page,
                screenshot,
                lobby_b0=lobby_b0,
                balance_x_frac=balance_x_frac,
                value_row_y_frac=value_row_y_frac,
            )
            if strip is None and up_strip is not None:
                logger.info(
                    "💰 FC footer strip via upscaled crop (miss fallback, region %s)",
                    idx,
                )
            chosen = _choose_fc_footer_strip(
                strip, up_strip, ref_b0=lobby_b0, min_bet=min_bet
            )
            if chosen is not None and chosen is up_strip and strip is not None and dirty:
                logger.info(
                    "💰 FC footer strip refined via upscaled crop (dirty OCR, region %s)",
                    idx,
                )
            strip = chosen
        if strip is None and lobby_b0 is not None:
            # Last resort: OCR dropped the decimals on the balance (e.g. "10,007,383").
            # Accept an integer balance only when a BALANCE label is present and the
            # value reconciles to lobby B0. bet/win stay n/a.
            strip = parse_fc_footer_integer_balance(
                footer_ocr,
                page,
                screenshot,
                lobby_b0=lobby_b0,
                balance_x_frac=balance_x_frac,
                allow_integer_bet_win=integer_bet_win,
            )
            if strip is None and up_ocr:
                strip = parse_fc_footer_integer_balance(
                    up_ocr,
                    page,
                    screenshot,
                    lobby_b0=lobby_b0,
                    balance_x_frac=balance_x_frac,
                    allow_integer_bet_win=integer_bet_win,
                )
        if strip is None:
            if footer_ocr:
                snippet = " | ".join(res[1] for res in footer_ocr[:10])
                miss_snippets.append(f"r{idx}:{snippet}")
                logger.debug("FC footer OCR miss (region %s): %s", idx, snippet)
            continue
        _store_fc_footer_anchor(game_config, strip)
        logger.info(
            "💰 FC footer strip: balance=%.2f win=%s total_bets=%s "
            "(region %s, anchor_x=%.2f)",
            strip.balance,
            f"{strip.win:.2f}" if strip.win is not None else "n/a",
            f"{strip.total_bets:.2f}" if strip.total_bets is not None else "n/a",
            idx,
            strip.balance_x_frac or 0.0,
        )
        return strip
    if miss_snippets:
        logger.info("⚠️ FC footer strip miss snippets: %s", " || ".join(miss_snippets[:4]))
    return None


def read_in_game_jdb_footer_strip(
    page,
    hybrid_locator,
    game_config: dict | None,
) -> JdbFooterStrip | None:
    """Read JDB portrait icon strip (balance / bet / win) with B0 column calibration."""
    if not use_jdb_portrait_footer_strip(game_config, page, hybrid_locator):
        return None
    canvas_visible = any(unity_canvas_ready(ctx) for ctx in iter_game_contexts(page))
    if not canvas_visible:
        return None
    lobby_b0 = game_config.get(audit_lobby_b0_key()) if game_config else None
    balance_x_frac = game_config.get(audit_fc_balance_x_frac_key()) if game_config else None
    value_row_y_frac = game_config.get(audit_fc_value_row_y_frac_key()) if game_config else None
    min_bet = resolve_spin_min_bet(game_config)
    screenshot = page.screenshot()
    ocr = hybrid_locator.ocr.reader.readtext(screenshot)
    miss_snippets: list[str] = []
    best: JdbFooterStrip | None = None
    for idx, footer in enumerate(footer_ocr_regions_to_try(page, game_config)):
        footer_ocr = _ocr_results_in_fraction_region(ocr, screenshot, page, footer)
        strip = parse_jdb_footer_from_ocr(
            footer_ocr,
            page,
            screenshot,
            lobby_b0=lobby_b0,
            balance_x_frac=balance_x_frac,
            value_row_y_frac=value_row_y_frac,
        )
        dirty = footer_ocr_has_spaced_amount(footer_ocr)
        missing_bet = strip is not None and (strip.bet is None or strip.bet <= 0)
        need_upscale = strip is None or dirty or missing_bet
        if need_upscale:
            up_ocr = ocr_upscaled_fraction_region(
                hybrid_locator, screenshot, page, footer
            )
            up_strip = parse_jdb_footer_from_ocr(
                up_ocr,
                page,
                screenshot,
                lobby_b0=lobby_b0,
                balance_x_frac=balance_x_frac,
                value_row_y_frac=value_row_y_frac,
            )
            if strip is None and up_strip is not None:
                logger.info(
                    "💰 JDB footer strip via upscaled crop (miss fallback, region %s)",
                    idx,
                )
            elif missing_bet and up_strip is not None and up_strip.bet:
                logger.info(
                    "💰 JDB footer bet/win via upscaled crop (region %s)",
                    idx,
                )
            strip = _choose_jdb_footer_strip(
                strip, up_strip, ref_b0=lobby_b0, min_bet=min_bet
            )
        if strip is None:
            if footer_ocr:
                snippet = " | ".join(res[1] for res in footer_ocr[:10])
                miss_snippets.append(f"r{idx}:{snippet}")
            continue
        best = _choose_jdb_footer_strip(
            best, strip, ref_b0=lobby_b0, min_bet=min_bet
        )
        if strip.bet is not None and strip.bet > 0:
            _store_jdb_footer_anchor(game_config, strip)
            logger.info(
                "💰 JDB footer strip: balance=%.3f bet=%s win=%s "
                "(region %s, anchor_x=%.2f)",
                strip.balance,
                f"{strip.bet:.3f}" if strip.bet is not None else "n/a",
                f"{strip.win:.3f}" if strip.win is not None else "n/a",
                idx,
                strip.balance_x_frac or 0.0,
            )
            return strip
    if best is not None:
        _store_jdb_footer_anchor(game_config, best)
        logger.info(
            "💰 JDB footer strip: balance=%.3f bet=%s win=%s "
            "(best effort, anchor_x=%.2f)",
            best.balance,
            f"{best.bet:.3f}" if best.bet is not None else "n/a",
            f"{best.win:.3f}" if best.win is not None else "n/a",
            best.balance_x_frac or 0.0,
        )
        return best
    if miss_snippets:
        logger.info("⚠️ JDB footer strip miss snippets: %s", " || ".join(miss_snippets[:4]))
    return None


def log_footer_primary_read_failure(
    page,
    hybrid_locator,
    game_config: dict | None,
) -> None:
    """INFO-level OCR dump when pre-balance cannot find a primary wallet amount."""
    try:
        dismiss_fc_side_panel_if_open(
            page,
            hybrid_locator,
            game_config=game_config,
            tag="pre_balance_fail",
        )
        screenshot = page.screenshot()
        ocr = hybrid_locator.ocr.reader.readtext(screenshot)
        parts: list[str] = []
        for idx, footer in enumerate(footer_ocr_regions_to_try(page, game_config)):
            footer_ocr = _ocr_results_in_fraction_region(ocr, screenshot, page, footer)
            snippet = " | ".join(res[1] for res in footer_ocr[:12]) or "(empty)"
            parts.append(
                f"r{idx} y={footer.get('y_start', 0):.2f}-{footer.get('y_end', 1):.2f}: {snippet}"
            )
        logger.warning("⚠️ Footer primary read failed. OCR by region: %s", " || ".join(parts))
    except Exception as exc:
        logger.warning("⚠️ Footer primary failure dump skipped: %s", exc)

def pick_primary_balance(
    ocr_results,
    *,
    min_value: float = PRIMARY_BALANCE_MIN,
) -> float | None:
    """Largest balance-like number (excludes bet/jackpot noise when min_value is high)."""
    amounts: list[float] = []
    for res in ocr_results:
        amounts.extend(parse_amounts_from_text(res[1]))
    candidates = [v for v in amounts if v >= min_value]
    if not candidates:
        candidates = [v for v in amounts if v >= WALLET_BALANCE_MIN]
    return max(candidates) if candidates else None


def collect_footer_amount_candidates(ocr_results) -> list[float]:
    """All wallet-like amounts from footer OCR (no primary minimum)."""
    amounts: list[float] = []
    seen: set[float] = set()
    for res in ocr_results:
        for val in parse_amounts_from_text(res[1]):
            if val not in seen:
                amounts.append(val)
                seen.add(val)
    return amounts


def lobby_balance_match_tolerance(lobby_b0: float) -> float:
    return max(DEFAULT_CROSS_VENUE_TOLERANCE, lobby_b0 * 0.0001)


def reconcile_fc_balance_with_b0(candidate: float, lobby_b0: float) -> float | None:
    """Recover balance when OCR drops leading digits (e.g. 10,007,352.02 → 0,007,352.02).

    Returns the reconstructed *current* balance (may differ from lobby_b0 after a spin).
    Does not blindly return lobby_b0 when only the leading digit was truncated.
    """
    tol = lobby_balance_match_tolerance(lobby_b0)
    max_delta = max(_FC_RECONCILE_MAX_ABS_DELTA, DEFAULT_MIN_BET_DELTA * 6)
    if abs(candidate - lobby_b0) <= tol:
        return candidate
    # Full wallet OCR already near B0 (no truncation) — allow small one-spin drift.
    if candidate >= PRIMARY_BALANCE_MIN and abs(candidate - lobby_b0) <= max_delta:
        return candidate
    b0_cents = str(int(round(lobby_b0 * 100)))
    cand_cents = str(int(round(candidate * 100)))
    if not cand_cents or cand_cents == "0":
        return None
    for suffix in (cand_cents, cand_cents.lstrip("0") or ""):
        if not suffix or len(suffix) < _FC_RECONCILE_MIN_SUFFIX_DIGITS:
            continue
        if len(suffix) >= len(b0_cents):
            continue
        recovered_cents = b0_cents[: len(b0_cents) - len(suffix)] + suffix
        try:
            recovered = int(recovered_cents) / 100.0
        except ValueError:
            continue
        if abs(recovered - lobby_b0) <= max_delta:
            return recovered
    return None


def match_footer_to_lobby_b0(
    ocr_results,
    lobby_b0: float,
    *,
    tolerance: float | None = None,
) -> float | None:
    """Pick footer candidate closest to lobby B0 within tolerance."""
    tol = tolerance if tolerance is not None else lobby_balance_match_tolerance(lobby_b0)
    candidates = collect_footer_amount_candidates(ocr_results)
    if not candidates:
        return None
    best = min(candidates, key=lambda v: abs(v - lobby_b0))
    if abs(best - lobby_b0) <= tol:
        logger.info(
            "💰 Footer matched lobby B0: %.2f (candidate=%.2f, tol=%.2f)",
            lobby_b0,
            best,
            tol,
        )
        return best
    return None


def read_primary_balance_in_region(
    page,
    hybrid_locator,
    region_frac: dict,
    *,
    min_value: float = PRIMARY_BALANCE_MIN,
) -> float | None:
    screenshot = page.screenshot()
    ocr = hybrid_locator.ocr.reader.readtext(screenshot)
    region_ocr = _ocr_results_in_fraction_region(ocr, screenshot, page, region_frac)
    return pick_primary_balance(region_ocr, min_value=min_value)


def resolve_lobby_wallet_regions(global_config: dict, entry_mode: str) -> list[dict]:
    env = get_client_env_config(global_config)
    if entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        combo = get_comboburst_config(global_config)
        region = combo.get("lobby_wallet_region") or COMBO_LOBBY_WALLET_REGION
        return [region]
    regions = env.get("jc_lobby_wallet_regions")
    if regions:
        return list(regions)
    return [JC_LOBBY_WALLET_HEADER_REGION, JC_LOBBY_WALLET_SIDEBAR_REGION]


def resolve_lobby_wallet_refresh_regions(
    global_config: dict, entry_mode: str
) -> list[dict]:
    """Fraction regions for wallet ↻ refresh buttons (COMBO header / JC header+sidebar)."""
    env = get_client_env_config(global_config)
    if entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        combo = get_comboburst_config(global_config)
        region = combo.get("lobby_wallet_refresh_region") or COMBO_LOBBY_WALLET_REFRESH_REGION
        return [region]
    regions = env.get("jc_lobby_wallet_refresh_regions")
    if regions:
        return list(regions)
    return [
        JC_LOBBY_WALLET_HEADER_REFRESH_REGION,
        JC_LOBBY_WALLET_SIDEBAR_REFRESH_REGION,
    ]


def _click_region_center(page, region_frac: dict) -> tuple[float, float]:
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    cx = (region_frac["x_start"] + region_frac["x_end"]) / 2 * vp_w
    cy = (region_frac["y_start"] + region_frac["y_end"]) / 2 * vp_h
    page.mouse.click(cx, cy)
    return cx, cy


def click_lobby_wallet_refresh(
    page,
    global_config: dict,
    entry_mode: str,
    *,
    label: str = "lobby",
) -> None:
    """Click wallet ↻ refresh icon(s) before OCR (COMBO top bar / JC header + sidebar)."""
    regions = resolve_lobby_wallet_refresh_regions(global_config, entry_mode)
    for i, region in enumerate(regions):
        cx, cy = _click_region_center(page, region)
        logger.info(
            "🔄 Click wallet refresh (%s) at (%.0f, %.0f) [region %s/%s]",
            label,
            cx,
            cy,
            i + 1,
            len(regions),
        )
        time.sleep(0.9)


def read_lobby_wallet_balance(
    page,
    hybrid_locator,
    global_config: dict,
    entry_mode: str,
    *,
    min_value: float = WALLET_BALANCE_MIN,
) -> float | None:
    """Read platform wallet from lobby header/sidebar (tries each configured region)."""
    for region in resolve_lobby_wallet_regions(global_config, entry_mode):
        val = read_primary_balance_in_region(
            page, hybrid_locator, region, min_value=min_value
        )
        if val is not None:
            logger.info(
                "💰 Lobby wallet OCR: %.2f (region x=%.2f–%.2f, y=%.2f–%.2f)",
                val,
                region["x_start"],
                region["x_end"],
                region["y_start"],
                region["y_end"],
            )
            return val
    logger.warning("⚠️ Lobby wallet balance not detected in configured regions.")
    return None


def is_plausible_ingame_balance(
    val: float | None,
    lobby_b0: float | None,
    *,
    min_bet: float = DEFAULT_MIN_BET_DELTA,
) -> bool:
    """Reject footer fragments (e.g. 361.02) when lobby B0 is a full wallet balance."""
    if val is None or lobby_b0 is None:
        return True
    if val >= lobby_b0 * 0.95:
        return True
    max_loss = max(min_bet * 50, lobby_b0 * 0.01)
    if lobby_b0 - val <= max_loss:
        return True
    return False


def read_in_game_footer_primary(
    page,
    hybrid_locator,
    game_config: dict | None,
    *,
    min_value: float = PRIMARY_BALANCE_MIN,
    allow_lobby_b0_fallback: bool | None = None,
) -> float | None:
    """Primary player balance from in-game footer strip."""
    # Do not collapse the side panel up-front — only after a balance miss (cleaner OCR).
    def _read_once() -> float | None:
        return _read_in_game_footer_primary_once(
            page,
            hybrid_locator,
            game_config,
            min_value=min_value,
            allow_lobby_b0_fallback=allow_lobby_b0_fallback,
        )

    val = _read_once()
    if val is not None:
        return val
    if collapse_fc_side_panel_after_balance_miss(
        page,
        hybrid_locator,
        game_config=game_config,
        tag="footer_primary_miss",
    ):
        return _read_once()
    return None


def _read_in_game_footer_primary_once(
    page,
    hybrid_locator,
    game_config: dict | None,
    *,
    min_value: float = PRIMARY_BALANCE_MIN,
    allow_lobby_b0_fallback: bool | None = None,
) -> float | None:
    """Single-pass footer primary read (no side-panel collapse)."""
    fc_strip = use_fc_portrait_footer_strip(game_config, page, hybrid_locator)
    if fc_strip:
        strip = read_in_game_fc_footer_strip(
            page,
            hybrid_locator,
            game_config,
            collapse_side_panel_on_miss=False,
        )
        if strip and strip.balance is not None:
            return strip.balance
        # Strip miss: fall through to generic region OCR (mid + bottom). Never invent from lobby B0.
        if allow_lobby_b0_fallback is None:
            allow_lobby_b0_fallback = False

    if use_jdb_portrait_footer_strip(game_config, page, hybrid_locator):
        jdb_strip = read_in_game_jdb_footer_strip(page, hybrid_locator, game_config)
        if jdb_strip and jdb_strip.balance is not None:
            return jdb_strip.balance
        if allow_lobby_b0_fallback is None:
            allow_lobby_b0_fallback = False

    canvas_visible = any(unity_canvas_ready(ctx) for ctx in iter_game_contexts(page))
    if not canvas_visible:
        logger.warning("⚠️ In-game footer OCR skipped: Unity canvas not visible.")
        return None
    lobby_b0 = None
    if game_config:
        lobby_b0 = game_config.get(audit_lobby_b0_key())
    use_b0_fallback = allow_lobby_b0_fallback
    if use_b0_fallback is None:
        use_b0_fallback = True
    screenshot = page.screenshot()
    ocr = hybrid_locator.ocr.reader.readtext(screenshot)
    footer_text_logged = False
    for idx, footer in enumerate(footer_ocr_regions_to_try(page, game_config)):
        footer_ocr = _ocr_results_in_fraction_region(ocr, screenshot, page, footer)
        if lobby_b0 is not None:
            matched = match_footer_to_lobby_b0(footer_ocr, lobby_b0)
            if matched is not None:
                if idx == 0:
                    logger.info("💰 In-game footer primary balance: %.2f (lobby B0 match)", matched)
                else:
                    logger.info(
                        "💰 In-game footer primary balance: %.2f "
                        "(lobby B0 match, fallback y=%.2f–%.2f)",
                        matched,
                        footer.get("y_start", 0),
                        footer.get("y_end", 1),
                    )
                return matched
        val = pick_primary_balance(footer_ocr, min_value=min_value)
        if val is not None and not is_plausible_ingame_balance(val, lobby_b0):
            logger.debug(
                "Footer balance %.2f rejected as fragment (lobby B0=%.2f)",
                val,
                lobby_b0,
            )
            val = None
        if val is not None:
            if idx == 0:
                logger.info("💰 In-game footer primary balance: %.2f", val)
            else:
                logger.info(
                    "💰 In-game footer primary balance: %.2f (fallback region y=%.2f–%.2f)",
                    val,
                    footer.get("y_start", 0),
                    footer.get("y_end", 1),
                )
            return val
        if not footer_text_logged and footer_ocr:
            snippet = " | ".join(res[1] for res in footer_ocr[:8])
            logger.debug("Footer OCR miss (region %s): %s", idx, snippet)
            footer_text_logged = True
    if use_b0_fallback and lobby_b0 is not None:
        logger.info("💰 In-game footer using lobby B0 fallback: %.2f", lobby_b0)
        return lobby_b0
    return None


def primary_balance_spin_delta(
    before: float | None,
    after: float | None,
    *,
    min_bet: float = DEFAULT_MIN_BET_DELTA,
    tolerance: float = 0.15,
    unchanged_eps: float = SPIN_BALANCE_UNCHANGED_EPS,
) -> float | None:
    """Return balance delta if it reflects a real bet (loss or win), else None.

    Flat wallets (``|Δ| <= unchanged_eps``) never count — important when
    ``min_bet`` is below ``tolerance`` (e.g. JDB floor 0.05), which used to let
    ``Δ=0`` pass the ``|Δ| + tolerance < min_bet`` gate.
    """
    if before is None or after is None:
        return None
    if not is_plausible_ingame_balance(after, before, min_bet=min_bet):
        return None
    delta = round(after - before, 4)
    if abs(delta) <= unchanged_eps:
        return None
    if abs(delta) + tolerance < min_bet:
        return None
    return delta


def wallet_spin_formula_ok(
    b0: float | None,
    b1: float | None,
    bet: float | None,
    win: float | None,
    *,
    tolerance: float = SPIN_WALLET_FORMULA_TOLERANCE,
    unchanged_eps: float = SPIN_BALANCE_UNCHANGED_EPS,
) -> bool:
    """True when B1 ≈ B0 - bet + win (OCR-tolerant; win is never trusted alone).

    Flat balance (B1≈B0 within ``unchanged_eps``) with win≈0 is rejected so a
    low stake cannot pass via ``|B1-(B0-bet)| ≈ bet ≤ formula tolerance``.
    Break-even spins (win≈bet, B1≈B0) still pass when the formula holds.
    """
    if b0 is None or b1 is None or bet is None or bet <= 0:
        return False
    if not is_plausible_ingame_balance(b1, b0, min_bet=bet):
        return False
    win_val = 0.0 if win is None else float(win)
    if win_val < 0:
        return False
    # Implausible WIN OCR — ignore formula rather than false-ack.
    if win_val > max(b0 * SPIN_WALLET_MAX_WIN_VS_B0_FRAC, bet * SPIN_WALLET_MAX_WIN_VS_BET):
        logger.debug(
            "Wallet formula skipped: win=%.2f looks like OCR noise (b0=%.2f bet=%.2f)",
            win_val,
            b0,
            bet,
        )
        return False
    expected = b0 - bet + win_val
    if abs(b1 - expected) > tolerance:
        return False
    # Unchanged wallet + no win → not evidence of a spin (esp. low bet).
    if abs(b1 - b0) <= unchanged_eps and win_val <= unchanged_eps:
        return False
    return True


def detect_in_game_win_banner(
    page,
    hybrid_locator,
    *,
    y_start: float = 0.12,
    y_end: float = 0.78,
) -> bool:
    """WIN text in reel area (not footer jackpots)."""
    screenshot = page.screenshot()
    vp_w = page.viewport_size["width"]
    vp_h = page.viewport_size["height"]
    region = {"x_start": 0.0, "x_end": 1.0, "y_start": y_start, "y_end": y_end}
    ocr = hybrid_locator.ocr.reader.readtext(screenshot)
    region_ocr = _ocr_results_in_fraction_region(ocr, screenshot, page, region)
    text = " ".join(r[1].lower() for r in region_ocr)
    return bool(re.search(r"\bwin\b", text) and re.search(r"[\d,]+\.\d{2}", text))


def ocr_spin_started_primary(
    page,
    hybrid_locator,
    before_primary: float | None,
    game_config: dict | None = None,
    *,
    min_bet: float | None = None,
) -> bool:
    """True when footer shows a real spin: balance delta and/or B0 - bet + win."""
    if before_primary is None:
        return False
    dismiss_fc_side_panel_if_open(
        page,
        hybrid_locator,
        game_config=game_config,
        tag="spin_ack",
    )

    if use_fc_portrait_footer_strip(game_config, page, hybrid_locator):
        strip = read_in_game_fc_footer_strip(page, hybrid_locator, game_config)
        if strip and strip.balance is not None:
            delta_min = (
                min_bet
                if min_bet is not None
                else resolve_spin_delta_min_bet(strip.total_bets, game_config)
            )
            if primary_balance_spin_delta(
                before_primary, strip.balance, min_bet=delta_min
            ) is not None:
                return True
            bet = resolve_effective_spin_bet(strip.total_bets, game_config)
            if bet is not None and wallet_spin_formula_ok(
                before_primary, strip.balance, bet, strip.win
            ):
                logger.info(
                    "✅ Spin ack via wallet formula: B0=%.2f B1=%.2f bet=%.2f win=%s",
                    before_primary,
                    strip.balance,
                    bet,
                    f"{strip.win:.2f}" if strip.win is not None else "0",
                )
                return True
        after = read_in_game_footer_primary(
            page,
            hybrid_locator,
            game_config,
            allow_lobby_b0_fallback=False,
        )
        delta_min = (
            min_bet
            if min_bet is not None
            else resolve_spin_delta_min_bet(None, game_config)
        )
        return (
            primary_balance_spin_delta(
                before_primary, after, min_bet=delta_min
            )
            is not None
        )

    if use_jdb_portrait_footer_strip(game_config, page, hybrid_locator):
        jdb = read_in_game_jdb_footer_strip(page, hybrid_locator, game_config)
        if jdb and jdb.balance is not None:
            delta_min = (
                min_bet
                if min_bet is not None
                else resolve_spin_delta_min_bet(jdb.bet, game_config)
            )
            if primary_balance_spin_delta(
                before_primary, jdb.balance, min_bet=delta_min
            ) is not None:
                return True
            bet = resolve_effective_spin_bet(jdb.bet, game_config)
            if bet is not None and wallet_spin_formula_ok(
                before_primary, jdb.balance, bet, jdb.win
            ):
                logger.info(
                    "✅ Spin ack via JDB wallet formula: B0=%.3f B1=%.3f bet=%.3f win=%s",
                    before_primary,
                    jdb.balance,
                    bet,
                    f"{jdb.win:.3f}" if jdb.win is not None else "0",
                )
                return True
        after = read_in_game_footer_primary(
            page,
            hybrid_locator,
            game_config,
            allow_lobby_b0_fallback=False,
        )
        delta_min = (
            min_bet
            if min_bet is not None
            else resolve_spin_delta_min_bet(None, game_config)
        )
        return (
            primary_balance_spin_delta(
                before_primary, after, min_bet=delta_min
            )
            is not None
        )

    after = read_in_game_footer_primary(
        page,
        hybrid_locator,
        game_config,
        allow_lobby_b0_fallback=False,
    )
    delta_min = (
        min_bet
        if min_bet is not None
        else resolve_spin_delta_min_bet(None, game_config)
    )
    if primary_balance_spin_delta(
        before_primary, after, min_bet=delta_min
    ) is not None:
        return True
    if detect_in_game_win_banner(page, hybrid_locator):
        after = read_in_game_footer_primary(
            page,
            hybrid_locator,
            game_config,
            allow_lobby_b0_fallback=False,
        )
        return (
            primary_balance_spin_delta(
                before_primary, after, min_bet=delta_min
            )
            is not None
        )
    return False


def capture_lobby_wallet_b0(
    page,
    hybrid_locator,
    global_config: dict,
    entry_mode: str,
    game_conf: dict,
) -> float | None:
    click_lobby_wallet_refresh(page, global_config, entry_mode, label="B0")
    b0 = read_lobby_wallet_balance(page, hybrid_locator, global_config, entry_mode)
    if b0 is not None:
        game_conf[audit_lobby_b0_key()] = b0
    return b0


def return_to_lobby(page, global_config: dict, entry_mode: str) -> None:
    if entry_mode == ENTRY_MODE_COMBOBURST_PORTAL:
        url = get_comboburst_config(global_config).get(
            "lobby_url", "https://games-dev.comboburst.com/home/index.html"
        )
    else:
        url = get_client_env_config(global_config).get("web_url", "")
    if not url:
        return
    logger.info("🔄 Returning to lobby for wallet audit: %s", url)
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(2.0)


def wait_for_lobby_wallet_balance(
    page,
    hybrid_locator,
    global_config: dict,
    entry_mode: str,
    expected: float,
    *,
    tolerance: float = DEFAULT_CROSS_VENUE_TOLERANCE,
    timeout_sec: float = LOBBY_WALLET_SYNC_TIMEOUT_SEC,
) -> float | None:
    """Poll lobby wallet until it matches in-game B1; clicks ↻ refresh before each read."""
    deadline = time.time() + timeout_sec
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        click_lobby_wallet_refresh(page, global_config, entry_mode, label=f"sync#{attempt}")
        val = read_lobby_wallet_balance(page, hybrid_locator, global_config, entry_mode)
        if val is not None and abs(val - expected) <= tolerance:
            logger.info(
                "✅ Lobby wallet synced to in-game B1 (attempt %s): %.2f",
                attempt,
                val,
            )
            return val
        if val is not None:
            if attempt <= 1:
                logger.info(
                    "⏳ Lobby wallet %.2f != expected %.2f (attempt %s); retry after refresh...",
                    val,
                    expected,
                    attempt,
                )
            else:
                logger.debug(
                    "Lobby wallet %.2f != expected %.2f (attempt %s); retry after refresh...",
                    val,
                    expected,
                    attempt,
                )
        time.sleep(LOBBY_WALLET_SYNC_POLL_SEC)
    click_lobby_wallet_refresh(page, global_config, entry_mode, label="final")
    return read_lobby_wallet_balance(page, hybrid_locator, global_config, entry_mode)


def audit_cross_venue_wallet(
    b0_lobby: float | None,
    b1_in_game: float | None,
    b1_lobby: float | None,
    *,
    tolerance: float = DEFAULT_CROSS_VENUE_TOLERANCE,
    require_lobby_change: bool = True,
    min_bet: float = DEFAULT_MIN_BET_DELTA,
    console_summary: dict | None = None,
) -> tuple[bool, str]:
    """Compare in-game footer vs lobby wallet after exiting the game."""
    if b1_in_game is None:
        return False, "in-game primary balance (B1) not captured"
    if b1_lobby is None:
        return False, "lobby wallet (B1) not detected after return"
    if abs(b1_lobby - b1_in_game) > tolerance:
        return (
            False,
            f"cross-venue mismatch: in-game B1={b1_in_game:.2f} vs lobby={b1_lobby:.2f} "
            f"(tol={tolerance})",
        )
    if require_lobby_change:
        lobby_ok = False
        if console_summary and console_summary.get("bet") is not None:
            bet = float(console_summary["bet"])
            win = console_summary.get("win")
            cb0 = console_summary.get("b0")
            cb1 = console_summary.get("b1")
            if win is None and cb0 is not None and cb1 is not None:
                win = round(float(cb1) - float(cb0) + bet, 4)
            if win is not None:
                if cb1 is not None and abs(b1_lobby - float(cb1)) <= tolerance:
                    lobby_ok = True
                elif cb0 is not None:
                    expected = round(float(cb0) - bet + float(win), 4)
                    if abs(b1_lobby - expected) <= tolerance:
                        lobby_ok = True
                    else:
                        return (
                            False,
                            f"lobby B1 vs console expected: console_B0={float(cb0):.2f} "
                            f"bet={bet:.2f} win={float(win):.2f} "
                            f"expected={expected:.2f} actual={b1_lobby:.2f}",
                        )
                if lobby_ok and b0_lobby is not None and cb0 is not None:
                    if abs(b0_lobby - float(cb0)) > tolerance:
                        logger.warning(
                            "Lobby B0 at entry (%.2f) differs from console B0 (%.2f); "
                            "using console settlement for audit.",
                            b0_lobby,
                            float(cb0),
                        )
        if (
            not lobby_ok
            and b0_lobby is not None
            and primary_balance_spin_delta(b0_lobby, b1_lobby, min_bet=min_bet) is not None
        ):
            lobby_ok = True
        if not lobby_ok:
            if b0_lobby is not None:
                return (
                    False,
                    f"lobby wallet unchanged: B0={b0_lobby:.2f} B1={b1_lobby:.2f} "
                    f"(no real bet detected)",
                )
            return False, "lobby wallet change could not be verified (no B0 snapshot)"
    logger.info(
        "✅ Cross-venue wallet audit OK: lobby B0=%s B1=%.2f, in-game B1=%.2f",
        f"{b0_lobby:.2f}" if b0_lobby is not None else "n/a",
        b1_lobby,
        b1_in_game,
    )
    return True, "OK"


def run_post_spin_lobby_audit(
    page,
    hybrid_locator,
    global_config: dict,
    entry_mode: str,
    game_conf: dict,
    artifact_handler,
    *,
    require_lobby_change: bool = True,
) -> tuple[bool, str]:
    """Exit to lobby and verify wallet matches in-game footer balance."""
    b0 = game_conf.get(audit_lobby_b0_key())
    b1_in_game = game_conf.get(audit_in_game_b1_key())
    if b1_in_game is None:
        b1_in_game = read_in_game_footer_primary(page, hybrid_locator, game_conf)
    elif not is_plausible_ingame_balance(b1_in_game, game_conf.get(audit_lobby_b0_key())):
        logger.warning(
            "In-game B1 %.2f looks like a footer fragment; re-reading before lobby audit",
            b1_in_game,
        )
        b1_in_game = read_in_game_footer_primary(page, hybrid_locator, game_conf)

    return_to_lobby(page, global_config, entry_mode)
    if b1_in_game is not None:
        b1_lobby = wait_for_lobby_wallet_balance(
            page,
            hybrid_locator,
            global_config,
            entry_mode,
            b1_in_game,
        )
    else:
        b1_lobby = read_lobby_wallet_balance(page, hybrid_locator, global_config, entry_mode)
    artifact_handler.capture(page, "audit_lobby_wallet", "gameplay", attach_to_allure=True)

    ok, reason = audit_cross_venue_wallet(
        b0,
        b1_in_game,
        b1_lobby,
        require_lobby_change=require_lobby_change,
        console_summary=game_conf.get(audit_console_summary_key()),
        min_bet=resolve_spin_min_bet(game_conf),
    )
    return ok, reason


def is_cached_coord_stale(
    x: float,
    y: float,
    page,
    spin_config: dict | None,
) -> bool:
    """True when cached coords sit in portal chrome or outside portrait spin region."""
    from core.game_utils import (
        PORTAL_CHROME_CLICK_MARGIN_PX,
        PORTRAIT_DEFAULT_SPIN_REGION,
        _portal_chrome_exclusions,
    )

    exclusions = _portal_chrome_exclusions(spin_config)
    if exclusions:
        vp_w = page.viewport_size["width"]
        vp_h = page.viewport_size["height"]
        for exc in exclusions:
            x0 = exc["x_start"] * vp_w
            x1 = exc["x_end"] * vp_w
            y0 = exc["y_start"] * vp_h
            if x0 <= x <= x1 and y >= y0 - PORTAL_CHROME_CLICK_MARGIN_PX:
                return True
    if spin_config and spin_config.get("_layout") == "portrait":
        region = spin_config.get("region") or PORTRAIT_DEFAULT_SPIN_REGION
        vp_w = page.viewport_size["width"]
        vp_h = page.viewport_size["height"]
        if vp_w and vp_h:
            margin = 0.03
            x_frac = x / vp_w
            y_frac = y / vp_h
            in_region = (
                region["x_start"] - margin
                <= x_frac
                <= region["x_end"] + margin
                and region["y_start"] - margin
                <= y_frac
                <= region["y_end"] + margin
            )
            if not in_region:
                return True
    return False
