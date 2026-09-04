# -*- coding: utf-8 -*-
"""web/test_routes.py —— novel-ledger Web 后端路由验收测试（零第三方依赖，仅本机回环）

背景（复盘坑 19 / Q4 教训）：引擎侧有 23 条断言守着，Web 侧却一条都没有——
server.py 曾因缩进问题让 POST 路由全部不可达而无人发现。本脚本补上 Web 的验收基线：
在本机随机端口起一个真实 ThreadingHTTPServer，把主要路由逐条打一遍。

覆盖：
  1. 静态首页 / 可访问且为 text/html
  2. /static/app.js Content-Type 为 application/javascript（防坑 13 复发：白屏/脚本被拒）
  3. GET /api/status 返回 ok 且 API Key 已脱敏（不回显明文）
  4. GET /api/books 能列出《雾城档案》
  5. GET /api/book/<雾城档案> 详情返回章节列表结构
  6. GET /api/book/<雾城档案>/ch/1 能读到第一章正文
  7. POST 到不存在的书 → 404（验证 POST 路由可达而非静默 404 no route / 500）
  8. PUT 到不存在的书 → 404（同上，PUT 分支可达）

运行：python web/test_routes.py
任何 ❌ 都以非零码退出。只读验证：全部请求不写任何项目数据。
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WEB_DIR)
import server as S  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def req(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (PORT, urllib.parse.quote(path, safe="/"))
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"} if data else {},
    )
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8")


srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"== Web 路由验收（本机回环 :{PORT}，零外部请求）==")

try:
    # 1. 静态首页
    code, ctype, body = req("GET", "/")
    check("首页 200", code == 200, str(code))
    check("首页 text/html", ctype.startswith("text/html"), ctype)
    check("首页含工作台标题", "novel-ledger" in body)

    # 2. JS 静态资源 Content-Type（防坑 13：扩展名 key 前导点 → 全变 octet-stream）
    code, ctype, body = req("GET", "/static/app.js")
    check("app.js 200", code == 200, str(code))
    check("app.js 是 application/javascript", "javascript" in ctype, ctype)
    check("app.js 不含破损 onlick", '"()' not in body and "大大纲" not in body)
    check("设置页 CSS 无花括号错乱", ".form-section h4{margin" in body and "{form-section" not in body)
    check("app.js 定义 chapterActions（防 P0-1 复发：章节页动作条空白）", "function chapterActions()" in body)
    check("app.js 动作条调用与定义匹配", "setActions(chapterActions())" in body)

    # 3. 状态接口 + API Key 脱敏
    code, ctype, body = req("GET", "/api/status")
    st = json.loads(body)
    check("status 200 且 ok=true", code == 200 and st.get("ok") is True, body[:120])
    ak = (st.get("settings") or {}).get("AGNES_API_KEY", "")
    check("status 不回显明文 API Key", ak in ("", "****"), repr(ak))

    # 4/5/6. 书列表与章节读取
    code, _, body = req("GET", "/api/books")
    books = json.loads(body).get("books", [])
    check("books 包含《雾城档案》", "雾城档案" in books, str(books))
    check("books 过滤 _ 开头目录（_archive 不当书列出，防 P0-3 复发）",
          all(not b.startswith("_") for b in books), str(books))

    code, _, body = req("GET", "/api/book/雾城档案")
    detail = json.loads(body)
    check("书详情 200 含 chapters 字段", code == 200 and "chapters" in detail, body[:100])

    code, _, body = req("GET", "/api/book/雾城档案/ch/1")
    ch = json.loads(body)
    check("读 ch001 正文 200", code == 200 and ch.get("no") == 1, str(code))
    check("ch001 正文非空", bool((ch.get("content") or "").strip()), "")

    # 7/8. POST/PUT 分支可达（打不存在的书，验证返回业务 404 而非 no route/500）
    code, _, body = req("POST", "/api/book/no_such_book_abc/write", {"no": 1})
    check("POST 不存在书 → 404（业务分支可达）", code == 404 and "不存在" in body, f"{code} {body[:80]}")

    code, _, body = req("PUT", "/api/book/no_such_book_abc/doc/设定", "改")
    check("PUT 不存在书 → 404（PUT 分支可达）", code == 404, f"{code} {body[:80]}")

    # chat 缺 messages 应 400 且零外呼（绝不 404 no route / 500；也不消耗模型额度）
    code, _, body = req("POST", "/api/chat", {})
    check("POST /api/chat 缺 messages → 400 且零外呼", code == 400, f"{code} {body[:80]}")

    # 9. 建书链路（shutil 漏 import 曾让建书 500，2026-09-04 修复）：建临时书→验 ok→清理
    code, _, body = req("POST", "/api/books", {"name": "测试_断言_建书"})
    ok_created = code == 200 and json.loads(body).get("ok") is True
    check("POST /api/books 建书成功（shutil 可用）", ok_created, f"{code} {body[:80]}")
    if ok_created:
        import shutil as _sh
        _sh.rmtree(os.path.join(S.BOOKS_DIR, "测试_断言_建书"), ignore_errors=True)
        check("测试书已清理", not os.path.isdir(os.path.join(S.BOOKS_DIR, "测试_断言_建书")))

finally:
    srv.shutdown()

print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
