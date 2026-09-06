#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_learn.py —— R37 学文风：从自己的成稿里提炼「文风指纹」（纯标准库）

做什么：对指定书做两步提炼，产出 books/<书>/文风指纹.md——
  L1 统计（零 token）：复用 deai.l1_scan_book 的结果口径（词表命中/标点/意象跨章复用），
                      汇总成「高频词与意象」画像；
  L2 画像（调模型）：结合最近章节片段，让模型总结句长节奏 / 对话密度 / 意象偏好 / 叙事人称。

用法：
  python scripts/style_learn.py --book books/X [--chapters N]
  产物：books/X/文风指纹.md（write_chapter.build_context 会自动注入续写配方）。

零第三方依赖；L2 走 deai.call_llm（重试/备用通道/用量记账同源复用）。
"""
import argparse
import os
import sys
from collections import Counter

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import deai            # noqa: E402
import write_chapter   # noqa: E402
import usage_log       # noqa: E402


def aggregate_l1(results, repeat_notes):
    """把 deai.l1_scan_book 的全书结果聚合成文风统计 dict（纯函数，零 token）。
    口径注释：soft 高频词按「总次数」累加（l1 结果里 soft=(词, 次数, 类别)），
    hard 只计命中总数（写文风时不需要逐条定位）。"""
    soft_total = Counter()
    hard_total = 0
    chars = 0
    for r in results:
        chars += r["chars"]
        hard_total += len(r["hard"])
        for w, n, _c in r["soft"]:
            soft_total[w] += n
    return {
        "chapters": len(results),
        "chars": chars,
        "hard_total": hard_total,
        "soft_top": soft_total.most_common(10),
        "image_reuse": [(iw, total, chs) for iw, total, chs, _d in repeat_notes],
    }


def build_style_prompt(stats, samples):
    """组装 L2 文风画像 prompt：L1 统计概况 + 最近章节片段 + 四维画像要求（纯函数）。"""
    parts = ["请根据下面的统计概况与正文片段，为这本书画一张「文风画像」，"
             "供 AI 续写时模仿。只输出画像本身（Markdown），分四节：",
             "## 句长节奏（平均句长/长短句交替习惯/段落密度）",
             "## 对话密度（对话占比/对话风格/引号习惯）",
             "## 意象偏好（高频意象与使用场景，避开套路化用法）",
             "## 叙事人称（视角/时态/心理描写习惯）",
             "",
             "要求：结论必须来自下方片段的实证观察，不要套通用写作建议；"
             "每节给 2-4 条可执行的「写法指令」式描述（如「段落多在 3 行内」而非「节奏紧凑」）。",
             "", "── L1 统计概况（词表硬筛口径）──",
             f"- 章节 {stats['chapters']} 章 / 共 {stats['chars']} 字",
             f"- AI 腔硬伤总数 {stats['hard_total']}（越少说明原稿越克制）",
             "- soft 高频词：" + ((", ".join(f"{w}×{n}" for w, n in stats["soft_top"]) or "无")),
             "- 跨章复用意象：" + ((", ".join(f"「{iw}」×{total} 跨 {chs} 章"
                                          for iw, total, chs in stats["image_reuse"]) or "无")), "",
             "── 正文片段（最近章节）──", ""]
    for s in samples:
        parts.append(f"【{s['file']}】\n{s['text']}\n")
    return "\n".join(parts)


def render_fingerprint(stats, profile_text, book_name):
    """渲染文风指纹.md：L1 统计块 + L2 画像（纯函数）。"""
    lines = [f"# 《{book_name}》文风指纹（R37 学文风）", "",
             "> 产出口径：L1 统计复用 deai.l1_scan_book；L2 画像由模型基于最近章节片段总结。",
             "> 本文件由 write_chapter.build_context 在续写时自动注入（文件存在才注入）。", "",
             "## L1 统计（词表硬筛口径）",
             f"- 章节 {stats['chapters']} 章 / 共 {stats['chars']} 字",
             f"- AI 腔硬伤总数：{stats['hard_total']}",
             "- soft 高频词：" + ((", ".join(f"{w}×{n}" for w, n in stats["soft_top"]) or "无")),
             "- 跨章复用意象：" + ((", ".join(f"「{iw}」×{total} 跨 {chs} 章"
                                          for iw, total, chs in stats["image_reuse"]) or "无")),
             "", "## 文风画像（L2）", "", (profile_text or "（L2 画像缺失）"), ""]
    return "\n".join(lines)


def learn_style(book_dir, chapters=0, api_key="", base_url="", model="",
                reasoning_effort="low"):
    """主流程：L1 统计 + （可选最近 N 章）片段 → L2 画像 → 落盘文风指纹.md。返回指纹路径。"""
    book_dir = os.path.abspath(book_dir)
    if not os.path.isdir(book_dir):
        raise SystemExit(f"书目录不存在：{book_dir}")
    results, repeat_notes = deai.l1_scan_book(book_dir)
    if not results:
        raise SystemExit(f"书目录里没有章节可分析（chapters/chNNN.md）：{book_dir}")
    if chapters and int(chapters) > 0:  # --chapters N：只统计最近 N 章
        results = results[-int(chapters):]
    stats = aggregate_l1(results, repeat_notes)
    samples = write_chapter.sample_chapters(book_dir, n=int(chapters) if chapters else 3)
    if not samples:
        raise SystemExit("chapters/ 里没有可用片段，无法学文风。")
    print(f"[style] L1 统计完成（{stats['chapters']} 章 / {stats['chars']} 字），"
          f"采样 {len(samples)} 章 → 调 L2 画画像...")
    prompt = build_style_prompt(stats, samples)
    profile = deai.call_llm(
        api_key, base_url, model, prompt,
        temperature=0.3, max_tokens=6000, reasoning_effort=reasoning_effort,
        system_prompt="你是文学编辑，只基于给出的正文片段输出文风画像，不要客套话。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_STYLE, "book": os.path.basename(book_dir.rstrip("/\\"))},
    ).strip()
    out = os.path.join(book_dir, "文风指纹.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_fingerprint(stats, profile, os.path.basename(book_dir.rstrip("/\\"))))
    print(f"[style] 文风指纹已落盘 → {out}（写章时自动注入）")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="R37 学文风：L1 统计 + L2 画像 → books/<书>/文风指纹.md")
    ap.add_argument("--book", required=True, help="书目录路径（支持相对项目根路径）")
    ap.add_argument("--chapters", type=int, default=0, metavar="N",
                    help="只统计最近 N 章（默认全部；片段采样同步取最近 N 章）")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--reasoning-effort", default="low")
    args = ap.parse_args()

    api_key = deai.env_or("AGNES_API_KEY", "AGNES_API_KEY", "")
    if not api_key:
        print("缺少 API key：请在项目根 .env 写 AGNES_API_KEY=sk-xxx")
        return 1
    base_url = args.base_url or deai.env_or("AGNES_BASE_URL", "AGNES_BASE_URL", deai.DEFAULT_BASE_URL)
    model = args.model or deai.env_or("AGNES_MODEL", "AGNES_MODEL", deai.DEFAULT_MODEL)
    learn_style(args.book, chapters=args.chapters, api_key=api_key,
                base_url=base_url, model=model, reasoning_effort=args.reasoning_effort)
    return 0


if __name__ == "__main__":
    sys.exit(main())
