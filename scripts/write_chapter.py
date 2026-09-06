#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-novel-workbench · P0 配方验证脚本（最小可跑版）
===================================================
目的：验证「上下文注入配方」能不能让大模型一章一章连写不崩。
  配方 = 创作宪章 + 全书大纲(本卷) + 活跃角色卡 + 上一章结尾800字 + 剧情记忆
用法：
  1) 设置环境变量 ZHIPU_API_KEY（或首次运行用 --key 传入）
  2) python write_chapter.py --book ../sample_book --chapter 1
     → 读 sample_book 里的 设定.md / 大纲.md / 角色卡.md
       生成第 1 章，落到 books/<书名>/chapters/ch001.md
  3) 连写第 2 章：python write_chapter.py --book ../sample_book --chapter 2
     → 自动带上第 1 章的「结尾 + 记忆」，验证人名/时间线不崩

零第三方依赖（纯标准库 urllib），任何机器装了 Python 3.9+ 就能跑。
OpenAI 兼容协议，改 base_url / model 即可切换任意厂商。
"""

import argparse
import json
import os
import re
import sys
import urllib.request

import chapters  # 章节文件命名/枚举的单一事实源（同目录模块）
import usage_log  # 用量记账常量/流水（R48；同目录模块，脚本与测试均可直接导入）

# ---------------------------------------------------------------------------
# 1. 配置（OpenAI 兼容协议，多后端通用）
#    默认读项目根 .env 里的 AGNES_API_KEY / AGNES_BASE_URL / AGNES_MODEL，
#    也可用环境变量或命令行参数覆盖（--key / --base-url / --model）。
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1/"
DEFAULT_MODEL = "agnes-2.5-flash"
DEFAULT_CHUNK_END = 800   # 上一章结尾保留字数（配方里的"上一章结尾800字"）


def load_dotenv(env_path: str) -> dict:
    """极简 .env 读取：每行 key=value，# 开头为注释。不存在则返回空。"""
    out = {}
    if not os.path.exists(env_path):
        return out
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# 项目根 .env（脚本上一级目录）
_DOT_ENV = load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))


def env_or(key_env: str, key_dotenv: str, default: str) -> str:
    return os.environ.get(key_env) or _DOT_ENV.get(key_dotenv) or default

# 去 AI 腔红线（P1 第二块·预防端）：由 scripts/deai.py 的 L1 词表实证提炼。
# 生成时就遵守，比事后改写省事。要增删红线在此维护。
# 命名说明：内置默认统一用 BUILTIN_ 前缀（server 默认端点取真内置版用），
# 仅作下方 load_rules 的兜底；运行值是加载块里的同名 effective 常量（rules/ 可覆盖）。
BUILTIN_DEAI_RULES ="""去AI腔红线（写作时必须逐条自检，违反即失败）：
1. 副词克制——微微、轻轻、缓缓、默默、淡淡、深深这类万能副词，一章每种至多出现一次；能用具体动作或物件细节替代时就不写副词。
2. 动作去模板——不连发「点了点头」「叹了口气」「皱了皱眉」「若有所思」这类表演式反应；对话要像活人一来一往，别每句都挂一个动作。
3. 禁陈词比喻——不写「夜色如墨」「空气凝固」「时间静止」「心头一紧」等用滥的比喻；同一种意象（雨刷、水雾、风、烟、灯光）一章至多用一次，严禁跨章反复用同一意象收尾。
4. 少虚指——「某种」「一种说不清道不明的」这类模糊指代一章至多一处，优先写具体可感的细节（气味、触感、声响、光线）。
5. 句式自然——少用「不是X而是Y」式排比转折，多用短句直陈。
6. 标点克制——破折号全章不超过10处（含对话内），省略号只在人物语塞、犹豫处使用。
7. 结尾戒套路——不用「夜还很长」「游戏才刚刚开始」这类开放式抒情收尾，用具体动作、画面或一句落地对话收束本章。"""

BUILTIN_SYSTEM_PROMPT = (
    "你是一位资深中文网文作者，擅长都市异能/玄幻/悬疑等类型小说的连载创作。"
    "你负责根据给定设定续写章节正文，只输出小说正文，不要输出任何解释、"
    "章节标题以外的标记或对话。正文用流畅的中文白话，有网文节奏感，"
    "对话要像活人说话。\n\n"
    "【去AI腔红线】\n"
    + BUILTIN_DEAI_RULES
)

# P1 记忆层：滚动状态账本（一本书 = 一本 story_state.md）
# 写完一章 → 模型读"旧账+本章正文"输出新账覆盖 → 续写只注入这一本账
STATE_FILE = "story_state.md"  # 滚动记忆账本，一本书只此一本

# 账本模板（结构固定，小节标题不可改；内容由模型维护、作者可手改）
STATE_TEMPLATE = """# 《{书名}》· 故事状态账本（机器维护，作者可改）
> 本文件是续写章节时的唯一记忆源。每写完一章，AI 会基于"旧账 + 本章正文"重写全账。
> 作者可随时直接修改本文件，AI 续写时必须遵守。

## 当前时间
- 2009-11-17 深夜（案发当晚）

## 计数与资源（每章必须核对更新）
- 陈默·今日回闪已用次数：0 / 3（1天上限3次，超限必须付出代价并提前铺垫）

## 角色状态（只记"本章结束时"相对旧账的新变化；无变化不写）
- （空）

## 关键事件时间线（最近约 10 条，新的在上）
1. （空）

## 伏笔账本（每条：状态[待回收/已回收/失效] · 埋设章节）
- （空）

## 关键物件（外观一经写死严禁漂移）
- （空）

## 情绪弧线（近 3 章的主导情绪与强度，避免章章同调）
- （第N章=主导情绪(强度1-5)）

## 待续状态
- （下一章最该接续的点，一句话）
"""

BUILTIN_STATE_UPDATER_PROMPT = """你是小说故事的"状态账本书记员"，职责是维护一本书的 {STATE_FILE}，让 AI 后续续写不崩。

输入分三块（用分隔线隔开）：
① 账本维护规则（见下）
② 【旧账本】当前 {STATE_FILE} 全文
③ 【本章正文】刚写好的章节正文

你的任务：综合旧账 + 本章正文，输出【完整的新账本全文】（整体覆盖旧账，不是增量补丁）。

账本维护规则（必须全部遵守）：
1. 严格保持固定小节结构，小节标题（## 当前时间 等）一个不能改、不能增删；只允许在小节内部增删条目。
2. ## 当前时间：按本章故事推进更新，只进不退；章节跨越数天就写明到哪一天哪一时段。
3. ## 计数与资源：逐项核对本章使用情况并更新（如"回闪已用次数"）；本章未使用的项保持原值，不许清零。
4. ## 角色状态：记录本章结束时相对旧账的"新变化/新认知/新位置"；无变化的角色不写。旧账中尚未了结的状态要保留（可追加"→已于第X章更新"），不许删除未了结事项。
5. ## 关键事件时间线：把本章关键事件按发生顺序整理，整体保留最近约 10 条；更早的合并压缩成一条"（更早：……）"放在最底。
6. ## 伏笔账本：本章新埋的伏笔加一条"待回收·埋设于第X章"（X=本章章号，必须写明埋设章）；本章被回收/解答的改成"已回收·埋设于第Y章，回收于本章"；其余条目原样保留，不许丢。若某条"待回收"伏笔的埋设章距本章已超过 3 章仍未回收，在该条目末尾追加"⚠超期（已N章未回收，建议尽快安排回收或标失效）"。
7. ## 关键物件：新出现的物件必须登记（含外观、现在归属、所在位置）；旧账里已登记过的物件，外观描述严禁改动（防止道具漂移）。
8. ## 情绪弧线（v0.9.2 新增第 7 节）：记录近 3 章的主导情绪与强度（格式：第N章=主导情绪(强度1-5)），每章滚动更新——保留最近 3 章即可；若连续两章情绪同调，必须在「待续状态」里标记换调节点。
9. 全文用紧凑 Markdown 列表；输出就是新账本全文本身，不要任何前言、后语、代码块围栏。
10. 冲突自检（防幻觉漏记/记错）：若本章正文与旧账存在矛盾——时间倒退、计数不一致、
   角色状态/位置矛盾、物件归属或外观变化——必须在新账对应小节用『⚠冲突：旧账记X，本章写Y（请作者裁决）』
   追加一条，明确标出差异，不许悄悄覆盖、不许假装没看见。无冲突则不写。

【旧账本】
{old_state}

【本章正文】
{chapter_body}"""


def read_text(path: str) -> str:
    """读文件，不存在则返回空串。"""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


# 账本 8 个小节的固定主干（允许模型给括号里的说明换措辞，但主干标题必须齐全）
# 血泪史（CH-26）：ch007 写完后账本被模型输出截断，末行停在"## 关键事件时间线（最近约 10"，
# 缺第 4–7 节还继续用——续写建立在错误前提上。此后每次落盘账本都要过这道校验。
# v0.9.2：第 7 节「情绪弧线」回归（数据事故重建时丢失）。
STATE_SECTIONS = ["## 当前时间", "## 计数与资源", "## 角色状态",
                  "## 关键事件时间线", "## 伏笔账本", "## 关键物件",
                  "## 情绪弧线", "## 待续状态"]


def validate_state(state_text: str) -> list:
    """核对账本 7 小节是否齐全。返回缺失小节的标题清单（空列表 = 结构完整）。"""
    lines = state_text.splitlines()
    return [sec for sec in STATE_SECTIONS
            if not any(ln.strip().startswith(sec) for ln in lines)]


# 章节文件口径统一（2026-09 清扫）：章号解析/章节枚举全部走 chapters.py 单一事实源，
# 这里保留同名 re-export 兼容旧调用方（vector_recall / relation_graph 等仍引用
# write_chapter.chapter_no_of）。CH_RE 3 位起、支持 4+ 位，999 章上限已解除。
chapter_no_of = chapters.chapter_no_of


def clamp_words(w) -> int:
    """R31 字数软控：目标字数夹在 1000–10000，默认 3000。非法输入回落默认。"""
    try:
        w = int(w)
    except (TypeError, ValueError):
        return 3000
    return max(1000, min(10000, w))


def build_context(book_dir: str, chapter_no: int, words: int = 3000) -> str:
    """组装上下文配方：宪章 + 大纲 + 角色 + 滚动账本 + 上一章结尾（+ 作者确认的章纲）。

    记忆来源优先级：chXXX.meta.md（章末回填的结构化摘要） > 旧版文尾注释块。
    上一章结尾始终取最新已写正文的末尾，保证文气衔接。
    words：R31 字数软控目标（1000–10000）。函数内自钳制（防直调方漏钳把
    999/10001/None 原样注入提示词），与 clamp_words 口径一致。"""
    words = clamp_words(words)
    parts = []

    charter = read_text(os.path.join(book_dir, "设定.md"))
    if charter:
        parts.append("【创作宪章·世界观与设定】\n" + charter)

    outline = read_text(os.path.join(book_dir, "大纲.md"))
    if outline:
        parts.append("【全书大纲与分卷细纲】\n" + outline)

    chars = read_text(os.path.join(book_dir, "角色卡.md"))
    if chars:
        parts.append("【活跃角色卡】\n" + chars)

    # 全书记忆：只注入滚动账本 story_state.md（唯一记忆源，上下文不随章数膨胀）
    state = read_text(os.path.join(book_dir, STATE_FILE))
    chapters_dir = chapters.chapter_dir(book_dir)
    prev_tail = ""
    if os.path.isdir(chapters_dir):
        legacy = chapters.list_chapter_files(book_dir)
        # 上一章正文结尾：只取编号【小于本章】的最近章节。
        # （回写重写第 N 章时，N+1 已存在——若取全局最新会拿"未来章"结尾来续写第 N 章，上下文错位）
        prior = [f for f in legacy if chapters.chapter_no_of(f) < chapter_no]
        if prior:
            txt = read_text(os.path.join(chapters_dir, prior[-1]))
            if "<!--MEMORY-->" in txt:
                txt = txt.split("<!--MEMORY-->", 1)[0]
            body = txt.strip()
            prev_tail = body[-DEFAULT_CHUNK_END:] if len(body) > DEFAULT_CHUNK_END else body

    if state:
        parts.append("【全书记忆账本（story_state.md 全文，续写的最高优先级依据，"
                     "其中的事实/计数/伏笔/物件描述不得违背或推翻）】\n" + state)
    else:
        parts.append("【提醒】本故事还没有记忆账本，请先用 --init-state 初始化（或人工创建 story_state.md）。")

    # v0.8 注入点①（R37）：文风指纹——style_learn.py 产出 books/<书>/文风指纹.md。
    # 文件不存在则不注入（零破坏）：没学过文风的书完全不受影响。
    style_fp = read_text(os.path.join(book_dir, "文风指纹.md"))
    if style_fp:
        parts.append("【文风指纹（学自本书成稿的文风画像：模仿其句长节奏、对话密度、"
                     "意象偏好与叙事人称；只学笔法，不复制内容）】\n" + style_fp)

    # v0.8 注入点②（R39 可选向量层）：向量召回缓存——vector_recall.py recall 后
    # 落盘 books/<书>/_recall/chXXX.md；文件不存在则不注入（零破坏，嵌入通道未配置时天然无此文件）。
    recall = read_text(os.path.join(book_dir, "_recall", f"ch{chapter_no:03d}.md"))
    if recall:
        parts.append("【向量召回·相关旧章片段（按语义相似度召回，供呼应旧情节，不是必须全部用到）】\n" + recall)

    # R32 闸口：作者确认过的章纲（--plan 产物），事件/钩子/伏笔操作必须严格遵循
    plan = read_text(os.path.join(chapters_dir, f"ch{chapter_no:03d}.章纲.md"))
    if plan:
        parts.append("【本章章纲（作者已在闸口确认，本章事件顺序/末尾钩子/伏笔操作必须严格遵循）】\n" + plan)

    if prev_tail:
        parts.append(f"【上一章结尾（续写从这里接，不要重复这段内容）】\n{prev_tail}")

    parts.append(
        f"【当前任务】请续写第 {chapter_no} 章正文，{words} 字左右（中文）。"
        f"要求：衔接上一章结尾自然推进；人物名字/身份/称呼与角色卡一致；"
        f"严格遵守上方结构化记忆里已发生的事件与伏笔，不得编造与其矛盾的前情；"
        f"时间线要与记忆中的时间顺延，不可倒退或跳变；本章结尾留一个小钩子。直接输出正文。"
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# R35 伏笔超期扫描：待回收伏笔的埋设章距当前章 > grace 章即告警
# ---------------------------------------------------------------------------
def parse_foreshadows(state_text: str) -> list:
    """解析账本「## 伏笔账本」小节 → [{text, status, planted}]。
    status ∈ 待回收/已回收/失效；planted = 埋设章号（解析不出为 None）。"""
    m = re.search(r"## 伏笔账本[^\n]*\n([\s\S]*?)(?=\n## |\Z)", state_text)
    items = []
    if not m:
        return items
    for ln in m.group(1).splitlines():
        t = ln.strip()
        if not t.startswith("- ") or t == "- （空）":
            continue
        text = t[2:]
        status = "待回收"
        if "已回收" in text:
            status = "已回收"
        elif "失效" in text:
            status = "失效"
        planted = None
        pm = re.search(r"埋设[^0-9]{0,4}第?\s*(\d+)\s*章", text)  # 「埋设于第1章/埋设·第1章」
        if pm:
            planted = int(pm.group(1))
        else:
            cm = re.search(r"第\s*(\d+)\s*章", text)  # 兼容旧格式「[待回收 · 第1章]」
            if cm:
                planted = int(cm.group(1))
        items.append({"text": text, "status": status, "planted": planted})
    return items


def overdue_foreshadows(state_text: str, current_chapter: int, grace: int = 3) -> list:
    """超期未回收伏笔清单：状态=待回收 且 本章号-埋设章 > grace（拍板：超 3 章告警）。"""
    out = []
    for it in parse_foreshadows(state_text):
        if it["status"] == "待回收" and it["planted"] and current_chapter - it["planted"] > grace:
            it["overdue_by"] = current_chapter - it["planted"]
            out.append(it)
    return out


def _post_chat(base_url: str, api_key: str, payload: dict, timeout: int = 240):
    """发一次 chat/completions POST，返回解析后的 JSON。"""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_llm(api_key: str, base_url: str, model: str, user_content: str,
             temperature: float = 0.85, max_tokens: int = 12000,
             reasoning_effort: str = "low", max_retries: int = 2,
             system_prompt: str = None, *,
             fallback_key: str = None, fallback_base_url: str = None,
             fallback_model: str = None, usage_meta: dict = None) -> str:
    """调用 chat completion（OpenAI 兼容），返回正文。
    注：
    - agnes-2.5-flash 带推理，长上下文+长创作下 reasoning 会失控吞光预算，
      必须用 reasoning_effort=low 抑制（实测 12000→419 tokens 思考）。
    - max_tokens 默认 12000，避免正文被截断。
    - 防单点故障：主模型连续失败（网络/限流/空内容）后自动切备用通道；
      备用通道优先级：显式参数 > .env 的 FALLBACK_API_KEY/FALLBACK_BASE_URL/FALLBACK_MODEL。
    - usage_meta={"action","book","chapter"}：传了就顺带记用量流水（R48），失败不影响主流程。
    - system_prompt 缺省在调用时取 load_rules 加载后的 effective SYSTEM_PROMPT
      （rules/system.md 可覆盖），避免函数定义时冻结内置默认。
    对空内容/限流做有限重试，不再静默吞错。"""
    import time

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if reasoning_effort and reasoning_effort != "none":
        payload["reasoning_effort"] = reasoning_effort  # 不支持的网关通常忽略该字段

    def _try_channel(ch_key, ch_url, ch_model, label):
        payload["model"] = ch_model  # 关键：切备用通道时必须把模型名换掉，否则请求体仍带主模型
        last_err = ""
        for attempt in range(max_retries + 1):
            if attempt > 0:
                print(f"  ⚠ {label} 第 {attempt} 次重试（等待 {attempt * 5}s）...", file=sys.stderr)
                time.sleep(attempt * 5)
            try:
                data = _post_chat(ch_url, ch_key, payload)
            except Exception as e:  # 网络/超时/HTTP 错误
                last_err = f"{type(e).__name__}: {e}"
                print(f"  ⚠ {label} 请求异常：{last_err}", file=sys.stderr)
                continue

            choice = data.get("choices", [{}])[0] if data.get("choices") else {}
            content = (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason", "?")
            usage = data.get("usage", {})
            print(
                f"[用量] 输入 {usage.get('prompt_tokens', '?')} / "
                f"输出 {usage.get('completion_tokens', '?')} / "
                f"总 {usage.get('total_tokens', '?')} tokens | finish={finish}",
                file=sys.stderr,
            )
            if usage:
                try:
                    import usage_log
                    m = usage_meta or {}
                    usage_log.log_usage(m.get("action", usage_log.ACTION_WRITE), ch_model,
                                        usage.get("prompt_tokens"),
                                        usage.get("completion_tokens"),
                                        book=m.get("book", ""), chapter=m.get("chapter"))
                except Exception:
                    pass  # 记账失败绝不影响写章主流程（R48 设计约束）
            if content.strip():
                return content.strip()
            last_err = f"空内容（finish_reason={finish}）"
            print(f"  ⚠ {label} 模型返回空：{last_err}", file=sys.stderr)
            if "error" in data:
                print(f"  ⚠ 服务端 error 字段：{data['error']}", file=sys.stderr)
        raise RuntimeError(f"{label}模型调用失败（重试 {max_retries} 次后放弃）：{last_err}")

    try:
        return _try_channel(api_key, base_url, model, "主模型")
    except RuntimeError:
        fb_key = fallback_key or env_or("FALLBACK_API_KEY", "FALLBACK_API_KEY", "")
        fb_model = fallback_model or env_or("FALLBACK_MODEL", "FALLBACK_MODEL", "")
        if not (fb_key and fb_model):
            raise
        fb_url = fallback_base_url or env_or("FALLBACK_BASE_URL", "FALLBACK_BASE_URL", base_url)
        print(f"⚠ 主模型 {model} 失败，切换备用模型 {fb_model}（{fb_url}）...", file=sys.stderr)
        return _try_channel(fb_key, fb_url, fb_model, "备用模型")


def snapshot_state(book_dir: str, chapter: int, state_text: str) -> str:
    """R47 章快照：账本更新成功后，把当时这份账本复印一份存到底账目录。
    _snapshots/chXXX.state.md —— 永不清理（拍板 Q16）；「从第 N 章重算」（R49，v0.3）拿它当起点。
    快照失败只警告不阻断主流程（账本本身已写盘，快照是加分项）。"""
    try:
        snap_dir = os.path.join(book_dir, "_snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        out = os.path.join(snap_dir, f"ch{chapter:03d}.state.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(state_text)
        print(f"     快照已存 → {out}")
        return out
    except OSError as e:
        print(f"⚠ 快照写入失败（不影响账本）：{e}", file=sys.stderr)
        return ""


def update_state(api_key: str, base_url: str, model: str, body: str,
                 old_state: str, reasoning_effort: str = "low",
                 usage_meta: dict = None) -> str:
    """滚动账本更新：模型读"旧账 + 本章正文"输出完整新账（覆盖式重写）。
    P1 记忆中枢核心：计数核对（回闪次数）、时间推进、伏笔状态、物件防漂移都靠它。
    注（ch4 实测修复）：正文过长会把请求输入顶过 ~5k tokens，触发 agnes-2.5-flash
    的 reasoning 失控（连 max_tokens 都被思考吞光、返回空），故对正文做首尾截短，
    并把 max_tokens 提到 12000 给足输出空间。账本更新只需"本章事实增量"，首尾足够。"""
    if len(body) > 3200:  # 只喂首尾，避免输入超阈值触发推理失控
        body = body[:1400] + "\n\n……（正文中段已省略，如中间有必须入账的事实请结合旧账推断标注）……\n\n" + body[-1400:]
    # 用 replace 而非 format：正文/账本可能含花括号，.format() 会抛 ValueError/KeyError
    prompt = (STATE_UPDATER_PROMPT
              .replace("{STATE_FILE}", STATE_FILE)
              .replace("{old_state}", old_state or "（尚无账本）")
              .replace("{chapter_body}", body))
    return call_llm(
        api_key, base_url, model, prompt,
        temperature=0.2, max_tokens=12000, reasoning_effort=reasoning_effort,
        system_prompt="你是严谨的故事状态账本维护程序，严格按用户给出的模板结构与规则输出完整账本全文，不要输出正文以外的东西。",
        max_retries=3,
        usage_meta=usage_meta,
    )


def init_state(api_key: str, base_url: str, model: str, book_dir: str,
               book_name: str, reasoning_effort: str = "low") -> str:
    """首次建账：根据设定/角色卡/大纲，按模板生成初始 story_state.md。"""
    settings = "\n\n".join(
        read_text(os.path.join(book_dir, f)) for f in ("设定.md", "角色卡.md", "大纲.md")
    )
    prompt = (
        "你是小说故事的状态账本书记员。一本新书刚完成设定，请为它建立初始的 "
        f"{STATE_FILE} 账本。\n"
        "输入：① 账本模板 ② 设定资料（创作宪章/角色卡/大纲）。\n"
        "任务：输出完整的初始账本全文——严格沿用模板的小节与标题，把设定资料里能确定的事实"
        "填进对应小节：当前时间=故事起点时间；计数与资源=设定中的硬限制（如一天限用三次之类）；"
        "关键物件=大纲或设定已点名的重要道具（含外观描述）；其余资料未涉及的小节保留空条目原样。"
        "严禁编造资料里没有的事实。全文就是账本本身，不要前言后语或代码块围栏。\n"
        f"【账本模板】\n{STATE_TEMPLATE.replace('{书名}', book_name)}\n"
        f"【设定资料】\n{settings}"
    )
    return call_llm(
        api_key, base_url, model, prompt,
        temperature=0.2, max_tokens=4000, reasoning_effort=reasoning_effort,
        system_prompt="你是严谨的故事状态账本初始化程序。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_LEDGER_INIT, "book": book_name},
    )


BUILTIN_AUDIT_PROMPT = """你是小说故事的一致性审计员。对照【旧账本】与【本章正文】（正文过长已截取首尾），
逐条找出并列出：
1. 冲突：正文与账本矛盾——时间倒退或跳跃异常、计数（如回闪次数/资源）对不上、
   角色状态或所在位置矛盾、物件归属/外观与账本冲突、已回收的伏笔又被当未解使用；
2. 漏记：本章发生了明显应入账的事实（新角色出场、新物件、重要决定、新伏笔）但账本没有；
3. 存疑：你拿不准但作者应该看一眼的地方；
4. 伏笔超期：账本中"待回收"伏笔若埋设章距本章已超过 3 章仍未回收，单独列出并给出处理建议（尽快回收/标失效）。
每条给出：位置（正文第几段附近 / 账本哪一小节）+ 问题描述 + 建议改法。
若确实没问题，就输出「未发现冲突/漏记」。只输出审计清单本身，不要客套话。"""


def audit_chapter(api_key: str, base_url: str, model: str, book_dir: str,
                  chapter: int, reasoning_effort: str = "low",
                  report_suffix: str = "") -> str:
    """一致性审计：对照账本检查单章正文的冲突/漏记。
    只读审计，不改账本与正文；报告落盘 chapters/chXXX.一致性审计<report_suffix>.md。
    report_suffix：报告文件名后缀（R42 交叉审计传 "-交叉"，与主通道审计报告分离共存）。"""
    state_path = os.path.join(book_dir, STATE_FILE)
    out_dir = os.path.join(book_dir, "chapters")
    src = os.path.join(out_dir, f"ch{chapter:03d}.md")
    old_state = read_text(state_path)
    body = read_text(src)
    if not old_state:
        raise SystemExit(f"缺 {STATE_FILE}，无法审计（先 --init-state 或写一章）")
    if not body:
        raise SystemExit(f"缺章节正文：{src}")
    # 输入瘦身，防输入 >5k tokens 触发 agnes 推理失控：
    #  ① 账本剥掉"伏笔账本"整节（伏笔状态流转已由账本更新器的规则9自查，此处聚焦时间/计数/角色/物件冲突）
    #  ② 正文同 update_state 截首尾
    old_state_core = re.sub(r"## 伏笔账本.*?(?=\n## |\Z)", "", old_state, flags=re.S).strip()
    if not old_state_core:
        old_state_core = old_state
    if len(body) > 3200:
        body = body[:1400] + "\n\n……（正文中段已省略）……\n\n" + body[-1400:]
    prompt = f"{AUDIT_PROMPT}\n\n【旧账本】\n{old_state_core}\n\n【本章正文（截取版）】\n{body}"
    print(f"[audit] ch{chapter:03d}：对照账本检查正文冲突/漏记...")
    report = call_llm(
        api_key, base_url, model, prompt,
        temperature=0.1, max_tokens=12000, reasoning_effort=reasoning_effort,
        system_prompt="你是严谨的小说一致性审计员，只输出审计清单。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_AUDIT, "book": os.path.basename(book_dir.rstrip("/\\")),
                    "chapter": chapter},
    ).strip()
    out = os.path.join(out_dir, f"ch{chapter:03d}.一致性审计{report_suffix}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[audit] 审计报告已落盘 → {out}（未改动账本与正文）")
    return out


# ── v0.9.2 插件提示词链 + 6 维评分（数据事故重建回补，蒸馏自 novel-evaluator）──
def plugin_prompt(name: str, builtin: str):
    """插件提示词链：插件启用且 prompts/judge.md 存在 → 用插件的；
    插件存在但已停用 → 返回 None（调用方拒绝执行，停用即生效）；
    无此插件 → 用内置兜底。坏 manifest 由 loader 容错跳过。"""
    try:
        import plugin_loader
    except ImportError:
        return builtin
    for p in plugin_loader.scan_plugins():
        if p["name"] == name or p["dir"] == name:
            if not p["enabled"]:
                return None
            jp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "plugins", p["dir"], "prompts", "judge.md")
            return read_text(jp) or builtin
    return builtin


BUILTIN_SCORE_PROMPT = """你是网文质量评审。对以下章节正文做六维评分（各 0-100 分）并给出总分与一句话总评：
情节（推进力与逻辑）、人物（动机与成长）、文笔（流畅度与画面感）、世界观（一致性）、情感（代入感）、创新（新鲜度）。
输出 JSON：{"scores":{"情节":0,"人物":0,"文笔":0,"世界观":0,"情感":0,"创新":0},"total":0,"comment":"一句话总评","issues":["具体问题"]}
只输出 JSON 本身。

【章节正文】
{chapter_body}"""


def score_chapter(api_key: str, base_url: str, model: str, book_dir: str,
                  chapter: int, reasoning_effort: str = "low") -> str:
    """6 维评分（情节/人物/文笔/世界观/情感/创新）：提示词走插件链，报告落盘 chXXX.评分.md。"""
    src = os.path.join(book_dir, "chapters", f"ch{chapter:03d}.md")
    body = read_text(src)
    if not body:
        raise SystemExit(f"缺章节正文：{src}")
    prompt_tmpl = plugin_prompt("evaluate", BUILTIN_SCORE_PROMPT)
    if prompt_tmpl is None:
        print("[score] 插件 evaluate 已停用，评分拒绝执行（在技能中心或 plugin.json 重新启用）。", file=sys.stderr)
        return ""
    if "{chapter_body}" not in prompt_tmpl:
        prompt_tmpl = prompt_tmpl.rstrip() + "\n\n【章节正文】\n{chapter_body}"
    if len(body) > 3200:
        body = body[:1400] + "\n\n……（正文中段已省略，评分以首尾为准）……\n\n" + body[-1400:]
    prompt = prompt_tmpl.replace("{chapter_body}", body)
    print(f"[score] ch{chapter:03d}：6 维评分中（提示词来源：插件链）...")
    report = call_llm(
        api_key, base_url, model, prompt,
        temperature=0.2, max_tokens=2000, reasoning_effort=reasoning_effort,
        system_prompt="你是专业小说评分员，只输出 JSON。",
        max_retries=3,
        usage_meta={"action": "评分", "book": os.path.basename(book_dir.rstrip("/\\")),
                    "chapter": chapter},
    ).strip()
    out = os.path.join(book_dir, "chapters", f"ch{chapter:03d}.评分.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[score] 评分已落盘 → {out}")
    return out


BUILTIN_PLAN_PROMPT = """【本次任务调整】先不要写正文全文。请作为策划输出：
1) 本章章纲：本章目标 / 关键事件 / 末尾钩子 / 伏笔操作（本章埋设/推进/回收哪条，引用账本中的伏笔）
2) 开头 200 字试写（定风格用）
只输出这两部分，不要输出正文全文。"""

# ── R32⑥ 规则外置：rules/*.md 存在即覆盖内置默认（改规则不改代码）──────────
RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "rules")


def load_rules(name: str, default: str) -> str:
    """读 rules/<name>；不存在/为空/读失败 → 用内置默认。"""
    try:
        p = os.path.normpath(os.path.join(RULES_DIR, name))
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                s = f.read().strip()
            if s:
                return s
    except Exception as e:  # 规则读不进去绝不能挡写作
        print(f"⚠ rules/{name} 读取失败，用内置默认：{e}", file=sys.stderr)
    return default


DEAI_RULES = load_rules("deai_rules.md", BUILTIN_DEAI_RULES)
SYSTEM_PROMPT = load_rules("system.md", BUILTIN_SYSTEM_PROMPT)
STATE_UPDATER_PROMPT = load_rules("state_updater.md", BUILTIN_STATE_UPDATER_PROMPT)
AUDIT_PROMPT = load_rules("audit.md", BUILTIN_AUDIT_PROMPT)
PLAN_PROMPT = load_rules("plan.md", BUILTIN_PLAN_PROMPT)


def plan_chapter(api_key: str, base_url: str, model: str, book_dir: str,
                 chapter: int, words: int = 3000, reasoning_effort: str = "low") -> str:
    """R32 闸口前半：按配方出「章纲 + 200 字试写」，落盘 chapters/chXXX.章纲.md。
    只落盘章纲不改正文；作者可在闸口修改，写章时 build_context 自动注入并强制遵循。"""
    context = build_context(book_dir, chapter, words=words)
    print(f"[plan] ch{chapter:03d}：按配方出章纲+试写（目标 {words} 字）...")
    text = call_llm(
        api_key, base_url, model, context + "\n\n" + PLAN_PROMPT,
        temperature=0.4, max_tokens=4000, reasoning_effort=reasoning_effort,
        system_prompt="你是中文网文资深策划，基于资料输出章纲与试写，简洁、可执行。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_OUTLINE, "book": os.path.basename(book_dir.rstrip("/\\")),
                    "chapter": chapter},
    ).strip()
    out = os.path.join(book_dir, "chapters", f"ch{chapter:03d}.章纲.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)  # 新书可能还没有 chapters/
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[plan] 章纲已落盘 → {out}（人工修改后写章自动遵循）")
    return out


def adjust_chapter(api_key: str, base_url: str, model: str, book_dir: str,
                   chapter: int, target: int, mode: str, reasoning_effort: str = "low") -> int:
    """R31 字数软控后半：一键加长/精简。先备份（.bak.md 仅首版规则同 deai），再按目标字数改写正文。"""
    src = os.path.join(book_dir, "chapters", f"ch{chapter:03d}.md")
    body = read_text(src)
    if not body:
        raise SystemExit(f"缺章节正文：{src}")
    if mode == "expand":
        task = (f"在不改变既有情节、人物、事实与伏笔的前提下，把下面这章正文扩写到约 {target} 字"
                f"（可增加场景细节、对话与心理描写，不得注水重复）。直接输出改写后的完整正文。")
    else:
        task = (f"在不丢失主线事件、关键对话与账本事实的前提下，把下面这章正文精简到约 {target} 字。"
                f"直接输出改写后的完整正文。")
    print(f"[adjust] ch{chapter:03d}：{mode} 到约 {target} 字（现 {len(body)} 字）...")
    new_body = call_llm(
        api_key, base_url, model, task + "\n\n【本章正文】\n" + body,
        temperature=0.5, max_tokens=12000, reasoning_effort=reasoning_effort,
        system_prompt="你是资深中文网文作者，只输出改写后的正文本身。",
        max_retries=2,
        usage_meta={"action": usage_log.ACTION_ADJUST_WORDS, "book": os.path.basename(book_dir.rstrip("/\\")),
                    "chapter": chapter},
    ).strip()
    bak = os.path.join(book_dir, "chapters", f"ch{chapter:03d}.bak.md")
    bak_existed = os.path.exists(bak)
    if not bak_existed:
        with open(bak, "w", encoding="utf-8") as f:
            f.write(body)
    with open(src, "w", encoding="utf-8") as f:
        f.write(new_body)
    print(f"[adjust] 完成 → {src}（{len(new_body)} 字；原稿备份：{'已有未覆盖' if bak_existed else bak}）")
    if abs(len(new_body) - target) / target > 0.30:
        print(f"⚠ 调整后 {len(new_body)} 字仍超出目标 ±30%，可再跑一次 --adjust。", file=sys.stderr)
    return len(new_body)


# ---------------------------------------------------------------------------
# v0.8 / v0.9 功能扩展（R36 拆书 / R37 学文风 / R39 向量注入 / R41 平台自检 /
# R42 交叉审计 / R43 读者反馈 / R45 账本体量 / R46 证据包 / R49 账本重算）
# ---------------------------------------------------------------------------

def sample_chapters(book_dir, n=3, frag=600):
    """R37 采集最近 n 章的片段（每章首尾各 frag 字）供学文风。返回 [{"file","text"}]。零 token。"""
    files = chapters.list_chapter_files(book_dir)[-int(n):]
    if not files:
        return []
    ch_dir = chapters.chapter_dir(book_dir)
    out = []
    for fn in files:
        body = read_text(os.path.join(ch_dir, fn))
        if "<!--MEMORY-->" in body:
            body = body.split("<!--MEMORY-->", 1)[0]
        body = body.strip()
        if not body:
            continue
        sample = body if len(body) <= frag * 2 else body[:frag] + "\n……\n" + body[-frag:]
        out.append({"file": fn, "text": sample})
    return out


_PLACEHOLDER_MARKERS = ("（待填写）", "待补充", "待填写", "TODO", "占位", "示例文本",
                        "{书名}", "{{", "此处输入", "在这里写下", "一句话简介")


def is_placeholder_doc(text) -> bool:
    """检测三件套等文档是否为占位/模板文档：空、过短、或含模板占位标记。
    用于写章前提醒（占位设定会让模型把模板文字当事实写进正文）。"""
    if not text or not text.strip():
        return True
    t = text.strip()
    if len(t) < 20:
        return True
    return any(m in t for m in _PLACEHOLDER_MARKERS)


def write_with_backup(book_dir, run_fn, *args, **kwargs):
    """写章前自动全书备份（--auto-backup 语义封装）：先备份整本书再执行 run_fn。
    返回 (备份zip路径, run_fn 结果)；备份失败只警告不阻断写章。"""
    bak = ""
    try:
        import backup_book
        bak = backup_book.backup_book(book_dir)
    except Exception as e:  # 备份失败绝不挡写作
        print(f"⚠ 写前备份失败（继续写章）：{e}", file=sys.stderr)
    return bak, run_fn(*args, **kwargs)


BUILTIN_DECONSTRUCT_RULES = (
    "按七维拆解：① 文风指纹 ② 情节结构 ③ 人物塑造 ④ 独特性 ⑤ 情绪曲线 "
    "⑥ 热梗与时代感 ⑦ 章节钩子设计。每维给结论与原文证据。")


def deconstruct_book(api_key, base_url, model, book_dir, reasoning_effort="low"):
    """R36 拆书：按 rules/deconstruct.md 七维规则拆解一本书，产出 _research/拆书报告.md。
    免章号动作（v0.8 修复：此前 --deconstruct 被夹在 --chapter 必填检查之后不可达）。"""
    rules = load_rules("deconstruct.md", BUILTIN_DECONSTRUCT_RULES)
    materials = []
    for fn in ("设定.md", "角色卡.md", "大纲.md"):
        t = read_text(os.path.join(book_dir, fn))
        if t:
            materials.append(f"【{fn}】\n{t[:2000]}")
    ch_dir = chapters.chapter_dir(book_dir)
    files = chapters.list_chapter_files(book_dir)[:3]  # 只喂前 3 章节选，防输入顶爆推理
    for fn in files:
        materials.append(f"【正文节选 {fn}】\n{read_text(os.path.join(ch_dir, fn))[:2500]}")
    if not materials:
        raise SystemExit(f"书目录里没有可拆的材料（三件套与 chapters/ 均为空）：{book_dir}")
    prompt = ("请按下方拆书规则对这本书做完整拆解，输出结构化拆书报告"
              "（Markdown；七维逐项给结论，证据引章节号或出处文件）。\n\n"
              f"【拆书规则】\n{rules}\n\n【拆解对象材料】\n" + "\n\n".join(materials))
    print(f"[deconstruct] 拆解《{os.path.basename(book_dir.rstrip('/\\'))}》（材料 {len(materials)} 块）...")
    report = call_llm(
        api_key, base_url, model, prompt,
        temperature=0.3, max_tokens=12000, reasoning_effort=reasoning_effort,
        system_prompt="你是资深网文拆书编辑，按规则输出拆书报告本身，不要客套话。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_DISSECT, "book": os.path.basename(book_dir.rstrip("/\\"))},
    )
    out_dir = os.path.join(book_dir, "_research")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "拆书报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report.strip())
    print(f"[deconstruct] 拆书报告已落盘 → {out}")
    return out


TRILOGY_PROMPT = """基于上面的拆书报告，为同一世界观规划一部三部曲蓝图。输出 Markdown：
1. 三部曲总名与一句话总纲；
2. 每一部：书名 / 主线一句话 / 核心冲突 / 主角弧光 / 结尾钩子（如何钩住下一部）；
3. 跨三部曲的总伏笔网（哪一部埋、哪一部收）；
4. 沿用拆书报告总结的文风要点。
只输出蓝图本身。"""


def blueprint_from_report(api_key, base_url, model, report_path, out_path=None,
                          reasoning_effort="low"):
    """读拆书报告 → LLM 生成三部曲蓝图 → 落盘蓝图文件（默认与报告同目录），返回蓝图路径。"""
    report = read_text(report_path)
    if not report:
        raise SystemExit(f"拆书报告为空或不存在：{report_path}")
    print(f"[blueprint] 读拆书报告 → 生成三部曲蓝图...")
    blueprint = call_llm(
        api_key, base_url, model, report + "\n\n" + TRILOGY_PROMPT,
        temperature=0.5, max_tokens=12000, reasoning_effort=reasoning_effort,
        system_prompt="你是网文总策划，只输出三部曲蓝图本身。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_BLUEPRINT, "book": os.path.basename(report_path)},
    )
    if out_path is None:
        out_path = os.path.join(os.path.dirname(os.path.abspath(report_path)), "三部曲蓝图.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(blueprint.strip())
    print(f"[blueprint] 蓝图已落盘 → {out_path}")
    return out_path


def gen_trilogy(api_key, base_url, model, book_dir, reasoning_effort="low"):
    """从书的 _research/拆书报告.md 生成三部曲蓝图（blueprint_from_report 的定位封装）。"""
    report_path = os.path.join(book_dir, "_research", "拆书报告.md")
    if not os.path.exists(report_path):
        raise SystemExit(f"缺拆书报告：{report_path}（先跑 --deconstruct）")
    return blueprint_from_report(api_key, base_url, model, report_path,
                                 reasoning_effort=reasoning_effort)


# ── R41 零 token 脱敏扫描：人名/地名/品牌词频+定位（输出报告，不改正文）──────
PRIVACY_BRANDS = ["微信", "支付宝", "腾讯", "阿里", "百度", "抖音", "快手", "微博",
                  "淘宝", "京东", "苹果", "华为", "小米", "特斯拉", "奔驰", "宝马",
                  "可口可乐", "星巴克", "耐克", "阿迪达斯"]


def collect_privacy_terms(book_dir):
    """零 token 收集脱敏候选词：角色卡里的人名、设定/大纲里标注的地名、内置品牌词表。
    返回 [{"term","type","count","locations"}]（count/locations 由调用方统计填充）。"""
    raw = []
    for ln in read_text(os.path.join(book_dir, "角色卡.md")).splitlines():
        m = re.match(r"^\s*[^：:]{1,6}[：:]\s*([\u4e00-\u9fa5A-Za-z0-9·]{2,6})", ln)
        if m and m.group(1) not in ("无", "空"):
            raw.append((m.group(1), "人名"))
    for fn in ("设定.md", "大纲.md"):
        for ln in read_text(os.path.join(book_dir, fn)).splitlines():
            m = re.search(r"(?:地名|城市|地点|场景)[：:]\s*([\u4e00-\u9fa5A-Za-z0-9]{2,8})", ln)
            if m:
                raw.append((m.group(1), "地名"))
    raw.extend((b, "品牌") for b in PRIVACY_BRANDS)
    seen, out = set(), []
    for term, ty in raw:
        if term not in seen:
            seen.add(term)
            out.append({"term": term, "type": ty, "count": 0, "locations": []})
    return out


def privacy_scan(book_dir):
    """零 token 版权脱敏扫描：人名/地名/品牌词频+定位，报告落盘 books/<书>/隐私脱敏扫描.md。
    只输出报告，绝不改正文。返回 report dict。"""
    terms = collect_privacy_terms(book_dir)
    ch_dir = chapters.chapter_dir(book_dir)
    files = chapters.list_chapter_files(book_dir)
    for item in terms:
        for fn in files:
            lines = read_text(os.path.join(ch_dir, fn)).splitlines()
            for ln_no, line in enumerate(lines, 1):
                c = line.count(item["term"])
                if c:
                    item["count"] += c
                    if len(item["locations"]) < 5:
                        item["locations"].append(f"{fn} L{ln_no}")
    hits = [t for t in terms if t["count"]]
    print(f"[privacy] 脱敏扫描：候选词 {len(terms)} 个，命中 {len(hits)} 个（{len(files)} 章）")
    for t in hits:
        print(f"  ⚠ [{t['type']}]「{t['term']}」×{t['count']}（{('、'.join(t['locations']))}）")
    out = os.path.join(book_dir, "隐私脱敏扫描.md")
    lines = [f"# 版权脱敏扫描报告（零 token，只读不改稿）", "",
             f"- 扫描章节：{len(files)} 章；候选词 {len(terms)} 个，命中 {len(hits)} 个", ""]
    if hits:
        lines.append("| 词 | 类型 | 次数 | 定位 |")
        lines.append("|---|---|---|---|")
        for t in hits:
            lines.append(f"| {t['term']} | {t['type']} | {t['count']} | {('、'.join(t['locations']))} |")
    else:
        lines.append("（未命中任何候选词）")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[privacy] 报告已落盘 → {out}")
    return {"terms": terms, "chapters": len(files), "report_path": out}


# ── R49 账本重算 ──────────────────────────────────────────────────────────────
def extract_conflicts(state_text):
    """提取账本中的『⚠冲突』条目（账本更新器规则 9 写入）。
    R49 重算报告与 R41 平台自检的冲突来源。"""
    return [ln.strip() for ln in (state_text or "").splitlines() if "⚠冲突" in ln]


def recalc_from(book_dir, start_chapter, update_fn):
    """R49 从 chNNN 快照起逐章重算账本：以快照为起点，逐章用 update_fn(body, old_state)
    推进并覆盖 story_state.md（含快照同步），产出重算报告（逐章结果 + 冲突列表）。
    update_fn 由调用方注入（CLI 接 update_state；测试注入假函数实现零网络）。
    账本结构校验（防坏账进快照链）：起点快照不合格 → 打印冲突清单并中止（不写任何快照）；
    每章重算产物不合格 → 同样中止，报告标注中断章。
    返回 report dict（中断时含 "interrupted" 章号），并落盘 chapters/账本重算报告.md。"""
    start = int(start_chapter)
    snap = read_text(os.path.join(book_dir, "_snapshots", f"ch{start:03d}.state.md"))
    if not snap:
        raise SystemExit(f"找不到快照 _snapshots/ch{start:03d}.state.md"
                         f"——R49 以章快照为重算起点（写章/--state-only 时自动生成）。")
    ch_dir = os.path.join(book_dir, "chapters")
    if not os.path.isdir(ch_dir):
        raise SystemExit(f"书目录里没有 chapters/：{book_dir}")
    nums = sorted(chapters.chapter_no_of(f) for f in os.listdir(ch_dir)
                  if chapters.CH_RE.match(f))
    todo = [n for n in nums if n >= start]
    if not todo:
        raise SystemExit(f"第 {start} 章及之后没有正文可重算。")
    miss = validate_state(snap)
    if miss:
        print(f"[recalc] 起点快照 ch{start:03d}.state.md 结构校验未通过：缺少小节 {miss}",
              file=sys.stderr)
        for c in extract_conflicts(snap):
            print(f"  ⚠ {c}", file=sys.stderr)
        raise SystemExit("[recalc] 起点账本不合格，中止重算（未写任何快照）。"
                         "请人工修复快照或 story_state.md 后再重算。")
    print(f"[recalc] 从 ch{start:03d} 快照起重算 {len(todo)} 章（ch{todo[0]:03d}~ch{todo[-1]:03d}）...")
    state = snap
    rows, total_conf = [], 0
    interrupted = None
    for n in todo:
        body = read_text(os.path.join(ch_dir, f"ch{n:03d}.md"))
        if "<!--MEMORY-->" in body:
            body = body.split("<!--MEMORY-->", 1)[0]
        new_state = update_fn(body, state)
        confs = extract_conflicts(new_state)
        miss = validate_state(new_state)
        if miss:
            interrupted = n
            print(f"  ✗ ch{n:03d} 重算产物结构校验未通过：缺少小节 {miss}，中止重算"
                  f"（保留上一章的账本与快照）。", file=sys.stderr)
            rows.append({"chapter": n, "chars": len(body.strip()),
                         "state_chars": len(new_state), "conflicts": confs,
                         "interrupted": True, "missing": miss})
            break
        total_conf += len(confs)
        rows.append({"chapter": n, "chars": len(body.strip()),
                     "state_chars": len(new_state), "conflicts": confs})
        state = new_state
        with open(os.path.join(book_dir, STATE_FILE), "w", encoding="utf-8") as f:
            f.write(state)
        snapshot_state(book_dir, n, state)
        print(f"  ✓ ch{n:03d} 重算完成（冲突 {len(confs)} 条）")
    recalced = sum(1 for r in rows if not r.get("interrupted"))
    report = {"start": start, "recalced": recalced, "total_conflicts": total_conf,
              "chapters": rows}
    if interrupted is not None:
        report["interrupted"] = interrupted
    lines = [f"# 账本重算报告（R49：从 ch{start:03d} 快照起重算 {recalced} 章）", ""]
    if interrupted is not None:
        lines.append(f"- ⚠ 中断于 ch{interrupted:03d}：该章重算产物结构校验未通过，"
                     f"其后章节未重算（账本/快照停留在上一合格章）")
    lines += [f"- 冲突总数：{total_conf}（>0 时请逐条人工裁决后重跑）", ""]
    for r in rows:
        mark = "（⚠ 中断章：产物不合格，未落盘）" if r.get("interrupted") else ""
        lines.append(f"## ch{r['chapter']:03d}{mark}")
        lines.append(f"- 正文 {r['chars']} 字 → 新账本 {r['state_chars']} 字；冲突 {len(r['conflicts'])} 条")
        if r.get("missing"):
            lines.append(f"- 缺少小节：{r['missing']}")
        lines.extend(f"  - {c}" for c in r["conflicts"])
        lines.append("")
    out = os.path.join(ch_dir, "账本重算报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[recalc] 完成：{recalced} 章 / 冲突 {total_conf} 条 → {out}"
          + (f"（中断于 ch{interrupted:03d}）" if interrupted is not None else ""))
    return report


# ── R45 账本体量警告 ─────────────────────────────────────────────────────────
STATE_WARN_CHARS = 6000


def state_size_warning(state_text, limit=STATE_WARN_CHARS):
    """R45 账本体量警告：story_state.md 超过 limit 字时返回 ⚠ 提示文案，否则空串。
    只提醒不阻断（写章与 --state-only 都调用）。"""
    n = len(state_text or "")
    if n > limit:
        return (f"⚠ 账本体量警告：story_state.md 已 {n} 字（阈值 {limit}），"
                f"过长会稀释模型注意力——建议人工精并历史条目或启用账本分段摘要。")
    return ""


# ── R41 平台自检 / R46 证据包 ────────────────────────────────────────────────
def platform_check(book_dir, chapter, write_report=True):
    """R41 零 token 平台自检：盘点账本冲突 / 伏笔未回收 / 体检单缺失 / 文件完整性，
    输出红灯清单 + 痕迹统计（L1 口径唯一来源 = deai.l1_scan_book）。
    返回 report dict；write_report=True 时落盘 chapters/chXXX.平台自检.md。"""
    ch = int(chapter)
    red, warn = [], []
    state = read_text(os.path.join(book_dir, STATE_FILE))
    if not state:
        red.append("缺记忆账本 story_state.md")
    else:
        confs = extract_conflicts(state)
        if confs:
            red.append(f"账本遗留未裁决冲突 {len(confs)} 条（搜「⚠冲突」逐条处理）")
        pending = [it for it in parse_foreshadows(state) if it["status"] == "待回收"]
        if pending:
            warn.append(f"伏笔未回收 {len(pending)} 条")
        for it in overdue_foreshadows(state, ch):
            red.append(f"伏笔超期：{it['text'][:40]}（埋设于第{it['planted']}章）")
    ch_dir = os.path.join(book_dir, "chapters")
    for suffix, label in (("AI腔体检.md", "AI 腔体检单"), ("一致性审计.md", "一致性审计报告")):
        if not os.path.exists(os.path.join(ch_dir, f"ch{ch:03d}.{suffix}")):
            warn.append(f"ch{ch:03d} 缺{label}（用 checkup --chapter {ch} 补齐）")
    files = chapters.list_chapter_files(book_dir)
    if files:
        have = {chapters.chapter_no_of(f) for f in files}
        for n in range(1, max(have) + 1):
            if n not in have:
                red.append(f"章节断号：缺 ch{n:03d}.md")
        for f in files:
            if os.path.getsize(os.path.join(ch_dir, f)) == 0:
                red.append(f"章节正文为空：{f}")
    # 痕迹统计：复用 deai 唯一 L1 实现（懒导入，保持本模块轻量）
    import deai as _deai
    results, _rn = _deai.l1_scan_book(book_dir)
    stats = {"chapters": len(results),
             "hard_hits": sum(len(r["hard"]) for r in results),
             "dash": sum(r["dash"] for r in results),
             "ellipsis": sum(r["ellipsis"] for r in results)}
    if stats["hard_hits"]:
        warn.append(f"全书 AI 腔硬伤 {stats['hard_hits']} 处（deai --scan 看定位）")
    report = {"chapter": ch, "red": red, "warn": warn, "stats": stats}
    print(f"[platform-check] ch{ch:03d} 自检：红灯 {len(red)} / 黄灯 {len(warn)}")
    for x in red:
        print(f"  🔴 {x}")
    for x in warn:
        print(f"  🟡 {x}")
    print(f"  痕迹统计：{stats['chapters']} 章 / hard×{stats['hard_hits']} / "
          f"破折号×{stats['dash']} / 省略号×{stats['ellipsis']}")
    if write_report:
        red_lines = [f"- 🔴 {x}" for x in red] or ["- （无）"]
        warn_lines = [f"- 🟡 {x}" for x in warn] or ["- （无）"]
        lines = [f"# ch{ch:03d} · 平台自检报告（R41，零 token）", "",
                 f"## 红灯清单（{len(red)}）", *red_lines, "",
                 f"## 黄灯提醒（{len(warn)}）", *warn_lines, "",
                 "## 痕迹统计",
                 f"- 章 {stats['chapters']} · hard {stats['hard_hits']} · "
                 f"破折号 {stats['dash']} · 省略号 {stats['ellipsis']}"]
        os.makedirs(ch_dir, exist_ok=True)
        out = os.path.join(ch_dir, f"ch{ch:03d}.平台自检.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        report["report_path"] = out
        print(f"[platform-check] 报告已落盘 → {out}")
    return report


def export_evidence(book_dir, chapter, out_dir=None):
    """R46 自证证据包：账本+快照+体检单+审计报告+平台自检（含交叉审计）打包 zip
    到项目根 backups/。零 token；缺件照常打包其余并说明。返回 zip 路径。"""
    import zipfile
    from datetime import datetime
    ch = int(chapter)
    name = os.path.basename(book_dir.rstrip("/\\"))
    out_dir = os.path.normpath(out_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "backups"))
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"自证-{name}-ch{ch:03d}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip")
    wanted = [
        os.path.join(book_dir, STATE_FILE),
        os.path.join(book_dir, "_snapshots", f"ch{ch:03d}.state.md"),
        os.path.join(book_dir, "chapters", f"ch{ch:03d}.AI腔体检.md"),
        os.path.join(book_dir, "chapters", f"ch{ch:03d}.一致性审计.md"),
        os.path.join(book_dir, "chapters", f"ch{ch:03d}.一致性审计-交叉.md"),
        os.path.join(book_dir, "chapters", f"ch{ch:03d}.平台自检.md"),
    ]
    packed, missing = [], []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for full in wanted:
            rel = os.path.relpath(full, book_dir)
            if os.path.exists(full):
                z.write(full, os.path.join(name, rel))
                packed.append(rel)
            else:
                missing.append(rel)
    print(f"[evidence] 证据包 → {zip_path}（{len(packed)} 件）")
    if missing:
        print(f"[evidence] 缺件（照常打包其余，建议先补齐）：{'、'.join(missing)}", file=sys.stderr)
    return zip_path


# ── R40 章纲评估 / R43 读者反馈 / R42 交叉审计 ───────────────────────────────
OUTLINE_CHECK_PROMPT = """请以资深网文责编视角评估这章章纲，输出 Markdown 报告：
1. 结构完整：目标/关键事件/末尾钩子/伏笔操作四要素是否齐备；
2. 钩子强度：末尾钩子能否支撑追更，给 1-5 分与理由；
3. 伏笔操作：埋/推/收是否与账本伏笔账自洽；
4. 节奏：事件密度是否合理，会不会注水或赶戏；
5. 修改建议：最多 5 条，按优先级排序。
只输出评估报告。"""


def outline_check(api_key, base_url, model, book_dir, chapter, reasoning_effort="low"):
    """章纲评估：LLM 审 chapters/chXXX.章纲.md 质量，落盘 chXXX.章纲评估.md。
    实测教训：max_tokens 必须 10000——6000 会被 agnes 的思考过程吞光返回空。"""
    ch = int(chapter)
    plan_path = os.path.join(book_dir, "chapters", f"ch{ch:03d}.章纲.md")
    plan = read_text(plan_path)
    if not plan:
        raise SystemExit(f"缺章纲：{plan_path}（先跑 --plan --chapter {ch}）")
    state = read_text(os.path.join(book_dir, STATE_FILE))
    prompt = (f"【记忆账本（评估伏笔操作是否自洽用）】\n{state or '（无账本）'}\n\n"
              f"【第 {ch} 章章纲】\n{plan}\n\n" + OUTLINE_CHECK_PROMPT)
    print(f"[outline-check] 评估 ch{ch:03d} 章纲（max_tokens=10000，防思考吞光）...")
    report = call_llm(
        api_key, base_url, model, prompt,
        temperature=0.2, max_tokens=10000, reasoning_effort=reasoning_effort,
        system_prompt="你是资深网文责编，只输出章纲评估报告。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_EVALUATE, "book": os.path.basename(book_dir.rstrip("/\\")),
                    "chapter": ch},
    )
    out = os.path.join(book_dir, "chapters", f"ch{ch:03d}.章纲评估.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report.strip())
    print(f"[outline-check] 评估报告已落盘 → {out}")
    return out


BETA_READER_PROMPT = """你是追更读者（不是编辑），刚读完这一章。用读者口吻输出反馈：
1. 末尾钩子：想不想点开下一章？为什么？
2. 节奏：哪里拖了想划走、哪里赶了没跟上？
3. 看不懂/出戏的地方：具体指出来（不用给改法）；
4. 本章最爽的一个点 & 最无聊的一个点。
只输出反馈本身，像评论区高赞长评，不像审稿意见。"""


def beta_reader(api_key, base_url, model, book_dir, chapter, reasoning_effort="low"):
    """R43 读者视角反馈：LLM 以追更读者身份读第 N 章，落盘 chXXX.读者反馈.md。"""
    ch = int(chapter)
    body = read_text(os.path.join(book_dir, "chapters", f"ch{ch:03d}.md"))
    if not body:
        raise SystemExit(f"缺章节正文：chapters/ch{ch:03d}.md")
    if len(body) > 3200:  # 与审计同款首尾截取，防推理失控
        body = body[:1400] + "\n\n……（正文中段已省略）……\n\n" + body[-1400:]
    print(f"[beta-reader] 以读者视角读 ch{ch:03d} ...")
    report = call_llm(
        api_key, base_url, model, f"【本章正文】\n{body}\n\n" + BETA_READER_PROMPT,
        temperature=0.7, max_tokens=10000, reasoning_effort=reasoning_effort,
        system_prompt="你是一位真实的追更读者，只输出读者反馈。",
        max_retries=3,
        usage_meta={"action": usage_log.ACTION_BETA, "book": os.path.basename(book_dir.rstrip("/\\")),
                    "chapter": ch},
    )
    out = os.path.join(book_dir, "chapters", f"ch{ch:03d}.读者反馈.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report.strip())
    print(f"[beta-reader] 反馈已落盘 → {out}")
    return out


def cross_audit(book_dir, chapter, reasoning_effort="low"):
    """R42 交叉审计：用备用通道（FALLBACK_* 环境变量）重跑一致性审计，
    报告落盘 chNNN.一致性审计-交叉.md，与主通道审计结论互相印证。
    未配置 FALLBACK_API_KEY/FALLBACK_MODEL 时友好报错（不静默降级到主通道）。"""
    fb_key = env_or("FALLBACK_API_KEY", "FALLBACK_API_KEY", "")
    fb_model = env_or("FALLBACK_MODEL", "FALLBACK_MODEL", "")
    if not (fb_key and fb_model):
        raise SystemExit("交叉审计需要备用通道：请在 .env 配置 FALLBACK_API_KEY 与 "
                         "FALLBACK_MODEL（可选 FALLBACK_BASE_URL）；未配置无法交叉印证。")
    fb_url = env_or("FALLBACK_BASE_URL", "FALLBACK_BASE_URL", DEFAULT_BASE_URL)
    print(f"[cross-audit] 用备用通道 {fb_model} 重审 ch{int(chapter):03d} ...")
    return audit_chapter(fb_key, fb_url, fb_model, book_dir, int(chapter),
                         reasoning_effort=reasoning_effort, report_suffix="-交叉")


def main() -> int:
    ap = argparse.ArgumentParser(description="ai-novel-workbench 引擎：单章连写 + 滚动状态账本记忆")
    ap.add_argument("--book", default="", help="书目录（必填，含 设定.md/大纲.md/角色卡.md）")
    ap.add_argument("--chapter", type=int, default=0, help="要写的章节号，如 1/2/3")
    ap.add_argument("--key", default="", help="API key（默认读 .env 的 AGNES_API_KEY）")
    ap.add_argument("--base-url", default=None, help="API Base URL（默认读 .env 的 AGNES_BASE_URL）")
    ap.add_argument("--model", default=None, help="模型 ID（默认读 .env 的 AGNES_MODEL）")
    ap.add_argument("--reasoning-effort", default="low", help="思考预算: low/medium/high/none（抑制推理模型过度思考）")
    ap.add_argument("--init-state", action="store_true", help="根据设定/角色卡/大纲初始化 story_state.md（写第1章前跑一次）")
    ap.add_argument("--no-state", action="store_true", help="写正文后跳过账本更新（调试用）")
    ap.add_argument("--state-only", action="store_true", help="只更新账本不重写正文（基于 chXXX.md + 旧账重算；用于账本漏更补救）")
    ap.add_argument("--auto-backup", action="store_true", help="R34③：写完本章后自动全书备份 zip（backups/ 留最近 10 份）")
    ap.add_argument("--audit", action="store_true", help="一致性审计：对照账本检查某章正文的冲突/漏记，落盘审计报告（不改文件）")
    ap.add_argument("--words", type=int, default=3000, help="R31 目标字数（1000–10000，默认 3000；超 ±30%% 仅提醒不硬卡）")
    ap.add_argument("--plan", action="store_true", help="R32 闸口前半：按配方出第 N 章章纲+试写，落盘 chapters/chXXX.章纲.md（写章自动遵循）")
    ap.add_argument("--adjust", action="store_true", help="R31 一键加长/精简：按 --target 改写第 N 章正文（--mode expand|shrink，先备份）")
    ap.add_argument("--target", type=int, default=0, help="--adjust 的目标字数")
    ap.add_argument("--mode", choices=["expand", "shrink"], default="expand", help="--adjust 的方向")
    # ── v0.8 扩展动作 ──
    ap.add_argument("--deconstruct", action="store_true",
                    help="R36 拆书：按 rules/deconstruct.md 七维产出 _research/拆书报告.md（免章号）")
    ap.add_argument("--sample-chapters", action="store_true",
                    help="R37 采集最近章节片段供学文风（零 token，免章号；学文风用 scripts/style_learn.py）")
    ap.add_argument("--privacy-scan", action="store_true",
                    help="零 token 版权脱敏扫描：人名/地名/品牌词频+定位，输出报告不改正文（免章号）")
    ap.add_argument("--gen-trilogy", action="store_true",
                    help="从 _research/拆书报告.md 生成三部曲蓝图（免章号）")
    ap.add_argument("--blueprint", action="store_true",
                    help="读拆书报告输出蓝图文件（同 --gen-trilogy，免章号）")
    # ── v0.9 扩展动作（N 为参数值本身，均免 --chapter）──
    ap.add_argument("--recalc-from", type=int, default=0, metavar="N",
                    help="R49 从 chNNN 快照起逐章重算账本，产出重算报告（冲突列表）")
    ap.add_argument("--cross-audit", type=int, default=0, metavar="N",
                    help="R42 用备用通道（FALLBACK_*）交叉审计第 N 章 → chNNN.一致性审计-交叉.md")
    ap.add_argument("--platform-check", type=int, default=0, metavar="N",
                    help="R41 零 token 平台自检：红灯清单+痕迹统计（免 API key）")
    ap.add_argument("--export-evidence", type=int, default=0, metavar="N",
                    help="R46 自证证据包（账本+快照+体检单+审计+自检）zip 到 backups/（零 token）")
    ap.add_argument("--outline-check", type=int, default=0, metavar="N",
                    help="章纲评估：LLM 审 chNNN.章纲.md 质量（max_tokens=10000）")
    ap.add_argument("--beta-reader", type=int, default=0, metavar="N",
                    help="R43 LLM 以读者视角给第 N 章反馈 → chNNN.读者反馈.md")
    ap.add_argument("--score", type=int, default=0, metavar="N",
                    help="v0.9.2 6 维评分（提示词走插件链，停用即拒）→ chNNN.评分.md")
    args = ap.parse_args()

    # 书目录解析提前：零 token 动作（平台自检/证据包/采样/脱敏扫描）不需要 API key
    book_dir = os.path.abspath(args.book) if args.book else ""
    if not book_dir or not os.path.exists(book_dir):
        print(f"书目录不存在：{book_dir or '（未指定 --book）'}")
        return 1

    # 书名 = 目录名；章节落在书目录自己的 chapters/ 下（一本书=一个文件夹）
    book_name = os.path.basename(book_dir.rstrip("/\\"))
    out_dir = os.path.join(book_dir, "chapters")
    state_path = os.path.join(book_dir, STATE_FILE)

    # ── 免章号·零 token 动作（无需 API key）──────────────────────────
    if args.sample_chapters:
        samples = sample_chapters(book_dir)
        if not samples:
            print(f"chapters/ 里没有可采样的章节：{book_dir}")
            return 1
        for s in samples:
            print(f"── {s['file']} ──\n{s['text']}\n")
        print(f"[sample] 已采集 {len(samples)} 章片段（学文风请跑："
              f"python scripts/style_learn.py --book {args.book}）")
        return 0

    if args.privacy_scan:
        privacy_scan(book_dir)
        return 0

    if args.platform_check:
        platform_check(book_dir, args.platform_check)
        return 0

    if args.export_evidence:
        export_evidence(book_dir, args.export_evidence)
        return 0

    api_key = (
        args.key
        or env_or("AGNES_API_KEY", "AGNES_API_KEY", "")
        or env_or("ZHIPU_API_KEY", "ZHIPU_API_KEY", "")
    )
    if not api_key:
        print("缺少 API key：请在项目根 .env 写 AGNES_API_KEY=sk-xxx，或用 --key 传入")
        return 1

    # 配置生效链：命令行 > .env > 内置默认（.env 换厂商必须真正生效）
    base_url = args.base_url if args.base_url else env_or("AGNES_BASE_URL", "AGNES_BASE_URL", DEFAULT_BASE_URL)
    model = args.model if args.model else env_or("AGNES_MODEL", "AGNES_MODEL", DEFAULT_MODEL)
    # R32⑤ 轻量多角色：策划/审校可配独立模型（.env 的 PLANNER_MODEL/REVIEWER_MODEL），留空回落写手
    planner_model = env_or("PLANNER_MODEL", "PLANNER_MODEL", "") or model
    reviewer_model = env_or("REVIEWER_MODEL", "REVIEWER_MODEL", "") or model

    # 动作一：初始化账本
    if args.init_state:
        print(f"[init] 根据 设定/角色卡/大纲 生成初始 {STATE_FILE} ...")
        state = init_state(api_key, base_url, model, book_dir, book_name,
                           reasoning_effort=args.reasoning_effort)
        with open(state_path, "w", encoding="utf-8") as f:
            f.write(state)
        print(f"[init] 账本已落盘 → {state_path}")
        miss = validate_state(state)
        if miss:
            print(f"⚠ [init] 账本结构校验未通过：缺少小节 {miss}。"
                  f"初始化产物不合格，请重试或人工修复 {state_path}。", file=sys.stderr)
            return 1
        return 0

    # ── 免章号动作（v0.8：--deconstruct 回归免章号分支，修复其被 --chapter
    #    必填检查拦截导致 Web 拆书报错的存量 bug）────────────────────────
    if args.deconstruct:
        deconstruct_book(api_key, base_url, model, book_dir,
                         reasoning_effort=args.reasoning_effort)
        return 0

    if args.gen_trilogy or args.blueprint:
        gen_trilogy(api_key, base_url, model, book_dir,
                    reasoning_effort=args.reasoning_effort)
        return 0

    if args.recalc_from:
        rep = recalc_from(book_dir, args.recalc_from,
                          update_fn=lambda body, old: update_state(
                              api_key, base_url, model, body, old,
                              reasoning_effort=args.reasoning_effort,
                              usage_meta={"action": usage_log.ACTION_LEDGER_RECALC, "book": book_name}))
        return 1 if rep.get("interrupted") else 0

    if args.chapter < 1:
        print("请指定 --chapter N（写第 N 章），或 --init-state 初始化账本")
        return 1

    # ── v0.9 章级扩展动作（N 是参数值，前面已越过 chapter 必填检查，防同款不可达 bug）──
    if args.cross_audit:
        cross_audit(book_dir, args.cross_audit, reasoning_effort=args.reasoning_effort)
        return 0

    if args.outline_check:
        outline_check(api_key, base_url, planner_model, book_dir, args.outline_check,
                      reasoning_effort=args.reasoning_effort)
        return 0

    if args.beta_reader:
        beta_reader(api_key, base_url, model, book_dir, args.beta_reader,
                    reasoning_effort=args.reasoning_effort)
        return 0

    # 动作：6 维评分（v0.9.2 回补，提示词走插件链，停用即拒）
    if args.score:
        score_chapter(api_key, base_url, model, book_dir, args.score,
                      reasoning_effort=args.reasoning_effort)
        return 0

    # 动作：一致性审计（只读，不改账本与正文；审校角色可用独立模型）
    if args.audit:
        audit_chapter(api_key, base_url, reviewer_model, book_dir, args.chapter,
                      reasoning_effort=args.reasoning_effort)
        return 0

    # 动作：R32 闸口前半——出章纲+试写落盘（策划角色可用独立模型）
    if args.plan:
        plan_chapter(api_key, base_url, planner_model, book_dir, args.chapter,
                     words=clamp_words(args.words), reasoning_effort=args.reasoning_effort)
        return 0

    # 动作：R31 一键加长/精简
    if args.adjust:
        target = clamp_words(args.target or args.words)
        adjust_chapter(api_key, base_url, model, book_dir, args.chapter,
                       target=target, mode=args.mode,
                       reasoning_effort=args.reasoning_effort)
        return 0

    # 动作二：只更新账本（补救漏更）
    if args.state_only:
        src = os.path.join(out_dir, f"ch{args.chapter:03d}.md")
        if not os.path.exists(src):
            print(f"找不到正文：{src}")
            return 1
        old_state = read_text(state_path)
        body = read_text(src)
        _w = state_size_warning(old_state)  # R45：账本过大只提醒不阻断
        if _w:
            print(_w, file=sys.stderr)
        print(f"[state] 基于 ch{args.chapter:03d}.md（{len(body)} 字）重算账本...")
        new_state = update_state(api_key, base_url, model, body,
                                 old_state, reasoning_effort=args.reasoning_effort,
                                 usage_meta={"action": usage_log.ACTION_LEDGER, "book": book_name,
                                             "chapter": args.chapter})
        with open(state_path, "w", encoding="utf-8") as f:
            f.write(new_state)
        print(f"[state] 账本已更新 → {state_path}")
        miss = validate_state(new_state)
        if miss:
            print(f"⚠ [state] 账本结构校验未通过：缺少小节 {miss}。"
                  f"重算产物仍不合格，请人工修复 {state_path}。", file=sys.stderr)
            return 1  # 坏账本不进快照链（R49 重算要拿它当起点）
        snapshot_state(book_dir, args.chapter, new_state)
        return 0

    # 主流程：写正文 → 更新账本
    words = clamp_words(args.words)
    print(f"[1/4] 组装上下文配方（第 {args.chapter} 章 · 目标 {words} 字）...")
    context = build_context(book_dir, args.chapter, words=words)

    print(f"[2/4] 调用 {model} 生成正文...")
    body = call_llm(api_key, base_url, model, context,
                    reasoning_effort=args.reasoning_effort,
                    usage_meta={"action": usage_log.ACTION_WRITE, "book": book_name,
                                "chapter": args.chapter})
    body = body.strip()

    out_file = os.path.join(out_dir, f"ch{args.chapter:03d}.md")
    os.makedirs(out_dir, exist_ok=True)  # 新建书（from-chat/模板复制）可能没有 chapters/，落盘前自建
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"[3/4] 正文已落盘 → {out_file}（{len(body)} 字）")

    # R31 字数软控：超 ±30% 只提醒不硬卡（拍板 Q11：提醒 + Web 一键加长/精简）
    if abs(len(body) - words) / words > 0.30:
        mode = "shrink" if len(body) > words else "expand"
        print(f"⚠ 字数软控提醒：本章 {len(body)} 字，目标 {words} 字，超出 ±30%。"
              f"可用 --adjust {args.chapter} --target {words} --mode {mode} 校正（Web 端有对应按钮）。")

    if not args.no_state:
        _w = state_size_warning(read_text(state_path))  # R45：账本过大只提醒不阻断
        if _w:
            print(_w, file=sys.stderr)
        print("     更新滚动账本（记忆回填）...")
        new_state = update_state(api_key, base_url, model, body,
                                 read_text(state_path),
                                 reasoning_effort=args.reasoning_effort,
                                 usage_meta={"action": usage_log.ACTION_LEDGER, "book": book_name,
                                             "chapter": args.chapter})
        with open(state_path, "w", encoding="utf-8") as f:
            f.write(new_state)
        print(f"     账本已更新 → {state_path}")
        miss = validate_state(new_state)
        if miss:
            # 正文已成功产出，账本残缺不阻断，但必须大声警告（防 CH-26 复发）
            print(f"⚠ 账本结构校验未通过：缺少小节 {miss}。"
                  f"请人工修复 {state_path} 或重跑 --state-only 重算，再写下一章。", file=sys.stderr)
        else:
            snapshot_state(book_dir, args.chapter, new_state)  # R47：校验通过才进快照链
            # R35 伏笔超期告警（拍板 Q15：超 3 章未回收即响）
            for it in overdue_foreshadows(new_state, args.chapter):
                print(f"⚠ 伏笔超期：{it['text'][:60]}"
                      f"（埋设于第{it['planted']}章，已 {it['overdue_by']} 章未回收）", file=sys.stderr)
    else:
        print("     （--no-state：跳过账本更新）")

    print("提示：下一章用 --chapter " + str(args.chapter + 1) + " 续写，会自动带滚动账本记忆验证不崩。")

    # R34③：可选开关——写完本章自动全书备份（backups/ 留最近 10 份）
    if args.auto_backup:
        try:
            import backup_book
            zp = backup_book.backup_book(book_dir)
            print(f"[backup] 全书已自动备份 → {zp}")
        except Exception as e:  # 备份失败不影响本章成果
            print(f"⚠ 自动备份失败（不影响本章成果）：{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
