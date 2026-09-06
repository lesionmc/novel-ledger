#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_longform.py —— 超长篇连写压测工具（纯标准库，零 token、零外呼）

用途：在 mock 掉模型通道的前提下，把「一章接一章连写 N 章」的完整链路压到真实盘上，
暴露长连载才有的故障（上下文配方膨胀、账本漂移、落盘变慢、意象重复…）。

两种模式：
  --mode inproc   本进程内 monkeypatch llm.post_chat / write_chapter._post_chat，
                  直接调 write_chapter 的函数跑主流程（最快，用于性能/记忆链路压测）。
  --mode subproc  每章起真子进程跑 write_chapter.py，靠 PYTHONPATH 注入 sitecustomize
                  在子进程里替换 urllib.request.urlopen（返回 mock JSON），隔离度更高。

防污染与安全：
  - usage_log.jsonl 跑前备份、跑后恢复（压测流水不混入真实记账）。
  - urlopen 打桩为 raise（inproc 双保险）：任何漏网请求一律当场炸掉，绝不外呼。
  - 压测书放在项目根 _bench/ 下，不动真实 books/。
  - 里程碑：每章 validate_state；每 5 章（含末章）deai.l1_scan_book + backup_book。

用法示例：
  python bench_longform.py --book A --chapters 20 --mode inproc
  python bench_longform.py --book B --chapters 10 --mode subproc --words 4500
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import backup_book    # noqa: E402
import deai           # noqa: E402
import llm            # noqa: E402
import usage_log      # noqa: E402
import write_chapter as wc  # noqa: E402

BENCH_ROOT = os.path.join(ROOT, "_bench")
BOOK_NAMES = {"A": "压测书A", "B": "压测书B"}
MOCK_SENT = "他沿着江堤往前走，风把外套吹得猎猎作响，远处传来一声悠长的汽笛。\n"


def mock_body(words):
    """按目标字数生成 mock 正文（可读长度足够 L1 扫描与字数软控走真逻辑）。"""
    reps = max(words // len(MOCK_SENT) + 1, 1)
    return (MOCK_SENT * reps)[:words]


def mock_state():
    """mock 账本：直接用 STATE_TEMPLATE，8 节标题齐全，validate_state 必过。"""
    return wc.STATE_TEMPLATE.replace("{书名}", "压测书")


def fake_post_chat(base_url, api_key, payload, timeout=240):
    """inproc 模式的模型替身：账本请求回完整模板账本，其余回 mock 正文。"""
    sys0 = (payload.get("messages") or [{}])[0].get("content", "")
    if "账本" in sys0:
        content, usage = mock_state(), {"prompt_tokens": 1800, "completion_tokens": 900,
                                        "total_tokens": 2700}
    else:
        n = BENCH_WORDS
        content = mock_body(n)
        usage = {"prompt_tokens": 2500, "completion_tokens": n, "total_tokens": 2500 + n}
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": usage}


def _no_external_call(req, timeout=None):  # 双保险：漏网请求一律炸掉，绝不外呼
    raise AssertionError(f"压测不允许外呼：{getattr(req, 'full_url', req)!r}")


def setup_book(name):
    """造压测书（三件套，无账本——第 1 章写完自动建账，覆盖真实链路）。"""
    book = os.path.join(BENCH_ROOT, name)
    shutil.rmtree(book, ignore_errors=True)
    os.makedirs(os.path.join(book, "chapters"))
    files = {
        "设定.md": "世界观：压测用架空城市。\n硬规则：回闪能力一天限 3 次。",
        "大纲.md": "主线：连写压测。\n第 1 卷：持续推进。",
        "角色卡.md": "主角：压测员。\n配角：搭档。",
    }
    for fn, s in files.items():
        with open(os.path.join(book, fn), "w", encoding="utf-8") as f:
            f.write(s)
    return book


def protect_usage_log():
    """备份项目根 usage_log.jsonl，返回恢复函数（压测流水不污染真实记账）。"""
    p = usage_log.DEFAULT_PATH
    saved = None
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            saved = f.read()
    existed = saved is not None

    def restore():
        try:
            if existed:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(saved)
            elif os.path.exists(p):
                os.remove(p)
        except OSError as e:
            print(f"⚠ usage_log 恢复失败：{e}", file=sys.stderr)
    return restore


def milestones(book, ch, rows):
    """里程碑：每章账本校验；每 5 章（含末章）L1 扫描 + 全书备份。"""
    state = ""
    sp = os.path.join(book, wc.STATE_FILE)
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            state = f.read()
    miss = wc.validate_state(state) if state else ["(缺账本)"]
    if miss:
        rows.append(f"  ⚠ ch{ch:03d} 账本缺小节：{'、'.join(miss)}")
    if ch % 5 == 0:
        res, _ = deai.l1_scan_book(book)
        worst = max(res, key=lambda r: r["index"]) if res else None
        if worst:
            rows.append(f"  ◆ 里程碑 ch{ch:03d}: L1 最高指数 {worst['file']} "
                        f"{worst['index']}（hard×{len(worst['hard'])}）")
        zp = backup_book.backup_book(book, out_dir=os.path.join(BENCH_ROOT, "backups"))
        rows.append(f"  ◆ 里程碑 ch{ch:03d}: 已备份 → {os.path.basename(zp)}")
    return not miss


def bench_inproc(book, n, words):
    rows, ok = [], True
    real_post, real_llm_post, real_urlopen = wc._post_chat, llm.post_chat, urllib.request.urlopen
    wc._post_chat = fake_post_chat
    llm.post_chat = fake_post_chat
    urllib.request.urlopen = _no_external_call
    old_state = ""
    try:
        for ch in range(1, n + 1):
            t0 = time.perf_counter()
            context = wc.build_context(book, ch, words=words)
            body = wc.call_llm("bench-key", "http://bench.invalid/v1", "bench-model",
                               context).strip()
            src = os.path.join(book, "chapters", f"ch{ch:03d}.md")
            with open(src, "w", encoding="utf-8") as f:
                f.write(body)
            new_state = wc.update_state("bench-key", "http://bench.invalid/v1",
                                        "bench-model", body, old_state)
            with open(os.path.join(book, wc.STATE_FILE), "w", encoding="utf-8") as f:
                f.write(new_state)
            old_state = new_state
            state_ok = milestones(book, ch, rows)
            ok = ok and state_ok
            rows.append(f"  ch{ch:03d}: {len(body)} 字 / 账本{'✓' if state_ok else '✗'} "
                        f"/ {time.perf_counter() - t0:.2f}s")
    finally:
        wc._post_chat = real_post
        llm.post_chat = real_llm_post
        urllib.request.urlopen = real_urlopen
    return ok, rows


SITECUSTOMIZE = '''# -*- coding: utf-8 -*-
# bench_longform.py 注入的子进程替身：把 urllib.request.urlopen 换成 mock 响应器
import json, os, urllib.request

class _Resp:
    def __init__(self, body): self._b = body.encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._b

_SENT = "他沿着江堤往前走，风把外套吹得猎猎作响，远处传来一声悠长的汽笛。\\n"

def _fake(req, timeout=None):
    payload = json.loads(req.data.decode("utf-8"))
    sys0 = (payload.get("messages") or [{}])[0].get("content", "")
    if "账本" in sys0:
        with open(os.environ["NOVEL_BENCH_STATE"], encoding="utf-8") as f:
            content = f.read()
        usage = {"prompt_tokens": 1800, "completion_tokens": 900, "total_tokens": 2700}
    else:
        n = int(os.environ.get("NOVEL_BENCH_WORDS", "3000"))
        content = (_SENT * (n // len(_SENT) + 1))[:n]
        usage = {"prompt_tokens": 2500, "completion_tokens": n, "total_tokens": 2500 + n}
    body = json.dumps({"choices": [{"message": {"content": content},
                                    "finish_reason": "stop"}], "usage": usage},
                      ensure_ascii=False)
    return _Resp(body)

urllib.request.urlopen = _fake
'''


def bench_subproc(book, n, words):
    """子进程模式：每章真跑 write_chapter.py，sitecustomize 注入 mock urlopen。"""
    rows, ok = [], True
    inj = os.path.join(BENCH_ROOT, "_inproc_inject")
    os.makedirs(inj, exist_ok=True)
    with open(os.path.join(inj, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(SITECUSTOMIZE)
    state_file = os.path.join(BENCH_ROOT, "_mock_state.md")
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(mock_state())
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = inj + os.pathsep + env.get("PYTHONPATH", "")
    env["NOVEL_BENCH_WORDS"] = str(words)
    env["NOVEL_BENCH_STATE"] = state_file
    try:
        for ch in range(1, n + 1):
            t0 = time.perf_counter()
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "write_chapter.py"),
                                "--book", book, "--chapter", str(ch), "--words", str(words)],
                               cwd=ROOT, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=600)
            src = os.path.join(book, "chapters", f"ch{ch:03d}.md")
            produced = os.path.exists(src) and os.path.getsize(src) > 0
            state_ok = milestones(book, ch, rows)
            ok = ok and produced and state_ok and p.returncode == 0
            rows.append(f"  ch{ch:03d}: rc={p.returncode} 正文{'✓' if produced else '✗'} "
                        f"/ 账本{'✓' if state_ok else '✗'} / {time.perf_counter() - t0:.2f}s")
            if not produced:
                rows.append(f"    ⚠ stderr: {(p.stderr or '')[-300:]}")
    finally:
        shutil.rmtree(inj, ignore_errors=True)
        os.remove(state_file)
    return ok, rows


def main() -> int:
    ap = argparse.ArgumentParser(description="超长篇连写压测（mock 模型通道，零 token 零外呼）")
    ap.add_argument("--book", required=True, choices=sorted(BOOK_NAMES), help="压测书代号 A/B")
    ap.add_argument("--chapters", type=int, default=5, help="连写章数（默认 5）")
    ap.add_argument("--mode", choices=["inproc", "subproc"], default="inproc")
    ap.add_argument("--words", type=int, default=3000, help="每章目标字数（1000–10000）")
    args = ap.parse_args()
    words = wc.clamp_words(args.words)

    global BENCH_WORDS
    BENCH_WORDS = words

    os.makedirs(BENCH_ROOT, exist_ok=True)
    book = setup_book(BOOK_NAMES[args.book])
    restore_usage = protect_usage_log()
    print(f"[bench] 书={BOOK_NAMES[args.book]} 模式={args.mode} "
          f"章数={args.chapters} 每章={words} 字")
    t0 = time.perf_counter()
    try:
        if args.mode == "inproc":
            ok, rows = bench_inproc(book, args.chapters, words)
        else:
            ok, rows = bench_subproc(book, args.chapters, words)
    finally:
        restore_usage()
    print("\n".join(rows))
    total = time.perf_counter() - t0
    print(f"\n[bench] {'✅ 全部通过' if ok else '❌ 存在失败'}：{args.chapters} 章 "
          f"/ 总耗时 {total:.1f}s / 均章 {total / max(args.chapters, 1):.2f}s"
          f"（usage_log 已恢复原状）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
