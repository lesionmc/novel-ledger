# -*- coding: utf-8 -*-
"""web/api_assistant.py —— AI 助手路由：POST /api/chat（多轮对话，SSE 可选）与
POST /api/book/{book}/write-stream（写章实时直播 SSE）。

llm_chat / llm_mod / live_env / read_settings / run_engine / WRITE_CH 等由
server 模块在调用时动态取用（与 test_routes.py 打桩语义兼容）。
"""
import json
import os
import subprocess
import sys

from common import (ROOT, api_error, api_ok, book_lock, book_path,
                    next_chapter_no, parse_usage, read_text, route)


def _server():
    import server
    return server


@route("POST", "chat")
def post_chat(h, params):
    srv = _server()
    data = h._read_json()
    msgs = data.get("messages") or []
    if not msgs:
        api_error(h, 400, "messages 不能为空")
        return
    if data.get("stream"):
        try:
            mt = int(data.get("max_tokens") or 2000)
        except (TypeError, ValueError):
            mt = 2000
        chat_stream(h, msgs, float(data.get("temperature") or 0.8), mt)
        return
    try:
        mt = int(data.get("max_tokens") or 2000)  # 建书三件套等长输出需要放宽（曾因 2000 截断丢大纲块）
        text = srv.llm_chat(msgs, temperature=float(data.get("temperature") or 0.8), max_tokens=mt)
        api_ok(h, {"ok": True, "content": text})
    except Exception as e:
        api_error(h, 502, f"AI 调用失败：{type(e).__name__}（上游服务暂不可用）")


def chat_stream(h, msgs, temperature, max_tokens=2000):
    """SSE 流式输出：event: delta / data: "文字块"，逐 token 推给前端。
    经 scripts/llm.py 的 chat_stream 生成器取流（主备切换在网关内完成）；
    帧契约不变：delta / done / error，首 token 前失败回 502。
    （原 Handler._chat_stream 主体，语义不变。）"""
    srv = _server()
    cfg = srv.live_env()
    if not cfg["key"]:
        h.send_response(401)
        h.send_header("Content-Type", "application/json")
        h.end_headers()
        h.wfile.write(json.dumps({"error": "未配置 AGNES_API_KEY"}).encode("utf-8"))
        return
    if srv.llm_mod is None or not hasattr(srv.llm_mod, "chat_stream"):
        h.send_response(502)
        h.send_header("Content-Type", "application/json")
        h.end_headers()
        h.wfile.write(json.dumps({"error": "llm 网关未就绪（scripts/llm.py 缺 chat_stream）"}).encode("utf-8"))
        return
    s = srv.read_settings()
    kw = {"model": cfg["model"], "base_url": cfg["base_url"], "api_key": cfg["key"],
          "temperature": temperature, "max_tokens": max_tokens,
          "max_retries": 2}  # 上游偶发空响应/波动：首 token 前共 4 次尝试再报错
    if s.get("FALLBACK_API_KEY"):
        kw["fallback_key"] = s["FALLBACK_API_KEY"]
    if s.get("FALLBACK_BASE_URL"):
        kw["fallback_base_url"] = s["FALLBACK_BASE_URL"]
    if s.get("FALLBACK_MODEL"):
        kw["fallback_model"] = s["FALLBACK_MODEL"]
    try:
        it = iter(srv.llm_mod.chat_stream(msgs, **kw))
        first = next(it)  # 首 token：连接/鉴权等失败在此抛出，尚未发出任何 SSE 头
    except Exception as e:
        h.send_response(502)
        h.send_header("Content-Type", "application/json")
        h.end_headers()
        h.wfile.write(json.dumps({"error": f"上游失败：{e}"}).encode("utf-8"))
        return
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()
    try:
        delta = first
        while True:
            if delta:
                h.wfile.write(b"event: delta\ndata: " +
                              json.dumps(delta, ensure_ascii=False).encode("utf-8") + b"\n\n")
                h.wfile.flush()
            delta = next(it)
    except StopIteration:
        h.wfile.write(b"event: done\ndata: {}\n\n")
        h.wfile.flush()
    except BrokenPipeError:
        pass  # 前端断开
    except Exception as e:
        try:
            h.wfile.write(b"event: error\ndata: " +
                          json.dumps(str(e), ensure_ascii=False).encode("utf-8") + b"\n\n")
            h.wfile.flush()
        except Exception:
            pass


@route("POST", "book/{book}/write-stream")
def post_write_stream(h, params):
    srv = _server()
    p = book_path(params["book"])
    if not p:
        api_error(h, 404, "书不存在: " + params["book"])
        return
    data = h._read_json()
    # 写章实时直播（SSE）：逐行推送引擎输出，前端看得见每一步在干嘛
    raw_no = data.get("no")
    if raw_no:
        no = h._get_no(data)
        if no is None:
            return
    else:
        no = next_chapter_no(p)
    words = data.get("words")
    try:
        words = max(1000, min(10000, int(words))) if words else None
    except (TypeError, ValueError):
        words = None
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.end_headers()

    def emit(obj):
        h.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
        h.wfile.flush()

    with book_lock(p):  # 写章动账本，同书并发写/审计/修复互斥
        try:
            if not os.path.exists(os.path.join(p, "story_state.md")):
                emit({"phase": "run", "line": "【准备】账本不存在，先初始化账本（调用模型，约 1 分钟）…"})
                ok0, o0, e0 = srv.run_engine([srv.WRITE_CH, "--book", p, "--init-state"])
                for ln in (o0 + e0).splitlines():
                    if ln.strip():
                        emit({"phase": "run", "line": ln})
            args = [srv.WRITE_CH, "--book", p, "--chapter", str(no)]
            if words:
                args += ["--words", str(words)]
            if data.get("auto_backup"):
                args += ["--auto-backup"]
            emit({"phase": "run", "line": f"【启动】开始写第 {no} 章（目标 {words or 3000} 字）…"})
            proc = subprocess.Popen([sys.executable] + args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", cwd=ROOT)
            buf = []
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                buf.append(line)
                emit({"phase": "run", "line": line})
            try:
                proc.wait(timeout=1200)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                emit({"phase": "done", "ok": False, "no": no,
                      "error": "引擎超时已终止（30 分钟未结束，子进程已杀）"})
                return
            ok = proc.returncode == 0
            log = "\n".join(buf)
            body = read_text(os.path.join(p, "chapters", f"ch{no:03d}.md"))
            plan_file = os.path.join(p, "chapters", f"ch{no:03d}.章纲.md")
            usage = parse_usage("", log)
            emit({"phase": "done", "ok": ok, "no": no, "chars": len(body or ""),
                  "body": body or "", "log": log[-4000:], "words": words,
                  "plan_used": os.path.exists(plan_file), "usage": usage})
        except BrokenPipeError:
            raise  # 前端断开（如用户关页）；引擎子进程自行跑完
        except Exception as e:
            try:
                emit({"phase": "done", "ok": False, "error": f"{type(e).__name__}: {e}"})
            except Exception:
                pass
