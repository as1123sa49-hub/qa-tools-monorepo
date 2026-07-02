#!/usr/bin/env python3
"""Parse mindmap platform-format MD and import via testing-hub MCP HTTP API."""
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

MCP_URL = "http://10.10.66.10:8001/mcp/"
PRODUCT_ID = "0501a731-1fe9-4fcb-ba84-197fff4af09e"
GROUP_ID = "78c1002b-1a58-4c57-ae21-696ed12aaafb"
ROOT_MODULE_NAME = "CMB官網-前端"

PRIORITY_MAP = {"P0": 1, "P1": 2, "P2": 3}


def load_auth_header():
    mcp_path = Path.home() / ".cursor" / "mcp.json"
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    return data["mcpServers"]["testing-hub"]["headers"]["Authorization"]


def mcp_call(auth: str, tool: str, arguments: dict):
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    req = Request(
        MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
    # SSE or JSON line
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line.startswith(":"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "result" in msg:
            return msg["result"]
        if "error" in msg:
            raise RuntimeError(msg["error"])
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"MCP parse failed: {body[:500]}") from e


def parse_content(text: str):
    text = text.replace("\r\n", "\n")
    parts = text.split("=== 模組路徑 ===")
    cases = []
    for part in parts[1:]:
        block = "=== 模組路徑 ===" + part
        m_path = re.search(r"=== 模組路徑 ===\s*\n(.+?)\n\s*\n=== 測試案例 ===", block, re.S)
        m_case = re.search(
            r"=== 測試案例 ===\n"
            r"標題：(.+?)\n"
            r"優先度：(.+?)\n"
            r"案例描述：(.+?)\n"
            r"前置條件：(.+?)\n\n"
            r"=== 測試步驟 ===\n(.+)",
            block,
            re.S,
        )
        if not m_path or not m_case:
            continue
        path = m_path.group(1).strip()
        title = m_case.group(1).strip()
        priority = PRIORITY_MAP.get(m_case.group(2).strip(), 1)
        description = m_case.group(3).strip()
        pre = m_case.group(4).strip()
        if pre in ("無", "—", "-", ""):
            pre = None
        steps_text = m_case.group(5).strip()
        steps = []
        for sm in re.finditer(
            r"(\d+)\.\s*動作：(.+?)\n\s*預期：(.+?)(?=\n\d+\.\s*動作：|\Z)",
            steps_text,
            re.S,
        ):
            steps.append(
                {
                    "step_number": int(sm.group(1)),
                    "action": sm.group(2).strip(),
                    "expected_result": sm.group(3).strip(),
                }
            )
        segments = [s.strip() for s in path.split("›")]
        cases.append(
            {
                "path": path,
                "segments": segments,
                "leaf": segments[-1] if segments else path,
                "title": title,
                "priority": priority,
                "description": description,
                "preconditions": pre,
                "test_steps": steps,
            }
        )
    return cases


def ensure_module(auth, cache, parent_id, name):
    key = (parent_id, name)
    if key in cache:
        return cache[key]
    res = mcp_call(
        auth,
        "create_module",
        {
            "name": name,
            "parent_id": parent_id,
            "group_id": GROUP_ID,
            "product_ids": [PRODUCT_ID],
        },
    )
    content = res.get("content") if isinstance(res, dict) else None
    if content and isinstance(content, list):
        mod = json.loads(content[0].get("text", "{}"))
    elif isinstance(res, dict) and "id" in res:
        mod = res
    else:
        mod = res
    mid = mod["id"]
    cache[key] = mid
    return mid


def main():
    if len(sys.argv) < 2:
        print("Usage: import_mindmap_to_qa.py <mindmap.md> [root_module_id]", file=sys.stderr)
        sys.exit(1)
    md_path = Path(sys.argv[1])
    root_id = sys.argv[2] if len(sys.argv) > 2 else None
    text = md_path.read_text(encoding="utf-8")
    cases = parse_content(text)
    if not cases:
        print("No cases parsed", file=sys.stderr)
        sys.exit(1)

    auth = load_auth_header()
    module_cache = {}

    if not root_id:
        root_id = ensure_module(auth, module_cache, None, ROOT_MODULE_NAME)
    else:
        module_cache[(None, ROOT_MODULE_NAME)] = root_id

    ok, fail = 0, 0
    errors = []

    for i, c in enumerate(cases, 1):
        parent_id = root_id
        segs = c["segments"]
        # path like 通用功能 › [頂部]功能列 — use all segments under root
        if segs and segs[0] in ("前端", "通用功能"):
            segs = segs[1:] if len(segs) > 1 else segs
        for seg in segs[:-1]:
            parent_id = ensure_module(auth, module_cache, parent_id, seg)
        leaf_id = ensure_module(auth, module_cache, parent_id, c["leaf"])

        display_title = f"{c['leaf']} - {c['title']}"
        try:
            mcp_call(
                auth,
                "create_test_case",
                {
                    "title": display_title,
                    "module_id": leaf_id,
                    "module_name": c["leaf"],
                    "group_name": "QA",
                    "description": c["description"],
                    "preconditions": c["preconditions"],
                    "priority": c["priority"],
                    "test_steps": c["test_steps"],
                    "tags": ["CMB官網", "前端", "mindmap匯入"],
                },
            )
            ok += 1
            print(f"[{i}/{len(cases)}] OK {display_title}")
        except Exception as e:
            fail += 1
            errors.append((display_title, str(e)))
            print(f"[{i}/{len(cases)}] FAIL {display_title}: {e}", file=sys.stderr)

    print(f"\nDone: {ok} ok, {fail} fail, total {len(cases)}")
    if errors:
        print("Errors:", file=sys.stderr)
        for t, e in errors[:10]:
            print(f"  - {t}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
