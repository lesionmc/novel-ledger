# -*- coding: utf-8 -*-
"""web/api_engine.py —— 引擎动作路由（write/plan/plan-save/resize/backup/audit/
scan/polish/apply/evaluate/publish-check/checkup/fix/deconstruct）。

全部为 POST /api/book/{book}/{action}；先校验书存在，再读 JSON、再跑引擎。
WRITE_CH/DEAI/BACKUP/CHECKUP 与 run_engine 会被 test_routes.py 以 S.xxx 打桩，
一律经 server 模块在调用时动态取用（不许 from import）。
"""
import os
import re
import sys

from common import (api_error, api_ok, book_lock, book_path, get_last_usage,
                    next_chapter_no, parse_usage, read_text, route, write_text)


def _server():
    import server
    return server


def _require_book(h, params):
    """书存在性校验（原 if 链口径：书不存在优先于一切子路由判断）。"""
    p = book_path(params["book"])
    if not p:
        api_error(h, 404, "书不存在: " + params["book"])
        return None
    return p


@route("POST", "book/{book}/write")
def post_write(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    raw_no = data.get("no")
    if raw_no:
        no = h._get_no(data)
        if no is None:
            return
    else:
        no = next_chapter_no(p)
    words = data.get("words")
    engine_args = [srv.WRITE_CH, "--book", p, "--chapter", str(no)]
    try:
        words = max(1000, min(10000, int(words))) if words else None
    except (TypeError, ValueError):
        words = None
    if words:
        engine_args += ["--words", str(words)]
    if data.get("auto_backup"):
        engine_args += ["--auto-backup"]  # R34③ 可选开关
    plan_file = os.path.join(p, "chapters", f"ch{no:03d}.章纲.md")
    with book_lock(p):  # 写章动账本，同书并发互斥
        if not os.path.exists(os.path.join(p, "story_state.md")):
            sys.stderr.write("  [web] 缺 story_state.md，自动 init-state…\n")
            srv.run_engine([srv.WRITE_CH, "--book", p, "--init-state"])
        ok, out, err = srv.run_engine(engine_args)
    body = read_text(os.path.join(p, "chapters", f"ch{no:03d}.md"))
    api_ok(h, {"ok": ok, "no": no, "chars": len(body or ""),
               "body": body, "log": (out + err)[-2000:],
               "words": words, "plan_used": os.path.exists(plan_file),
               "usage": parse_usage(out, err)})


@route("POST", "book/{book}/plan")
def post_plan(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    # R32 闸口：出章纲（走引擎 --plan，落盘 chapters/chXXX.章纲.md）
    raw_no = data.get("no")
    if raw_no:
        no = h._get_no(data)
        if no is None:
            return
    else:
        no = next_chapter_no(p)
    words = data.get("words")
    if words is None:
        words = 3000
    try:
        words = int(words)
    except (TypeError, ValueError):
        api_error(h, 400, "words 需为 1000-10000 的整数")
        return
    if not (1000 <= words <= 10000):
        api_error(h, 400, "words 需为 1000-10000 的整数")
        return
    ok, out, err = srv.run_engine([srv.WRITE_CH, "--book", p, "--plan",
                                   "--chapter", str(no), "--words", str(words)], timeout=300)
    report = read_text(os.path.join(p, "chapters", f"ch{no:03d}.章纲.md"))
    # R35②：随章纲返回超期伏笔，确认卡顶部红条数据源
    try:
        import write_chapter as _wc
        overdue = _wc.overdue_foreshadows(read_text(os.path.join(p, "story_state.md")), no)
    except Exception:
        overdue = []
    api_ok(h, {"ok": ok, "no": no, "outline": report, "log": (out + err)[-1500:],
               "usage": parse_usage(out, err) or get_last_usage(), "overdue": overdue})


@route("POST", "book/{book}/plan-save")
def post_plan_save(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    # R32 闸口：保存作者修改后的章纲（覆盖 chXXX.章纲.md）
    no = int(data.get("no") or 0)
    text = data.get("text")
    if no < 1 or text is None:
        api_error(h, 400, "需要 no 与 text")
        return
    write_text(os.path.join(p, "chapters", f"ch{no:03d}.章纲.md"), text)
    api_ok(h, {"ok": True, "no": no})


@route("POST", "book/{book}/resize")
def post_resize(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    # R31 字数软控后半：一键加长/精简
    no = int(data.get("no") or 0)
    mode = data.get("mode") if data.get("mode") in ("expand", "shrink") else "expand"
    if data.get("target") is None:
        api_error(h, 400, "需要 target（1000–10000 的整数）")
        return
    target = data.get("target")
    try:
        target = max(1000, min(10000, int(target)))
    except (TypeError, ValueError):
        api_error(h, 400, "target 需为 1000–10000 的整数")
        return
    ok, out, err = srv.run_engine([srv.WRITE_CH, "--book", p, "--adjust", "--chapter", str(no),
                                   "--target", str(target), "--mode", mode], timeout=600)
    body = read_text(os.path.join(p, "chapters", f"ch{no:03d}.md"))
    api_ok(h, {"ok": ok, "no": no, "chars": len(body or ""), "log": (out + err)[-1500:],
               "usage": parse_usage(out, err)})


@route("POST", "book/{book}/backup")
def post_backup(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    # R34 一键备份：全家桶 zip，backups/ 保留最近 10 份
    ok, out, err = srv.run_engine([srv.BACKUP, "--book", p], timeout=120)
    m = re.search(r"已生成 → (.+)", out)
    api_ok(h, {"ok": ok, "path": m.group(1).strip() if m else "", "log": (out + err)[-1000:]})


@route("POST", "book/{book}/audit")
def post_audit(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = int(data.get("no") or 0)
    if no < 1:
        api_error(h, 400, "需要 no")
        return
    with book_lock(p):  # 审计动账本（自动 init + 引擎读账本），同书互斥
        if not os.path.exists(os.path.join(p, "story_state.md")):
            sys.stderr.write("  [web] 缺 story_state.md，自动 init-state…\n")
            srv.run_engine([srv.WRITE_CH, "--book", p, "--init-state"])
        ok, out, err = srv.run_engine([srv.WRITE_CH, "--book", p, "--audit", "--chapter", str(no)])
    report = read_text(os.path.join(p, "chapters", f"ch{no:03d}.一致性审计.md"))
    api_ok(h, {"ok": ok, "no": no, "report": report, "log": (out + err)[-1500:],
               "usage": parse_usage(out, err)})


@route("POST", "book/{book}/scan")
def post_scan(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    ok, out, err = srv.run_engine([srv.DEAI, "--scan", p], timeout=120)
    api_ok(h, {"ok": ok, "report": out + err})


@route("POST", "book/{book}/polish")
def post_polish(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = int(data.get("no") or 0)
    if no < 1:
        api_error(h, 400, "需要 no")
        return
    ok, out, err = srv.run_engine([srv.DEAI, "--polish", p, "--chapter", str(no)], timeout=300)
    report = read_text(os.path.join(p, "chapters", f"ch{no:03d}.AI腔体检.md"))
    api_ok(h, {"ok": ok, "no": no, "report": report, "log": (out + err)[-1500:],
               "usage": parse_usage(out, err)})


@route("POST", "book/{book}/apply")
def post_apply(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = int(data.get("no") or 0)
    if no < 1:
        api_error(h, 400, "需要 no")
        return
    ok, out, err = srv.run_engine([srv.DEAI, "--apply", p, "--chapter", str(no)], timeout=60)
    api_ok(h, {"ok": ok, "log": (out + err)[-1500:]})


# ---- v0.5 章节体检 / 账本修复 / 拆书（evaluate/publish-check 走 checkup 引擎，零 token）----
@route("POST", "book/{book}/evaluate")
def post_evaluate(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = h._get_no(data)
    if no is None:
        return
    r = h._run_or_502(srv.CHECKUP, [srv.CHECKUP, "--book", p, "--evaluate",
                                    "--chapter", str(no)])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "no": no, "report": (out + err)[-6000:],
               "log": (out + err)[-1500:]})


@route("POST", "book/{book}/publish-check")
def post_publish_check(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = h._get_no(data)
    if no is None:
        return
    r = h._run_or_502(srv.CHECKUP, [srv.CHECKUP, "--book", p, "--publish-check",
                                    "--chapter", str(no)])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "no": no, "report": (out + err)[-6000:],
               "log": (out + err)[-1500:]})


@route("POST", "book/{book}/checkup")
def post_checkup(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    # 默认只跑免费 L1（--evaluate）；full=true 三步全跑（审计+评估+发布检查）
    no = h._get_no(data)
    if no is None:
        return
    flag = "--full" if data.get("full") else "--evaluate"
    r = h._run_or_502(srv.CHECKUP, [srv.CHECKUP, "--book", p, flag,
                                    "--chapter", str(no)])
    if r is None:
        return
    ok, out, err = r
    # v0.9.2 数字门禁：从输出解析 gate 结论（体检台统一打印 🚦 [gate] 行）
    import re as _re
    m = _re.search(r"门禁：(pause|continue)", out + err)
    gate = m.group(1) if m else None
    sheet = os.path.join(p, "chapters", f"ch{no:03d}.体检单.md")
    sheet_body = ""
    if os.path.isfile(sheet):
        with open(sheet, encoding="utf-8") as f:
            sheet_body = f.read()
    api_ok(h, {"ok": ok, "no": no, "full": bool(data.get("full")),
               "gate": gate, "report": sheet_body or (out + err)[-6000:],
               "log": (out + err)[-1500:]})


@route("POST", "book/{book}/score")
def post_score(h, params):
    """v0.9.2 6 维评分（LLM，提示词走插件链）：照 evaluate 模式转引擎 --score。"""
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = h._get_no(data)
    if no is None:
        return
    r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, "--score", str(no),
                                     "--chapter", str(no)])
    if r is None:
        return
    ok, out, err = r
    report = ""
    fp = os.path.join(p, "chapters", f"ch{no:03d}.评分.md")
    if os.path.isfile(fp):
        with open(fp, encoding="utf-8") as f:
            report = f.read()
    # 以「评分文件落盘」为成功依据（引擎退出码在部分 Windows 子进程场景不稳）
    api_ok(h, {"ok": bool(report), "no": no, "report": report,
               "log": (out + err)[-1500:]})


@route("POST", "book/{book}/fix")
def post_fix(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = h._get_no(data)
    if no is None:
        return
    # 审计修复闭环后半步：引擎无 --fix，落地为 --state-only 账本重算
    # （与 task_runner 账本失败补救同通道；审计报告由 /audit 产出）
    with book_lock(p):  # fix 直接重写账本，同书互斥
        r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, "--state-only",
                                         "--chapter", str(no)])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "no": no, "log": (out + err)[-2000:]})


@route("POST", "book/{book}/deconstruct")
def post_deconstruct(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    # 拆书七维报告（免章号，烧 token；报告落 _research/拆书报告.md）
    r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, "--deconstruct"])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "report": (out + err)[-6000:],
               "log": (out + err)[-2000:]})
