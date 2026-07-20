#!/usr/bin/env python3
"""
Test Script Generator — 用 Claude Sonnet 4.5 自動生成 pytest 測試腳本

使用方式：
  python tools/generate_test.py "針對 COMBO slot015 spin 3 次"
  python tools/generate_test.py "JILI tiger game 登入並轉輪"

流程：
  1. 讀取核心模組原始碼
  2. 用 Claude Sonnet 4.5（透過 Siraya）生成測試腳本
  3. 存檔到 tests/generated/ 並顯示
  4. 詢問用戶：執行(y) / 放棄(n) / 編輯後執行(e)
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

# ============================================================
# 設定
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
TESTS_GENERATED = PROJECT_ROOT / "tests" / "generated"
TESTS_GENERATED.mkdir(parents=True, exist_ok=True)

SIRAYA_API_KEY = os.environ.get("SIRAYA_API_KEY")
if not SIRAYA_API_KEY:
    print("❌ 未設定 SIRAYA_API_KEY 環境變數")
    sys.exit(1)

client = AsyncOpenAI(api_key=SIRAYA_API_KEY, base_url="https://llm.siraya.ai/v1")

# ============================================================
# Context — 讀取相關模組
# ============================================================
def read_context_modules() -> str:
    """讀取核心模組原始碼作為 LLM context"""
    modules = [
        "core/cloud_vision_agent.py",
        "conftest.py",
        "config/games.yaml",
        "core/vision_client.py",
    ]
    
    context = ""
    for mod in modules:
        path = PROJECT_ROOT / mod
        if path.exists():
            content = path.read_text()
            context += f"\n\n{'='*60}\n# {mod}\n{'='*60}\n{content}\n"
        else:
            print(f"⚠️  找不到 {mod}")
    
    return context


# ============================================================
# System Prompt
# ============================================================
SYSTEM_PROMPT = """You are an expert QA automation engineer for online casino games.
Your task is to generate production-ready pytest test scripts.

## Key Principles

1. **Use GoalAgent for vision-based automation (COMBO games)**
   - LLM-driven ReAct loop: goal → plan → tool call → observe → repeat
   - Planning model decides actions; state model analyzes screenshots cheaply
   - Layout discovery is cached automatically on first run
   - Always initialize with SIRAYA_API_KEY from environment

2. **Follow async/await patterns**
   - Use AsyncOpenAI for API calls
   - Use async with page fixture (pytest-asyncio)
   - Proper error handling and logging

3. **Game-specific logic**
   - Read game config from config/games.yaml
   - Express goals in natural language passed to GoalAgent.run()
   - Use appropriate wait strategies

4. **Code quality**
   - Clear variable names and comments
   - Proper assertions and error checks
   - Log important steps
   - Handle edge cases (no balance, network timeout, etc.)

## Output Format

Generate ONLY the complete pytest test function/file. No explanation, no markdown.
Start directly with imports, end with the final line of code.

Example structure:
```python
import os
import pytest
from core.goal_agent import GoalAgent

@pytest.mark.asyncio
async def test_combo_spin():
    # setup
    # execute
    # assert
```

## Available Game Configs

Loaded from config/games.yaml:
- Provider: COMBO, JILI, etc.
- Game: id, name, category
- Mechanics: bet_levels, features, lines
- UI: action_button region, balance_check config

## GoalAgent API

```python
from core.goal_agent import GoalAgent

agent = GoalAgent(
    api_key=os.environ["SIRAYA_API_KEY"],
    plan_model="claude-sonnet-4.5",      # decides which tools to call each step
    discovery_model="gemini-2.5-pro",    # one-time UI element discovery (cached)
    state_model="qwen3.5-flash",         # cheap per-step screenshot analysis
    max_steps=50,
)

# Natural language goal drives the entire execution.
# GoalAgent automatically: discovers layout, checks state, spins, waits, handles popups.
success = await agent.run(page, game_cfg, goal="spin 3 times")
success = await agent.run(page, game_cfg, goal="spin until feature game triggers")
success = await agent.run(page, game_cfg, goal="set bet to minimum, then spin 3 times")
success = await agent.run(page, game_cfg, goal="click buy_feature and wait for result")

# Default goal from game_cfg["goal"] field, or per-category default:
goal_text = game_cfg.get("goal") or GoalAgent.default_goal(game_cfg)
success = await agent.run(page, game_cfg, goal_text)
```

## Available GoalAgent Tools (called internally by the LLM planner)

- `check_state()` → {spinning, popup_visible, popup_close, feature_triggered, current_bet, current_balance, notes}
- `click_element(element)` → click named UI element (spin_button, bet_increase, bet_decrease, buy_feature, extra_bet, ...)
- `click_at(x, y)` → click at normalized coordinate 0.0–1.0
- `wait_settled()` → poll until reels stop, auto-handles popups, returns final state
- `wait(seconds)` → pause
- `complete(success, reason)` → end the ReAct loop

Generate the test now.
"""



async def generate_test_script(goal: str) -> str:
    """用 Claude Sonnet 4.5 生成測試腳本"""
    
    print("📚 讀取模組原始碼...")
    context = read_context_modules()
    
    print("🚀 呼叫 Claude Sonnet 4.5（透過 Siraya）生成測試腳本...")
    
    response = await client.chat.completions.create(
        model="claude-sonnet-4.5",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n\n## Available Modules\n" + context,
            },
            {
                "role": "user",
                "content": f"生成以下目標的 pytest 測試腳本：\n\n{goal}",
            },
        ],
        max_tokens=4000,
        temperature=0,
    )
    
    code = response.choices[0].message.content or ""
    
    # 移除可能的 markdown code fence
    code = code.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1] if "\n" in code else code[3:]
    if code.endswith("```"):
        code = code.rsplit("\n", 1)[0] if "\n" in code else code[:-3]
    
    return code.strip()


def display_code(code: str, max_lines: int = 50) -> None:
    """漂亮地顯示代碼"""
    lines = code.split("\n")
    
    if len(lines) > max_lines:
        print("\n📄 生成的測試腳本（前 50 行）：\n")
        print("\n".join(lines[:max_lines]))
        print(f"\n... （共 {len(lines)} 行，省略 {len(lines) - max_lines} 行）\n")
    else:
        print("\n📄 生成的測試腳本：\n")
        print(code)
        print()


async def save_and_review(code: str) -> str | None:
    """保存腳本並詢問用戶是否執行"""
    
    # 生成檔案名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_generated_{timestamp}.py"
    filepath = TESTS_GENERATED / filename
    
    # 保存
    filepath.write_text(code)
    print(f"✅ 腳本已保存到：{filepath.relative_to(PROJECT_ROOT)}\n")
    
    # 顯示
    display_code(code)
    
    # 詢問用戶
    while True:
        prompt = "執行? (y=是 / n=放棄 / e=編輯後執行): "
        choice = input(prompt).lower().strip()
        
        if choice == "y":
            return str(filepath)
        elif choice == "n":
            print("❌ 已放棄執行")
            return None
        elif choice == "e":
            # 用 $EDITOR 編輯
            editor = os.environ.get("EDITOR", "vim")
            subprocess.call([editor, str(filepath)])
            # 重新顯示編輯後的內容
            code = filepath.read_text()
            display_code(code)
            # 再問一次
            continue
        else:
            print("❌ 輸入無效，請輸入 y/n/e")


async def run_test(filepath: str) -> bool:
    """執行 pytest"""
    print(f"\n🧪 執行測試：{Path(filepath).name}\n")
    
    result = subprocess.run(
        ["pytest", filepath, "-v", "-s"],
        cwd=PROJECT_ROOT,
    )
    
    return result.returncode == 0


async def main():
    if len(sys.argv) < 2:
        print("使用方式：python tools/generate_test.py \"目標描述\"\n")
        print("範例：")
        print('  python tools/generate_test.py "針對 COMBO slot015 spin 3 次"')
        print('  python tools/generate_test.py "JILI tiger game 登入並轉輪"')
        sys.exit(1)
    
    goal = " ".join(sys.argv[1:])
    print(f"📋 目標：{goal}\n")
    
    try:
        # 生成
        code = await generate_test_script(goal)
        
        # 保存並詢問
        filepath = await save_and_review(code)
        
        if filepath:
            # 執行
            success = await run_test(filepath)
            if success:
                print("\n✅ 測試通過！")
            else:
                print("\n❌ 測試失敗")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  用戶中斷")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
