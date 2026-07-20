#!/usr/bin/env python
"""清理並生成 Allure 報告的工具腳本"""

import argparse
import os
import shutil
import subprocess
import sys


def remove_directory(dir_path: str) -> None:
    """刪除目錄（如果存在）"""
    if os.path.exists(dir_path):
        print(f"正在刪除 {dir_path}...")
        shutil.rmtree(dir_path)
        print(f"✓ 已刪除 {dir_path}")
    else:
        print(f"跳過 {dir_path}（不存在）")


def run_command(command: list[str], description: str) -> bool:
    """執行命令並回傳是否成功"""
    print(f"\n正在執行: {description}")
    print(f"命令: {' '.join(command)}")
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        print(f"✓ {description}成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description}失敗")
        if e.stderr:
            print(f"錯誤訊息: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"✗ 命令未找到: {command[0]}")
        print("請確保 Allure 已安裝並在 PATH 中")
        return False


def clean_directories():
    """清理所有報告目錄"""
    print("=== 清理報告目錄 ===\n")

    # 刪除 allure-results/ 和 allure-report/
    print("清理 Allure 目錄")
    remove_directory("allure-results")
    remove_directory("allure-report")

    # 刪除 results 和 report
    print("\n清理其他報告目錄")
    remove_directory("results")
    remove_directory("report")
    remove_directory("recordings")

    print("\n=== 清理完成！===")


def generate_and_open_report(host: str = "0.0.0.0", port: int = 0):
    """生成並開啟 Allure 報告"""
    print("=== 生成 Allure 報告 ===\n")

    # 檢查是否有 allure-results
    if not os.path.exists("allure-results") or not os.listdir("allure-results"):
        print("⚠ 沒有找到 allure-results 或目錄為空")
        print("請先執行測試生成結果，例如：")
        print("  pytest --alluredir=allure-results")
        sys.exit(1)

    # 生成 Allure 報告
    print("步驟 1/2: 生成 Allure 報告")
    success = run_command(
        ["allure", "generate", "allure-results", "--clean", "-o", "allure-report"],
        "生成 Allure 報告",
    )

    if not success:
        print("\n報告生成失敗")
        sys.exit(1)

    # 開啟 Allure 報告 (改用 Python http.server)
    print("\n步驟 2/2: 啟動報告服務")
    print(f"正在 {host}:{port if port > 0 else 50000} 啟動 Web Server...")

    try:
        import http.server
        import socketserver

        # 預設埠號
        target_port = port if port > 0 else 50000
        directory = "allure-report"

        # 建立一個簡單的固定目錄伺服器
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=directory, **kwargs)

        # 允許 port 重複使用
        socketserver.TCPServer.allow_reuse_address = True

        with socketserver.TCPServer((host, target_port), Handler) as httpd:
            print(f"\n✅ Allure 報告服務已啟動！")
            print(f"👉 請在瀏覽器開啟： http://{'127.0.0.1' if host == '0.0.0.0' else host}:{target_port}")
            print(f"👉 區域網路存取： http://(您的主機IP):{target_port}")
            print("\n按 Ctrl+C 即可終止服務\n")
            httpd.serve_forever()

    except KeyboardInterrupt:
        print("\n\n=== 服務已終止 ===")
    except Exception as e:
        print(f"✗ 啟動服務失敗: {e}")
        sys.exit(1)


def main():
    """主要執行流程"""
    parser = argparse.ArgumentParser(
        description="Allure 報告管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例：
  清理所有報告目錄：
    python %(prog)s clean
  
  生成並開啟報告：
    python %(prog)s report
        """,
    )

    parser.add_argument(
        "action",
        choices=["clean", "report"],
        help="clean: 清理所有報告目錄 | report: 生成並開啟 Allure 報告",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="指定 Web Server 監聽的主機位址 (預設: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="指定 Web Server 監聽的連接埠 (預設: 自動分配)",
    )

    args = parser.parse_args()

    if args.action == "clean":
        clean_directories()
    elif args.action == "report":
        generate_and_open_report(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
