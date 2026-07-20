"""
Raw CDP (Chrome DevTools Protocol) client — minimal domain-free interaction.

只用 Page.captureScreenshot 和 Input.dispatchMouseEvent/dispatchKeyEvent，
不啟用任何 CDP domain (Runtime, Page, Debugger 等)，
避免觸發 JILI astarte2 的反調試偵測。
"""
import asyncio
import base64
import json
import logging

import aiohttp

logger = logging.getLogger(__name__)

_MSG_ID = 0


def _next_id():
    global _MSG_ID
    _MSG_ID += 1
    return _MSG_ID


async def _find_game_ws_url(debug_port: int = 9222, url_match: str = "jlfafafa3.com") -> str | None:
    """從 Chrome debug endpoint 找到遊戲頁面的 WebSocket URL。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{debug_port}/json/list") as resp:
                targets = await resp.json()
        for t in targets:
            if url_match in t.get("url", "") and t.get("type") == "page":
                return t["webSocketDebuggerUrl"]
    except Exception as e:
        logger.error(f"❌ Failed to find game target: {e}")
    return None


async def _send_cdp(ws, method: str, params: dict = None) -> dict:
    """Send a CDP command and wait for its response."""
    msg_id = _next_id()
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send_json(payload)

    # Read responses until we get ours (skip events)
    while True:
        msg = await ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("id") == msg_id:
                return data
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            return {"error": {"message": "WebSocket closed"}}


async def raw_screenshot(debug_port: int = 9222) -> bytes | None:
    """Take a PNG screenshot via raw CDP without enabling any domain."""
    ws_url = await _find_game_ws_url(debug_port)
    if not ws_url:
        logger.error("❌ No game target found for raw screenshot")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, max_msg_size=50 * 1024 * 1024) as ws:
                resp = await _send_cdp(ws, "Page.captureScreenshot", {"format": "png"})
                if "result" in resp and "data" in resp["result"]:
                    return base64.b64decode(resp["result"]["data"])
                else:
                    logger.error(f"❌ Screenshot failed: {resp.get('error', resp)}")
                    return None
    except Exception as e:
        logger.error(f"❌ Raw screenshot exception: {e}")
        return None


async def raw_click(x: float, y: float, debug_port: int = 9222):
    """Send a mouse click at (x, y) via raw CDP Input.dispatchMouseEvent."""
    ws_url = await _find_game_ws_url(debug_port)
    if not ws_url:
        logger.error("❌ No game target found for raw click")
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                await _send_cdp(ws, "Input.dispatchMouseEvent", {
                    "type": "mousePressed",
                    "x": int(x), "y": int(y),
                    "button": "left", "clickCount": 1,
                })
                await _send_cdp(ws, "Input.dispatchMouseEvent", {
                    "type": "mouseReleased",
                    "x": int(x), "y": int(y),
                    "button": "left", "clickCount": 1,
                })
    except Exception as e:
        logger.error(f"❌ Raw click exception: {e}")


async def raw_type(text: str, debug_port: int = 9222):
    """Type text character by character via raw CDP Input.dispatchKeyEvent."""
    ws_url = await _find_game_ws_url(debug_port)
    if not ws_url:
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url) as ws:
                for char in text:
                    await _send_cdp(ws, "Input.dispatchKeyEvent", {
                        "type": "char",
                        "text": char,
                    })
    except Exception as e:
        logger.error(f"❌ Raw type exception: {e}")


async def raw_get_page_url(debug_port: int = 9222) -> str | None:
    """Get the current URL of the game page from target info."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{debug_port}/json/list") as resp:
                targets = await resp.json()
        for t in targets:
            if "jlfafafa3.com" in t.get("url", "") and t.get("type") == "page":
                return t["url"]
    except Exception:
        pass
    return None
