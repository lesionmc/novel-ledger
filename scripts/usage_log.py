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
import threading
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "usage_log.jsonl")

# 动作名统一常量（写正文是前端排序/每章平均的锚点，字符串写散了容易改漏一处）。
# 各引擎调用 usage_meta={"action": ...} 时一律引这里的常量；冷僻一次性动作名才允许裸字符串。
ACTION_WRITE = "写正文"          # 写章正文（前端每章平均/排序锚点，勿改字面）
ACTION_LEDGER = "账本更新"       # 写章后滚动账本更新
ACTION_LEDGER_INIT = "建账"      # --init-state 首次建账
ACTION_LEDGER_RECALC = "账本重算"  # R49 从快照重算账本
ACTION_AUDIT = "审计"            # 一致性审计（单章/交叉共用）
ACTION_OUTLINE = "出章纲"        # 生成下一章章纲
ACTION_EVALUATE = "章纲评估"     # 章纲质量评估
ACTION_ADJUST_WORDS = "字数调整"  # --words 字数软控改写
ACTION_BETA = "读者反馈"         # R43 读者视角反馈
ACTION_DEAI = "去味精判"         # L2 去 AI 味精判
ACTION_GRAPH = "关系图谱"        # R38 关系短语提炼
ACTION_STYLE = "学文风"          # R37 文风指纹学习
ACTION_DISSECT = "拆书"          # R36 拆书报告
ACTION_BLUEPRINT = "三部曲蓝图"  # R36 三部曲规划
ACTION_STREAM = "流式对话"       # llm.post_chat_stream 流式通道

# 并发追加锁：Web 多线程 + 连写引擎同时记账时，裸 append 可能交叉丢行
_LOG_LOCK = threading.Lock()


def log_usage(action, model, prompt_tokens, completion_tokens,
              book="", chapter=None, path=None, elapsed_ms=None):
    """记一笔流水账。返回写入的 dict；失败返回 None（绝不抛异常打扰主流程）。
    elapsed_ms：可选耗时（毫秒）。非数字一律省略该键（旧格式行不含此键，读取端兼容）。"""
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
    if isinstance(elapsed_ms, (int, float)) and not isinstance(elapsed_ms, bool):
        entry["elapsed_ms"] = round(elapsed_ms)
    try:
        with _LOG_LOCK:
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
    """汇总：总消耗 / 调用次数 / 按天 / 按动作 / 每章明细与写章平均 / 按动作平均耗时。
    注意：by_action 保持纯数字（前端 Usage.jsx 按值排序）；耗时均值放平行的 avg_ms_by_action。"""
    def _n(v):
        return v or 0

    by_day, by_action, avg_ms, chapters = {}, {}, {}, []
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
        em = e.get("elapsed_ms")
        if isinstance(em, (int, float)) and not isinstance(em, bool):
            # 平行键：均值 = 总耗时 / 带耗时条数（旧格式行无 elapsed_ms，不参与）
            cur = avg_ms.setdefault(act, {"ms": 0, "n": 0})
            cur["ms"] += em
            cur["n"] += 1
        if act == ACTION_WRITE:
            chapters.append({"book": e.get("book", ""), "chapter": e.get("chapter"),
                             "total": _n(e.get("total")), "ts": e.get("ts", "")})
    writes = [c for c in chapters if c.get("chapter")]
    avg = round(sum(c["total"] for c in writes) / len(writes)) if writes else None
    avg_ms_by_action = {a: round(v["ms"] / v["n"]) for a, v in avg_ms.items() if v["n"]}
    return {
        "calls": calls, "total_in": t_in, "total_out": t_out, "total": t_all,
        "by_day": by_day, "by_action": by_action,
        "avg_ms_by_action": avg_ms_by_action,
        "chapters": sorted(chapters, key=lambda c: c["ts"]),
        "write_count": len(writes), "write_avg": avg,
    }
