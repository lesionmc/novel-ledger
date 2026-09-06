# -*- coding: utf-8 -*-
"""novel-ledger MCP server —— 纯标准库手写 JSON-RPC 2.0 over stdio（逐行 JSON）

让 MCP 客户端（如 Claude Desktop 等）以工具方式调用 novel-ledger 引擎：
  7 只读：list_books / get_usage / scan_book / checkup / read_report /
          recall_history / platform_check
  8 写类：write_chapter / audit_full / evaluate / publish_check / backup /
          index_book / recalc_account / cross_audit
写类工具 inputSchema.required 含 confirm，handle 时 confirm 非 true 一律拦截。

协议：MCP 规范 2024-11-05 子集——initialize / tools/list / tools/call；
未知方法回 -32601。通知（无 id）不回包。子进程统一 text=True, encoding="utf-8",
errors="replace"（Windows 控制台 GBK 防炸）。

自测：python mcp_server/server.py --selftest
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT, "books")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
WRITE_CH = os.path.join(SCRIPTS_DIR, "write_chapter.py")
DEAI = os.path.join(SCRIPTS_DIR, "deai.py")
BACKUP = os.path.join(SCRIPTS_DIR, "backup_book.py")
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "novel-ledger-mcp", "version": "0.9.1"}

sys.path.insert(0, SCRIPTS_DIR)  # usage_log / write_chapter（引擎侧公共模块）


# ─────────────────────────── 路径安全 ───────────────────────────
def book_path(name):
    """安全解析 books/ 下的书目录，三道防线：
    ① 拒绝空 / . / .. / _ 或 . 前缀（快照、归档等底账目录不外露）；
    ② normpath 后做前缀判断，且前缀必须带 os.sep——防 books_evil 这类
       兄弟目录名绕过裸 startswith（/x/books_evil 也 startswith(/x/books)）；
    ③ 结果必须真实存在且为目录。
    """
    if not isinstance(name, str) or not name.strip():
        return None
    rel = os.path.normpath(name.strip())
    if rel in (".", "..") or rel.startswith("_") or rel.startswith("."):
        return None
    root = os.path.abspath(BOOKS_DIR)
    p = os.path.normpath(os.path.join(root, rel))
    if p != root and not p.startswith(root + os.sep):
        return None
    return p if os.path.isdir(p) else None


# read_report 白名单：chapters/ 产物、账本、章快照、体检/审计/评分单、三件套文本
_READ_PATTERNS = (
    r"chapters/[^/]+\.(?:md|json)",
    r"story_state\.md",
    r"_snapshots/ch\d+\.state\.md",
    r"chapters/[^/]*?(?:评分|体检单|审计)[^/]*\.(?:md|json|txt)",
    r"[^/]*?(?:评分|体检单|审计)[^/]*\.(?:md|txt)",
    r"(?:大纲|角色卡|设定)\.md",
)


def report_path(p, rel):
    """校验 rel 是否在白名单内并拼绝对路径；非法返回 None。"""
    if not isinstance(rel, str) or not rel.strip():
        return None
    norm = os.path.normpath(rel.strip()).replace("\\", "/")
    if norm.startswith("..") or "/../" in norm:
        return None
    if not any(re.fullmatch(pat, norm) for pat in _READ_PATTERNS):
        return None
    full = os.path.normpath(os.path.join(p, norm))
    if not full.startswith(os.path.abspath(p) + os.sep) and full != os.path.abspath(p):
        return None
    return full if os.path.isfile(full) else None


def run_engine(args, timeout=900):
    """跑引擎脚本（子进程），返回 (ok, stdout, stderr)。cwd=项目根。"""
    try:
        r = subprocess.run([sys.executable] + args, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=ROOT)
        return (r.returncode == 0, r.stdout, r.stderr)
    except subprocess.TimeoutExpired:
        return (False, "", "引擎执行超时（超过 %ss）" % timeout)


def chapter_list(p):
    ch_dir = os.path.join(p, "chapters")
    if not os.path.isdir(ch_dir):
        return []
    return sorted(int(m.group(1)) for m in
                  (re.match(r"ch(\d+)\.md$", f) for f in os.listdir(ch_dir)) if m)


def list_books():
    if not os.path.isdir(BOOKS_DIR):
        return []
    return sorted(d for d in os.listdir(BOOKS_DIR)
                  if os.path.isdir(os.path.join(BOOKS_DIR, d))
                  and not d.startswith("_") and not d.startswith("."))


# ─────────────────────────── 工具定义 ───────────────────────────
_BOOL_CONFIRM = {"confirm": {"type": "boolean", "description": "必须显式传 true 才会执行写操作"}}

TOOLS = [
    {"name": "list_books", "description": "列出所有书（跳过 _/. 开头的底账目录）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_usage", "description": "读本地用量流水 usage_log.jsonl 现算汇总（零外呼）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "scan_book", "description": "全书 AI 腔体检（本地零 token，deai --scan）",
     "inputSchema": {"type": "object", "required": ["book"],
                     "properties": {"book": {"type": "string", "description": "书名"}}}},
    {"name": "checkup", "description": "书健康体检（本地只读）：章数/账本状态/超期伏笔/快照数",
     "inputSchema": {"type": "object", "required": ["book"],
                     "properties": {"book": {"type": "string"}}}},
    {"name": "read_report", "description": "读书内报告/正文/账本（白名单：chapters/ 产物、story_state.md、_snapshots/ 章快照、评分/体检单/审计单、大纲/角色卡/设定）",
     "inputSchema": {"type": "object", "required": ["book", "path"],
                     "properties": {"book": {"type": "string"},
                                    "path": {"type": "string", "description": "相对书目录的路径，如 chapters/ch001.md"}}}},
    {"name": "write_chapter", "description": "写下一章/指定章（长时，调模型；缺账本自动 init）",
     "inputSchema": {"type": "object", "required": ["book", "confirm"],
                     "properties": {"book": {"type": "string"}, "no": {"type": "integer"},
                                    "words": {"type": "integer"}, "auto_backup": {"type": "boolean"},
                                    **_BOOL_CONFIRM}}},
    {"name": "audit_full", "description": "全章一致性审计（调模型，落盘 chXXX.一致性审计.md）",
     "inputSchema": {"type": "object", "required": ["book", "no", "confirm"],
                     "properties": {"book": {"type": "string"}, "no": {"type": "integer"},
                                    **_BOOL_CONFIRM}}},
    {"name": "evaluate", "description": "去 AI 腔 L1 评估（零 token，checkup --evaluate，与 Web /evaluate 同通道）",
     "inputSchema": {"type": "object", "required": ["book", "no", "confirm"],
                     "properties": {"book": {"type": "string"}, "no": {"type": "integer"},
                                    **_BOOL_CONFIRM}}},
    {"name": "publish_check", "description": "发布体检：AI 腔扫描 + 章数/账本/伏笔超期汇总，给可发布结论",
     "inputSchema": {"type": "object", "required": ["book", "confirm"],
                     "properties": {"book": {"type": "string"}, **_BOOL_CONFIRM}}},
    {"name": "backup", "description": "一键备份全书为 zip（backups/ 保留最近 10 份）",
     "inputSchema": {"type": "object", "required": ["book", "confirm"],
                     "properties": {"book": {"type": "string"}, **_BOOL_CONFIRM}}},
    # —— v0.8/9 新增 ——
    {"name": "recall_history",
     "description": "向量召回历史章节片段（只读，vector_recall recall）：按 query 检索与"
                    "当前情节相关的历史剧情/设定，用于写作前回忆前文。需先 index_book。",
     "inputSchema": {"type": "object", "required": ["book", "query"],
                     "properties": {"book": {"type": "string"},
                                    "query": {"type": "string", "description": "检索问题/情节描述"},
                                    "k": {"type": "integer", "description": "返回条数（默认引擎自定）"}}}},
    {"name": "index_book",
     "description": "为全书建/更新向量索引（写类，vector_recall index）。需 chromadb 与"
                    " EMBED_* 配置就绪，否则引擎报降级提示。",
     "inputSchema": {"type": "object", "required": ["book", "confirm"],
                     "properties": {"book": {"type": "string"}, **_BOOL_CONFIRM}}},
    {"name": "recalc_account",
     "description": "从第 N 章起重算账本 story_state.md（写类，write_chapter --recalc-from）："
                    "章节回改/重写后让账本重新对齐，调模型，长时。",
     "inputSchema": {"type": "object", "required": ["book", "no", "confirm"],
                     "properties": {"book": {"type": "string"}, "no": {"type": "integer"},
                                    **_BOOL_CONFIRM}}},
    {"name": "cross_audit",
     "description": "跨章一致性审计（写类，write_chapter --cross-audit）：检查第 N 章与全书"
                    "前后文的设定/时间线/人物冲突，调模型，长时。",
     "inputSchema": {"type": "object", "required": ["book", "no", "confirm"],
                     "properties": {"book": {"type": "string"}, "no": {"type": "integer"},
                                    **_BOOL_CONFIRM}}},
    {"name": "platform_check",
     "description": "平台合规体检（只读，write_chapter --platform-check）：按番茄等平台审核"
                    "红线扫第 N 章，输出风险点与修改建议。",
     "inputSchema": {"type": "object", "required": ["book", "no"],
                     "properties": {"book": {"type": "string"}, "no": {"type": "integer"}}}},
]

_WRITE_TOOLS = {"write_chapter", "audit_full", "evaluate", "publish_check", "backup",
                "index_book", "recalc_account", "cross_audit"}


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _need_book(args):
    p = book_path(args.get("book"))
    if not p:
        raise RpcError(-32602, "书不存在或名字非法: %r" % (args.get("book"),))
    return p


def _need_confirm(name, args):
    if args.get("confirm") is not True:
        raise ToolBlocked("工具 %s 是写操作：必须显式传 confirm=true 才会执行" % name)


class ToolBlocked(Exception):
    pass


# ─────────────────────────── 工具实现 ───────────────────────────
def tool_list_books(args):
    return json.dumps({"books": list_books()}, ensure_ascii=False, indent=1)


def tool_get_usage(args):
    import usage_log
    return json.dumps(usage_log.aggregate(usage_log.load_entries()),
                      ensure_ascii=False, indent=1)


def tool_scan_book(args):
    p = _need_book(args)
    ok, out, err = run_engine([DEAI, "--scan", p], timeout=300)
    return json.dumps({"ok": ok, "report": (out + err)[-8000:]}, ensure_ascii=False)


def tool_checkup(args):
    p = _need_book(args)
    chs = chapter_list(p)
    overdue = []
    try:
        import write_chapter as wc
        overdue = wc.overdue_foreshadows(
            open(os.path.join(p, "story_state.md"), encoding="utf-8").read()
            if os.path.exists(os.path.join(p, "story_state.md")) else "",
            chs[-1] if chs else 0)
    except Exception:
        pass
    return json.dumps({
        "book": os.path.basename(p),
        "chapters": len(chs),
        "next_no": (chs[-1] + 1) if chs else 1,
        "has_state": os.path.exists(os.path.join(p, "story_state.md")),
        "snapshots": len([f for f in (os.listdir(os.path.join(p, "_snapshots"))
                                      if os.path.isdir(os.path.join(p, "_snapshots")) else [])
                          if re.match(r"ch\d+\.state\.md$", f)]),
        "overdue": [{"text": o.get("text", ""), "overdue_by": o.get("overdue_by")} for o in overdue],
    }, ensure_ascii=False, indent=1)


def tool_read_report(args):
    p = _need_book(args)
    full = report_path(p, args.get("path"))
    if not full:
        raise RpcError(-32602, "path 不在白名单或文件不存在: %r" % (args.get("path"),))
    with open(full, encoding="utf-8") as f:
        return f.read()[:20000]


def tool_write_chapter(args):
    p = _need_book(args)
    _need_confirm("write_chapter", args)
    chs = chapter_list(p)
    no = int(args.get("no") or 0) or ((chs[-1] + 1) if chs else 1)
    engine_args = [WRITE_CH, "--book", p, "--chapter", str(no)]
    if args.get("words"):
        engine_args += ["--words", str(max(1000, min(10000, int(args["words"]))))]
    if args.get("auto_backup"):
        engine_args += ["--auto-backup"]
    ok, out, err = run_engine(engine_args)
    body_fp = os.path.join(p, "chapters", "ch%03d.md" % no)
    body = open(body_fp, encoding="utf-8").read() if os.path.exists(body_fp) else ""
    return json.dumps({"ok": ok, "no": no, "chars": len(body), "body": body[:4000],
                       "log": (out + err)[-2000:]}, ensure_ascii=False)


def tool_audit_full(args):
    p = _need_book(args)
    _need_confirm("audit_full", args)
    no = int(args.get("no") or 0)
    if no < 1:
        raise RpcError(-32602, "需要正整数 no")
    ok, out, err = run_engine([WRITE_CH, "--book", p, "--audit", "--chapter", str(no)])
    rp = os.path.join(p, "chapters", "ch%03d.一致性审计.md" % no)
    report = open(rp, encoding="utf-8").read() if os.path.exists(rp) else ""
    return json.dumps({"ok": ok, "no": no, "report": report[:8000],
                       "log": (out + err)[-1500:]}, ensure_ascii=False)


def tool_evaluate(args):
    p = _need_book(args)
    _need_confirm("evaluate", args)
    no = int(args.get("no") or 0)
    if no < 1:
        raise RpcError(-32602, "需要正整数 no")
    # 与 Web /evaluate 同通道：checkup --evaluate（本地规则评估，零 token），
    # 不再走 deai --polish（烧 token）。报告取引擎 stdout。
    ok, out, err = run_engine([CHECKUP, "--book", p, "--evaluate", "--chapter", str(no)])
    return json.dumps({"ok": ok, "no": no, "report": (out + err)[-8000:],
                       "log": (out + err)[-1500:]}, ensure_ascii=False)


def tool_publish_check(args):
    p = _need_book(args)
    _need_confirm("publish_check", args)
    ok, out, err = run_engine([DEAI, "--scan", p], timeout=300)
    chs = chapter_list(p)
    has_state = os.path.exists(os.path.join(p, "story_state.md"))
    verdict = "可发布" if (ok and chs and has_state) else "建议先补齐再发布"
    return json.dumps({"ok": ok, "verdict": verdict, "chapters": len(chs),
                       "has_state": has_state, "scan": (out + err)[-6000:]},
                      ensure_ascii=False, indent=1)


def tool_backup(args):
    p = _need_book(args)
    _need_confirm("backup", args)
    ok, out, err = run_engine([BACKUP, "--book", p], timeout=300)
    m = re.search(r"已生成 → (.+)", out)
    return json.dumps({"ok": ok, "path": m.group(1).strip() if m else "",
                       "log": (out + err)[-1500:]}, ensure_ascii=False)


# —— v0.8/9 新增 ——
def tool_recall_history(args):
    p = _need_book(args)
    q = (args.get("query") or "").strip()
    if not q:
        raise RpcError(-32602, "需要 query（检索问题/情节描述）")
    ea = [VECTOR, "--book", p, "recall", "--query", q]
    if args.get("k"):
        try:
            ea += ["--k", str(max(1, min(50, int(args["k"]))))]
        except (TypeError, ValueError):
            pass
    ok, out, err = run_engine(ea)
    return json.dumps({"ok": ok, "result": (out + err)[-8000:]}, ensure_ascii=False)


def tool_index_book(args):
    p = _need_book(args)
    _need_confirm("index_book", args)
    ok, out, err = run_engine([VECTOR, "--book", p, "index"])
    return json.dumps({"ok": ok, "log": (out + err)[-4000:]}, ensure_ascii=False)


def tool_recalc_account(args):
    p = _need_book(args)
    _need_confirm("recalc_account", args)
    no = int(args.get("no") or 0)
    if no < 1:
        raise RpcError(-32602, "需要正整数 no")
    ok, out, err = run_engine([WRITE_CH, "--book", p, "--recalc-from", str(no)])
    return json.dumps({"ok": ok, "no": no, "log": (out + err)[-3000:]}, ensure_ascii=False)


def tool_cross_audit(args):
    p = _need_book(args)
    _need_confirm("cross_audit", args)
    no = int(args.get("no") or 0)
    if no < 1:
        raise RpcError(-32602, "需要正整数 no")
    ok, out, err = run_engine([WRITE_CH, "--book", p, "--cross-audit", str(no)])
    return json.dumps({"ok": ok, "no": no, "report": (out + err)[-8000:]}, ensure_ascii=False)


def tool_platform_check(args):
    p = _need_book(args)
    no = int(args.get("no") or 0)
    if no < 1:
        raise RpcError(-32602, "需要正整数 no")
    ok, out, err = run_engine([WRITE_CH, "--book", p, "--platform-check", str(no)])
    return json.dumps({"ok": ok, "no": no, "report": (out + err)[-8000:]}, ensure_ascii=False)


_HANDLERS = {
    "list_books": tool_list_books,
    "get_usage": tool_get_usage,
    "scan_book": tool_scan_book,
    "checkup": tool_checkup,
    "read_report": tool_read_report,
    "write_chapter": tool_write_chapter,
    "audit_full": tool_audit_full,
    "evaluate": tool_evaluate,
    "publish_check": tool_publish_check,
    "backup": tool_backup,
    "recall_history": tool_recall_history,
    "index_book": tool_index_book,
    "recalc_account": tool_recalc_account,
    "cross_audit": tool_cross_audit,
    "platform_check": tool_platform_check,
}


# ─────────────────────────── JSON-RPC 2.0 ───────────────────────────
def handle_request(msg):
    """处理一条 JSON-RPC 请求；通知（无 id）返回 None（不回包）。"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    method = msg["method"]
    mid = msg.get("id")
    if "id" not in msg:  # 通知：不回包（包括 notifications/initialized）
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    try:
        if method == "initialize":
            return ok({"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {"tools": {}},
                       "serverInfo": SERVER_INFO})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in _HANDLERS:
                return err(-32602, "unknown tool: %r" % (name,))
            try:
                text = _HANDLERS[name](args if isinstance(args, dict) else {})
                return ok({"content": [{"type": "text", "text": text}], "isError": False})
            except ToolBlocked as e:
                return ok({"content": [{"type": "text", "text": "已拦截：" + str(e)}],
                           "isError": True})
        return err(-32601, "method not found: %s" % method)
    except RpcError as e:
        return err(e.code, e.message)
    except Exception as e:  # 工具内部异常 → -32603，栈打到 stderr
        sys.stderr.write("[mcp] tools/call %s 异常: %r\n" % (method, e))
        import traceback
        traceback.print_exc()
        return err(-32603, "%s: %s" % (type(e).__name__, e))


def serve_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "Parse error"}},
                                        ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# ─────────────────────────── 自测 ───────────────────────────
def selftest():
    global BOOKS_DIR
    base = tempfile.mkdtemp(prefix="novel_mcp_selftest_")
    BOOKS_DIR = os.path.join(base, "books")
    book = os.path.join(BOOKS_DIR, "测试书")
    os.makedirs(os.path.join(book, "chapters"))
    with open(os.path.join(book, "chapters", "ch001.md"), "w", encoding="utf-8") as f:
        f.write("# 第一章 测试\n\n正文内容。\n")
    with open(os.path.join(book, "story_state.md"), "w", encoding="utf-8") as f:
        f.write("# 账本\n")
    os.makedirs(os.path.join(BOOKS_DIR, "_archive"))          # _ 前缀底账
    os.makedirs(os.path.join(base, "books_evil"))             # books 兄弟目录（防绕过靶子）

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else "  " + str(detail)))
        if not cond:
            ok = False

    print("== MCP 自测 ==")
    # —— 会话断言 4 条 ——
    r = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    check("initialize 返回协议版本 2024-11-05",
          r and r.get("result", {}).get("protocolVersion") == "2024-11-05", r)
    r = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in (r.get("result", {}).get("tools") or [])] if r else []
    write_tools = {t["name"]: t for t in (r.get("result", {}).get("tools") or [])} if r else {}
    check("tools/list 共 15 个工具且写类 required 含 confirm",
          len(names) == 15 and all("confirm" in (write_tools.get(n, {}).get("inputSchema", {})
                                                 .get("required", [])) for n in _WRITE_TOOLS),
          names)
    check("v0.8/9 新增五工具在列（recall_history/index_book/recalc_account/cross_audit/platform_check）",
          {"recall_history", "index_book", "recalc_account", "cross_audit",
           "platform_check"} <= set(names), names)
    check("只读工具不带 confirm（recall_history/platform_check）",
          all("confirm" not in (write_tools.get(n, {}).get("inputSchema", {})
                                .get("required", [])) for n in ("recall_history", "platform_check")),
          {n: write_tools.get(n, {}).get("inputSchema", {}).get("required") for n in ("recall_history", "platform_check")})
    r = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "list_books", "arguments": {}}})
    text = (r.get("result", {}).get("content") or [{}])[0].get("text", "") if r else ""
    check("tools/call list_books 列出真书且不见 _archive",
          "测试书" in text and "_archive" not in text, text[:120])
    r = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "write_chapter",
                                   "arguments": {"book": "测试书", "no": 2, "confirm": False}}})
    check("写类工具 confirm=false 被拦截（isError）",
          r and r.get("result", {}).get("isError") is True, r)
    # —— book_path 防绕过 3 条 ——
    check("book_path 拒绝 books_evil 兄弟目录穿越（正/反斜杠两种写法）",
          book_path("../books_evil") is None and book_path("..\\books_evil") is None)
    check("book_path 拒绝 _archive 底账目录", book_path("_archive") is None)
    check("book_path 放行真实书目录", book_path("测试书") == book)
    # 未知方法 -32601（顺手守一句）
    check("未知方法回 -32601",
          handle_request({"jsonrpc": "2.0", "id": 9, "method": "nope"})
          .get("error", {}).get("code") == -32601)

    shutil.rmtree(base, ignore_errors=True)
    if ok:
        print("MCP 自测通过：initialize / tools/list / list_books / confirm 拦截 / book_path 防绕过")
        return 0
    print("MCP 自测失败")
    return 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    serve_stdio()


if __name__ == "__main__":
    main()
