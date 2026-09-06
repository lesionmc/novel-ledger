# -*- coding: utf-8 -*-
"""launch_webview.py — novel-ledger 可选桌面壳

先用子进程拉起 web/server.py（PYTHONUTF8=1，端口 8801，已占用则直接复用），
再用 pywebview 开一个桌面窗口加载 http://127.0.0.1:8801。

pywebview 是全项目唯一可选依赖：
  pip install pywebview
未安装时给出友好提示并回退为纯浏览器地址。

零其他第三方依赖。
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8801
URL = f"http://127.0.0.1:{PORT}"


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server():
    """端口已占用则复用；否则拉起 web/server.py 子进程并等它就绪。"""
    if port_in_use(PORT):
        print(f"[launch] 端口 {PORT} 已有服务，直接复用")
        return None
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "web" / "server.py"), "--port", str(PORT)],
        cwd=str(ROOT), env=env,
    )
    for _ in range(30):  # 最多等 6 秒
        if port_in_use(PORT):
            print(f"[launch] 服务已就绪：{URL}")
            return proc
        time.sleep(0.2)
    print("[launch] 服务启动超时，请检查 web/server.py")
    return proc


def main():
    server = start_server()
    try:
        import webview  # 全项目唯一可选依赖
    except ImportError:
        print("[launch] 未安装 pywebview，无法打开桌面窗口。")
        print("         可选安装：pip install pywebview")
        print(f"         或直接用浏览器访问：{URL}")
        if server:
            print("[launch] 服务器进程保留运行中，关闭请 Ctrl+C")
            try:
                server.wait()
            except KeyboardInterrupt:
                pass
        return 0
    try:
        urllib.request.urlopen(URL, timeout=3)
    except Exception:
        pass  # 窗口仍会加载，首屏稍慢无碍
    webview.create_window("novel-ledger · 中文 AI 小说写作台", URL, width=1280, height=820)
    print(f"[launch] 桌面窗口已打开：{URL}（关闭窗口后服务器进程随主程序退出）")
    webview.start()
    if server:
        server.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
