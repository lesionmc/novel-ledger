#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all_tests.py —— 一键回归（纯标准库）

依次跑五套件并实时透传输出：
  1. scripts/smoke_test.py          冒烟（引擎/体检/记账/插件等全部断言）
  2. scripts/test_task_runner.py    连写调度器专项（超时/补救/记账并发）
  3. scripts/test_llm_stream.py     LLM 流式专项
  4. web/test_routes.py             Web 路由验收
  5. mcp_server --selftest          MCP 自检（server.py / mcp_server.py 任一存在即跑）

行为约定：
- PYTHONUTF8=1 注入子进程，Windows 控制台不炸中文。
- 解析各套件输出里的「N 通过 / M 失败」行做汇总；解析不到就只看退出码。
- 套件脚本文件缺失 → 标记 SKIP（不阻断其它套件，也不判失败——可能正被并行重建）。
- 任一套件失败（退出码非 0 或解析到 M>0）→ 本脚本退出码 1。

运行：python scripts/run_all_tests.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SUMMARY_RE = re.compile(r"(\d+)\s*通过\s*/\s*(\d+)\s*失败")


def find_mcp_entry():
    """mcp_server 自检入口探测（目录由另一侧并行重建，布局以存在者为准）。"""
    for name in ("server.py", "mcp_server.py", "main.py"):
        p = os.path.join(ROOT, "mcp_server", name)
        if os.path.isfile(p):
            return [p, "--selftest"]
    return None


def build_suites():
    suites = [("smoke_test", [os.path.join(SCRIPTS, "smoke_test.py")]),
              ("test_task_runner", [os.path.join(SCRIPTS, "test_task_runner.py")]),
              ("test_llm_stream", [os.path.join(SCRIPTS, "test_llm_stream.py")]),
              ("web/test_routes", [os.path.join(ROOT, "web", "test_routes.py")])]
    mcp = find_mcp_entry()
    if mcp:
        suites.append(("mcp_server --selftest", mcp))
    else:
        suites.append(("mcp_server --selftest", None))
    return suites


def run_suite(name, cmd):
    """跑单个套件。返回 True=通过 / False=失败 / None=SKIP。"""
    if cmd is None or not os.path.exists(cmd[0]):
        print(f"—— {name}: SKIP（脚本缺失，可能正被并行重建）\n")
        return None
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    print(f"—— {name}: 运行 {os.path.relpath(cmd[0], ROOT)} {' '.join(cmd[1:])}".rstrip())
    n_pass = n_fail = 0
    saw_summary = False
    proc = subprocess.Popen([sys.executable] + cmd, cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        sys.stdout.write(line)  # 实时透传
        m = SUMMARY_RE.search(line)
        if m:
            saw_summary = True
            n_pass, n_fail = int(m.group(1)), int(m.group(2))
    proc.wait()
    failed = (proc.returncode != 0) or (saw_summary and n_fail > 0)
    tag = "✅ 通过" if not failed else "❌ 失败"
    detail = f"（{n_pass} 通过 / {n_fail} 失败）" if saw_summary \
        else f"（退出码 {proc.returncode}，无汇总行）"
    print(f"   ⇒ {name}: {tag} {detail}\n")
    return not failed


def main() -> int:
    print("=" * 48)
    print("一键回归：smoke_test / task_runner / llm_stream / web 路由 / mcp 自检")
    print("=" * 48)
    results, rows = {}, []
    for name, cmd in build_suites():
        results[name] = run_suite(name, cmd)
    print("=" * 48)
    hard_fail = 0
    for name, r in results.items():
        if r is None:
            rows.append(f"  ⏭ {name}: SKIP")
        elif r:
            rows.append(f"  ✅ {name}")
        else:
            rows.append(f"  ❌ {name}")
            hard_fail += 1
    print("\n".join(rows))
    print("=" * 48)
    if hard_fail:
        print(f"汇总：{hard_fail} 个套件失败 → 退出码 1")
        return 1
    print("汇总：全部就绪 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
