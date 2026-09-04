# -*- coding: utf-8 -*-
"""boundary_test.py —— v0.2 新功能边界情况测试（零网络、零模型调用、临时目录造书）

覆盖：
  A. R31 words 边界：clamp_words + build_context 注入（999/1000/10001/None）
  B. R32 章纲注入：有章纲/无章纲
  C. R35 超期解析：埋设于第1章@ch6 超期 / 埋设于第5章 不超 / 恰好差3章不超
  D. R34 backup：zip 内容全家桶、keep=2 修剪、不存在的书报错不崩
  E. R48 usage 容错：坏行跳过、空流水汇总全 0
  F. server 边界（进程内起真实 Handler，临时端口，零残留）：
     404 / 400 / 书详情 snapshots+overdue / /api/usage
运行：python _research/boundary_test.py
任何 ❌ 都以非零码退出。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(ROOT, "web"))

import write_chapter  # noqa: E402
import usage_log      # noqa: E402

PASS = 0
FAIL = 0
BUGS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        BUGS.append(name)
        print(f"  ❌ {name} {detail}")


def make_book(tmp, name="边界书", chapters=None, snapshots=None):
    """造临时书：三件套 + 账本 + 可选章节与快照，返回书目录路径。"""
    book = os.path.join(tmp, name)
    os.makedirs(os.path.join(book, "chapters"), exist_ok=True)

    def w(p, s):
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)

    w(os.path.join(book, "设定.md"), "世界观：边界测试城。")
    w(os.path.join(book, "大纲.md"), "主线：测边界。")
    w(os.path.join(book, "角色卡.md"), "主角：边界员。")
    w(os.path.join(book, "story_state.md"),
      "## 当前时间\n- 2009-11-20\n\n## 伏笔账本\n- （空）\n")
    for fn, content in (chapters or {}).items():
        w(os.path.join(book, "chapters", fn), content)
    if snapshots:
        sd = os.path.join(book, "_snapshots")
        os.makedirs(sd, exist_ok=True)
        for fn, content in snapshots.items():
            w(os.path.join(sd, fn), content)
    return book


_tmp = tempfile.mkdtemp(prefix="boundary_")
try:
    # ── A. R31 words 边界 ─────────────────────────────────────
    print("== A. R31 字数边界 ==")
    check("clamp_words(999)=1000", write_chapter.clamp_words(999) == 1000)
    check("clamp_words(1000)=1000", write_chapter.clamp_words(1000) == 1000)
    check("clamp_words(10001)=10000", write_chapter.clamp_words(10001) == 10000)
    check("clamp_words(None)=3000", write_chapter.clamp_words(None) == 3000)
    check("clamp_words('abc')=3000", write_chapter.clamp_words("abc") == 3000)
    check("clamp_words(-5)=1000", write_chapter.clamp_words(-5) == 1000)

    bk = make_book(_tmp, "字数书", chapters={"ch001.md": "第一章正文。" * 30})
    # build_context 直调（绕过 main 的钳制）：应同样落在 1000–10000 安全区
    ctx = write_chapter.build_context(bk, 2, words=999)
    check("build_context(words=999) 注入钳到 1000", "1000 字左右" in ctx and "999 字左右" not in ctx,
          [ln for ln in ctx.splitlines() if "字左右" in ln][:1].__str__())
    ctx = write_chapter.build_context(bk, 2, words=10001)
    check("build_context(words=10001) 注入钳到 10000", "10000 字左右" in ctx,
          [ln for ln in ctx.splitlines() if "字左右" in ln][:1].__str__())
    ctx = write_chapter.build_context(bk, 2, words=None)
    check("build_context(words=None) 回默认 3000", "3000 字左右" in ctx and "None" not in ctx,
          [ln for ln in ctx.splitlines() if "字左右" in ln][:1].__str__())
    ctx = write_chapter.build_context(bk, 2, words=4500)
    check("build_context(words=4500) 原样注入", "4500 字左右" in ctx)

    # ── B. R32 章纲注入 ───────────────────────────────────────
    print("== B. R32 章纲注入 ==")
    with open(os.path.join(bk, "chapters", "ch002.章纲.md"), "w", encoding="utf-8") as f:
        f.write("# ch002 章纲\n- 末尾钩子：边界测试独有钩子XYZ")
    ctx = write_chapter.build_context(bk, 2, words=3000)
    check("有章纲：注入章纲内容", "本章章纲" in ctx and "边界测试独有钩子XYZ" in ctx)
    ctx3 = write_chapter.build_context(bk, 3, words=3000)
    check("无章纲：不注入章纲块", "本章章纲" not in ctx3)

    # ── C. R35 超期解析 ───────────────────────────────────────
    print("== C. R35 伏笔超期 ==")
    state = """## 伏笔账本
- 神秘监视者 [待回收·埋设于第 1 章]
- 车祸真相 [待回收·埋设于第 5 章]
- 徽记同源 [待回收·埋设于第 3 章]
- 已了结的 [已回收·埋设于第 1 章，回收于第 4 章]
- 无章号条目 [待回收]
- （空）
"""
    over = write_chapter.overdue_foreshadows(state, 6)
    texts = [o["text"] for o in over]
    check("埋设于第1章@ch6 判超期", any("神秘监视者" in t for t in texts), str(texts))
    check("埋设于第5章@ch6 不超期（差1章）", not any("车祸真相" in t for t in texts), str(texts))
    check("埋设于第3章@ch6 不超期（恰好差3章=边界内）", not any("徽记同源" in t for t in texts), str(texts))
    check("已回收/无章号条目不误报", len(over) == 1, str(over))
    check("overdue_by 数值正确", over and over[0]["overdue_by"] == 5, str(over))
    over7 = write_chapter.overdue_foreshadows(state, 7)
    check("ch7 时第3章条目转为超期（差4章）", any("徽记同源" in o["text"] for o in over7),
          str([o["text"] for o in over7]))
    # 埋设于第 4 章@ch6 → 差 2，不超
    state2 = "## 伏笔账本\n- 新伏笔 [待回收·埋设于第4章]\n"
    check("埋设于第4章@ch6 不超期", write_chapter.overdue_foreshadows(state2, 6) == [])

    # ── D. R34 backup ─────────────────────────────────────────
    print("== D. R34 备份 ==")
    import backup_book
    bkbk = make_book(_tmp, "备份书",
                     chapters={"ch001.md": "正文", "ch001.章纲.md": "章纲"},
                     snapshots={"ch001.state.md": "## 当前时间\n- 快照"})
    outdir = os.path.join(_tmp, "backups_out")
    p1 = backup_book.backup_book(bkbk, out_dir=outdir, keep=10)
    check("备份 zip 生成", os.path.exists(p1) and p1.endswith(".zip"))
    with zipfile.ZipFile(p1) as z:
        names = z.namelist()
    need = ["设定.md", "角色卡.md", "大纲.md", "story_state.md",
            "chapters/ch001.md", "chapters/ch001.章纲.md", "_snapshots/ch001.state.md"]
    missing = [n for n in need if not any(x.endswith(n) for x in names)]
    check("zip 含全家桶（三件套+账本+chapters+_snapshots）", not missing, "缺: " + str(missing))

    # 连跑 4 次 keep=2 → 只剩 2 份（时间戳精确到秒，间隔 1.1s 防同名覆盖）
    for i in range(3):
        time.sleep(1.1)
        backup_book.backup_book(bkbk, out_dir=outdir, keep=2)
    left = sorted(f for f in os.listdir(outdir) if f.startswith("备份书-") and f.endswith(".zip"))
    check("连跑 4 次 keep=2 只剩 2 份", len(left) == 2, str(left))

    # 不存在的书：CLI 子进程方式，exit code 非 0 且有中文提示
    r = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "backup_book.py"), "--book", os.path.join(_tmp, "不存在的书")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    combined = (r.stdout or "") + (r.stderr or "")
    check("对不存在的书备份：exit code 非 0", r.returncode != 0, str(r.returncode))
    check("对不存在的书备份：有中文报错", "书目录不存在" in combined, combined[:120])

    # ── E. R48 usage 容错 ─────────────────────────────────────
    print("== E. R48 用量容错 ==")
    upath = os.path.join(_tmp, "usage.jsonl")
    with open(upath, "w", encoding="utf-8") as f:
        f.write('{"day":"2026-09-04","action":"写正文","model":"m","in":10,"out":5,"total":15,"book":"b","chapter":1,"ts":"2026-09-04 10:00:00"}\n')
        f.write("\n")                      # 空行
        f.write('{"day":"2026-09-04","acti')  # 半截 JSON
        f.write("   \n")                   # 纯空白行
        f.write("not json at all\n")       # 纯文本坏行
    entries = usage_log.load_entries(path=upath)
    check("坏行（空行/半截JSON/文本）跳过不崩，剩 1 条合法", len(entries) == 1, str(len(entries)))
    agg = usage_log.aggregate(entries)
    check("合法行汇总正确", agg["total"] == 15 and agg["calls"] == 1, str(agg)[:120])
    empty_agg = usage_log.aggregate([])
    check("空流水汇总全 0 不报错",
          empty_agg["calls"] == 0 and empty_agg["total"] == 0
          and empty_agg["total_in"] == 0 and empty_agg["total_out"] == 0
          and empty_agg["chapters"] == [] and empty_agg["write_avg"] is None,
          str(empty_agg)[:120])
    check("文件不存在时 load_entries 返回空", usage_log.load_entries(path=os.path.join(_tmp, "nope.jsonl")) == [])
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# ── F. server 边界（进程内真实 Handler，临时端口，零残留、零模型调用）──
print("== F. server 边界 ==")
import server as S  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def req(method, path, body=None):
    url = "http://127.0.0.1:%d%s" % (PORT, urllib.parse.quote(path, safe="/"))
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json; charset=utf-8"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


try:
    code, body = req("POST", "/api/book/不存在书XYZ/backup", {})
    check("POST backup 不存在的书 → 404（而非 500）", code == 404, f"{code} {body[:80]}")

    code, body = req("POST", "/api/book/雾城档案/resize", {})  # 缺 target
    check("POST resize 缺 target → 400", code == 400, f"{code} {body[:100]}")

    code, body = req("POST", "/api/book/雾城档案/resize", {"no": 1, "target": "abc"})
    check("POST resize target 非法 → 400", code == 400, f"{code} {body[:100]}")

    code, body = req("POST", "/api/book/雾城档案/plan-save", {"no": 1})  # 缺 text
    check("POST plan-save 缺 text → 400", code == 400, f"{code} {body[:100]}")

    code, body = req("GET", "/api/book/雾城档案")
    d = json.loads(body)
    check("GET 书详情 200", code == 200)
    check("书详情含 snapshots 字段", "snapshots" in d, str(list(d.keys())))
    check("书详情含 overdue 字段", "overdue" in d, str(list(d.keys())))
    check("雾城档案 snapshots 非空（22 章底账）", isinstance(d.get("snapshots"), list) and len(d["snapshots"]) > 0,
          str(d.get("snapshots"))[:80])

    code, body = req("GET", "/api/usage")
    u = json.loads(body)
    check("GET /api/usage 200 且含 summary", code == 200 and "summary" in u, f"{code} {body[:80]}")
    s = u.get("summary") or {}
    check("summary 字段齐全（calls/total/by_day/by_action/chapters）",
          all(k in s for k in ("calls", "total", "by_day", "by_action", "chapters")), str(list(s.keys())))
    check("summary 数值为非负", s.get("calls", -1) >= 0 and s.get("total", -1) >= 0)
finally:
    srv.shutdown()

print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
if FAIL:
    print("疑似 bug：" + "；".join(BUGS))
    sys.exit(1)
print("全部通过 ✅")
