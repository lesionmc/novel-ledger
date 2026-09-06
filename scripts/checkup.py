#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup.py —— 章节体检台（纯标准库）

把「写完一章该做的检查」收敛成一个命令：
  --audit          一致性审计（子进程调 write_chapter.py --audit，走它自己的重试/记账链路）
  --evaluate       AI 腔评估（纯本地：复用 deai.l1_scan_book，零 token）
  --publish-check  发布前检查（账本小节齐全 + 伏笔超期 + 正文存在，纯本地，失败退出码 1）
  --full           三步全跑：依次以子进程方式各跑一遍（互相隔离，一步失败不影响前步产物）

为什么 --full 走子进程：审计要烧 token 且可能卡很久，子进程隔离超时/崩溃；
参数由 build_full_steps 统一构造（历史 bug：--full 曾把章号直接跟在 flag 后且缺
--chapter，argparse 必报错。测试守此行为）。

L1 口径说明：指数与判定一律以 deai.l1_scan_book 为唯一实现（hard×2 + soft 全文次数
+ 破折号/省略号超标标志），本文件不再复制词表扫描逻辑，只做渲染与调度。

用法示例：
  python checkup.py --book "books/雾城档案" --chapter 5 --full
  python checkup.py --book "books/雾城档案" --chapter 5 --evaluate
"""
import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)  # 保证 `python scripts/checkup.py` 之外的场景也能 import 同目录模块

import deai            # noqa: E402
import write_chapter   # noqa: E402

WRITE_CH = os.path.join(SCRIPTS_DIR, "write_chapter.py")
AUDIT_TIMEOUT = 1800   # 审计要调模型，放宽超时


# ---------------------------------------------------------------- 纯函数（可单测）
def build_full_steps(book_dir, ch):
    """--full 的三步子进程参数表（不含 python/脚本路径，只有 argparse 参数）。
    铁律：--chapter 紧跟章号；每个 flag 在一条命令里只出现一次。"""
    book = str(book_dir)
    n = str(ch)
    return [
        ["--book", book, "--audit", "--chapter", n],
        ["--book", book, "--evaluate", "--chapter", n],
        ["--book", book, "--publish-check", "--chapter", n],
    ]


def l1_report_from_result(r):
    """把 deai.l1_scan_book 的单章结果 dict 渲染成体检单行（纯函数，不改任何状态）。"""
    flags = []
    if r["dash_flag"]:
        flags.append(f"破折号每千字 {r['dash_rate']}（超阈 {deai.DASH_PER_1000}）")
    if r["ell_flag"]:
        flags.append(f"省略号每千字 {r['ell_rate']}（超阈 {deai.ELLIPSIS_PER_1000}）")
    tail = f" / {'；'.join(flags)}" if flags else ""
    return (f"■ {r['file']}（{r['chars']} 字）AI 腔指数 {r['index']}"
            f"（hard×{len(r['hard'])} / soft高频×{len(r['soft'])}{tail}）")


# ---------------------------------------------------------------- 各步实现
def step_audit(book_dir, ch):
    """一致性审计：转交 write_chapter.py 子进程（烧 token 的步骤不在此复制实现）。"""
    cmd = [sys.executable, WRITE_CH, "--book", book_dir, "--audit", "--chapter", str(ch)]
    print(f"[audit] 子进程执行：{' '.join(cmd[2:])}")
    try:
        p = subprocess.run(cmd, timeout=AUDIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"[audit] 超时（>{AUDIT_TIMEOUT}s），请单独重跑该章。", file=sys.stderr)
        return 1
    return p.returncode


def step_evaluate(book_dir, ch):
    """AI 腔评估：L1 词表硬筛指定章（复用 deai 唯一实现），打印体检单行。"""
    target = f"ch{int(ch):03d}.md"
    results, _repeat = deai.l1_scan_book(book_dir)
    r = next((x for x in results if x["file"] == target), None)
    if r is None:
        print(f"[evaluate] 找不到 {target}，目录里现有：{', '.join(x['file'] for x in results)}",
              file=sys.stderr)
        return 1
    print("[evaluate] " + l1_report_from_result(r))
    return 0


def collect_publish_problems(book_dir, ch):
    """发布前检查的问题收集（只读、零 token）。gate 与 step_publish_check 共用。"""
    book = os.path.abspath(book_dir)
    problems = []
    state_path = os.path.join(book, write_chapter.STATE_FILE)
    state = ""
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = f.read()
    else:
        problems.append(f"缺 {write_chapter.STATE_FILE}")
    if state:
        miss = write_chapter.validate_state(state)
        if miss:
            problems.append(f"账本缺少小节：{'、'.join(miss)}")
        for it in write_chapter.overdue_foreshadows(state, int(ch)):
            problems.append(f"伏笔超期：{it['text'][:40]}"
                            f"（埋设于第{it['planted']}章，已 {it['overdue_by']} 章未回收）")
    src = os.path.join(book, "chapters", f"ch{int(ch):03d}.md")
    if not os.path.exists(src):
        problems.append(f"缺章节正文：{src}")
    elif os.path.getsize(src) == 0:
        problems.append(f"章节正文为空：{src}")
    # 备份文件被误当正文剔除（chXXX.apply.bak.md 不参与 ch\d{3}.md 匹配，天然不会误判）
    return problems


def gate_verdict(book_dir, ch):
    """v0.9.2 数字门禁（红灯分级，蒸馏自 v0.4 定稿 Q7=C）：
    账本冲突类问题（缺节/超期伏笔/正文缺失）→ pause（暂停连写，需人工处理）；
    文风类（L1 词表 hard 命中）→ continue（只标记，交给去味流程）。
    返回 {"gate": "continue"|"pause", "reasons": [...]}。"""
    reasons = collect_publish_problems(book_dir, ch)
    if reasons:
        return {"gate": "pause", "reasons": reasons}
    # 文风类只标记不拦截
    target = f"ch{int(ch):03d}.md"
    style = []
    try:
        results, _ = deai.l1_scan_book(book_dir)
        r = next((x for x in results if x["file"] == target), None)
        if r and r.get("hard"):
            style.append(f"L1 hard 命中 {len(r['hard'])} 处（建议去味精判，不拦截）")
    except Exception as e:  # 扫描失败不拦门禁
        style.append(f"L1 扫描异常（不拦截）：{e}")
    return {"gate": "continue", "reasons": style}


def write_gate_sheet(book_dir, ch, verdict, l1_line=None):
    """把门禁结论落盘体检单（chXXX.体检单.md，v0.5 产物形态回归）。"""
    ch = int(ch)
    out = os.path.join(book_dir, "chapters", f"ch{ch:03d}.体检单.md")
    lines = [f"# ch{ch:03d} · 体检单", "",
             f"门禁：**{verdict['gate']}**（{'继续连写' if verdict['gate'] == 'continue' else '暂停连写，先处理以下问题'}）"]
    if verdict["reasons"]:
        lines += ["", "## 门禁详情"] + [f"- {r}" for r in verdict["reasons"]]
    if l1_line:
        lines += ["", "## L1 文风扫描"] + [f"- {l1_line}"]
    lines += ["", f"> 生成于体检台 v0.9.2 · {__import__('time').strftime('%Y-%m-%d %H:%M')}"]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out


def step_publish_check(book_dir, ch):
    """发布前检查（只读、零 token）：账本结构齐全 + 伏笔超期 + 正文存在非空。"""
    problems = collect_publish_problems(book_dir, ch)
    if problems:
        print(f"[publish-check] ch{int(ch):03d} 未通过：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"[publish-check] ch{int(ch):03d} 通过：账本结构齐全、无超期伏笔、正文就绪。")
    return 0


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="章节体检台：审计 / AI 腔评估 / 发布前检查 / 三步全跑")
    ap.add_argument("--book", required=True, help="书目录路径")
    ap.add_argument("--chapter", type=int, default=0, help="章节号（--full/单步都需要）")
    ap.add_argument("--audit", action="store_true", help="第 1 步：一致性审计（调模型）")
    ap.add_argument("--evaluate", action="store_true", help="第 2 步：AI 腔 L1 评估（零 token）")
    ap.add_argument("--publish-check", action="store_true", help="第 3 步：发布前检查（零 token）")
    ap.add_argument("--full", action="store_true", help="三步全跑（子进程隔离执行）")
    args = ap.parse_args()

    if not args.full and not (args.audit or args.evaluate or args.publish_check):
        ap.print_help()
        return 1
    if args.chapter < 1:
        print("请指定 --chapter N")
        return 1
    if not os.path.isdir(args.book):
        print(f"书目录不存在：{args.book}")
        return 1

    if args.full:
        # 三步各自独立子进程：参数统一由 build_full_steps 构造（防 flag/章号拼接 bug 复发）
        failed = 0
        for step_args in build_full_steps(args.book, args.chapter):
            step_name = next(s.lstrip("-") for s in step_args if s.startswith("--")
                             and s not in ("--book", "--chapter"))
            print(f"\n===== [full] {step_name} =====")
            p = subprocess.run([sys.executable, os.path.abspath(__file__)] + step_args)
            if p.returncode != 0:
                failed += 1
                print(f"⚠ [full] {step_name} 失败（退出码 {p.returncode}）", file=sys.stderr)
        print(f"\n[full] 完成：{3 - failed}/3 步通过")
    # v0.9.2 数字门禁：任何一步跑完都出 gate 结论 + 体检单（含 --full 与单步）
    verdict = gate_verdict(args.book, args.chapter)
    l1_line = None
    try:
        results, _ = deai.l1_scan_book(args.book)
        r = next((x for x in results if x["file"] == f"ch{args.chapter:03d}.md"), None)
        if r:
            l1_line = l1_report_from_result(r)
    except Exception:
        pass
    sheet = write_gate_sheet(args.book, args.chapter, verdict, l1_line)
    print(f"🚦 [gate] ch{args.chapter:03d} 门禁：{verdict['gate']}"
          f"（{'；'.join(verdict['reasons']) if verdict['reasons'] else '干净'}）")
    print(f"🚦 [gate] 体检单已生成 → {sheet}")
    if args.full:
        return 1 if failed else 0

    if args.audit:
        return step_audit(args.book, args.chapter)
    if args.evaluate:
        return step_evaluate(args.book, args.chapter)
    if args.publish_check:
        return step_publish_check(args.book, args.chapter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
