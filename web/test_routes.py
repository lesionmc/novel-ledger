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
  9. v0.8/v0.9 新增 13 路由（文风/图谱/向量/样章/隐私 + 重算/跨章/平台/试读/证据链）：
     不存在书→404、真实书语义（200/404/502）、文件白名单扩展、stub 引擎下 200+ok

运行：python web/test_routes.py
任何 ❌ 都以非零码退出。
注意：§9 建书、§12.3 任务系统会创建并删除临时测试书（测试_断言_建书 / 测试_任务书），
测试结束均清理；不触碰任何真实书籍数据。实际断言数见结尾输出行。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
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
        with urllib.request.urlopen(r, timeout=180) as resp:  # 建书断言内含引擎建账（模型调用），放宽到 180s
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8")


srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"== Web 路由验收（本机回环 :{PORT}，零外部请求）==")

try:
    # 1. 静态首页（v0.2 转正：/ = React 工作台；旧界面在 /legacy）
    code, ctype, body = req("GET", "/")
    check("首页 200", code == 200, str(code))
    check("首页 text/html", ctype.startswith("text/html"), ctype)
    check("首页为 React 工作台（含 root 挂载点与工作台标题）",
          'id="root"' in body and "novel-ledger" in body, body[:80])

    code, ctype, body = req("GET", "/legacy")
    check("旧界面 /legacy 200 可回退", code == 200 and ctype.startswith("text/html"), str(code))
    check("旧界面含旧版标记（app.js 引用）", "static/app.js" in body, body[:60])

    # 2. JS 静态资源 Content-Type（防坑 13：扩展名 key 前导点 → 全变 octet-stream）
    code, ctype, body = req("GET", "/assets/" + os.listdir(os.path.join(S.WEB_DIR, "ui", "assets"))[0])
    check("React assets 200", code == 200, str(code))
    check("React assets Content-Type 正确",
          ("javascript" in ctype) or ("css" in ctype) or ("html" in ctype), ctype)
    code, ctype, body = req("GET", "/static/app.js")
    check("app.js（旧界面资产）200", code == 200, str(code))
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
    #    幂等：上次超时的请求可能已在服务端建成功，先清理残留
    import shutil as _sh
    _sh.rmtree(os.path.join(S.BOOKS_DIR, "测试_断言_建书"), ignore_errors=True)
    code, _, body = req("POST", "/api/books", {"name": "测试_断言_建书"})
    ok_created = code == 200 and json.loads(body).get("ok") is True
    check("POST /api/books 建书成功（shutil 可用）", ok_created, f"{code} {body[:80]}")
    if ok_created:
        _sh.rmtree(os.path.join(S.BOOKS_DIR, "测试_断言_建书"), ignore_errors=True)
        check("测试书已清理", not os.path.isdir(os.path.join(S.BOOKS_DIR, "测试_断言_建书")))

    # 10.x 模板端点穿越防护 + /api/tasks + 流式/设置静态断言（2026-09-05 安全重建）
    # 10.1 valid_tpl_name 单元断言（模板 read/copy 端点共用）
    check("valid_tpl_name 拒绝 ../ 穿越", S.valid_tpl_name("../evil") is False)
    check("valid_tpl_name 拒绝反斜杠穿越", S.valid_tpl_name("..\\evil") is False)
    check("valid_tpl_name 拒绝 _ 前缀", S.valid_tpl_name("_tpl") is False)
    check("valid_tpl_name 放行正常名", S.valid_tpl_name("正常模板名") is True)

    # 10.2 模板端点穿越 4 例全 404（..%2F、反斜杠编码；read 与 copy 各两例）
    def req_raw(method, raw_path, body=None):
        # 不做二次编码：直接发原始路径（含 %2F/%5C 等穿越载荷）
        url = "http://127.0.0.1:%d%s" % (PORT, raw_path)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        r = urllib.request.Request(url, data=data, method=method,
                                   headers={"Content-Type": "application/json; charset=utf-8"} if data else {})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    code, _ = req_raw("GET", "/api/tpl/..%2F..%2F.env")
    check("模板 read ..%2F 穿越 → 404", code == 404, str(code))
    code, _ = req_raw("GET", "/api/tpl/..%5C..%5C.env")
    check("模板 read 反斜杠编码穿越 → 404", code == 404, str(code))
    books_before = set(json.loads(req("GET", "/api/books")[2]).get("books", []))
    code, _ = req_raw("POST", "/api/tpl/..%2F..%2Fsample_book/copy", {"name": "穿越测试书"})
    check("模板 copy ..%2F 穿越 → 404", code == 404, str(code))
    code, _ = req_raw("POST", "/api/tpl/..%5C..%5Cevil/copy", {"name": "穿越测试书"})
    check("模板 copy 反斜杠编码穿越 → 404", code == 404, str(code))
    books_after = set(json.loads(req("GET", "/api/books")[2]).get("books", []))
    check("模板穿越未建出书（books 目录未新增、未越界落盘）",
          books_after == books_before
          and not os.path.isdir(os.path.join(os.path.dirname(S.BOOKS_DIR), "穿越测试书"))
          and not os.path.exists(os.path.join(S.BOOKS_DIR, "..env")),
          str(sorted(books_after ^ books_before)))

    # 10.3 GET /api/tasks：200 且 tasks 为 list（并验证 _/. 前缀目录被过滤）
    code, _, body = req("GET", "/api/tasks")
    tasks = json.loads(body).get("tasks") if code == 200 else None
    check("GET /api/tasks 200", code == 200, f"{code} {body[:80]}")
    check("/api/tasks 返回 tasks 为 list", isinstance(tasks, list), str(type(tasks)))

    # 10.4 CSRF 同源防护（_same_origin_guard）行为断言：伪造 Origin 拒、同源/无 Origin 放行
    def req_origin(method, path, body, origin=None):
        url = "http://127.0.0.1:%d%s" % (PORT, urllib.parse.quote(path, safe="/"))
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
        if origin:
            headers["Origin"] = origin
        r = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    code, _ = req_origin("POST", "/api/chat", {}, origin="http://evil.example.com")
    check("伪造跨站 Origin POST → 403（CSRF 拦截）", code == 403, str(code))
    code, _ = req_origin("POST", "/api/chat", {},
                         origin="http://127.0.0.1:%d" % PORT)
    check("同源 Origin POST 放行（到达业务校验 400）", code == 400, str(code))
    code, _ = req_origin("POST", "/api/chat", {})
    check("无 Origin POST 放行（curl/脚本场景）", code == 400, str(code))

    # 10.5 write_settings 原子写行为断言（打临时 .env 路径，不碰真实配置）
    _tmp_env_dir = tempfile.mkdtemp(prefix="nl_env_")
    _tmp_env = os.path.join(_tmp_env_dir, ".env")
    _real_env, _real_keyset = S.ENV_PATH, S.KEY_SET
    try:
        with open(_tmp_env, "w", encoding="utf-8") as f:
            f.write("AGNES_API_KEY=sk-test-old-12345\n# AGNES_MODEL=\n")
        S.ENV_PATH = _tmp_env
        S.write_settings({"AGNES_MODEL": "m-test"})
        txt = open(_tmp_env, encoding="utf-8").read()
        check("write_settings 白名单键写入且保留其余行",
              "AGNES_MODEL=m-test" in txt and "AGNES_API_KEY=sk-test-old-12345" in txt, txt[:80])
        check("write_settings 原子写无 .tmp 残留（os.replace）",
              not os.path.exists(_tmp_env + ".tmp"))
        S.write_settings({"AGNES_API_KEY": "****"})
        txt2 = open(_tmp_env, encoding="utf-8").read()
        check("write_settings 脱敏占位符 **** 不写回（不覆盖真实 key）",
              "sk-test-old-12345" in txt2, txt2[:80])
    finally:
        S.ENV_PATH, S.KEY_SET = _real_env, _real_keyset
        shutil.rmtree(_tmp_env_dir, ignore_errors=True)

    # 10.6 其他安全修复防回归：兜底 500 脱敏 + 用量锁
    check("_LAST_USAGE 有锁保护（ThreadingHTTPServer 并发防串话）",
          isinstance(getattr(S, "_USAGE_LOCK", None), type(threading.Lock())))

    # 11. v0.8/v0.9 新增 13 路由：可达性 + 业务语义（2026-09-06）
    BK = "雾城档案"
    NOBOOK = "no_such_book_abc"

    # 11.1 不存在的书 → 业务 404（13 条路由全覆盖，验证路由可达而非 no route/500）
    v089 = [("GET", "/style", None), ("GET", "/graph", None), ("GET", "/vector", None),
            ("GET", "/sample-chapters", None),
            ("POST", "/style-learn", {}), ("POST", "/graph", {}), ("POST", "/vector-index", {}),
            ("POST", "/privacy-scan", {}),
            ("POST", "/recalc-from", {"no": 1}), ("POST", "/cross-audit", {"no": 1}),
            ("POST", "/platform-check", {"no": 1}), ("POST", "/beta-reader", {"no": 1}),
            ("POST", "/export-evidence", {"no": 1})]
    for method, tail, body in v089:
        code, _, resp = req(method, f"/api/book/{NOBOOK}{tail}", body)
        check(f"{method} /api/book/<不存在>/{tail.strip('/')} → 404",
              code == 404 and "不存在" in resp, f"{code} {resp[:60]}")

    # 11.2 GET 读文件类路由：真实书语义（文件在→200 带内容；不在→404 带友好引导）
    code, _, resp = req("GET", f"/api/book/{BK}/style")
    d = json.loads(resp) if code in (200, 404) else {}
    check("GET /style 真书 200/404 语义正确",
          (code == 200 and "content" in d) or (code == 404 and "文风指纹" in resp),
          f"{code} {resp[:80]}")
    code, _, resp = req("GET", f"/api/book/{BK}/graph")
    d = json.loads(resp) if code in (200, 404) else {}
    check("GET /graph 真书 200/404 语义正确",
          (code == 200 and ("json" in d or "md" in d)) or (code == 404 and "关系图谱" in resp),
          f"{code} {resp[:80]}")

    # 11.3 vector 状态：200 且 available 为 bool（未装 chromadb → available:false，绝不 500）
    code, _, resp = req("GET", f"/api/book/{BK}/vector")
    d = json.loads(resp) if code == 200 else {}
    check("GET /vector 200 且 available 为 bool",
          code == 200 and isinstance(d.get("available"), bool), f"{code} {resp[:80]}")

    # 11.4 文件白名单扩展：书根三产物放行（在→200 / 不在→404，绝不能 403）；白名单外仍 403
    for rel in ("文风指纹.md", "关系图谱.json", "关系图谱.md"):
        code, _, _ = req("GET", f"/api/book/{BK}/file/{rel}")
        check(f"file 白名单放行书根产物 {rel}（非 403）", code in (200, 404), str(code))
    code, _, _ = req("GET", f"/api/book/{BK}/file/机密.txt")
    check("file 对照：白名单外仍 403", code == 403, str(code))

    # 11.5 长任务路由（stub 引擎）：patch run_engine 与脚本常量 → 零外呼、零模型消耗、毫秒级
    _real_run = S.run_engine
    _real_scripts = (S.STYLE_LEARN, S.REL_GRAPH, S.VECTOR)
    _stub_script = os.path.join(S.SCRIPTS_DIR, "usage_log.py")   # 项目内一定存在的真实文件
    _bogus_script = os.path.join(S.SCRIPTS_DIR, "__no_such_engine__.py")
    try:
        S.run_engine = lambda args, timeout=900: (True, "[stub] 引擎输出", "")
        S.STYLE_LEARN = S.REL_GRAPH = S.VECTOR = _stub_script
        code, _, resp = req("GET", f"/api/book/{BK}/sample-chapters")
        check("GET /sample-chapters（stub 引擎）200 且 ok",
              code == 200 and json.loads(resp).get("ok") is True, f"{code} {resp[:60]}")
        for tail, body in [("/style-learn", {}), ("/graph", {}), ("/vector-index", {}),
                           ("/privacy-scan", {}),
                           ("/recalc-from", {"no": 1}), ("/cross-audit", {"no": 1}),
                           ("/platform-check", {"no": 1}), ("/beta-reader", {"no": 1}),
                           ("/export-evidence", {"no": 1})]:
            code, _, resp = req("POST", f"/api/book/{BK}{tail}", body)
            d = json.loads(resp) if code == 200 else {}
            check(f"POST {tail}（stub 引擎）200 且 ok=true",
                  code == 200 and d.get("ok") is True, f"{code} {resp[:60]}")
        # 引擎脚本未就位 → 502（明确的业务降级语义，而非 500/no route）
        S.STYLE_LEARN = _bogus_script
        code, _, resp = req("POST", f"/api/book/{BK}/style-learn", {})
        check("引擎脚本未就位 → 502（业务降级语义）", code == 502 and "未就位" in resp,
              f"{code} {resp[:60]}")
    finally:
        S.run_engine = _real_run
        S.STYLE_LEARN, S.REL_GRAPH, S.VECTOR = _real_scripts

    # 12. v0.5/v0.6 补齐路由：体检/修复/拆书/连写任务/提示词/模板（stub 引擎，零 token）
    # 12.1 不存在的书 → 业务 404（新路由全可达，404 先于任何引擎调用，零消耗）
    for method, tail, body in [
        ("POST", "/evaluate", {"no": 1}), ("POST", "/publish-check", {"no": 1}),
        ("POST", "/checkup", {"no": 1}), ("POST", "/checkup", {"no": 1, "full": True}),
        ("POST", "/fix", {"no": 1}), ("POST", "/deconstruct", {}),
        ("GET", "/task", None),
        ("POST", "/task/start", {"count": 2}),
        ("POST", "/task/control", {"id": "x", "action": "cancel"}),
    ]:
        code, _, resp = req(method, f"/api/book/{NOBOOK}{tail}", body)
        check(f"{method} /api/book/<不存在>/{tail.strip('/')} → 404",
              code == 404 and "不存在" in resp, f"{code} {resp[:60]}")

    # 12.2 真书 + stub run_engine → 200 且 ok（evaluate/publish-check/checkup/fix/deconstruct）
    _real_run12 = S.run_engine
    _captured = []

    def _stub_run12(args, timeout=900):
        _captured.append(args)
        return (True, "[stub] 体检输出", "")

    try:
        S.run_engine = _stub_run12
        for tail, body in [("/evaluate", {"no": 1}), ("/publish-check", {"no": 1}),
                           ("/checkup", {"no": 1}), ("/checkup", {"no": 1, "full": True}),
                           ("/fix", {"no": 1}), ("/deconstruct", {})]:
            code, _, resp = req("POST", f"/api/book/{BK}{tail}", body)
            d = json.loads(resp) if code == 200 else {}
            check(f"POST {tail}（stub 引擎）200 且 ok=true",
                  code == 200 and d.get("ok") is True, f"{code} {resp[:60]}")
        # evaluate 必须走 checkup.py --evaluate（零 token 通道，防 flag 拼错测试发现不了）
        check("evaluate 传入命令含 checkup.py 与 --evaluate（且非 --full）",
              any(os.path.basename(a[0]) == "checkup.py" and "--evaluate" in a and "--full" not in a
                  for a in _captured), str(_captured)[:160])
        # 参数校验：no 非法 → 400 且不触引擎（零消耗）
        for tail, bad in [("/evaluate", {"no": "abc"}), ("/evaluate", {"no": -3}),
                          ("/publish-check", {"no": 0}), ("/checkup", {"no": "x"}),
                          ("/fix", {"no": None}), ("/write", {"no": -5}),
                          ("/plan", {"no": 1, "words": 20000}),
                          ("/plan", {"no": 1, "words": "abc"})]:
            code, _, resp = req("POST", f"/api/book/{BK}{tail}", bad)
            check(f"POST {tail} 非法参数 {json.dumps(bad, ensure_ascii=False)} → 400",
                  code == 400, f"{code} {resp[:60]}")
    finally:
        S.run_engine = _real_run12

    # 12.3 连写任务三端点（临时书 + stub run_engine，毫秒级完成，零 token）
    import shutil as _sh2
    _tb_name = "测试_任务书"
    _tb = os.path.join(S.BOOKS_DIR, _tb_name)
    _sh2.rmtree(_tb, ignore_errors=True)
    os.makedirs(os.path.join(_tb, "chapters"))
    try:
        code, _, resp = req("GET", f"/api/book/{_tb_name}/task")
        check("GET /task 无任务 → task 为 null",
              code == 200 and json.loads(resp).get("task") is None, f"{code} {resp[:60]}")
        code, _, resp = req("POST", f"/api/book/{_tb_name}/task/start", {"count": 11})
        check("task/start count=11 未确认 → 400 带 token 预估(55000)",
              code == 400 and "55000" in resp, f"{code} {resp[:80]}")
        code, _, resp = req("POST", f"/api/book/{_tb_name}/task/start",
                            {"count": 31, "confirmed": True})
        check("task/start count=31 → 400（单任务上限 30 章）",
              code == 400 and "30" in resp, f"{code} {resp[:80]}")
        S.run_engine = lambda args, timeout=900: (True, "[stub] 假章写完", "")
        try:
            code, _, resp = req("POST", f"/api/book/{_tb_name}/task/start",
                                {"start": 3, "count": 2, "confirmed": True})
            d = json.loads(resp) if code == 200 else {}
            tid = (d.get("task") or {}).get("id")
            check("task/start count=2 → 200 且带 task.id",
                  code == 200 and bool(tid), f"{code} {resp[:80]}")
            status, task = None, None
            for _ in range(50):
                code, _, resp = req("GET", f"/api/book/{_tb_name}/task")
                task = json.loads(resp).get("task")
                status = (task or {}).get("status")
                if status != "running":
                    break
                time.sleep(0.05)
            check("任务跑完 status=done 且 done 记录两章",
                  status == "done" and len((task or {}).get("done") or []) == 2, str(task)[:120])
            code, _, resp = req("POST", f"/api/book/{_tb_name}/task/control",
                                {"id": tid, "action": "nope"})
            check("task/control 非法 action → 400", code == 400, f"{code} {resp[:60]}")
            code, _, resp = req("POST", f"/api/book/{_tb_name}/task/control",
                                {"id": "task-nope", "action": "cancel"})
            check("task/control 未知 id → 404", code == 404, f"{code} {resp[:60]}")
            code, _, resp = req("POST", f"/api/book/{_tb_name}/task/control",
                                {"id": tid, "action": "cancel"})
            check("task/control cancel 已结束任务 → 200",
                  code == 200 and json.loads(resp).get("ok") is True, f"{code} {resp[:60]}")
        finally:
            S.run_engine = _real_run12
    finally:
        _sh2.rmtree(_tb, ignore_errors=True)

    # 12.4 提示词管理三端点（GET 列表/default 用真实 rules/；PUT 往返用临时目录，不动真实规则）
    code, _, resp = req("GET", "/api/rules")
    rules = json.loads(resp).get("rules") if code == 200 else None
    check("GET /api/rules 200 且含 system.md",
          code == 200 and isinstance(rules, list) and "system.md" in rules, str(rules)[:80])
    code, _, resp = req("GET", "/api/rules/deai_rules.md/default")
    d = json.loads(resp) if code == 200 else {}
    check("rules default 返回内置默认 >50 字",
          code == 200 and len(d.get("body") or "") > 50, f"{code} {resp[:60]}")
    code, _ = req_raw("GET", "/api/rules/..%2F.env/default")
    check("rules default ..%2F 穿越 → 404", code == 404, str(code))
    code, _ = req_raw("GET", "/api/rules/no_such_rule.md/default")
    check("rules default 坏名 → 404", code == 404, str(code))
    import tempfile
    _tmp_rules = tempfile.mkdtemp(prefix="nl_rules_")
    with open(os.path.join(_tmp_rules, "my_rule.md"), "w", encoding="utf-8") as f:
        f.write("v1 旧内容")
    _real_rules = S.RULES_DIR
    try:
        S.RULES_DIR = _tmp_rules
        code, _, resp = req("PUT", "/api/rules/my_rule.md", {"body": "v2 新内容"})
        d = json.loads(resp) if code == 200 else {}
        new_txt = open(os.path.join(_tmp_rules, "my_rule.md"), encoding="utf-8").read()
        bak_txt = open(os.path.join(_tmp_rules, "my_rule.md.bak"), encoding="utf-8").read()
        check("PUT /api/rules 往返：内容更新且旧内容备份 .bak",
              code == 200 and d.get("ok") is True and new_txt == "v2 新内容"
              and bak_txt == "v1 旧内容", f"{code} {resp[:60]}")
        code, _, resp = req("GET", "/api/rules")
        check("GET /api/rules（临时目录）含 my_rule.md",
              "my_rule.md" in (json.loads(resp).get("rules") or []), resp[:60])
        code, _, _ = req("PUT", "/api/rules/no_such_rule.md", {"body": "x"})
        check("PUT rules 白名单外坏名 → 404", code == 404, str(code))
    finally:
        S.RULES_DIR = _real_rules
        _sh2.rmtree(_tmp_rules, ignore_errors=True)

    # 12.5 GET /api/templates：题材模板结构 + 模式卡
    code, _, resp = req("GET", "/api/templates")
    d = json.loads(resp) if code == 200 else {}
    tpls = {t.get("name"): t for t in d.get("templates") or []}
    check("templates 200 且含三套题材模板",
          code == 200 and {"悬疑推理", "都市异闻", "武侠江湖"} <= set(tpls), str(list(tpls)))
    check("每套模板 docs 三件套（设定/角色卡/大纲）齐全",
          all(all((t.get("docs") or {}).get(k) for k in ("设定", "角色卡", "大纲"))
              for t in tpls.values()), str({k: v.get("docs") for k, v in tpls.items()}))
    check("模式卡含闸口逐章与连写冲刺",
          {"闸口逐章", "连写冲刺"} <= set(d.get("mode_cards") or []), str(d.get("mode_cards")))

    # 12.6 插件清单与开关（v0.3 技能中心 API）
    code, _, resp = req("GET", "/api/plugins")
    d = json.loads(resp) if code == 200 else {}
    plugs = {p.get("name"): p for p in d.get("plugins") or []}
    check("plugins 200 且含首批三插件",
          code == 200 and {"evaluate", "publish-check", "audit-full"} <= set(plugs), str(list(plugs)))
    code, _, resp = req("POST", "/api/plugins/no_such_plugin/toggle", {"enabled": False})
    check("toggle 坏插件名 → 404", code == 404, f"{code} {resp[:60]}")

    # 12.7 书本管理：archive（删除=移入 _archive，不真删）——建临时书→归档→书架消失→残留清理
    import shutil as _sh3
    _tname = "测试_断言_归档"
    _sh3.rmtree(os.path.join(S.BOOKS_DIR, _tname), ignore_errors=True)
    code, _, resp = req("POST", "/api/books", {"name": _tname})
    check("归档前置：建临时书成功", code == 200 and json.loads(resp).get("ok") is True, f"{code} {resp[:60]}")
    code, _, resp = req("POST", f"/api/book/{_tname}/archive", {})
    d = json.loads(resp) if code == 200 else {}
    check("POST /archive 归档成功且指向 _archive",
          code == 200 and d.get("ok") is True and "_archive" in (d.get("archived_to") or ""), f"{code} {resp[:80]}")
    code, _, resp = req("GET", "/api/books")
    check("归档后书架不再列出该书", _tname not in resp, "")
    check("归档目录真实存在（可手工找回）",
          any(p.startswith(_tname + "-") for p in os.listdir(os.path.join(S.BOOKS_DIR, "_archive"))), "")
    for p in os.listdir(os.path.join(S.BOOKS_DIR, "_archive")):
        if p.startswith(_tname + "-"):
            _sh3.rmtree(os.path.join(S.BOOKS_DIR, "_archive", p), ignore_errors=True)
    code, _, resp = req("POST", "/api/book/no_such_book_abc/archive", {})
    check("POST /archive 不存在书 → 404", code == 404, f"{code} {resp[:60]}")

finally:
    srv.shutdown()

print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
