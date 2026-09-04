# -*- coding: utf-8 -*-
"""usage_log.py —— 模型用量记账（R48，2026-09-04 拍板，纯标准库）

设计（大白话）：
- 流水账：每次调模型追加一行 JSON 到项目根 usage_log.jsonl（时间/书/章/动作/模型/输入/输出/总量）。
- 按天汇总不落第二份文件，由 aggregate() 现算（避免两份数据对不上的新故障源）。
- 记账失败绝不影响主流程：调用方 try/except 兜底，本模块自身也不抛盘外异常。
- 本地估算口径（拍板 Q4/Q18）：不查厂商余额、不折算钱，只给「平均每章消耗 / 已累计」。
"""
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "usage_log.jsonl")


def log_usage(action, model, prompt_tokens, completion_tokens,
              book="", chapter=None, path=None):
    """记一笔流水账。返回写入的 dict；失败返回 None（绝不抛异常打扰主流程）。"""
    p = path or DEFAULT_PATH
    try:
        i = int(prompt_tokens) if prompt_tokens is not None else None
        o = int(completion_tokens) if completion_tokens is not None else None
    except (TypeError, ValueError):
        i = o = None
    now = datetime.now()
    entry = {
        "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
        "day": now.strftime("%Y-%m-%d"),
        "book": book or "",
        "chapter": chapter,
        "action": action or "",
        "model": model or "",
        "in": i,
        "out": o,
        "total": (i + o) if (i is not None and o is not None) else None,
    }
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
    except OSError:
        return None


def load_entries(path=None):
    """读全部流水（文件不存在/坏行容错）。"""
    p = path or DEFAULT_PATH
    out = []
    if not os.path.exists(p):
        return out
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def aggregate(entries):
    """汇总：总消耗 / 调用次数 / 按天 / 按动作 / 每章明细与写章平均。"""
    def _n(v):
        return v or 0

    by_day, by_action, chapters = {}, {}, []
    t_in = t_out = t_all = calls = 0
    for e in entries:
        calls += 1
        t_in += _n(e.get("in"))
        t_out += _n(e.get("out"))
        t_all += _n(e.get("total"))
        day = e.get("day") or "?"
        dd = by_day.setdefault(day, {"calls": 0, "in": 0, "out": 0, "total": 0})
        dd["calls"] += 1
        dd["in"] += _n(e.get("in"))
        dd["out"] += _n(e.get("out"))
        dd["total"] += _n(e.get("total"))
        act = e.get("action") or "?"
        by_action[act] = by_action.get(act, 0) + _n(e.get("total"))
        if act == "写正文":
            chapters.append({"book": e.get("book", ""), "chapter": e.get("chapter"),
                             "total": _n(e.get("total")), "ts": e.get("ts", "")})
    writes = [c for c in chapters if c.get("chapter")]
    avg = round(sum(c["total"] for c in writes) / len(writes)) if writes else None
    return {
        "calls": calls, "total_in": t_in, "total_out": t_out, "total": t_all,
        "by_day": by_day, "by_action": by_action,
        "chapters": sorted(chapters, key=lambda c: c["ts"]),
        "write_count": len(writes), "write_avg": avg,
    }
