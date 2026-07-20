import json
import logging
import re
import time

logger = logging.getLogger(__name__)



WIN_SCALE = 10000  # TotalWin / MainWin JSON string → display balance units





class GameConsoleListener:

    def __init__(self):

        self._latest_data = {}

        self._is_active = False
        self._page = None
        self._attached: set[int] = set()
        self._last_msg_fp: tuple[str, str] | None = None
        self._last_msg_ts = 0.0



    def start(self, page):

        if self._is_active:

            return

        self._page = page
        self._attach_context(page)
        page.on("frameattached", self._on_frame_attached)
        self.refresh_frames()

        self._is_active = True

        logger.debug("👂 Listener attached (page + frameattached).")

    def refresh_frames(self) -> int:
        """Attach to any new frames (e.g. after game iframe loads)."""
        if not self._page:
            return 0
        before = len(self._attached)
        for frame in self._page.frames:
            self._attach_context(frame)
        added = len(self._attached) - before
        if added:
            logger.info("👂 Console listener attached to %s additional frame(s).", added)
        return added

    def _on_frame_attached(self, frame) -> None:
        self._attach_context(frame)

    def _attach_context(self, ctx) -> None:
        ctx_id = id(ctx)
        if ctx_id in self._attached:
            return
        try:
            ctx.on("console", self._handle_console_message)
            self._attached.add(ctx_id)
            logger.debug("👂 Listener attached to %s.", type(ctx).__name__)
        except Exception as exc:
            logger.debug("Could not attach console listener to %s: %s", type(ctx).__name__, exc)

    def note_visual_spin_started(self) -> None:
        """Mark spin as started via OCR when console events are unavailable."""
        self._latest_data["visual_spin_started"] = True
        self._latest_data["spin_triggered"] = True
        self._open_spin_window()
        logger.info("🎰 Spin started (visual fallback).")



    @staticmethod

    def _spin_defaults() -> dict:

        return {

            "spin_triggered": False,

            "spin_response_ok": False,

            "has_spin_response": False,

            "spin_txn_id": None,

            "spin_cmd": None,

            "balance_before_spin": None,

            "balance_after_bet": None,

            "balance_after_settle": None,

            "bet_amount": None,

            "win_amount": None,

            "in_free_game": False,

            "free_game_finished": False,

            "spin_settled": False,

            "total_win_raw": None,

            "is_free_game": False,

            "fg_total": 0,

            "game_mode": 1,

            "current_balance": None,

            "spin_window_open": False,

            "balance_trace": [],

            "recivied_spin_json_seen": False,

            "ui_reported_win": 0.0,

            "ui_bottom_normal_seen": False,

            "awaiting_post_spin_balance": False,

            "visual_spin_started": False,

        }



    def clear(self):

        """Reset spin tracking for a new round. Keeps last known balance as B0 hint."""

        preserved_balance = self._latest_data.get("current_balance")

        self._latest_data = self._spin_defaults()

        if preserved_balance is not None:

            self._latest_data["current_balance"] = preserved_balance

        logger.debug("🧹 Listener spin state cleared.")



    def get_hint(self, key, default=None):

        return self._latest_data.get(key, default)

    def has_spin_acknowledged(self) -> bool:
        """True after ReciviedSpinResponse or Spin response Code=0 with TxnId."""
        if self.get_hint("has_spin_response"):
            return True
        return bool(self.get_hint("spin_response_ok") and self.get_hint("spin_txn_id"))

    def _sync_spin_acknowledged_flag(self) -> None:
        if self.has_spin_acknowledged():
            self._latest_data["has_spin_response"] = True

    def is_spin_settled(self) -> bool:

        if not self.get_hint("spin_settled"):

            return False

        if not (self.get_hint("spin_triggered") or self.get_hint("spin_cmd")):

            return False

        if not self.get_hint("has_spin_response"):

            return False

        if not self.get_hint("spin_response_ok"):

            return False

        if self.get_hint("bet_amount") is None:

            return False

        if self.get_hint("balance_before_spin") is None:

            return False

        if self.get_hint("balance_after_settle") is None:

            return False

        if self.get_hint("in_free_game"):

            return False

        return True



    def get_settlement_summary(self) -> dict:

        b0 = self.get_hint("balance_before_spin")

        b1 = self.get_hint("balance_after_settle")

        bet = self.get_hint("bet_amount")

        win = self.get_hint("win_amount")

        if win is None and b0 is not None and b1 is not None and bet is not None:

            win = round(b1 - b0 + bet, 4)

        return {

            "b0": b0,

            "b1": b1,

            "bet": bet,

            "win": win,

            "txn_id": self.get_hint("spin_txn_id"),

            "spin_cmd": self.get_hint("spin_cmd"),

            "total_win_raw": self.get_hint("total_win_raw"),

        }



    def _open_spin_window(self) -> None:

        if self.get_hint("spin_window_open"):

            return

        self._latest_data["spin_window_open"] = True

        trace: list[float] = []

        current = self.get_hint("current_balance")

        if current is not None:

            trace.append(current)

        self._latest_data["balance_trace"] = trace

        logger.debug("📂 Spin window opened (balance snapshot=%s)", current)



    def _append_balance_trace(self, new_balance: float) -> None:

        trace: list[float] = self._latest_data.setdefault("balance_trace", [])

        if trace and trace[-1] == new_balance:

            return

        trace.append(new_balance)



    def _infer_settlement_from_trace(self) -> bool:

        """Reconstruct B0/Bet/B1/Win from balance_trace (order-agnostic)."""

        trace: list[float] = list(self.get_hint("balance_trace") or [])

        if not trace:

            return (

                self.get_hint("balance_before_spin") is not None

                and self.get_hint("bet_amount") is not None

                and self.get_hint("balance_after_settle") is not None

            )



        b0 = trace[0]

        b1 = trace[-1]

        after_bet = None

        bet = None



        for value in trace[1:]:

            if value < b0 - 0.001:

                after_bet = value

                bet = round(b0 - value, 4)

                break



        if after_bet is None:

            if b1 < b0 - 0.001:

                after_bet = b1

                bet = round(b0 - b1, 4)

            else:

                after_bet = b0

                bet = 0.0



        self._latest_data["balance_before_spin"] = b0

        self._latest_data["balance_after_bet"] = after_bet

        self._latest_data["bet_amount"] = bet

        self._latest_data["balance_after_settle"] = b1



        win = None

        raw = self.get_hint("total_win_raw")

        if raw is not None:

            try:

                win = round(int(raw) / WIN_SCALE, 4)

            except (ValueError, TypeError):

                pass

        if win is None:

            win = round(b1 - b0 + bet, 4)

        self._latest_data["win_amount"] = win

        return True



    def _on_balance_change(self, new_balance: float) -> None:

        self._latest_data["current_balance"] = new_balance



        if self.get_hint("spin_window_open"):

            self._append_balance_trace(new_balance)

            self._try_finalize_post_spin_balance()



        if self.get_hint("free_game_finished") and self.get_hint("spin_window_open"):

            if self._infer_settlement_from_trace():

                self._latest_data["spin_settled"] = True

                self._latest_data["spin_window_open"] = False

                summary = self.get_settlement_summary()

                logger.info(

                    f"✅ FG settled: B0={summary['b0']}, B1={summary['b1']}, "

                    f"Bet={summary['bet']}, Win={summary['win']}"

                )



    def _mark_spin_settled(self) -> None:

        if self.get_hint("in_free_game"):

            return

        if not self._infer_settlement_from_trace():

            logger.warning("UIBottomNormal received but settlement fields could not be inferred")

            return

        self._latest_data["spin_settled"] = True

        self._latest_data["spin_window_open"] = False

        summary = self.get_settlement_summary()

        logger.info(

            f"✅ Spin settled: B0={summary['b0']}, B1={summary['b1']}, "

            f"Bet={summary['bet']}, Win={summary['win']}"

        )



    def _try_finalize_post_spin_balance(self) -> None:

        if not self.get_hint("awaiting_post_spin_balance"):

            return

        if not self.get_hint("ui_bottom_normal_seen") or self.get_hint("spin_settled"):

            return

        if self.get_hint("in_free_game"):

            return

        if not self._infer_settlement_from_trace():

            return

        after_bet = self.get_hint("balance_after_bet")

        b1 = self.get_hint("balance_after_settle")

        if after_bet is None or b1 is None:

            return

        if b1 + 0.001 < after_bet:

            return

        self._latest_data["awaiting_post_spin_balance"] = False

        self._mark_spin_settled()



    def _handle_ui_bottom_normal(self) -> None:

        has_spin = self.get_hint("spin_triggered") or self.get_hint("spin_cmd")

        if not (has_spin and self.has_spin_acknowledged()):

            return

        self._latest_data["ui_bottom_normal_seen"] = True

        ui_win = float(self.get_hint("ui_reported_win") or 0)

        if self.get_hint("recivied_spin_json_seen") or ui_win <= 0:

            self._mark_spin_settled()

            return

        self._latest_data["awaiting_post_spin_balance"] = True



    def _handle_console_message(self, msg):

        text = msg.text
        msg_type = getattr(msg, "type", "")
        fp = (text[:300], str(msg_type))
        now = time.monotonic()
        if fp == self._last_msg_fp and now - self._last_msg_ts < 0.05:
            return
        self._last_msg_fp = fp
        self._last_msg_ts = now



        if "SpinTriggerDispatchEvent" in text or "OnSpinTriggerEvent" in text:

            self._latest_data["spin_triggered"] = True

            self._open_spin_window()

            logger.info("🎰 Spin triggered.")



        elif "SendCommend:" in text and "cmd:" in text:

            match = re.search(r"cmd:\s*(\S+)", text)

            if match:

                cmd = match.group(1).rstrip(",")

                if cmd != "GetBalance":

                    self._latest_data["spin_cmd"] = cmd

                    self._open_spin_window()



        elif "GetBalance response:" in text:

            balance_match = re.search(r"Balance=(\d+)", text)

            if balance_match:

                try:

                    raw = int(balance_match.group(1))

                    self._on_balance_change(round(raw / WIN_SCALE, 4))

                except (ValueError, TypeError):

                    pass



        elif "Spin response:" in text:

            code_match = re.search(r"Code=(\d+)", text)

            if code_match and code_match.group(1) == "0":

                self._latest_data["spin_response_ok"] = True

            txn_match = re.search(r"TxnId=([a-f0-9-]+)", text, re.I)

            if txn_match:

                self._latest_data["spin_txn_id"] = txn_match.group(1)

            self._sync_spin_acknowledged_flag()



        elif "OnFreeGameEnterEvent" in text:

            self._latest_data["in_free_game"] = True

            self._latest_data["is_free_game"] = True

            self._latest_data["spin_settled"] = False

            logger.info("🎁 Free Game entered.")



        elif "OnFreeGameLeaveEvent" in text:

            self._latest_data["in_free_game"] = False

            self._latest_data["free_game_finished"] = True

            self._latest_data["is_free_game"] = False

            self._latest_data["spin_settled"] = False

            logger.info("🎁 Free Game left — awaiting final balance.")



        elif "UIBottomNormalDispatchEvent" in text or "OnUIBottomNormalEvent" in text:

            self._handle_ui_bottom_normal()



        elif "OnUIAddWinEvent" in text:

            win_match = re.search(r"AddWin:\s*([\d.]+)", text)

            if win_match:

                self._latest_data["ui_reported_win"] = float(win_match.group(1))



        elif "OnSetWin:" in text:

            win_match = re.search(r"OnSetWin:\s*[\d.]+\s*->\s*([\d.]+)", text)

            if win_match:

                self._latest_data["ui_reported_win"] = float(win_match.group(1))



        elif "OnChangeBalance" in text:

            try:

                match = re.search(r"balance:\s*([\d\.,]+)", text)

                if match:

                    val_str = match.group(1).replace(",", "")

                    self._on_balance_change(float(val_str))

            except (ValueError, TypeError):

                pass



        elif "ReciviedSpinResponse" in text:

            self._latest_data["recivied_spin_json_seen"] = True

            self._latest_data["has_spin_response"] = True
            self._sync_spin_acknowledged_flag()

            if "{" not in text:

                return

            try:

                match = re.search(r"(\{.*\})", text)

                if not match:

                    return

                data = json.loads(match.group(1))

                self._parse_spin_response(data)

            except json.JSONDecodeError:

                total_match = re.search(r'"TotalWin":\s*"(\d+)"', text)

                if total_match:

                    self._latest_data["total_win_raw"] = total_match.group(1)

                main_match = re.search(r'"MainWin":\s*"(\d+)"', text)

                if main_match and not self.get_hint("total_win_raw"):

                    self._latest_data["total_win_raw"] = main_match.group(1)

            except Exception:

                pass



    def _parse_spin_response(self, data: dict):

        self._latest_data["game_mode"] = data.get("GameMode", 1)



        total_win = data.get("TotalWin") or data.get("MainWin")

        if total_win is not None:

            self._latest_data["total_win_raw"] = str(total_win)



        mg = data.get("MGResult") or {}

        tumble = mg.get("MGTumbleList", []) if mg else []

        if isinstance(tumble, list):

            self._latest_data["tumble_count"] = len(tumble)



        fg_result = data.get("FGResult") or {}

        if fg_result:

            total = fg_result.get("TotalSpin") or fg_result.get("totalSpin") or 0

            current = fg_result.get("CurrentSpin") or fg_result.get("currentSpin") or 0

            self._latest_data["fg_total"] = total

            if total > 0:

                logger.info(f"🕵️ FG in response: Total={total}, Current={current}")


