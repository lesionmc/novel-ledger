# -*- coding: utf-8 -*-
"""guard_push.py — novel-ledger v0.7 守卫进程

铁律：本脚本【只读不写】。除内存快照外，不落任何文件、不改任何书稿、
不写日志文件；所有输出只进 stdout/stderr。

职责：
  轮询各书 tasks.json 的状态变化 + books/*/chapters/chNNN.md 新章增量，
  有变化时 POST 企业微信 webhook（或任意自定义接收 URL）。

配置：
  WEBHOOK_URL —— 启动时一次性读取（环境变量优先，其次项目根 .env），
  只用不回显、不落日志。

用法：
  python scripts/guard_push.py            # 常驻轮询（默认 30s 一轮）
  python scripts/guard_push.py --once     # 单轮模式，供 cron 调度
  python scripts/guard_push.py --interval 60

零第三方依赖（纯标准库）。
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import chapters  # 章节文件命名/枚举单一事实源（同目录模块，纯标准库）

ROOT = Path(__file__).resolve().parent.parent

SECONDS = 30  # 默认轮询间隔


def load_webhook():
    """启动时一次性读取 WEBHOOK_URL：环境变量优先，其次 .env。只返回值，不打印。"""
    val = os.environ.get("WEBHOOK_URL", "").strip()
    if val:
        return val
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("WEBHOOK_URL") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def scan_books():
    """扫描全部书籍，返回 {book_name: {"tasks": {task_id: status}, "chapters": {fname: mtime}}}"""
    snapshot = {}
    books_dir = ROOT / "books"
    if not books_dir.exists():
        return snapshot
    for book_dir in sorted(books_dir.iterdir()):
        if not book_dir.is_dir() or book_dir.name.startswith(("_", ".")):
            continue
        info = {"tasks": {}, "chapters": {}}
        tasks_file = book_dir / "tasks.json"
        if tasks_file.exists():
            try:
                data = json.loads(tasks_file.read_text(encoding="utf-8"))
                items = data.get("tasks", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for t in items:
                        if isinstance(t, dict) and t.get("id"):
                            info["tasks"][str(t["id"])] = str(t.get("status", ""))
                elif isinstance(items, dict):
                    for k, v in items.items():
                        info["tasks"][str(k)] = str(v.get("status", "") if isinstance(v, dict) else v)
            except (OSError, ValueError):
                pass  # 只读不写：解析失败不回写、不修复
        ch_dir = book_dir / "chapters"
        if ch_dir.is_dir():
            for f in ch_dir.iterdir():
                if f.is_file() and chapters.CH_RE.match(f.name):
                    try:
                        info["chapters"][f.name] = f.stat().st_mtime
                    except OSError:
                        pass
        snapshot[book_dir.name] = info
    return snapshot


def diff_changes(old, new):
    """对比两轮快照，产出变更描述列表。首轮（old 为 None）不推历史。
    章节检测两类：新增文件（新章落盘）+ mtime 变化的已知文件（改章更新）——
    快照本来就采集了 mtime，之前只判新增是死数据，这里把改章也接上。"""
    changes = []
    if old is None:
        return changes
    for book, info in new.items():
        prev = old.get(book, {"tasks": {}, "chapters": {}})
        for tid, status in info["tasks"].items():
            if prev["tasks"].get(tid) != status:
                changes.append(f"《{book}》任务 {tid}：{prev['tasks'].get(tid) or '无'} → {status}")
        for fname, mtime in info["chapters"].items():
            old_mtime = prev["chapters"].get(fname)
            if old_mtime is None:
                changes.append(f"《{book}》新章落盘：{fname}")
            elif old_mtime != mtime:
                changes.append(f"《{book}》改章更新：{fname}")
    return changes


def push(webhook, changes):
    """POST 纯文本到企业微信 webhook 格式。失败只打印，不退出、不重试落盘。"""
    text = "novel-ledger 守卫\n" + "\n".join(changes[:20])
    if len(changes) > 20:
        text += f"\n…（共 {len(changes)} 条）"
    payload = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[guard] 推送成功（{len(changes)} 条变更，HTTP {resp.status}）")
    except Exception as e:  # noqa: BLE001
        print(f"[guard] 推送失败（继续轮询）：{e}")


def main():
    once = "--once" in sys.argv
    interval = SECONDS
    if "--interval" in sys.argv:
        i = sys.argv.index("--interval")
        if i + 1 < len(sys.argv):
            try:
                interval = max(5, int(sys.argv[i + 1]))
            except ValueError:
                pass
    webhook = load_webhook()
    print(f"[guard] novel-ledger 守卫进程启动（间隔 {interval}s，模式={'单轮' if once else '常驻'}）")
    print(f"[guard] webhook：{'已配置' if webhook else '未配置（仅打印变更，不推送）'}")
    seen = None  # 首轮建立基线，不推历史
    while True:
        new = scan_books()
        changes = diff_changes(seen, new)
        if changes:
            for c in changes:
                print(f"[guard] {c}")
            if webhook:
                push(webhook, changes)
        else:
            print(f"[guard] 本轮无变化（书籍 {len(new)} 本）")
        seen = new
        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[guard] 已停止")
