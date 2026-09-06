# -*- coding: utf-8 -*-
"""novel-ledger · 本地 Web 工作台后端（入口 + 路由表 + 共享基础设施）

纯 Python 标准库（零第三方依赖）。桥接 scripts/ 下两个引擎：write_chapter.py（连载引擎，写章/审计）与 deai.py（去 AI 味引擎，scan/polish/apply）。

启动：
  python web/server.py [--port 8801]
浏览器打开 http://127.0.0.1:8801

本文件只保留：Handler（同源守卫 → 静态 → 路由表分派）、静态服务、.env 读写、
llm_chat、脚本路径常量与兜底路由。业务路由按域拆在（依赖方向 server → api_* → common）：
  api_books.py      书 CRUD/章读写/doc/export/rename/import-txt/模板建书
  api_engine.py     引擎动作（write/audit/scan/polish/apply/evaluate/publish-check/checkup/fix/plan/plan-save/resize/deconstruct/backup）
  api_tasks.py      task start/control/查询 + 后台连写调度全套
  api_assistant.py  chat SSE / write-stream
  api_meta.py       status/settings/usage/plugins/rules/templates/tpl + v0.8/9 扩展（style/graph/vector/sample-chapters/privacy-scan 等）

API 一览（均返回 JSON；完整端点清单与行为见各 api_*.py 的 @route 注册处）。
"""
import json
import os
import subprocess
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT, "books")
SAMPLE_DIR = os.path.join(ROOT, "sample_book")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
WEB_DIR = os.path.join(ROOT, "web")
ENV_PATH = os.path.join(ROOT, ".env")
for _p in (WEB_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)  # web 件（common/api_*）与引擎侧公共模块（llm/usage_log 等，R48）
try:
    import llm as llm_mod  # scripts/llm.py：统一 LLM 网关（chat_stream 流式生成器由 R1 侧提供）
except ImportError:  # llm.py 尚未就位时不阻塞 server 启动，流式端点运行时再报错
    llm_mod = None

from common import (_USAGE_LOCK,  # test_routes 断言用量锁存在（S._USAGE_LOCK）
                    api_error, api_ok, book_path, match_route, route,
                    valid_tpl_name)  # 兼容导出：test_routes 以 S.valid_tpl_name 断言

WRITE_CH = os.path.join(SCRIPTS_DIR, "write_chapter.py")
DEAI = os.path.join(SCRIPTS_DIR, "deai.py")
BACKUP = os.path.join(SCRIPTS_DIR, "backup_book.py")
STYLE_LEARN = os.path.join(SCRIPTS_DIR, "style_learn.py")   # v0.8 文风学习
REL_GRAPH = os.path.join(SCRIPTS_DIR, "relation_graph.py")  # v0.8 关系图谱
VECTOR = os.path.join(SCRIPTS_DIR, "vector_recall.py")      # v0.8/9 向量召回（index / recall）
CHECKUP = os.path.join(SCRIPTS_DIR, "checkup.py")           # v0.5 章节体检台（evaluate/publish-check 零 token）
RULES_DIR = os.path.join(ROOT, "rules")                     # v0.6 提示词管理
PORT = 8000

# ---- 业务路由注册（import 即把各自 @route 挂进 common.ROUTES；顺序即优先级）----
import api_books  # noqa: E402
import api_engine  # noqa: E402
import api_tasks  # noqa: E402
import api_assistant  # noqa: E402
import api_meta  # noqa: E402


def _check():
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                if line.startswith("AGNES_API_KEY=") and len(line.split("=", 1)[1].strip()) > 10:
                    return True
    except FileNotFoundError:
        pass
    return False


KEY_SET = _check()

# ---- .env 安全读写（只允许改这些键，其余行原样保留）----
SETTING_KEYS = ("AGNES_API_KEY", "AGNES_BASE_URL", "AGNES_MODEL",
                "FALLBACK_API_KEY", "FALLBACK_BASE_URL", "FALLBACK_MODEL",
                "PLANNER_MODEL", "REVIEWER_MODEL")  # R32⑤：策划/审校角色模型，留空回落写手


def read_settings():
    out = {}
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, _, v = s.partition("=")
                    if k.strip() in SETTING_KEYS:
                        out[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return out


def public_settings():
    """给前端页面/日志看的设置：API Key 一律打码，只回显是否已配置。
    真实 key 只在 live_env() 内部使用（请求模型时读），绝不出现在任何 HTTP 响应里。"""
    s = read_settings()
    return {k: ("****" if (k.endswith("_API_KEY") and v) else v) for k, v in s.items()}


def write_settings(changes):
    """只更新白名单键；不存在的键追加到文件尾。返回完整新 settings。"""
    lines = []
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)
    except FileNotFoundError:
        pass
    for k, v in changes.items():
        if k not in SETTING_KEYS:
            continue
        if v == "****":  # 前端脱敏占位符：用户没动过的 key 不得写回（否则会覆盖真实 key）
            continue
        hit = False
        for i, ln in enumerate(lines):
            if ln.strip().startswith(k + "=") or (ln.strip().startswith("#") and k + "=" in ln):
                # 命中已启用行：整行替换；命中被注释的模板行：在其后补一行启用
                if ln.strip().startswith(k + "="):
                    lines[i] = f"{k}={v}\n"
                    hit = True
                    break
                else:
                    lines.insert(i + 1, f"{k}={v}\n")
                    hit = True
                    break
        if not hit:
            lines.append(f"{k}={v}\n")
    tmp = ENV_PATH + ".tmp"  # 原子写：先落同目录临时文件再 os.replace，避免半截 .env
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, ENV_PATH)
    global KEY_SET
    KEY_SET = bool(read_settings().get("AGNES_API_KEY", ""))
    return read_settings()


def live_env():
    """实时读 .env 的模型配置（改完设置立刻生效，无需重启）。"""
    s = read_settings()
    return {
        "key": s.get("AGNES_API_KEY", ""),
        "base_url": s.get("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1/"),
        "model": s.get("AGNES_MODEL", "agnes-2.5-flash"),
    }


def llm_chat(messages, temperature=0.7, max_tokens=2000, action="Web对话"):
    """用配置的模型做一次 chat（供对话建书/测试连接用）。返回文本。
    R48：响应带 usage 时顺带记用量流水，记账失败不影响返回。
    max_tokens 下限 800：agnes-2.5-flash 的 reasoning 先于正文消耗预算，
    预算太小（如 4/100）会被思考吞光返回空 content（docs/16 问题#5）。"""
    from common import set_last_usage
    set_last_usage(None)
    cfg = live_env()
    if not cfg["key"]:
        raise RuntimeError("未配置 AGNES_API_KEY（请在 ⚙ 设置 里填写）")
    import urllib.request as _ur
    max_tokens = max(int(max_tokens or 0), 800)
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "reasoning_effort": "low",
    }
    req = _ur.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + cfg["key"]},
                      method="POST")
    # 空响应重试（agnes 偶发思考吞光输出预算返回空，docs/16 问题#5）：最多试 3 次
    data = {}
    choice = {}
    for attempt in range(3):
        with _ur.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choice = (data.get("choices") or [{}])[0]
        if ((choice.get("message") or {}).get("content") or "").strip():
            break
        print(f"  ⚠ [llm_chat] 第 {attempt + 1} 次空响应（finish={choice.get('finish_reason')}），重试...",
              file=sys.stderr)
    u = data.get("usage") or {}
    if u:
        set_last_usage({"in": u.get("prompt_tokens") or 0,
                        "out": u.get("completion_tokens") or 0,
                        "total": u.get("total_tokens") or ((u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0))})
        try:
            import usage_log
            usage_log.log_usage(action, cfg["model"],
                                u.get("prompt_tokens"), u.get("completion_tokens"))
        except Exception:
            pass  # 记账失败不影响对话（R48 设计约束）
    choice = (data.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content", "").strip()


def run_engine(args, timeout=900):
    """跑引擎脚本（子进程），返回 (ok, stdout, stderr)。cwd=项目根。"""
    try:
        r = subprocess.run([sys.executable] + args, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=ROOT)
        return (r.returncode == 0, r.stdout, r.stderr)
    except subprocess.TimeoutExpired:
        return (False, "", "引擎执行超时（超过 %ss）" % timeout)


def serve_static(h, path):
    rel = path.lstrip("/")
    # React 工作台（A′ 预构建产物）；v0.2 起转正：/ 与 /ui/ 都指向新工作台
    if rel == "ui" or rel.startswith("ui/") or rel.startswith("assets/"):
        sub = rel[3:].lstrip("/") if rel.startswith("ui") else rel
        sub = sub or "index.html"
        if rel.startswith("assets/"):
            sub = rel  # /assets/* → web/ui/assets/*
        full = os.path.normpath(os.path.join(WEB_DIR, "ui", sub))
        # 前缀必须带 os.sep：防 ui_evil 这类兄弟目录名绕过裸 startswith
        if not full.startswith(os.path.join(WEB_DIR, "ui") + os.sep):
            api_error(h, 403, "forbidden")
            return
        if not os.path.isfile(full):
            api_error(h, 404, "not found: " + rel)
            return
        _send_static_file(h, full)
        return
    # 旧版界面归档为 /legacy（保留可回退，不再做美化）
    if rel == "legacy" or rel == "legacy/" or rel == "legacy/index.html":
        full = os.path.join(WEB_DIR, "static", "index.html")
        if os.path.isfile(full):
            _send_static_file(h, full)
            return
        api_error(h, 404, "legacy index missing")
        return
    if rel.startswith("legacy/"):
        rel = rel[len("legacy/"):]  # /legacy/static/app.js → 旧 static 资源
    if rel == "":
        # 转正：根路径 = React 工作台
        full = os.path.join(WEB_DIR, "ui", "index.html")
        if os.path.isfile(full):
            _send_static_file(h, full)
            return
        api_error(h, 404, "ui build missing")
        return
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    full = os.path.normpath(os.path.join(WEB_DIR, "static", rel))
    if not full.startswith(os.path.join(WEB_DIR, "static") + os.sep):
        api_error(h, 403, "forbidden")
        return
    if not os.path.isfile(full):
        api_error(h, 404, "not found: " + rel)
        return
    _send_static_file(h, full)


def _send_static_file(h, full):
    ext = os.path.splitext(full)[1].lstrip(".").lower()  # 去掉前导点，与 ctype dict key 对齐
    ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
             "css": "text/css; charset=utf-8", "png": "image/png", "svg": "image/svg+xml",
             "ico": "image/x-icon", "json": "application/json; charset=utf-8"}.get(ext, "application/octet-stream")
    with open(full, "rb") as f:
        data = f.read()
    h.send_response(200)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


class _BadJSON(Exception):
    """请求体不是合法 JSON（_read_json 抛出，do_POST/do_PUT 统一转 400）。"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  [web] %s\n" % (fmt % args))

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _BadJSON  # do_POST/do_PUT 捕获后统一回 400「请求体不是合法 JSON」

    def _get_no(self, data):
        """从请求体取 "no" 并校验为正整数；非法直接回 400 并返回 None。"""
        try:
            no = int(data.get("no"))
        except (TypeError, ValueError):
            api_error(self, 400, "no 需为正整数")
            return None
        if no < 1:
            api_error(self, 400, "no 需为正整数")
            return None
        return no

    def _same_origin_guard(self):
        """CSRF 防护（POST/PUT 入口调用）：校验 Origin 头。
        无 Origin 放行（curl / 同源 GET 表单等非浏览器场景）；
        Origin 的 host 与请求 Host 头一致（同源）放行；其余 403 拒绝。"""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            ohost = urllib.parse.urlsplit(origin).netloc
        except Exception:
            ohost = ""
        if ohost and ohost == (self.headers.get("Host") or ""):
            return True
        api_error(self, 403, "cross-origin request blocked")
        return False

    def _run_or_502(self, script, args, timeout=900):
        """v0.8/v0.9 长任务路由统一入口：引擎脚本未就位 → 502（业务语义明确的降级，
        而非 500/no route）；就位则跑引擎（子进程，cwd=项目根）。
        返回 (ok, stdout, stderr)；已回 502 时返回 None（调用方直接 return）。"""
        if not os.path.isfile(script):
            api_error(self, 502, "引擎脚本未就位（scripts/%s）——请先升级引擎到 v0.8+"
                      % os.path.basename(script))
            return None
        return run_engine(args, timeout=timeout)

    # ---------------- 分派（路由表） ----------------
    def _dispatch(self, method, segs):
        fn, params = match_route(method, segs)
        if fn is None:
            return False
        fn(self, params)
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        segs = [s for s in path.split("/") if s]
        try:
            if not segs or segs[0] in ("index.html", "static", "ui", "legacy", "assets"):
                serve_static(self, path)
                return
            if segs[0] == "api":
                if not self._dispatch("GET", segs[1:]):
                    api_error(self, 404, "no route")
                return
            api_error(self, 404, "unknown path")
        except BrokenPipeError:
            pass
        except Exception as e:
            # 兜底 500：响应只回「类型名: 服务器内部错误」防内部细节泄露；完整异常+栈进 stderr
            sys.stderr.write("  [web] 500 %s: %s\n" % (type(e).__name__, e))
            traceback.print_exc()
            api_error(self, 500, f"{type(e).__name__}: 服务器内部错误")

    def do_POST(self):
        if not self._same_origin_guard():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        segs = [s for s in path.split("/") if s]
        try:
            if segs[:1] == ["api"]:
                if not self._dispatch("POST", segs[1:]):
                    api_error(self, 404, "no route")
                return
            api_error(self, 404, "unknown path")
        except BrokenPipeError:
            pass
        except _BadJSON:
            api_error(self, 400, "请求体不是合法 JSON")
        except Exception as e:
            sys.stderr.write("  [web] 500 %s: %s\n" % (type(e).__name__, e))
            traceback.print_exc()
            api_error(self, 500, f"{type(e).__name__}: 服务器内部错误")

    def do_PUT(self):
        if not self._same_origin_guard():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        segs = [s for s in path.split("/") if s]
        try:
            if segs[:1] == ["api"]:
                if not self._dispatch("PUT", segs[1:]):
                    api_error(self, 404, "no route")
                return
            api_error(self, 404, "unknown path")
        except BrokenPipeError:
            pass
        except _BadJSON:
            api_error(self, 400, "请求体不是合法 JSON")
        except Exception as e:
            sys.stderr.write("  [web] 500 %s: %s\n" % (type(e).__name__, e))
            traceback.print_exc()
            api_error(self, 500, f"{type(e).__name__}: 服务器内部错误")

    # ---------------- SSE 流式对话（主体在 api_assistant.chat_stream） ----------------
    def _chat_stream(self, msgs, temperature, max_tokens=2000):
        from api_assistant import chat_stream
        chat_stream(self, msgs, temperature, max_tokens)


# ---- 兜底路由（最后注册）：还原原 if 链「书不存在优先于 no route」的报错口径 ----
@route("GET", "book/{book}/{rest...}")
def _book_get_fallback(h, params):
    # 原 GET book 块对一切 len>=2 的 /api/book/{b}/... 先查书再匹配子路由
    p = book_path(params["book"])
    if not p:
        api_error(h, 404, "书不存在: " + params["book"])
        return
    api_error(h, 404, "no route")


@route("POST", "book/{book}/{rest...}")
def _book_post_fallback(h, params):
    # 原 POST 口径：len==3 的未知动作与 task/* 的未知子动作会先查书；
    # 更深/更浅的未知路径不会进 book 分支，直接 no route。
    rest = params["rest"]
    if len(rest) == 1 or (len(rest) == 2 and rest[0] == "task"):
        p = book_path(params["book"])
        if not p:
            api_error(h, 404, "书不存在: " + params["book"])
            return
    api_error(h, 404, "no route")


@route("PUT", "book/{book}/{rest...}")
def _book_put_fallback(h, params):
    # 原 PUT 口径：仅 len(segs)==4 的未知子路径（doc/ch 之外的）先查书；其余直接 no route。
    rest = params["rest"]
    if len(rest) == 2:
        p = book_path(params["book"])
        if not p:
            api_error(h, 404, "书不存在: " + params["book"])
            return
    api_error(h, 404, "no route")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="novel-ledger Web 工作台")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    api_tasks.recover_stale_tasks()  # 启动恢复：清掉崩溃残留的 running 任务（改 paused），防书被永久锁死
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("novel-ledger Web 工作台已启动")
    print(f"  浏览器打开 → http://127.0.0.1:{args.port}")
    print(f"  书目录 → {BOOKS_DIR}")
    print(f"  API key: {'已配置 ✅' if KEY_SET else '未配置 ⚠ 写章会失败，请先配 .env'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
