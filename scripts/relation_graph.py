#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relation_graph.py —— R38 关系图谱：从正文统计角色共现 + L2 提炼关系短语（纯标准库）

防幻觉三道闸（rules/graph.md 的代码化）：
  ① 关系短语必须来自原文证据句——L2 输出的 evidence 逐条回验：不是引用章节正文的
     精确子串就丢弃，绝不入图；
  ② 证据必须带章节号——evidence 只允许从「角色对同段共现」的段落里取，天然带出处；
  ③ 泛称过滤——他/她/那人等泛称一律不建节点，防止图谱被代词污染成星型垃圾图。

L2 输入超 3000 token 截断（防 agnes 推理失控，1 汉字≈1 token 保守口径）。

用法：
  python scripts/relation_graph.py --book books/X
  产物：books/X/关系图谱.json + 关系图谱.md（未配置 API key 时仅共现图谱，标注降级）。
"""
import argparse
import json
import os
import re
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import chapters        # noqa: E402
import deai            # noqa: E402
import write_chapter   # noqa: E402
import usage_log       # noqa: E402

# 泛称/代词黑名单：这些词不准成为图谱节点（防「他—她—那人」星型污染）
GENERIC_NAMES = {"他", "她", "它", "我", "你", "您", "咱", "俺",
                 "那人", "那个人", "这人", "这个人", "此人", "对方",
                 "大家", "众人", "别人", "有人", "谁", "男人", "女人",
                 "老头", "老者", "少女", "少年", "孩子", "家伙"}

MAX_L2_TOKENS = 3000   # L2 输入 token 预算（1 汉字≈1 token 的保守口径）


def filter_generic(name):
    """泛称过滤：命中黑名单或单字名一律不入图（纯函数）。"""
    n = (name or "").strip()
    return (not n) or n in GENERIC_NAMES or len(n) < 2


def load_character_names(book_dir):
    """从 角色卡.md 提取角色名（「前缀：名字」行），过泛称过滤，保序去重。"""
    names = []
    for ln in write_chapter.read_text(os.path.join(book_dir, "角色卡.md")).splitlines():
        m = re.match(r"^\s*[^：:]{1,8}[：:]\s*([\u4e00-\u9fa5A-Za-z0-9·]{2,6})", ln)
        if not m:
            continue
        n = m.group(1)
        if n in ("无", "空") or filter_generic(n):
            continue
        if n not in names:
            names.append(n)
    return names


def chapter_texts(book_dir):
    """读 chapters/chNNN.md → {文件名: 正文}（剥掉文尾 MEMORY 注释块），按章号排序。"""
    ch_dir = os.path.join(book_dir, "chapters")
    out = {}
    if os.path.isdir(ch_dir):
        for f in chapters.list_chapter_files(book_dir):
            t = write_chapter.read_text(os.path.join(ch_dir, f))
            if "<!--MEMORY-->" in t:
                t = t.split("<!--MEMORY-->", 1)[0]
            out[f] = t
    return out


def count_cooccurrence(texts, names):
    """共现统计：同一段落同时出现两个角色名即计一次边。
    返回 (edges, name_counts)：
      edges   {(a,b) 按名字典序排序: {"weight": n, "evidence": [(文件名, 段落)]}}（最多留 2 条证据）
      name_counts {名字: 出现段落数}"""
    edges, name_counts = {}, {n: 0 for n in names}
    for fn, text in texts.items():
        for para in re.split(r"\n+", text):
            if not para.strip():
                continue
            present = [n for n in names if n in para]
            for n in present:
                name_counts[n] += 1
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    key = tuple(sorted((present[i], present[j])))
                    e = edges.setdefault(key, {"weight": 0, "evidence": []})
                    e["weight"] += 1
                    if len(e["evidence"]) < 2:
                        e["evidence"].append((fn, para.strip()[:120]))
    return edges, name_counts


def build_relation_prompt(edges, max_tokens=MAX_L2_TOKENS):
    """组装 L2 关系短语 prompt：每个角色对给共现权重 + 原文证据句。
    超过 max_tokens（按字符保守估算）从后往前截断证据池，保头部角色对。"""
    parts = ["下面是角色共现统计与共现段落的原文证据。请为每个角色对提炼 1 条「关系短语」。",
             "铁律（防幻觉）：",
             "1. 关系短语必须改写自给出的原文证据句，严禁编造原文里没有的关系；",
             "2. evidence 字段必须原样摘抄给出的证据句（或其子串）；",
             "3. 证据不足或关系不明的角色对直接跳过；",
             "只输出 JSON 数组：[{\"a\":\"名A\",\"b\":\"名B\",\"phrase\":\"关系短语\","
             "\"evidence\":\"原文证据句\",\"chapter\":章号}]",
             "", "── 角色对与证据 ──", ""]
    budget = max_tokens
    items = sorted(edges.items(), key=lambda kv: -kv[1]["weight"])
    used = 0
    kept_any = False
    for (a, b), e in items:
        if used > budget:
            break  # 超预算截断：后续角色对不喂（防推理失控）
        block = [f"【{a} × {b}】共现 {e['weight']} 次"]
        for fn, para in e["evidence"]:
            block.append(f"  证据（{fn}）：{para}")
        blk = "\n".join(block) + "\n"
        if used + len(blk) > budget:
            break
        parts.append(blk)
        used += len(blk)
        kept_any = True
    if not kept_any:
        parts.append("（无共现证据）")
    return "\n".join(parts)


def parse_relations(raw):
    """解析 L2 返回的 JSON 数组；容忍前后杂物（截出 [] 段）。"""
    raw = (raw or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    return data if isinstance(data, list) else []


def validate_relations(rels, texts, edges):
    """防幻觉回验：关系短语必须 ① 角色对真实有共现边 ② evidence 是所指章节
    正文的精确子串（chapter 章号 → chNNN.md；章号缺失/越界 → 丢弃）。
    返回 (合格列表, 丢弃数)。"""
    ok, dropped = [], 0
    for r in rels:
        a, b = str(r.get("a", "")).strip(), str(r.get("b", "")).strip()
        phrase = str(r.get("phrase", "")).strip()
        ev = str(r.get("evidence", "")).strip()
        ch = r.get("chapter")
        key = tuple(sorted((a, b)))
        if key not in edges or not phrase or not ev or len(phrase) > 30:
            dropped += 1
            continue
        fn = f"ch{int(ch):03d}.md" if isinstance(ch, (int, float)) and int(ch) > 0 else ""
        if not fn or fn not in texts or ev not in texts[fn]:
            dropped += 1
            continue
        ok.append({"a": a, "b": b, "phrase": phrase, "evidence": ev, "chapter": int(ch)})
    return ok, dropped


def render_graph_md(book_name, name_counts, edges, relations, l2_used):
    """渲染关系图谱.md（纯函数）。"""
    lines = [f"# 《{book_name}》关系图谱（R38）", "",
             f"> 节点口径：角色卡角色名（泛称已过滤）；边口径：同段共现次数；"
             f"关系短语{'由 L2 从原文证据提炼并逐条回验' if l2_used else '未生成（未配置 API key，仅共现图谱）'}。",
             "", "## 节点（出场段落数）", ""]
    for n, c in sorted(name_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {n}：{c}")
    lines += ["", "## 边（共现次数）", ""]
    if edges:
        for (a, b), e in sorted(edges.items(), key=lambda kv: -kv[1]["weight"]):
            rel = next((r for r in relations
                        if tuple(sorted((r["a"], r["b"]))) == (a, b)), None)
            tail = f" —— {rel['phrase']}（第{rel['chapter']}章）" if rel else ""
            lines.append(f"- {a} ↔ {b}：共现 {e['weight']} 次{tail}")
    else:
        lines.append("- （无共现）")
    if l2_used and relations:
        lines += ["", "## 关系短语（附原文证据）", ""]
        for r in relations:
            lines.append(f"- {r['a']} ↔ {r['b']}：{r['phrase']}")
            lines.append(f"  > 证据（第{r['chapter']}章）：{r['evidence']}")
    return "\n".join(lines) + "\n"


def build_graph(book_dir, api_key="", base_url="", model="", reasoning_effort="low"):
    """主流程：角色名 → 共现统计 → （可选）L2 关系短语 + 回验 → 落盘 json/md。
    返回图 dict。零 token 可跑（无 key 时跳过 L2 并在产物中标注降级）。"""
    book_dir = os.path.abspath(book_dir)
    if not os.path.isdir(book_dir):
        raise SystemExit(f"书目录不存在：{book_dir}")
    names = load_character_names(book_dir)
    if not names:
        raise SystemExit("角色卡.md 里没提取到角色名（格式参考「主角：某某」）。")
    texts = chapter_texts(book_dir)
    edges, name_counts = count_cooccurrence(texts, names)
    print(f"[graph] 角色 {len(names)} 个 / 共现边 {len(edges)} 条（{len(texts)} 章）")

    relations, dropped, l2_used = [], 0, False
    if api_key:
        prompt = build_relation_prompt(edges)
        raw = deai.call_llm(
            api_key, base_url, model, prompt,
            temperature=0.1, max_tokens=6000, reasoning_effort=reasoning_effort,
            system_prompt="你是严谨的小说关系图谱编辑，只输出 JSON 数组。",
            max_retries=3,
            usage_meta={"action": usage_log.ACTION_GRAPH, "book": os.path.basename(book_dir.rstrip("/\\"))},
        )
        relations, dropped = validate_relations(parse_relations(raw), texts, edges)
        l2_used = True
        print(f"[graph] L2 关系短语：合格 {len(relations)} 条 / 回验丢弃 {dropped} 条（防幻觉）")
    else:
        print("[graph] 未配置 API key，跳过 L2 关系短语（仅共现图谱，零 token）")

    book_name = os.path.basename(book_dir.rstrip("/\\"))
    nodes = [{"name": n, "count": c} for n, c in
             sorted(name_counts.items(), key=lambda kv: -kv[1])]
    edge_list = [{"a": a, "b": b, "weight": e["weight"],
                  "evidence": [f"{fn}：{para}" for fn, para in e["evidence"]]}
                 for (a, b), e in sorted(edges.items(), key=lambda kv: -kv[1]["weight"])]
    graph = {"nodes": nodes, "edges": edge_list, "relations": relations,
             "meta": {"l2_used": l2_used, "dropped_relations": dropped}}
    with open(os.path.join(book_dir, "关系图谱.json"), "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    with open(os.path.join(book_dir, "关系图谱.md"), "w", encoding="utf-8") as f:
        f.write(render_graph_md(book_name, name_counts, edges, relations, l2_used))
    print(f"[graph] 已落盘 → {os.path.join(book_dir, '关系图谱.json')} 与 关系图谱.md")
    return graph


def main() -> int:
    ap = argparse.ArgumentParser(description="R38 关系图谱：角色共现统计 + 防幻觉关系短语")
    ap.add_argument("--book", required=True, help="书目录路径（支持相对项目根路径）")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--reasoning-effort", default="low")
    args = ap.parse_args()

    api_key = deai.env_or("AGNES_API_KEY", "AGNES_API_KEY", "")
    base_url = args.base_url or deai.env_or("AGNES_BASE_URL", "AGNES_BASE_URL", deai.DEFAULT_BASE_URL)
    model = args.model or deai.env_or("AGNES_MODEL", "AGNES_MODEL", deai.DEFAULT_MODEL)
    build_graph(args.book, api_key=api_key, base_url=base_url, model=model,
                reasoning_effort=args.reasoning_effort)
    return 0


if __name__ == "__main__":
    sys.exit(main())
