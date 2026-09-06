#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vector_recall.py —— R39 可选向量层：旧章片段的语义召回（可选依赖 chromadb）

设计：向量层是「加分项」不是「必需品」——
  - 未安装 chromadb → 输出「不可用，已降级」并正常退出（exit 0），绝不报错阻断主流程；
  - 未配置嵌入通道（EMBED_*）→ llm.post_embed 抛 ValueError，同样友好降级；
  - 都就绪时：index 把各章分块嵌入入库（books/<书>/_vector/），recall 按当前写作位置
    召回相关旧章片段，落盘 books/<书>/_recall/chXXX.md——build_context 检测到该文件
    才注入（文件不存在则不注入，零破坏）。

用法：
  python scripts/vector_recall.py --book books/X index    # 建库（分块嵌入入库）
  python scripts/vector_recall.py --book books/X recall   # 召回（为「下一章」准备相关旧章片段）
"""
import argparse
import os
import re
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import chapters        # noqa: E402
import llm             # noqa: E402
import write_chapter   # noqa: E402

try:  # 可选依赖：没有 chromadb 就降级，绝不阻断
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None
    CHROMA_AVAILABLE = False

VECTOR_DIR = "_vector"    # chroma 持久化目录（书内）
RECALL_DIR = "_recall"    # 召回结果落盘目录（书内，build_context 读取）
CHUNK_SIZE = 800          # 分块长度（字）
CHUNK_OVERLAP = 100       # 相邻块重叠（防语义被切断）
TOP_K = 5                 # 召回片段数


def check_available():
    """chromadb 是否可用（纯函数式探测，供测试与降级判断）。"""
    return CHROMA_AVAILABLE


def degrade(reason):
    """统一降级出口：说明原因、给出解锁方式，永远不抛异常。"""
    print(f"⚠ 向量层不可用，已降级（不影响写作主流程）：{reason}")
    if "chromadb" in reason:
        print("  解锁方式：pip install chromadb（可选安装；不装也能正常写书）")
    else:
        print("  解锁方式：在 .env 配置 EMBED_API_KEY / EMBED_MODEL（可选 EMBED_BASE_URL）")
    return 0


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """定长滑动窗口分块（纯函数）：末块不足 size 也保留；空文本返回 []。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    return [text[i:i + size] for i in range(0, len(text), step)]


def _embed_fn():
    """返回嵌入函数（llm.post_embed）；未配置嵌入通道时给出可读错误。"""
    return llm.post_embed


def index_book(book_dir, embed_fn=None):
    """把全书章节分块嵌入入库（chroma 持久化到 books/<书>/_vector/）。
    返回入库块数；依赖缺失时走降级返回 0。"""
    if not CHROMA_AVAILABLE:
        degrade("未安装 chromadb")
        return 0
    embed_fn = embed_fn or _embed_fn()
    texts = _chapter_texts(book_dir)
    if not texts:
        print(f"[vector] chapters/ 里没有章节可入库：{book_dir}")
        return 0
    client = chromadb.PersistentClient(path=os.path.join(book_dir, VECTOR_DIR))
    col = client.get_or_create_collection("chapters")
    n = 0
    for fn, text in texts.items():
        chunks = chunk_text(text)
        if not chunks:
            continue
        vecs = embed_fn(chunks)  # list[str] → [vec, ...]（批量口径）
        ids = [f"{fn}::{i:03d}" for i in range(len(chunks))]
        col.upsert(ids=ids, embeddings=vecs, documents=chunks,
                   metadatas=[{"chapter_file": fn}] * len(chunks))
        n += len(chunks)
        print(f"[vector] {fn}：{len(chunks)} 块入库")
    print(f"[vector] 建库完成：{n} 块 → {os.path.join(book_dir, VECTOR_DIR)}")
    return n


def recall_history(book_dir, top_k=TOP_K, chapter=None, embed_fn=None, query=None):
    """按当前写作位置召回相关旧章片段，落盘 _recall/chXXX.md（build_context 注入源）。
    召回目标章默认 = 最新章 + 1（为写下一章准备）；可用 --chapter 覆盖。
    query 非空时直接作为查询语义（MCP recall_history 用），覆盖「上章结尾」默认。
    返回召回文本；依赖缺失时走降级返回空串。"""
    if not CHROMA_AVAILABLE:
        degrade("未安装 chromadb")
        return ""
    vec_dir = os.path.join(book_dir, VECTOR_DIR)
    if not os.path.isdir(vec_dir):
        degrade("还没有向量库（先跑 index 子命令建库）")
        return ""
    embed_fn = embed_fn or _embed_fn()
    texts = _chapter_texts(book_dir)
    if not texts:
        print(f"[vector] chapters/ 里没有章节：{book_dir}")
        return ""
    # 查询文本 = 目标章的前一章结尾（写 ch N 时最相关的是 ch N-1 的收束语境）
    nums = sorted(write_chapter.chapter_no_of(f) for f in texts)
    target = int(chapter) if chapter else nums[-1] + 1
    if query:  # 显式查询优先（MCP recall_history 契约）：独立语义，不受「无更早章」守卫拦截
        query_text = query
    else:
        query_from = [n for n in nums if n < target]
        if not query_from:
            print("[vector] 没有更早的章节可召回（第一章不需要旧章记忆）。")
            return ""
        query_text = texts[f"ch{query_from[-1]:03d}.md"][-CHUNK_SIZE:]
    client = chromadb.PersistentClient(path=vec_dir)
    col = client.get_or_create_collection("chapters")
    if col.count() == 0:
        degrade("向量库为空（先跑 index 子命令建库）")
        return ""
    qvec = embed_fn(query_text)  # str → vec
    res = col.query(query_embeddings=[qvec], n_results=min(top_k, col.count()))
    lines = [f"以下 {len(res['ids'][0])} 条旧章片段与当前写作位置语义相关"
             f"（向量召回 top{min(top_k, col.count())}，供呼应旧情节）：", ""]
    for i, doc in enumerate(res["documents"][0]):
        meta = (res.get("metadatas") or [[]])[0][i] if res.get("metadatas") else {}
        lines.append(f"- 【{meta.get('chapter_file', '?')}】{doc[:200]}……")
    text = "\n".join(lines)
    out_dir = os.path.join(book_dir, RECALL_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"ch{target:03d}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[vector] 召回完成（{len(res['ids'][0])} 条）→ {out}（写第 {target} 章时自动注入）")
    return text


def _chapter_texts(book_dir):
    """读 chapters/chNNN.md → {文件名: 正文}（剥 MEMORY 块）。"""
    ch_dir = os.path.join(book_dir, "chapters")
    out = {}
    if os.path.isdir(ch_dir):
        for f in chapters.list_chapter_files(book_dir):
            t = write_chapter.read_text(os.path.join(ch_dir, f))
            if "<!--MEMORY-->" in t:
                t = t.split("<!--MEMORY-->", 1)[0]
            out[f] = t
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="R39 可选向量层：旧章片段语义召回（无 chromadb 自动降级）")
    ap.add_argument("--book", required=True, help="书目录路径（支持相对项目根路径）")
    ap.add_argument("action", choices=["index", "recall"], help="index=建库 / recall=召回")
    ap.add_argument("--chapter", type=int, default=0,
                    help="召回目标章号（默认=最新章+1，为写下一章准备）")
    ap.add_argument("--query", default="", help="显式查询文本（默认用目标章前一章结尾）")
    ap.add_argument("--k", type=int, default=0, help="召回条数（默认 TOP_K）")
    args = ap.parse_args()

    book_dir = os.path.abspath(args.book)
    if not os.path.isdir(book_dir):
        print(f"书目录不存在：{book_dir}")
        return 1
    try:
        if args.action == "index":
            index_book(book_dir)
        else:
            recall_history(book_dir, top_k=(args.k or TOP_K),
                           chapter=args.chapter or None, query=args.query or None)
    except ValueError as e:  # 嵌入通道未配置：友好降级，绝不报错阻断
        return degrade(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
