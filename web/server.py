# -*- coding: utf-8 -*-
"""novel-ledger · 本地 Web 工作台后端

纯 Python 标准库（零第三方依赖）。桥接 scripts/ 下两个引擎：
  write_chapter.py  连载引擎（写章 / 审计）
  deai.py           去 AI 味引擎（scan / polish / apply）

启动：
  python web/server.py [--port 8801]
浏览器打开 http://127.0.0.1:8801

API 一览（均返回 JSON）：
  GET  /api/status                       引擎与 key 就绪状态（含 settings 回显）
  GET  /api/settings                     读 .env 中白名单配置（不含密钥回显到前端日志）
  PUT  /api/settings                     {"changes":{...}} 写回 .env，实时生效
  POST /api/settings/test                ping 一次模型验证连通（4 token）
  POST /api/chat                         {"messages":[...], "stream":bool} 多轮对话；stream=true 为 SSE
  GET  /api/books                        书列表
  POST /api/books                        {"name": "新书"} 从 sample_book 建书并自动 init-state
  POST /api/book/from-chat               {"name":..., "files":{设定,角色卡,大纲}} AI 建书（写三件套+初始化）
  GET  /api/book/{book}                  书详情（章节列表 + next_no + has_state）
  GET  /api/book/{book}/files            chapters/ 下正文与报告产物列表
  GET  /api/book/{book}/doc/{doc}        读 设定/角色卡/大纲/账本 文本 (doc=设定|角色卡|大纲|state)
  PUT  /api/book/{book}/doc/{doc}        保存文本（body 原文）
  GET  /api/book/{book}/ch/{no}          读章节正文
  PUT  /api/book/{book}/ch/{no}          保存章节正文
  POST /api/book/{book}/write            {"no":可选} 写下一章（长时，同步等待；缺账本自动 init）
  POST /api/book/{book}/audit            {"no":N} 一致性审计（缺账本自动 init）
  POST /api/book/{book}/scan             全书 AI 腔体检（本地零 token）
  POST /api/book/{book}/polish           {"no":N} 去味精判报告
  POST /api/book/{book}/apply            {"no":N} 应用改写（自动备份）
  GET  /api/book/{book}/file/{rel}       读 chapters/ 下报告/diff/正文文件（白名单防穿越）
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT, "books")
SAMPLE_DIR = os.path.join(ROOT, "sample_book")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
WEB_DIR = os.path.join(ROOT, "web")
ENV_PATH = os.path.join(ROOT, ".env")

WRITE_CH = os.path.join(SCRIPTS_DIR, "write_chapter.py")
DEAI = os.path.join(SCRIPTS_DIR, "deai.py")
DOCS = ("设定", "角色卡", "大纲", "state")
DOC_FILE = {"设定": "设定.md", "角色卡": "角色卡.md", "大纲": "大纲.md", "state": "story_state.md"}
PORT = 8000


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
                "FALLBACK_API_KEY", "FALLBACK_BASE_URL", "FALLBACK_MODEL")


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
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
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


def llm_chat(messages, temperature=0.7, max_tokens=2000):
    """用配置的模型做一次 chat（供对话建书/测试连接用）。返回文本。"""
    cfg = live_env()
    if not cfg["key"]:
        raise RuntimeError("未配置 AGNES_API_KEY（请在 ⚙ 设置 里填写）")
    import urllib.request as _ur
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
    with _ur.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choice = (data.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content", "").strip()


def book_path(name):
    """安全取书目录：name 只能是合法目录名，防路径穿越。"""
    if not name or name in (".", "..") or re.search(r"[/\\]", name):
        return None
    p = os.path.join(BOOKS_DIR, name)
    return p if os.path.isdir(p) else None


def list_books():
    if not os.path.isdir(BOOKS_DIR):
        return []
    return sorted(d for d in os.listdir(BOOKS_DIR)
                  if os.path.isdir(os.path.join(BOOKS_DIR, d)) and not d.startswith("."))


def chapter_list(p):
    ch_dir = os.path.join(p, "chapters")
    if not os.path.isdir(ch_dir):
        return []
    return sorted((int(m.group(1)), m.group(0))
                  for m in (re.match(r"ch(\d+)\.md$", f) for f in os.listdir(ch_dir))
                  if m)


def read_text(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def run_engine(args, timeout=900):
    """跑引擎脚本（子进程），返回 (ok, stdout, stderr)。cwd=项目根。"""
    try:
        r = subprocess.run([sys.executable] + args, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=ROOT)
        return (r.returncode == 0, r.stdout, r.stderr)
    except subprocess.TimeoutExpired:
        return (False, "", "引擎执行超时（超过 %ss）" % timeout)


def next_chapter_no(p):
    chs = chapter_list(p)
    return (max(n for n, _ in chs) + 1) if chs else 1


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


def serve_static(h, path):
    rel = path.lstrip("/")
    if rel == "":
        rel = "index.html"
    elif rel.startswith("static/"):
        rel = rel[len("static/"):]
    full = os.path.normpath(os.path.join(WEB_DIR, "static", rel))
    if not full.startswith(os.path.join(WEB_DIR, "static")):
        api_error(h, 403, "forbidden")
        return
    if not os.path.isfile(full):
        api_error(h, 404, "not found: " + rel)
        return
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



class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  [web] %s\n" % (fmt % args))

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    # ---------------- 分派 ----------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        segs = [s for s in path.split("/") if s]
        try:
            if not segs or segs[0] in ("index.html", "static"):
                serve_static(self, path)
                return
            if segs[0] == "api":
                self.handle_api_get(segs[1:])
                return
            api_error(self, 404, "unknown path")
        except BrokenPipeError:
            pass
        except Exception as e:
            api_error(self, 500, f"{type(e).__name__}: {e}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        segs = [s for s in path.split("/") if s]
        try:
            if segs[:1] == ["api"]:
                self.handle_api_post(segs[1:])
                return
            api_error(self, 404, "unknown path")
        except BrokenPipeError:
            pass
        except Exception as e:
            api_error(self, 500, f"{type(e).__name__}: {e}")

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        segs = [s for s in path.split("/") if s]
        try:
            if segs[:1] == ["api"]:
                self.handle_api_put(segs[1:])
                return
            api_error(self, 404, "unknown path")
        except BrokenPipeError:
            pass
        except Exception as e:
            api_error(self, 500, f"{type(e).__name__}: {e}")

    # ---------------- GET ----------------
    def handle_api_get(self, segs):
        if segs == ["status"]:
            api_ok(self, {"ok": True, "key_set": KEY_SET, "books_dir": BOOKS_DIR,
                           "settings": public_settings()})
            return
        if segs == ["settings"]:
            api_ok(self, {"settings": public_settings()})
            return
        if segs == ["books"]:
            api_ok(self, {"books": list_books()})
            return
        if segs and segs[0] == "book" and len(segs) >= 2:
            name = segs[1]
            p = book_path(name)
            if not p:
                api_error(self, 404, "书不存在: " + name)
                return
            if len(segs) == 2:
                api_ok(self, {
                    "name": name,
                    "chapters": [{"no": n, "file": f,
                                   "size": os.path.getsize(os.path.join(p, "chapters", f))}
                                 for n, f in chapter_list(p)],
                    "next_no": next_chapter_no(p),
                    "has_state": os.path.exists(os.path.join(p, "story_state.md")),
                })
                return
            if len(segs) == 4 and segs[2] == "doc":
                doc = segs[3]
                if doc not in DOCS:
                    api_error(self, 404, "doc 必须是 " + "|".join(DOCS))
                    return
                txt = read_text(os.path.join(p, DOC_FILE[doc]))
                if txt is None:
                    api_error(self, 404, "文件不存在")
                    return
                api_ok(self, {"doc": doc, "content": txt})
                return
            if len(segs) == 4 and segs[2] == "ch":
                if not re.fullmatch(r"(\d+)", segs[3]):
                    api_error(self, 400, "章号格式错误")
                    return
                no = int(segs[3])
                txt = read_text(os.path.join(p, "chapters", f"ch{no:03d}.md"))
                if txt is None:
                    api_error(self, 404, "该章不存在")
                    return
                api_ok(self, {"no": no, "content": txt})
                return
            if len(segs) >= 4 and segs[2] == "file":
                rel = "/".join(segs[3:])
                if not re.fullmatch(r"chapters/[^/]+\.(md|json)", rel) and rel != "story_state.md":
                    api_error(self, 403, "只允许读 chapters/ 下的文件或账本")
                    return
                txt = read_text(os.path.join(p, rel))
                if txt is None:
                    api_error(self, 404, "文件不存在: " + rel)
                    return
                api_ok(self, {"file": rel, "content": txt})
                return
            if len(segs) == 3 and segs[2] == "files":
                ch_dir = os.path.join(p, "chapters")
                out = []
                if os.path.isdir(ch_dir):
                    for f in sorted(os.listdir(ch_dir)):
                        if re.match(r"ch\d+\.(md|json)$", f) or "体检" in f or "审计" in f:
                            out.append({"file": "chapters/" + f,
                                        "size": os.path.getsize(os.path.join(ch_dir, f))})
                api_ok(self, {"files": out})
                return
        api_error(self, 404, "no route")

    # ---------------- POST ----------------
    def handle_api_post(self, segs):
        if segs == ["settings", "test"]:
            cfg = live_env()
            try:
                answer = llm_chat([
                    {"role": "system", "content": "ping"},
                    {"role": "user", "content": "ping"},
                ], max_tokens=4)
                api_ok(self, {"ok": True, "sample": answer, "model": cfg["model"]})
            except Exception as e:
                api_error(self, 502, f"连接失败：{e}")
            return

        if segs == ["chat"]:
            data = self._read_json()
            msgs = data.get("messages") or []
            if not msgs:
                api_error(self, 400, "messages 不能为空")
                return
            if data.get("stream"):
                self._chat_stream(msgs, float(data.get("temperature") or 0.8))
                return
            try:
                text = llm_chat(msgs, temperature=float(data.get("temperature") or 0.8))
                api_ok(self, {"ok": True, "content": text})
            except Exception as e:
                api_error(self, 502, f"AI 调用失败：{e}")
            return

        if segs == ["books"]:
            data = self._read_json()
            name = (data.get("name") or "").strip()
            if not name or re.search(r"[/\\]", name):
                api_error(self, 400, "书名非法（不能含 / 或 \\）")
                return
            if os.path.exists(os.path.join(BOOKS_DIR, name)):
                api_error(self, 400, "同名书已存在")
                return
            shutil.copytree(SAMPLE_DIR, os.path.join(BOOKS_DIR, name))
            ok, _, _ = run_engine([WRITE_CH, "--book", os.path.join(BOOKS_DIR, name), "--init-state"])
            api_ok(self, {"ok": ok, "name": name})
            return

        if segs == ["book", "from-chat"]:
            data = self._read_json()
            name = (data.get("name") or "").strip()
            files = data.get("files") or {}
            if not name or re.search(r"[/\\]", name):
                api_error(self, 400, "书名非法")
                return
            if not all(k in files for k in ("设定", "角色卡", "大纲")):
                api_error(self, 400, "files 需要包含 设定/角色卡/大纲 三份")
                return
            if os.path.exists(os.path.join(BOOKS_DIR, name)):
                api_error(self, 400, "同名书已存在")
                return
            try:
                shutil.copytree(SAMPLE_DIR, os.path.join(BOOKS_DIR, name))
                for k in ("设定", "角色卡", "大纲"):
                    if k not in files:
                        raise RuntimeError(f"缺少 {k} 文件内容")
                    write_text(os.path.join(BOOKS_DIR, name, DOC_FILE[k]), files[k])
                ok, _, _ = run_engine([WRITE_CH, "--book",
                                       os.path.join(BOOKS_DIR, name), "--init-state"])
            except Exception as e:
                api_error(self, 500, f"建书失败：{e}")
                return
            api_ok(self, {"ok": ok, "name": name})
            return

        if segs and segs[0] == "book" and len(segs) == 3:
            name = segs[1]
            p = book_path(name)
            if not p:
                api_error(self, 404, "书不存在: " + name)
                return
            action = segs[2]
            data = self._read_json()

            if action == "write":
                no = int(data.get("no") or 0) or next_chapter_no(p)
                if not os.path.exists(os.path.join(p, "story_state.md")):
                    sys.stderr.write("  [web] 缺 story_state.md，自动 init-state…\n")
                    run_engine([WRITE_CH, "--book", p, "--init-state"])
                ok, out, err = run_engine([WRITE_CH, "--book", p, "--chapter", str(no)])
                body = read_text(os.path.join(p, "chapters", f"ch{no:03d}.md"))
                api_ok(self, {"ok": ok, "no": no, "chars": len(body or ""),
                              "body": body, "log": (out + err)[-2000:]})
                return

            if action == "audit":
                no = int(data.get("no") or 0)
                if no < 1:
                    api_error(self, 400, "需要 no")
                    return
                if not os.path.exists(os.path.join(p, "story_state.md")):
                    sys.stderr.write("  [web] 缺 story_state.md，自动 init-state…\n")
                    run_engine([WRITE_CH, "--book", p, "--init-state"])
                ok, out, err = run_engine([WRITE_CH, "--book", p, "--audit", "--chapter", str(no)])
                report = read_text(os.path.join(p, "chapters", f"ch{no:03d}.一致性审计.md"))
                api_ok(self, {"ok": ok, "no": no, "report": report, "log": (out + err)[-1500:]})
                return

            if action == "scan":
                ok, out, err = run_engine([DEAI, "--scan", p], timeout=120)
                api_ok(self, {"ok": ok, "report": out + err})
                return

            if action == "polish":
                no = int(data.get("no") or 0)
                if no < 1:
                    api_error(self, 400, "需要 no")
                    return
                ok, out, err = run_engine([DEAI, "--polish", p, "--chapter", str(no)], timeout=300)
                report = read_text(os.path.join(p, "chapters", f"ch{no:03d}.AI腔体检.md"))
                api_ok(self, {"ok": ok, "no": no, "report": report, "log": (out + err)[-1500:]})
                return

            if action == "apply":
                no = int(data.get("no") or 0)
                if no < 1:
                    api_error(self, 400, "需要 no")
                    return
                ok, out, err = run_engine([DEAI, "--apply", p, "--chapter", str(no)], timeout=60)
                api_ok(self, {"ok": ok, "log": (out + err)[-1500:]})
                return

        api_error(self, 404, "no route")

    # ---------------- PUT ----------------
    def handle_api_put(self, segs):
        if segs == ["settings"]:
            data = self._read_json()
            changes = data.get("changes") or {}
            if not isinstance(changes, dict) or not changes:
                api_error(self, 400, "需要 changes 字段")
                return
            write_settings(changes)
            api_ok(self, {"ok": True, "settings": public_settings(), "key_set": KEY_SET})
            return
        if segs and segs[0] == "book" and len(segs) == 4:
            name = segs[1]
            p = book_path(name)
            if not p:
                api_error(self, 404, "书不存在: " + name)
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            if segs[2] == "doc":
                doc = segs[3]
                if doc not in DOCS:
                    api_error(self, 404, "doc 必须是 " + "|".join(DOCS))
                    return
                write_text(os.path.join(p, DOC_FILE[doc]), raw)
                api_ok(self, {"ok": True})
                return
            if segs[2] == "ch":
                if not re.fullmatch(r"(\d+)", segs[3]):
                    api_error(self, 400, "章号格式错误")
                    return
                no = int(segs[3])
                os.makedirs(os.path.join(p, "chapters"), exist_ok=True)
                write_text(os.path.join(p, "chapters", f"ch{no:03d}.md"), raw)
                api_ok(self, {"ok": True, "no": no})
                return
        api_error(self, 404, "no route")

    # ---------------- SSE 流式对话 ----------------
    def _chat_stream(self, msgs, temperature):
        """SSE 流式输出：event: delta / data: "文字块"，逐 token 推给前端。"""
        cfg = live_env()
        if not cfg["key"]:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "未配置 AGNES_API_KEY"}).encode("utf-8"))
            return
        import urllib.request as _ur
        payload = {
            "model": cfg["model"],
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": 2000,
            "stream": True,
            "reasoning_effort": "low",
        }
        req = _ur.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json",
                                   "Authorization": "Bearer " + cfg["key"]},
                          method="POST")
        try:
            resp = _ur.urlopen(req, timeout=240)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"上游失败：{e}"}).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            buf = b""
            while True:
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.decode("utf-8", errors="replace").rstrip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        self.wfile.write(b"event: done\ndata: {}\n\n")
                        self.wfile.flush()
                        break
                    try:
                        obj = json.loads(payload)
                        delta = (((obj.get("choices") or [{}])[0]).get("delta") or {}).get("content", "")
                        if delta:
                            self.wfile.write(
                                b"event: delta\ndata: " +
                                json.dumps(delta, ensure_ascii=False).encode("utf-8") + b"\n\n")
                            self.wfile.flush()
                    except Exception:
                        pass
        except Exception as e:
            try:
                self.wfile.write(b"event: error\ndata: " +
                                 json.dumps(str(e), ensure_ascii=False).encode("utf-8") + b"\n\n")
                self.wfile.flush()
            except Exception:
                pass
        finally:
            try:
                resp.close()
            except Exception:
                pass


def main():
    import argparse
    ap = argparse.ArgumentParser(description="novel-ledger Web 工作台")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
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
