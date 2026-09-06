# -*- coding: utf-8 -*-
"""web/common.py —— server 与各 api_* 模块共享的基础设施（纯标准库）。

依赖方向（单向，绝不反向）：server → api_* → common；本模块不许 import server。
注意：会被 web/test_routes.py 以 `S.xxx = ...` 打桩/改路径的符号
（run_engine / ENV_PATH / KEY_SET / RULES_DIR / STYLE_LEARN / REL_GRAPH / VECTOR
及脚本路径常量 WRITE_CH 等）必须留在 server.py，api_* 在调用时经 server 动态取用，
保证打桩语义不破。
"""
import json
import os
import re
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT, "books")
SAMPLE_DIR = os.path.join(ROOT, "sample_book")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
WEB_DIR = os.path.join(ROOT, "web")
TEMPLATES_DIR = os.path.join(BOOKS_DIR, "_templates")       # v0.6 题材模板 + 推进模式卡
# 书根目录产物白名单（/api/book/{b}/file/{rel} 除 chapters/ 外额外放行的文件）
BOOK_ROOT_FILES = ("文风指纹.md", "关系图谱.json", "关系图谱.md")
DOCS = ("设定", "角色卡", "大纲", "state")
DOC_FILE = {"设定": "设定.md", "角色卡": "角色卡.md", "大纲": "大纲.md", "state": "story_state.md"}

# ---- R48 用量共享状态（ThreadingHTTPServer 并发下保护 _LAST_USAGE 读写，防串话）----
_LAST_USAGE = None  # 最近一次 llm_chat 的用量（供接口回传前端显示）
_USAGE_LOCK = threading.Lock()


def set_last_usage(v):
    global _LAST_USAGE
    with _USAGE_LOCK:
        _LAST_USAGE = v


def get_last_usage():
    with _USAGE_LOCK:
        return _LAST_USAGE


# ---- v0.6 连写任务系统共享状态（调度在 api_tasks 侧实现）----
_TASK_LOCK = threading.RLock()  # RLock：worker 与 handler 会持锁调 _persist_task（内部再取锁）
_TASK_STOP = {}  # task_id -> threading.Event（cancel 信号）
_TASKS = {}      # task_id -> 运行中任务的共享 dict（cancel 与 worker 操作同一对象，防落盘互相覆盖）


# ---- 书级互斥：write/write-stream/fix/recalc-from/cross-audit/audit 六类端点
#      都会动账本，同一本书并发跑会互相踩 story_state.md，按书加锁串行化 ----
_BOOK_LOCKS = {}                      # 书目录绝对路径 -> threading.Lock
_BOOK_LOCKS_GUARD = threading.Lock()  # 保护 _BOOK_LOCKS 本身的创建


def book_lock(p):
    """取某本书的互斥锁（懒创建；进程生命周期内同一书始终同一把锁）。"""
    with _BOOK_LOCKS_GUARD:
        return _BOOK_LOCKS.setdefault(p, threading.Lock())


# ---------------- 响应包装 ----------------
def api_error(h, code, msg):
    body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def api_ok(h, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(200)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


# ---------------- 文件 / 书目录公共件 ----------------
def read_text(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def book_path(name):
    """安全取书目录：name 只能是合法目录名，防路径穿越。"""
    if not name or name in (".", "..") or re.search(r"[/\\]", name):
        return None
    p = os.path.join(BOOKS_DIR, name)
    return p if os.path.isdir(p) else None


def valid_tpl_name(name):
    """模板名合法性校验（模板 read 与 copy 端点共用）：
    拒绝空、..、含 / 或 \\、_ 前缀——先校验再 isdir，防 ../..\\ 穿越出 books/。"""
    if not name or name == ".." or name.startswith("_"):
        return False
    if re.search(r"[/\\]", name):
        return False
    return True


def list_books():
    if not os.path.isdir(BOOKS_DIR):
        return []
    return sorted(d for d in os.listdir(BOOKS_DIR)
                  if os.path.isdir(os.path.join(BOOKS_DIR, d))
                  and not d.startswith(".") and not d.startswith("_"))


def chapter_list(p):
    ch_dir = os.path.join(p, "chapters")
    if not os.path.isdir(ch_dir):
        return []
    return sorted((int(m.group(1)), m.group(0))
                  for m in (re.match(r"ch(\d+)\.md$", f) for f in os.listdir(ch_dir))
                  if m)


def chapter_title(p, fname):
    """取章节标题：正文第一行的 # 标题（去掉 # 前缀）；取不到返回空。"""
    try:
        with open(os.path.join(p, "chapters", fname), encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                return re.sub(r"^#+\s*", "", s)[:40]
    except Exception:
        pass
    return ""


def next_chapter_no(p):
    chs = chapter_list(p)
    return (max(n for n, _ in chs) + 1) if chs else 1


def parse_usage(out, err):
    """从引擎输出解析 [用量] 行（R48→前端显示本次消耗）。"""
    m = re.search(r"\[用量\] 输入 (\d+) / 输出 (\d+) / 总 (\d+)", out + err)
    return {"in": int(m.group(1)), "out": int(m.group(2)), "total": int(m.group(3))} if m else None


# ---------------- 路由表 ----------------
# pattern 为「/」切段后的段模式：字面段精确匹配；{var} 捕获单段；
# {var...} 贪婪捕获剩余段（可捕获 1..n 段，且其后只允许字面段，如 tpl/{name...}/copy）。
# 先注册先匹配——具体路由必须先于兜底路由注册。
ROUTES = []  # [(method, pattern_segs, handler)]


def route(method, pattern):
    """@route("GET", "book/{book}/ch/{no}") —— 把 handler 注册进路由表。"""
    segs = tuple(s for s in pattern.split("/") if s)

    def deco(fn):
        ROUTES.append((method, segs, fn))
        return fn
    return deco


def match_route(method, segs):
    """按注册顺序查表。命中返回 (handler, params)，未命中返回 (None, None)。"""
    for m, pat, fn in ROUTES:
        if m != method:
            continue
        params = _match(pat, segs)
        if params is not None:
            return fn, params
    return None, None


def _match(pat, segs):
    params = {}
    i = 0
    for j, p in enumerate(pat):
        if p.startswith("{") and p.endswith("...}"):
            k = len(pat) - j - 1          # 贪婪段之后的模式段数（只支持字面/{var}锚点）
            avail = len(segs) - i - k
            if avail < 1:                  # 贪婪段至少吃 1 段（空剩余交给 no route 兜底）
                return None
            params[p[1:-4]] = segs[i:i + avail]
            for off in range(k):           # 校验贪婪段之后的尾部锚点
                q = pat[j + 1 + off]
                if q.startswith("{") and q.endswith("}"):
                    params[q[1:-1]] = segs[i + avail + off]
                elif segs[i + avail + off] != q:
                    return None
            return params
        if i >= len(segs):
            return None
        if p.startswith("{") and p.endswith("}"):
            params[p[1:-1]] = segs[i]
        elif segs[i] != p:
            return None
        i += 1
    return params if i == len(segs) else None
