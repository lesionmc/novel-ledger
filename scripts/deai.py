# -*- coding: utf-8 -*-
"""ai-novel-workbench · 去 AI 味引擎（P1 第二块）

治什么病：AI 写中文小说常见的「AI 腔」——套路意象反复用、万能副词堆砌、
动作模板化、破折号滥用等。这层"说不清哪里不对"被引擎变成"可数、可改"。

两级检测：
  L1 词表硬筛（本地跑，零 token）：黑名单词 + 标点密度 + 跨章意象重复，出 AI 腔指数
  L2 AI 精判（调模型）：只喂命中句 + 局部上下文，逐句判定「真 AI 腔 / 正常表达」+ 给改写建议

工作流（先报告后应用，不改原文）：
  --scan    <书目录>               全书体检，控制台出指数报告（不烧 token）
  --polish <书目录> --chapter N    单章 AI 精判，落盘 chXXX.AI腔体检.md（不改正文）
  （--apply 应用改写：留待人工看完报告后下一步再做）

用法示例：
  python deai.py --scan "books/雾城档案"
  python deai.py --polish "books/雾城档案" --chapter 5

注意：与 write_chapter.py 同源复用的坑（agnes-2.5-flash 输入 >5k tokens 触发
reasoning 失控）已规避——L2 只喂命中句局部上下文，不喂全文。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

# ---------------------------------------------------------------- 模型配置
DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1/"
DEFAULT_MODEL = "agnes-2.5-flash"
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def load_dotenv(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


DOTENV = load_dotenv(ENV_PATH)


def env_or(key_env, key_dotenv, default):
    return os.environ.get(key_env) or DOTENV.get(key_dotenv) or default


def call_llm(api_key, base_url, model, user_content, temperature=0.2,
             max_tokens=4000, reasoning_effort="low", max_retries=2,
             system_prompt=None, *,
             fallback_key=None, fallback_base_url=None, fallback_model=None,
             usage_meta=None):
    """调用 chat completion（OpenAI 兼容），返回正文文本。
    与 write_chapter.py 同款：reasoning_effort=low 抑制 agnes 推理失控；空内容报警重试。
    防单点故障：主模型连续失败后自动切备用通道（参数 > .env 的 FALLBACK_API_KEY 等）。
    usage_meta={"action","book","chapter"}：传了就顺带记用量流水（R48），失败不影响主流程。"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or "你是严谨的中文小说编辑。"},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if reasoning_effort and reasoning_effort != "none":
        payload["reasoning_effort"] = reasoning_effort

    def _try_channel(ch_key, ch_url, ch_model, label):
        payload["model"] = ch_model  # 关键：切备用通道时必须把模型名换掉，否则请求体仍带主模型
        last_err = ""
        for attempt in range(max_retries + 1):
            if attempt > 0:
                wait = 5 * (2 ** (attempt - 1))
                print(f"  ⚠ {label} 第 {attempt} 次重试（等待 {wait}s）...")
                time.sleep(wait)
            # 每次发送前现序列化：payload["model"] 可能已被切换，确保请求体带的是本通道模型
            req_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(ch_url.rstrip("/") + "/chat/completions",
                                         data=req_body, method="POST", headers={
                                             "Content-Type": "application/json",
                                             "Authorization": f"Bearer {ch_key}",
                                         })
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices") or []
                choice = choices[0] if choices else {}
                finish = choice.get("finish_reason", "?")
                usage = data.get("usage", {})
                print(f"[用量] 输入 {usage.get('prompt_tokens', '?')} / 输出 "
                      f"{usage.get('completion_tokens', '?')} / 总 {usage.get('total_tokens', '?')} tokens | "
                      f"finish={finish}")
                if usage:
                    try:
                        import usage_log
                        m = usage_meta or {}
                        usage_log.log_usage(m.get("action", "去味"), ch_model,
                                            usage.get("prompt_tokens"),
                                            usage.get("completion_tokens"),
                                            book=m.get("book", ""), chapter=m.get("chapter"))
                    except Exception:
                        pass  # 记账失败绝不影响主流程（R48 设计约束）
                content = (choice.get("message") or {}).get("content") or ""
                content = content.strip()
                if not content:
                    last_err = f"空内容（finish_reason={finish}）"
                    print(f"  ⚠ {label} 模型返回空：{last_err}")
                    continue
                return content
            except Exception as e:
                last_err = str(e)
                print(f"  ⚠ {label} 请求异常：{last_err}")
        raise RuntimeError(f"{label}模型调用失败（重试 {max_retries} 次后放弃）：{last_err}")

    try:
        return _try_channel(api_key, base_url, model, "主模型")
    except RuntimeError:
        fb_key = fallback_key or env_or("FALLBACK_API_KEY", "FALLBACK_API_KEY", "")
        fb_model = fallback_model or env_or("FALLBACK_MODEL", "FALLBACK_MODEL", "")
        if not (fb_key and fb_model):
            raise
        fb_url = fallback_base_url or env_or("FALLBACK_BASE_URL", "FALLBACK_BASE_URL", base_url)
        print(f"⚠ 主模型 {model} 失败，切换备用模型 {fb_model}（{fb_url}）...")
        return _try_channel(fb_key, fb_url, fb_model, "备用模型")


# ---------------------------------------------------------------- AI 腔词表
# 词表维护：直接在此 dict 增删。weight=hard（出现即大概率腔）/ soft（单章 ≥2 次才算腔）
AI_TONE_BLACKLIST = {
    # —— 动作/神态模板（hard）
    "若有所思": ("动作模板", "hard"),
    "陷入沉思": ("动作模板", "hard"),
    "陷入了沉思": ("动作模板", "hard"),
    "五味杂陈": ("成语腔", "hard"),
    "百感交集": ("成语腔", "hard"),
    "心头一紧": ("身体反应模板", "hard"),
    "心中一动": ("身体反应模板", "hard"),
    "心里一沉": ("身体反应模板", "hard"),
    "心下一沉": ("身体反应模板", "hard"),
    "不禁": ("副词堆砌", "hard"),
    "不由得": ("副词堆砌", "hard"),
    "下意识地": ("副词堆砌", "hard"),
    "下意识": ("副词堆砌", "hard"),
    # —— 虚指/神秘化（hard）
    "说不清道不明": ("虚指腔", "hard"),
    "某种说不清": ("虚指腔", "hard"),
    "一种说不清": ("虚指腔", "hard"),
    # —— 空气/时间凝固类陈词（hard）
    "空气仿佛凝固": ("陈词比喻", "hard"),
    "时间仿佛静止": ("陈词比喻", "hard"),
    "仿佛置身": ("陈词比喻", "hard"),
    "一股寒意": ("身体反应模板", "hard"),
    # —— 万能副词（soft，单章≥2 才报）
    "微微": ("万能副词", "soft"),
    "轻轻": ("万能副词", "soft"),
    "缓缓": ("万能副词", "soft"),
    "默默": ("万能副词", "soft"),
    "静静": ("万能副词", "soft"),
    "淡淡": ("万能副词", "soft"),
    "深深": ("万能副词", "soft"),
    "某种": ("虚指腔", "soft"),
    "若有若无": ("虚指腔", "soft"),   # 形容气味/光影属正常表达，仅高频才报
    "似有似无": ("虚指腔", "soft"),
    "点了点头": ("动作模板", "soft"),
    "摇了摇头": ("动作模板", "soft"),
    "皱了皱眉": ("动作模板", "soft"),
    "叹了口气": ("动作模板", "soft"),
    "沉默了片刻": ("动作模板", "soft"),
    "沉默了良久": ("动作模板", "soft"),
    "沉默了一会儿": ("动作模板", "soft"),
}

# 陈词比喻整句模板（hard，正则）
HARD_PATTERNS = [
    (re.compile(r"夜色.{0,4}(如墨|似墨|像墨|沉得像墨|浓得像墨)"), "陈词比喻（夜色如墨）"),
    (re.compile(r"仿佛[^，。！？]{1,12}(一般|似的)"), "陈词比喻（仿佛…一般）"),
    (re.compile(r"空气.{0,6}(凝固|安静得|静得)"), "陈词比喻（空气凝固）"),
]

# 语境依赖的句式（soft，单章 ≥ 阈值才报；如"不是X而是Y"在推理/对比场景属正常表达）
SOFT_PATTERNS = [
    (re.compile(r"不是[^，。！？]{1,24}，而是"), "对仗句式（不是X而是Y）"),
]

# 意象复用提示（不是判错，跨章≥2 章且总≥3 次才提示人工留意）
# 注意：别放专名（如城市名"雾城"每章都出现是正常的），只放"可换写法的意象词"
IMAGE_WORDS = ["雨刷", "雨刮", "水雾", "雾气", "夜色", "墨色", "霓虹"]

SOFT_THRESHOLD = 2      # soft 词单章 ≥ 此值才算高频命中
DASH_PER_1000 = 2.0     # 破折号每千字阈值
ELLIPSIS_PER_1000 = 1.5  # 省略号每千字阈值


# ---------------------------------------------------------------- 工具函数
def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def clean_text(s):
    return re.sub(r"\s+", "", s)


def chapter_files(book_dir):
    ch_dir = os.path.join(book_dir, "chapters")
    if not os.path.isdir(ch_dir):
        ch_dir = book_dir  # 兼容直接指到含 chXXX.md 的目录
    files = sorted((f for f in os.listdir(ch_dir) if re.match(r"^ch\d{3}\.md$", f)),
                   key=lambda f: int(f[2:5]))  # 按章节号排序，避免 ch010 排在 ch002 前
    return ch_dir, files


def hit_window(line, word, width=28):
    """返回命中词前后各 width 字符的窗口文本，方便报告定位。"""
    i = line.find(word)
    if i < 0:
        return line
    return line[max(0, i - width): i + len(word) + width]


def l1_scan_book(book_dir):
    """L1 词表硬筛全书，返回逐章结果 dict。零 token。"""
    ch_dir, files = chapter_files(book_dir)
    results = []
    image_hits = {}  # 意象词 -> [(章, 行号, 句窗口)]
    for fn in files:
        lines = read_text(os.path.join(ch_dir, fn)).splitlines()
        text = "".join(lines)
        length = len(clean_text(text))
        hard_hits = []   # (行号, 词/模式, 类别, 窗口)
        soft_hits = []
        dash_n = len(re.findall(r"—{2,}|——", text))
        ellipsis_n = len(re.findall(r"…{2,}|……", text))
        for ln, line in enumerate(lines, 1):
            if not line.strip():
                continue
            for word, (cat, weight) in AI_TONE_BLACKLIST.items():
                if weight == "hard" and word in line:
                    hard_hits.append((ln, word, cat, hit_window(line, word)))
            for pat, cat in HARD_PATTERNS:
                m = pat.search(line)
                if m:
                    hard_hits.append((ln, m.group(0), cat, hit_window(line, m.group(0))))
            for iw in IMAGE_WORDS:
                if iw in line:
                    image_hits.setdefault(iw, []).append((fn, ln, hit_window(line, iw)))
        # soft 词/句式按【全文出现次数】计（同一行堆砌多个也如实计数，跨行跨句都算）
        for word, (cat, weight) in AI_TONE_BLACKLIST.items():
            if weight == "soft":
                n = text.count(word)
                if n >= SOFT_THRESHOLD:
                    soft_hits.append((word, n, cat))
        for pat, label in SOFT_PATTERNS:
            n = len(pat.findall(text))
            if n >= SOFT_THRESHOLD:
                soft_hits.append((label, n, "句式高频"))
        dash_rate = dash_n * 1000 / max(length, 1)
        ell_rate = ellipsis_n * 1000 / max(length, 1)
        dash_flag = dash_rate >= DASH_PER_1000
        ell_flag = ell_rate >= ELLIPSIS_PER_1000
        score = len(hard_hits) * 2 + len(soft_hits) + dash_flag + ell_flag
        index = round(score * 1000 / max(length, 1), 1)
        results.append({
            "file": fn, "chars": length,
            "hard": hard_hits, "soft": soft_hits,
            "dash": dash_n, "dash_rate": round(dash_rate, 1), "dash_flag": dash_flag,
            "ellipsis": ellipsis_n, "ell_rate": round(ell_rate, 1), "ell_flag": ell_flag,
            "score": score, "index": index,
        })
    # 跨章意象重复：出现章数 ≥2 且总次 ≥3 提示
    repeat_notes = []
    for iw, hits in image_hits.items():
        chs = sorted({h[0] for h in hits})
        if len(hits) >= 3 and len(chs) >= 2:
            detail = "、".join(f"{h[0]} L{h[1]}" for h in hits[:6])
            repeat_notes.append((iw, len(hits), len(chs), detail))
    return results, repeat_notes


def render_scan_report(results, repeat_notes, book_dir):
    """把 L1 结果渲染成控制台文本。"""
    out = []
    out.append(f"《{os.path.basename(book_dir)}》AI 腔指数报告（L1 词表硬筛 · 本地零 token）")
    out.append("指数口径：每千字加权分（hard×2 + soft高频 + 标点超标，越高越腔）\n")
    for r in results:
        out.append(f"■ {r['file']}（{r['chars']} 字）指数 {r['index']}")
        for ln, word, cat, win in r["hard"]:
            out.append(f"  [硬伤] L{ln} {word}（{cat}）…{win}…")
        for word, n, cat in r["soft"]:
            out.append(f"  [高频] 「{word}」×{n}（阈值{SOFT_THRESHOLD}，{cat}）")
        if r["dash_flag"]:
            out.append(f"  [标点] 破折号 ×{r['dash']}（每千字 {r['dash_rate']}，超阈 {DASH_PER_1000}）")
        if r["ell_flag"]:
            out.append(f"  [标点] 省略号 ×{r['ellipsis']}（每千字 {r['ell_rate']}，超阈 {ELLIPSIS_PER_1000}）")
        if not r["hard"] and not r["soft"] and not r["dash_flag"] and not r["ell_flag"]:
            out.append("  （干净）")
        out.append("")
    out.append("── 跨章意象复用提示（同一意象多章反复用，最容易被读者察觉出「AI 腔」）──")
    if repeat_notes:
        for iw, total, chs, detail in repeat_notes:
            out.append(f"  ⚠ 「{iw}」全书 {total} 次，跨 {chs} 章：{detail}")
    else:
        out.append("  （暂无强信号）")
    return "\n".join(out)


SENT_END = "。！？；…\"'“”‘’「」『』"  # 句末标点 + 各类引号都算边界，锚点不吞引号


def extract_full_sentence(line, keyword):
    """从一行文本中，以 keyword 为中心切出包含它的完整句子（作为 --apply 的替换锚）。
    锚必须是原行里的精确子串，程序才能可靠替换。"""
    i = line.find(keyword)
    if i < 0:
        return line.strip()
    start = i
    while start > 0 and line[start - 1] not in SENT_END:
        start -= 1
    end = i + len(keyword)
    while end < len(line) and line[end] not in SENT_END:
        end += 1
    if end < len(line):
        end += 1  # 吃掉句末标点
    return line[start:end].strip()


# ---------------------------------------------------------------- L2 AI 精判
L2_SYSTEM = "你是资深中文小说编辑，专门剔除「AI 腔」。只按用户给出的清单逐句判定，不扩大范围。"


def build_l2_prompt(fn, length, hard, soft, dash_flag, ell_flag, repeat_hits, lines):
    """给 L2 组 prompt：命中句局部上下文（不喂全文，防推理失控）。
    返回 (prompt, hard_idx_map)：hard_idx_map 记录可自动应用项的行号+完整原句，
    供 --apply 精确替换。"""
    parts = [f"请对《{fn}》的 AI 腔候选句逐条精判。正文约 {length} 字，以下是候选句及其前后文（行号对应原文）。",
             "判定规则：",
             "1. verdict=ai：确实是 AI 腔（套路表达/副词堆砌/模板动作/意象陈词），给出自然的中文改写；",
             "2. verdict=ok：虽是候选词但放在这里属于正常文学表达（如人物对话、有意为之的修辞），保留；",
             "3. 【可自动应用项】（标了「原文整句」的条目）：rewrite 必须给出该完整句的改写版——",
             "   保留句中无需改动的部分，只替换病句成分。程序会用 rewrite 整句替换原句，",
             "   所以 rewrite 必须是完整句子，不能是片段、不能省略句尾标点；",
             "4. 【示范项】（高频/标点/意象条目）：给出改写示范即可，不会被自动应用；",
             "5. 改写不改变情节、语气与叙事视角，越朴素越好。",
             "只输出 JSON 数组，不要 markdown、不要解释：",
             '[{"idx":1,"verdict":"ai|ok","rewrite":"(verdict=ai 给完整句改写，否则留空)","reason":"一句话理由"}]',
             "", "── 候选清单 ──", ""]
    idx = 0
    hard_idx_map = {}
    for ln, word, cat, win in hard:
        idx += 1
        ctx = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
        full = extract_full_sentence(ctx, word)
        hard_idx_map[idx] = {"line": ln, "orig": full}
        parts.append(f"[{idx}] L{ln} 命中「{word}」（{cat}）【可自动应用】")
        parts.append(f"    原文整句：{full}")
        parts.append(f"    定位窗口：…{win}…")
    for word, n, cat in soft:
        idx += 1
        parts.append(f"[{idx}] 「{word}」本章出现 {n} 次（{cat}·高频）【示范】——"
                     "请判断是否构成重复腔调，可只针对最刺眼处给一条改写示范")
    if dash_flag or ell_flag:
        idx += 1
        flag = []
        if dash_flag:
            flag.append("破折号密集")
        if ell_flag:
            flag.append("省略号密集")
        parts.append(f"[{idx}] 全章标点提示：{'、'.join(flag)}【示范】（未逐句列出，请在改写示范里体现归并思路）")
    if repeat_hits:
        idx += 1
        parts.append(f"[{idx}] 跨章意象提示：本章以下意象与前面章节重复出现——{repeat_hits}"
                     "【示范】（请至少对其中一处给出差异化改写示范）")
    return "\n".join(parts), hard_idx_map


def polish_chapter(book_dir, chapter, api_key, base_url, model, reasoning_effort):
    """L2 精判单章，产出 chXXX.AI腔体检.md（不改正文）。"""
    ch_dir, files = chapter_files(book_dir)
    target = f"ch{int(chapter):03d}.md"
    if target not in files:
        raise SystemExit(f"找不到 {target}，目录里现有：{', '.join(files)}")
    lines = read_text(os.path.join(ch_dir, target)).splitlines()
    text = clean_text("".join(lines))

    # 复用 L1 逻辑取该章候选（简化：临时跑一次单章扫描）
    all_res, repeat_notes = l1_scan_book(book_dir)
    r = next(x for x in all_res if x["file"] == target)
    # 跨章意象：找出本章相关提示
    _, files2 = chapter_files(book_dir)
    from collections import defaultdict
    img_map = defaultdict(list)
    for fn in files2:
        for ln, line in enumerate(read_text(os.path.join(ch_dir, fn)).splitlines(), 1):
            for iw in IMAGE_WORDS:
                if iw in line:
                    img_map[iw].append((fn, ln))
    repeat_hits = []
    for iw, hits in img_map.items():
        chs = sorted({h[0] for h in hits})
        mine = [h for h in hits if h[0] == target]
        if mine and len(hits) >= 3 and len(chs) >= 2:
            others = "、".join(f"{h[0]}" for h in hits if h[0] != target)
            repeat_hits.append(f"「{iw}」本章 {len(mine)} 处（另见 {others}）")

    print(f"[polish] {target}：L1 命中 hard×{len(r['hard'])} / soft高频×{len(r['soft'])} / "
          f"标点{'超标' if r['dash_flag'] or r['ell_flag'] else '正常'} → 调模型 L2 精判...")
    prompt, hard_idx_map = build_l2_prompt(target, len(text), r["hard"], r["soft"],
                                           r["dash_flag"], r["ell_flag"],
                                           "；".join(repeat_hits) or "无", lines)
    raw = call_llm(api_key, base_url, model, prompt,
                   temperature=0.2, max_tokens=6000,
                   reasoning_effort=reasoning_effort,
                   system_prompt=L2_SYSTEM,
                   usage_meta={"action": "去味精判",
                               "book": os.path.basename(book_dir.rstrip("/\\")),
                               "chapter": int(chapter)})
    try:
        verdicts = json.loads(raw)
    except json.JSONDecodeError:
        # 模型偶尔前后带杂物，试着截出 [] 段
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            raise SystemExit(f"L2 返回不是 JSON：\n{raw[:500]}")
        verdicts = json.loads(m.group(0))

    # 生成机读 diff JSON（只收 hard 级且 verdict=ai 的可自动应用项，供 --apply）
    diffs = []
    for v in verdicts:
        if v.get("verdict") == "ai" and v.get("rewrite") and v.get("idx") in hard_idx_map:
            h = hard_idx_map[v["idx"]]
            diffs.append({
                "idx": v["idx"], "line": h["line"], "orig": h["orig"],
                "rewrite": v["rewrite"], "reason": v.get("reason", ""),
            })
    diff_path = os.path.join(ch_dir, f"{target.replace('.md', '')}.AI腔diff.json")
    if diffs:
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diffs, f, ensure_ascii=False, indent=2)
        print(f"[polish] 可自动应用 {len(diffs)} 处 → {diff_path}")
    else:
        if os.path.exists(diff_path):
            os.remove(diff_path)
        print("[polish] 无 hard 级改写项，未生成 diff JSON")

    # 渲染报告
    out = [f"# {target} · AI 腔体检报告", "",
           f"> 引擎：L1 词表硬筛（hard×{len(r['hard'])} / soft高频×{len(r['soft'])} / "
           f"破折号×{r['dash']} / 省略号×{r['ellipsis']}）→ L2 AI 精判 {len(verdicts)} 条。",
           "> 本报告不改原文。确认后运行 --apply 应用（自动备份原稿；只应用 hard 级自动项）。", ""]
    ai_list, ok_list = [], []
    for v in verdicts:
        if v.get("verdict") == "ai":
            ai_list.append(v)
        else:
            ok_list.append(v)
    out.append(f"## 判定为 AI 腔 · {len(ai_list)} 条（建议改）")
    out.append("")
    if ai_list:
        for v in ai_list:
            out.append(f"**{v.get('idx')}.** {v.get('reason', '')}")
            out.append(f"- 建议：{v.get('rewrite', '')}")
            out.append("")
    else:
        out.append("（无）")
        out.append("")
    out.append(f"## 正常表达（保留）· {len(ok_list)} 条")
    out.append("")
    if ok_list:
        for v in ok_list:
            out.append(f"- {v.get('idx')}. {v.get('reason', '')}")
    else:
        out.append("（无）")
    out.append("")
    if repeat_hits:
        out.append("## 跨章意象提示（L1 给出，供作者斟酌）")
        out.append("")
        for h in repeat_hits:
            out.append(f"- ⚠ {h}")
        out.append("")
    report = "\n".join(out)
    report_path = os.path.join(ch_dir, f"{target.replace('.md', '')}.AI腔体检.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[polish] 报告已落盘 → {report_path}（正文未改动）")
    return report_path


def apply_chapter(book_dir, chapter):
    """按 diff JSON 应用改写：只动 hard 级自动项，替换前自动备份原稿到 .bak.md。"""
    ch_dir, files = chapter_files(book_dir)
    target = f"ch{int(chapter):03d}.md"
    base = target.replace(".md", "")
    diff_path = os.path.join(ch_dir, f"{base}.AI腔diff.json")
    if not os.path.exists(diff_path):
        raise SystemExit(f"找不到 {diff_path}。请先跑 --polish 生成 diff，再 --apply。")
    with open(diff_path, encoding="utf-8") as f:
        diffs = json.load(f)
    if not diffs:
        print("[apply] diff 为空，无需应用")
        return 0

    src_path = os.path.join(ch_dir, target)
    raw = read_text(src_path)
    lines = raw.splitlines(keepends=True)  # 保真换行
    bak_path = os.path.join(ch_dir, f"{base}.bak.md")
    if not os.path.exists(bak_path):
        with open(bak_path, "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"[apply] 原稿已备份 → {bak_path}")

    applied, skipped = [], []
    for d in diffs:
        ln, orig, rewrite = d.get("line"), d.get("orig", ""), d.get("rewrite", "")
        idx = d.get("idx")
        if not orig or not rewrite:
            skipped.append((ln, idx, "orig/rewrite 为空"))
            continue
        if not (0 < ln <= len(lines)):
            skipped.append((ln, idx, "行号越界"))
            continue
        cur = lines[ln - 1]
        if orig not in cur:
            skipped.append((ln, idx, f"正文找不到原文「{orig[:36]}…」"))
            continue
        lines[ln - 1] = cur.replace(orig, rewrite, 1)
        applied.append((ln, idx, orig, rewrite))
    with open(src_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    print(f"[apply] {target}：成功应用 {len(applied)} 处 / 跳过 {len(skipped)} 处")
    for ln, idx, orig, rewrite in applied:
        print(f"  ✅ L{ln} [{idx}] {orig[:32]}… → {rewrite[:32]}…")
    for ln, idx, why in skipped:
        print(f"  ⚠️ 跳过 L{ln} [{idx}]：{why}")
    return 0


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="ai-novel-workbench 去 AI 味引擎：L1 词表硬筛 + L2 AI 精判 + 安全应用")
    ap.add_argument("--scan", metavar="BOOK_DIR", help="全书 L1 体检（不烧 token）")
    ap.add_argument("--polish", metavar="BOOK_DIR", help="单章 L2 精判出报告+diff JSON")
    ap.add_argument("--apply", metavar="BOOK_DIR", help="按 diff JSON 应用改写（自动备份原稿到 .bak.md）")
    ap.add_argument("--chapter", type=int, help="配合 --polish / --apply 指定章节号")
    ap.add_argument("--model", default=None, help="模型名（默认读 .env 或 agnes-2.5-flash）")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--reasoning-effort", default="low")
    args = ap.parse_args()

    if not args.scan and not args.polish and not args.apply:
        ap.print_help()
        return 1

    api_key = env_or("AGNES_API_KEY", "AGNES_API_KEY", "")
    base_url = args.base_url or env_or("AGNES_BASE_URL", "AGNES_BASE_URL", DEFAULT_BASE_URL)
    model = args.model or env_or("AGNES_MODEL", "AGNES_MODEL", DEFAULT_MODEL)

    if args.scan:
        results, repeat_notes = l1_scan_book(args.scan)
        print(render_scan_report(results, repeat_notes, args.scan))
        return 0

    if args.polish:
        if not args.chapter:
            print("--polish 需要 --chapter N")
            return 1
        if not api_key:
            raise SystemExit("缺少 AGNES_API_KEY（.env 里配）")
        polish_chapter(args.polish, args.chapter, api_key, base_url, model,
                       args.reasoning_effort)
        return 0

    if args.apply:
        if not args.chapter:
            print("--apply 需要 --chapter N")
            return 1
        apply_chapter(args.apply, args.chapter)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
