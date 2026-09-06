# -*- coding: utf-8 -*-
"""test_task_runner.py —— task_runner 专项测试（零网络、零第三方依赖、不真跑子进程）

覆盖：
  1. run_engine 捕获 subprocess.TimeoutExpired → 结构化失败结果（引擎超时）
  2. classify_failure 各类别映射
  3. 账本补漏：补救成功续跑 / 补救失败停机 / tried 持久化——同章重复失败不再补漏并标「已试过补漏」
  4. usage_log 并发记账：10 线程 × 50 条 = 500 行不丢
  5. aggregate 只按 ACTION_WRITE（写正文）计每章明细

运行：python scripts/test_task_runner.py（失败退出码 1）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)

import task_runner   # noqa: E402
import usage_log     # noqa: E402
import write_chapter  # noqa: E402

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


# ── 打桩基建：monkeypatch subprocess.run ───────────────────────
class FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


CALLS = []  # [(cmd_list, timeout)]


def make_fake_run(write_rc=1, write_out="", write_err="",
                  repair_rc=0, repair_out="账本已更新", repair_err=""):
    """按命令形态分流：--state-only → 补救行为；否则 → 写章行为（固定返回 write_rc）。"""
    def fake_run(cmd, capture_output=True, text=True, encoding="utf-8",
                 errors="replace", timeout=None):
        CALLS.append((list(cmd), timeout))
        joined = " ".join(str(x) for x in cmd)
        if "--state-only" in joined:
            return FakeProc(repair_rc, repair_out, repair_err)
        return FakeProc(write_rc, write_out, write_err)
    return fake_run


_real_run = subprocess.run
_real_sleep = task_runner.time.sleep
task_runner.time.sleep = lambda s: None  # 失败退避不等真 5s
subprocess.run = make_fake_run()         # 默认桩，下面各节按需覆盖

_tmp = tempfile.mkdtemp(prefix="runner_")
try:
    # ── 1. 超时：TimeoutExpired → 结构化失败，classify 首位「引擎超时」──
    print("== 1. 引擎超时 ==")
    book1 = os.path.join(_tmp, "书超时")
    os.makedirs(os.path.join(book1, "chapters"), exist_ok=True)

    def raise_timeout(cmd, **kw):
        CALLS.append((list(cmd), kw.get("timeout")))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"),
                                        output="写了一半的输出".encode("utf-8"),
                                        stderr=b"")
    subprocess.run = raise_timeout
    res = task_runner.run_engine(["--book", book1, "--chapter", 1], timeout=123)
    check("超时返回 ok=False", res["ok"] is False and res["timeout"] is True, str(res))
    check("超时保留部分输出且退出码 None",
          "写了一半的输出" in res["stdout"] and res["returncode"] is None, str(res))
    check("超时被归为「引擎超时」",
          task_runner.classify_failure(res) == task_runner.CAT_TIMEOUT)
    check("超时按传入 timeout 生效", CALLS and CALLS[-1][1] == 123, str(CALLS[-1]))

    # ── 2. run_engine 正常/失败路径 ────────────────────────────
    print("\n== 2. run_engine 常规路径 ==")
    subprocess.run = make_fake_run(write_rc=0, write_out="done")
    ok_res = task_runner.run_engine(["--book", book1, "--chapter", 2])
    check("退出码 0 → ok=True", ok_res["ok"] is True and ok_res["returncode"] == 0)
    subprocess.run = make_fake_run(write_rc=2, write_err="boom")
    bad_res = task_runner.run_engine(["--book", book1, "--chapter", 2])
    check("退出码非 0 → ok=False", bad_res["ok"] is False and bad_res["returncode"] == 2)
    check("stdout/stderr 进结果", bad_res["stderr"] == "boom")

    # ── 3. classify_failure 映射 ──────────────────────────────
    print("\n== 3. classify_failure 映射 ==")
    cases = [
        ({"timeout": True, "returncode": None}, task_runner.CAT_TIMEOUT, "超时→引擎超时"),
        ({"timeout": False, "returncode": 1, "stdout": "⚠ 账本结构校验未通过：缺少小节",
          "stderr": ""}, task_runner.CAT_STATE, "账本→账本失败"),
        ({"timeout": False, "returncode": 1, "stdout": "缺少 API key：请在项目根 .env 写",
          "stderr": ""}, task_runner.CAT_KEY, "密钥→缺少密钥"),
        ({"timeout": False, "returncode": 1, "stdout": "URLError: <urlopen error>",
          "stderr": ""}, task_runner.CAT_NET, "URLError→网络/限流"),
        ({"timeout": False, "returncode": 1, "stdout": "", "stderr": "空内容（finish=length）"},
         task_runner.CAT_EMPTY, "空内容→空内容"),
        ({"timeout": False, "returncode": 1, "stdout": "Segmentation fault", "stderr": ""},
         task_runner.CAT_UNKNOWN, "其余→未知失败"),
    ]
    for payload, expect, label in cases:
        check(label, task_runner.classify_failure(payload) == expect, str(payload)[:60])

    # ── 4. 补漏三分支 ─────────────────────────────────────────
    print("\n== 4. 账本补漏三分支 ==")
    book2 = os.path.join(_tmp, "书补漏")
    os.makedirs(os.path.join(book2, "chapters"), exist_ok=True)
    with open(os.path.join(book2, "chapters", "ch001.md"), "w", encoding="utf-8") as f:
        f.write("第一章正文。")
    with open(os.path.join(book2, "chapters", "ch002.md"), "w", encoding="utf-8") as f:
        f.write("第二章正文。")

    # 4a. 补救成功 → 该章视为完成继续写下一章
    CALLS.clear()
    subprocess.run = make_fake_run(write_rc=1,
                                   write_err="⚠ 账本结构校验未通过：缺少小节 ['## 伏笔账本']",
                                   repair_rc=0)
    rs = task_runner.run_book(book2, 1, 2, max_consecutive_failures=2)
    check("补救成功：两章都完成", len(rs) == 2 and all(t["ok"] for t in rs), str(rs))
    check("补救成功：第 1 章标记 repaired", rs[0]["repaired"] is True, str(rs[0]))
    state_only_n = sum(1 for c, _t in CALLS if "--state-only" in " ".join(c))
    check("补救成功：state-only 被调 2 次（每章一次）", state_only_n == 2, str(state_only_n))
    check("补救命令是 write_chapter.py --state-only",
          all("write_chapter.py" in " ".join(c) and "--state-only" in " ".join(c)
              for c, _t in CALLS if "--state-only" in " ".join(c)))

    # 4b. 补救失败 → 停机（不写下一章）
    CALLS.clear()
    subprocess.run = make_fake_run(write_rc=1,
                                   write_err="⚠ 账本结构校验未通过：缺少小节 ['## 伏笔账本']",
                                   repair_rc=1, repair_err="重算产物仍不合格")
    rs = task_runner.run_book(book2, 1, 2, max_consecutive_failures=1)
    check("补救失败：只处理了第 1 章就停机", len(rs) == 1, str(len(rs)))
    check("补救失败：该章 ok=False", rs[0]["ok"] is False)

    # 4c. 同章重复失败：tried 持久化生效，不再重复补漏，记「已试过补漏」状态
    CALLS.clear()
    subprocess.run = make_fake_run(write_rc=1,
                                   write_err="⚠ 账本结构校验未通过：缺少小节 ['## 伏笔账本']",
                                   repair_rc=1, repair_err="仍失败")
    rs = task_runner.run_book(book2, 1, 1, max_consecutive_failures=1)
    state_only_n = sum(1 for c, _t in CALLS if "--state-only" in " ".join(c))
    check("tried 持久化：同章重复失败不再补漏（state-only 0 次）",
          state_only_n == 0, str(state_only_n))
    check("重复失败标记「已试过补漏」",
          rs and rs[0].get("repair_state") == "已试过补漏", str(rs))
    check("tried 落盘保留上次记录", rs and rs[0]["tried"] == [1], str(rs))
    _state_path = os.path.join(book2, task_runner.RUNNER_STATE_FILE)
    check("tried 状态文件真实落盘", os.path.exists(_state_path), _state_path)

    # 4d. 该章最终写成功 → 从 tried 移除（将来再失败仍可自动补漏）
    CALLS.clear()
    subprocess.run = make_fake_run(write_rc=0, write_out="done")
    rs = task_runner.run_book(book2, 1, 1, max_consecutive_failures=2)
    check("写成功清除 tried 记录", rs and rs[0]["ok"] is True and rs[0]["tried"] == [], str(rs))

    # ── 5. usage_log 并发：10 线程 × 50 条 = 500 行 ────────────
    print("\n== 5. usage_log 并发记账 ==")
    upath = os.path.join(_tmp, "concurrent.jsonl")
    def worker(tid):
        for i in range(50):
            usage_log.log_usage(usage_log.ACTION_WRITE, f"m{tid}", tid, i,
                                book="并发书", chapter=i + 1, path=upath)
    threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(upath, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]
    parsed = []
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except ValueError:
            pass
    check("10 线程 × 50 条 = 500 行不丢", len(lines) == 500, str(len(lines)))
    check("500 行全部是合法 JSON", len(parsed) == 500, str(len(parsed)))
    check("并发锁下无交叉损坏（action 全为写正文）",
          all(p["action"] == usage_log.ACTION_WRITE for p in parsed))

    # ── 6. aggregate 只按 ACTION_WRITE 计每章明细 ──────────────
    print("\n== 6. aggregate 口径 ==")
    entries = usage_log.load_entries(path=upath)
    entries.append({"day": "2026-09-06", "ts": "t", "book": "并发书", "chapter": None,
                    "action": "审计", "model": "m", "in": 1, "out": 1, "total": 2})
    entries.append({"day": "2026-09-06", "ts": "t", "book": "并发书", "chapter": 3,
                    "action": "账本更新", "model": "m", "in": 1, "out": 1, "total": 2})
    agg = usage_log.aggregate(entries)
    check("write_count 只数「写正文」且必须带章号（500 章记录）",
          agg["write_count"] == 500, str(agg["write_count"]))
    check("by_action 含审计/账本更新但不进 chapters",
          agg["by_action"].get("审计") == 2 and agg["by_action"].get("账本更新") == 2)
    check("calls = 全部条数 502", agg["calls"] == 502, str(agg["calls"]))
finally:
    subprocess.run = _real_run
    task_runner.time.sleep = _real_sleep
    shutil.rmtree(_tmp, ignore_errors=True)

print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
if FAIL:
    sys.exit(1)
print("全部通过 ✅")
