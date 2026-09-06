#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_runner.py —— 无人值守连写调度器（纯标准库）

职责：把「一章接一章写下去」做成可托管的批处理循环，并处理两类最常翻车的事故：

1. 引擎超时：run_engine 捕获 subprocess.TimeoutExpired，返回结构化失败结果，
   classify_failure 把「引擎超时」作为首位类别（超时=子进程已被杀，重试要防重复落盘）。
2. 账本类失败（写完正文但账本更新没成）：正文 chNNN.md 已在盘上时，
   自动补跑 `write_chapter.py --book <book> --state-only --chapter <no>` 补账本；
   补成功则该章视为完成继续写下一章。tried 持久化到书目录 _runner_state.json——
   每章补救失败后记录在案，同章再次失败不再重复补漏（防「补-败-再补」死循环），
   而是记「已试过补漏」状态等人工介入。

用法示例：
  python task_runner.py --book "books/雾城档案" --from 5 --to 10
"""
import argparse
import json
import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
WRITE_CH = os.path.join(SCRIPTS_DIR, "write_chapter.py")

WRITE_TIMEOUT = 1800   # 单章（正文+账本）整体超时
REPAIR_TIMEOUT = 900   # --state-only 补账本超时

# 失败类别（classify_failure 的判定顺序即此列表语义：超时最先，账本次之）
CAT_TIMEOUT = "引擎超时"
CAT_STATE = "账本失败"
CAT_KEY = "缺少密钥"
CAT_NET = "网络/限流"
CAT_EMPTY = "空内容"
CAT_UNKNOWN = "未知失败"


def _as_text(v):
    """TimeoutExpired 携带的输出可能是 str/bytes/None，统一成 str。"""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def run_engine(args, timeout=WRITE_TIMEOUT, script=WRITE_CH):
    """跑一个引擎子进程，返回结构化结果 dict：
    {ok, timeout, returncode, stdout, stderr, cmd}。
    超时不再向上抛异常——超时就是一种「失败结果」，由 classify_failure 归类并计入连续失败。"""
    cmd = [sys.executable, script] + [str(a) for a in args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "timeout": True, "returncode": None,
                "stdout": _as_text(e.stdout), "stderr": _as_text(e.stderr), "cmd": cmd}
    return {"ok": p.returncode == 0, "timeout": False, "returncode": p.returncode,
            "stdout": p.stdout or "", "stderr": p.stderr or "", "cmd": cmd}


def classify_failure(res):
    """把 run_engine 的失败结果归成一类。判定顺序：超时 > 账本 > 密钥 > 网络 > 空内容 > 未知。"""
    if res.get("timeout"):
        return CAT_TIMEOUT
    text = (res.get("stdout", "") or "") + "\n" + (res.get("stderr", "") or "")
    if "账本" in text and ("校验未通过" in text or "缺少小节" in text):
        return CAT_STATE
    if "缺少 API key" in text or "缺少 AGNES_API_KEY" in text:
        return CAT_KEY
    if any(k in text for k in ("URLError", "TimeoutError", "Connection",
                               "429", "-rate-limit", "RateLimit")):
        return CAT_NET
    if "空内容" in text:
        return CAT_EMPTY
    return CAT_UNKNOWN


def _chapter_body_path(book_dir, ch):
    return os.path.join(book_dir, "chapters", f"ch{int(ch):03d}.md")


def _state_only_repair(book_dir, ch, timeout=REPAIR_TIMEOUT):
    """账本类失败的自动补救：正文已在盘上时补跑 --state-only 重算账本。
    只补账本、不重写正文；失败原样返回，由调用方停机。"""
    args = ["--book", book_dir, "--state-only", "--chapter", ch]
    print(f"  ⚙ 账本补救：write_chapter.py {' '.join(str(a) for a in args)}")
    return run_engine(args, timeout=timeout)


RUNNER_STATE_FILE = "_runner_state.json"  # tried 持久化文件（落书目录）


def _load_tried(book_dir):
    """读书目录 _runner_state.json → 已试过补漏且仍失败的章号集合（真持久化，跨进程生效）。"""
    try:
        with open(os.path.join(book_dir, RUNNER_STATE_FILE), encoding="utf-8") as f:
            return {int(c) for c in json.load(f).get("tried", [])}
    except (OSError, ValueError, TypeError):
        return set()


def _save_tried(book_dir, tried):
    """把 tried 集合落盘到书目录 _runner_state.json（失败不阻断主流程）。"""
    try:
        with open(os.path.join(book_dir, RUNNER_STATE_FILE), "w", encoding="utf-8") as f:
            json.dump({"tried": sorted(tried)}, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"  ⚠ tried 状态落盘失败（不影响本次连写）：{e}", file=sys.stderr)


def run_book(book_dir, start, end, timeout=WRITE_TIMEOUT, max_consecutive_failures=2):
    """从 start 连写到 end（含）。返回 task dict 列表，一条一章：
    {chapter, ok, fail(类别), repaired, repair_state, tried(已试过补漏的章号)}。
    tried 持久化到书目录 _runner_state.json：补救失败的章记录在案，同章再次
    账本失败时不再重复补漏，task 记 repair_state=「已试过补漏」等人工介入。
    补救成功或该章最终写成功时会从 tried 里移除。
    停机条件：不可修复失败，或连续失败达 max_consecutive_failures（超时也计入连续失败）。"""
    results = []
    consecutive = 0
    tried = _load_tried(book_dir)
    for ch in range(int(start), int(end) + 1):
        task = {"chapter": ch, "ok": False, "fail": None, "repaired": False,
                "repair_state": None, "tried": sorted(tried)}
        print(f"── 第 {ch} 章 ──")
        res = run_engine(["--book", book_dir, "--chapter", ch], timeout=timeout)

        if res["ok"]:
            task["ok"] = True
            consecutive = 0
            if ch in tried:
                tried.discard(ch)
                _save_tried(book_dir, tried)
                task["tried"] = sorted(tried)
            print(f"  ✅ 第 {ch} 章完成")
            results.append(task)
            continue

        cat = classify_failure(res)
        task["fail"] = cat
        print(f"  ✗ 第 {ch} 章失败：{cat}", file=sys.stderr)

        # 账本类失败 + 正文已在盘上 → 每章只自动补一次（tried 持久化防死循环）
        if cat == CAT_STATE and os.path.exists(_chapter_body_path(book_dir, ch)):
            if ch in tried:
                task["repair_state"] = "已试过补漏"
                print(f"  ⚠ 第 {ch} 章已试过账本补救且仍失败（见 {RUNNER_STATE_FILE}），"
                      f"跳过自动补漏，需人工介入。", file=sys.stderr)
            else:
                tried.add(ch)
                _save_tried(book_dir, tried)
                task["tried"] = sorted(tried)
                rep = _state_only_repair(book_dir, ch)
                if rep["ok"]:
                    tried.discard(ch)
                    _save_tried(book_dir, tried)
                    task["tried"] = sorted(tried)
                    task["ok"] = True
                    task["repaired"] = True
                    task["repair_state"] = "补漏成功"
                    consecutive = 0
                    print(f"  ✅ 第 {ch} 章账本补救成功，视为完成，继续")
                    results.append(task)
                    continue
                task["fail"] = classify_failure(rep)
                print(f"  ✗ 账本补救仍失败：{task['fail']}（已记入 tried），停机", file=sys.stderr)

        results.append(task)
        consecutive += 1
        if consecutive >= max_consecutive_failures:
            print(f"■ 连续失败 {consecutive} 章，停止连写。", file=sys.stderr)
            break
        time.sleep(5)  # 失败后稍等再写下一章，避开限流窗口
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="无人值守连写调度器（超时分类 + 账本自动补救）")
    ap.add_argument("--book", required=True, help="书目录路径")
    ap.add_argument("--from", dest="start", type=int, required=True, help="起始章号（含）")
    ap.add_argument("--to", dest="end", type=int, required=True, help="结束章号（含）")
    ap.add_argument("--timeout", type=int, default=WRITE_TIMEOUT, help="单章超时秒数")
    args = ap.parse_args()
    if not os.path.isdir(args.book):
        print(f"书目录不存在：{args.book}")
        return 1
    results = run_book(args.book, args.start, args.end, timeout=args.timeout)
    done = sum(1 for t in results if t["ok"])
    print(f"\n[runner] {done}/{len(results)} 章完成")
    for t in results:
        mark = "✅" if t["ok"] else f"✗ {t['fail']}"
        if t.get("repaired"):
            extra = "（账本已补救）"
        elif t.get("repair_state") == "已试过补漏":
            extra = "（已试过补漏，需人工介入）"
        else:
            extra = ""
        print(f"  ch{t['chapter']:03d} {mark}{extra}")
    return 0 if done == len(results) and results else 1


if __name__ == "__main__":
    sys.exit(main())
