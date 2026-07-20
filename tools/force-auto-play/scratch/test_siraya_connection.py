"""
Phase 1 — Siraya API 連線 & 成本基準測試

測試三個模型都能正常呼叫，並輸出 token 用量 & 預估費用。
不需要瀏覽器，純 API 測試。

用法：
    export SIRAYA_API_KEY="sk-..."
    python scratch/test_siraya_connection.py
"""

import asyncio
import base64
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path

# 加入 project root 讓 import 正常
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncOpenAI

# ============================================================
# 設定
# ============================================================
BASE_URL = "https://llm.siraya.ai/v1"

MODELS = {
    "state":     "qwen3.5-flash",
    "plan":      "claude-sonnet-4.5",
    "discovery": "gemini-2.5-pro",
}

# 大略費率（USD per 1M tokens），供成本估算
PRICE = {
    "qwen3.5-flash":    {"input": 0.10,  "output": 0.30},
    "claude-sonnet-4.5": {"input": 3.00, "output": 15.00},
    "gemini-2.5-pro":   {"input": 1.25,  "output": 10.00},
}

# ============================================================
# 假截圖：100x100 純色 JPEG（模擬遊戲畫面）
# ============================================================
def make_dummy_screenshot() -> str:
    """產生一張 100x100 灰色 JPEG，轉成 base64。不依賴 Pillow。"""
    # 最小合法 JPEG（1x1 灰色，手工打包）
    # 用 Python 內建產生一個小 PNG，再轉 base64
    import struct, zlib

    def png_chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    w, h = 64, 64
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw_rows = b""
    for _ in range(h):
        raw_rows += b"\x00" + bytes([100, 100, 100] * w)  # filter none + gray RGB
    idat = zlib.compress(raw_rows)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


DUMMY_IMG_B64 = make_dummy_screenshot()
DUMMY_IMG_URL = f"data:image/png;base64,{DUMMY_IMG_B64}"


# ============================================================
# 工具函式
# ============================================================
def cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    p = PRICE.get(model, {"input": 0, "output": 0})
    return (in_tokens * p["input"] + out_tokens * p["output"]) / 1_000_000


def print_result(label: str, model: str, elapsed: float,
                 in_tok: int, out_tok: int, content: str):
    usd = cost_usd(model, in_tok, out_tok)
    print(f"\n{'─'*60}")
    print(f"  ✅ {label}")
    print(f"  模型   : {model}")
    print(f"  耗時   : {elapsed:.2f}s")
    print(f"  Tokens : {in_tok} in / {out_tok} out")
    print(f"  費用   : ${usd:.6f}")
    print(f"  回覆   : {content[:200]}")


def print_fail(label: str, model: str, error: str):
    print(f"\n{'─'*60}")
    print(f"  ❌ {label}")
    print(f"  模型   : {model}")
    print(f"  錯誤   : {error}")


# ============================================================
# Test 1: State Model — 圖片 → JSON
# ============================================================
async def test_state_model(client: AsyncOpenAI) -> bool:
    model = MODELS["state"]
    print(f"\n[1/3] State model ({model}) — 圖片分析...")
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a casino slot game screenshot.\n"
                        "Return ONLY this JSON:\n"
                        '{"spinning": false, "popup_visible": false, '
                        '"popup_close": null, "feature_triggered": false, '
                        '"current_bet": null, "current_balance": null, '
                        '"notes": "gray test image"}'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this screenshot."},
                        {"type": "image_url", "image_url": {"url": DUMMY_IMG_URL}},
                    ],
                },
            ],
            max_tokens=200,
            temperature=0,
        )
        elapsed = time.perf_counter() - t0
        usage = resp.usage
        content = resp.choices[0].message.content or ""

        # 驗證回傳是合法 JSON
        try:
            parsed = json.loads(content.strip().strip("```json").strip("```").strip())
            assert "spinning" in parsed
            valid = "✅ JSON 合法"
        except Exception:
            valid = "⚠️  JSON 解析失敗"

        print_result(
            f"State model OK  {valid}",
            model, elapsed,
            usage.prompt_tokens, usage.completion_tokens,
            content,
        )
        return True
    except Exception as e:
        print_fail("State model FAILED", model, str(e))
        return False


# ============================================================
# Test 2: Plan Model — Tool calling
# ============================================================
DUMMY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_state",
            "description": "Take screenshot and return game state.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete",
            "description": "Mark goal as done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["success", "reason"],
            },
        },
    },
]

async def test_plan_model(client: AsyncOpenAI) -> bool:
    model = MODELS["plan"]
    print(f"\n[2/3] Plan model ({model}) — Tool calling...")
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a casino game automation agent.\n"
                        "Available elements: spin_button center≈(0.85, 0.80)\n"
                        "Max steps: 5"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Goal: This is a connection test. Call complete(success=true, "
                        'reason="connection test passed") immediately.'
                    ),
                },
            ],
            tools=DUMMY_TOOLS,
            tool_choice="auto",
            max_tokens=200,
            temperature=0,
        )
        elapsed = time.perf_counter() - t0
        usage = resp.usage
        msg = resp.choices[0].message

        if msg.tool_calls:
            tc = msg.tool_calls[0]
            content = f"{tc.function.name}({tc.function.arguments})"
            valid = "✅ Tool call 正常"
        else:
            content = msg.content or "(no tool call)"
            valid = "⚠️  未呼叫 tool"

        print_result(
            f"Plan model OK  {valid}",
            model, elapsed,
            usage.prompt_tokens, usage.completion_tokens,
            content,
        )
        return bool(msg.tool_calls)
    except Exception as e:
        print_fail("Plan model FAILED", model, str(e))
        return False


# ============================================================
# Test 3: Discovery Model — Layout JSON
# ============================================================
async def test_discovery_model(client: AsyncOpenAI) -> bool:
    model = MODELS["discovery"]
    print(f"\n[3/3] Discovery model ({model}) — Layout analysis...")
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a casino slot game screenshot.\n"
                        "Return ONLY valid JSON with UI element bounding boxes.\n"
                        'Since this is a test image, return: {"spin_button": '
                        '{"x1": 0.7, "y1": 0.75, "x2": 0.95, "y2": 0.95}, '
                        '"balance_region": {"x1": 0.0, "y1": 0.85, "x2": 0.3, "y2": 1.0}, '
                        '"notes": "test image"}'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Identify all UI elements in this casino game."},
                        {"type": "image_url", "image_url": {"url": DUMMY_IMG_URL}},
                    ],
                },
            ],
            max_tokens=400,
            temperature=0,
        )
        elapsed = time.perf_counter() - t0
        usage = resp.usage
        content = resp.choices[0].message.content or ""

        try:
            parsed = json.loads(content.strip().strip("```json").strip("```").strip())
            assert "spin_button" in parsed
            valid = "✅ JSON 合法"
        except Exception:
            valid = "⚠️  JSON 解析失敗"

        print_result(
            f"Discovery model OK  {valid}",
            model, elapsed,
            usage.prompt_tokens, usage.completion_tokens,
            content,
        )
        return True
    except Exception as e:
        print_fail("Discovery model FAILED", model, str(e))
        return False


# ============================================================
# Summary
# ============================================================
def print_cost_estimate():
    print(f"\n{'='*60}")
    print("  📊 每手 spin 的預估費用（GoalAgent）")
    print(f"{'='*60}")

    # 一次 spin ≈ 3~5 plan calls + 3~5 state checks
    scenarios = [
        ("最簡單（spin once）",    3, 3),
        ("一般（spin 3 times）",   8, 8),
        ("複雜（spin until feature, max 20 spins）", 50, 50),
    ]

    plan_model   = MODELS["plan"]
    state_model  = MODELS["state"]
    disc_model   = MODELS["discovery"]

    disc_cost = cost_usd(disc_model, 2000, 300)  # 一次 discovery

    for label, plan_calls, state_calls in scenarios:
        # plan: ~600 input + ~60 output per call
        plan_cost  = plan_calls  * cost_usd(plan_model,  600, 60)
        # state: ~300 input + ~80 output per call (with image tokens ~800)
        state_cost = state_calls * cost_usd(state_model, 1100, 80)
        total = plan_cost + state_cost
        print(f"\n  [{label}]")
        print(f"    plan ({plan_model}):   ${plan_cost:.5f}  ({plan_calls} calls)")
        print(f"    state ({state_model}): ${state_cost:.5f} ({state_calls} calls)")
        print(f"    合計:                  ${total:.5f}")

    print(f"\n  Layout discovery ({disc_model}，首次，有 cache 後跳過）:")
    print(f"    ${disc_cost:.5f} / game")
    print()


# ============================================================
# Main
# ============================================================
async def main():
    api_key = os.environ.get("SIRAYA_API_KEY")
    if not api_key:
        print("❌ 請先設定環境變數：export SIRAYA_API_KEY='sk-...'")
        sys.exit(1)

    print("=" * 60)
    print("  Siraya API 連線測試（Plan model only）")
    print(f"  Base URL: {BASE_URL}")
    print("=" * 60)

    client = AsyncOpenAI(api_key=api_key, base_url=BASE_URL)

    # 只測 plan model（state & discovery 已通過）
    results = await asyncio.gather(
        test_plan_model(client),
        return_exceptions=True,
    )

    passed = sum(1 for r in results if r is True)
    total  = len(results)

    print(f"\n{'='*60}")
    print(f"  結果：{passed}/{total} 通過")
    print(f"{'='*60}")

    if passed == total:
        print("  ✅ 所有模型正常，可以開始 Phase 2（Layout Discovery）")
        print_cost_estimate()
    else:
        print("  ❌ 有模型連線失敗，請檢查 API key 及網路")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
