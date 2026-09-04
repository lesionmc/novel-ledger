# -*- coding: utf-8 -*-
"""smoke_test.py —— ai-novel-workbench 冒烟测试（零网络、零第三方依赖）

覆盖：
  1. 两个引擎模块可正常 import
  2. deai.extract_full_sentence 句子切分 / 引号边界断言
  3. deai.L1 词表扫描对样例文本的命中断言
  4. deai.apply_chapter 备份 + 替换 + 跳过演练（临时目录，不动真实书）
  5. write_chapter.build_context 配方组装断言（临时书目录）

运行：
  python scripts/smoke_test.py

任何 ❌ 都会以非零码退出（可接入 CI）。"""
import json
import os
import shutil
import sys
import tempfile

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)

import deai              # noqa: E402
import write_chapter     # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def make_book(tmp, name="测试书", chapters=None):
    """造一个临时书目录（三件套 + 账本 + 可选章节），返回书目录路径。"""
    book = os.path.join(tmp, name)
    os.makedirs(os.path.join(book, "chapters"), exist_ok=True)

    def w(p, s):
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)

    w(os.path.join(book, "设定.md"),
      "世界观：架空测试城。\n硬规则：回闪能力一天限 3 次。\n关键道具：银鸟徽章（外观：银色，鸟形，翅膀收拢）。")
    w(os.path.join(book, "大纲.md"), "全书主线：查案。\n第 1 卷：4 章细纲。")
    w(os.path.join(book, "角色卡.md"), "主角：测试者（法医）。\n配角：搭档。")
    w(os.path.join(book, "story_state.md"),
      "## 当前时间\n- 2009-11-19 深夜\n\n## 计数与资源\n- 回闪已用：1 / 3\n\n## 待续状态\n- 第 2 章接续点。")
    for fn, content in (chapters or {}).items():
        w(os.path.join(book, "chapters", fn), content)
    return book


# ── 1. 模块 import ─────────────────────────────────────────────
print("== 1. 模块加载 ==")
check("deai 可导入", callable(getattr(deai, "call_llm", None)) and callable(deai.l1_scan_book))
check("write_chapter 可导入", callable(write_chapter.build_context) and callable(write_chapter.update_state))

# ── 2. extract_full_sentence ───────────────────────────────────
print("\n== 2. 句子切分/引号边界 ==")
check("普通句切分",
      deai.extract_full_sentence("夜色沉得像墨。他转身离开。", "夜色沉得像墨") == "夜色沉得像墨。")
check("引号不算句内容(不吞引号)",
      deai.extract_full_sentence('"就是那些说不清道不明的服务。"她说。', "说不清道不明")
      == "就是那些说不清道不明的服务。")
check("词在中段,整句完整",
      deai.extract_full_sentence("他需要再去一次星梦公司。这次不是查资料，而是亲自去看看。他走了。",
                                 "不是查资料，而是")
      == "这次不是查资料，而是亲自去看看。")

# ── 3. L1 词表扫描 ─────────────────────────────────────────────
print("\n== 3. L1 词表扫描 ==")
_tmp = tempfile.mkdtemp(prefix="novel_smoke_")
try:
    book1 = make_book(_tmp, "扫描书", chapters={
        "ch001.md": "夜色沉得像墨。\n他微微笑了笑，又微微点头，微微叹了口气。\n空气中传来一声叹息。\n",
    })
    results, repeat_notes = deai.l1_scan_book(book1)
    r = next(x for x in results if x["file"] == "ch001.md")
    hard_words = [w for (_ln, w, _c, _win) in r["hard"]]
    soft_words = [w for (w, _n, _c) in r["soft"]]
    check("hard 命中夜色如墨模板", any("夜色" in w or "墨" in w for w in hard_words), str(hard_words))
    check("soft 命中微微×3", "微微" in soft_words, str(soft_words))
    check("字数统计非零", r["chars"] > 0)

    # ── 4. apply_chapter 演练 ─────────────────────────────────
    print("\n== 4. apply 备份/替换/跳过 ==")
    book2 = make_book(_tmp, "改写书", chapters={
        "ch999.md": '正文第一句。\n"就是那些说不清道不明的服务。"她说。\n这是第三行结尾。\n',
    })
    diff = [
        {"idx": 1, "line": 1, "orig": "正文第一句。", "rewrite": "正文第一句已改。", "reason": ""},
        {"idx": 2, "line": 2, "orig": "就是那些说不清道不明的服务。",
         "rewrite": "就是那些不好明说的服务。", "reason": ""},
        {"idx": 3, "line": 9, "orig": "不存在的句子。", "rewrite": "不应该应用。", "reason": ""},  # 行越界→跳过
    ]
    with open(os.path.join(book2, "chapters", "ch999.AI腔diff.json"), "w", encoding="utf-8") as f:
        json.dump(diff, f, ensure_ascii=False)
    code = deai.apply_chapter(book2, 999)
    check("apply 返回码 0", code == 0)
    with open(os.path.join(book2, "chapters", "ch999.md"), encoding="utf-8") as _f:
        new_txt = _f.read()
    check("第1句被替换", "正文第一句已改。" in new_txt)
    check("对话句替换且引号保留", '"就是那些不好明说的服务。"她说。' in new_txt, new_txt.splitlines()[1])
    check("行越界项未误改", "不应该应用" not in new_txt)
    check("原稿已备份", os.path.exists(os.path.join(book2, "chapters", "ch999.bak.md")))

    # ── 5. build_context 配方组装 ─────────────────────────────
    print("\n== 5. build_context 配方组装 ==")
    book3 = make_book(_tmp, "配方书", chapters={
        "ch001.md": "第一章正文……结尾留钩子：他推开了那扇门。\n",
    })
    ctx = write_chapter.build_context(book3, 2)
    check("含创作宪章", "【创作宪章" in ctx)
    check("含角色卡", "【活跃角色卡" in ctx)
    check("含账本记忆", "2009-11-19 深夜" in ctx)
    check("含上一章结尾", "他推开了那扇门。" in ctx)
    check("含当前任务", "请续写第 2 章正文" in ctx)

    # ── 5.5 账本 7 小节结构校验（防 CH-26 账本截断复发）────────
    print("\n== 5.5 账本 7 小节结构校验 ==")
    _full = write_chapter.STATE_TEMPLATE
    check("完整模板 7 节齐全", write_chapter.validate_state(_full) == [])
    _cut = _full[:_full.find("## 关键事件时间线") + 9]          # 停在半截标题，模拟模型输出被截断
    _miss = write_chapter.validate_state(_cut)
    check("截断文本能查出缺失小节", len(_miss) >= 3, str(_miss))
    check("截断时尾节「待续状态」被判缺", "## 待续状态" in _miss, str(_miss))
    _book4 = make_book(_tmp, "缺节书")                            # make_book 的账本只有 3 节
    with open(os.path.join(_book4, "story_state.md"), encoding="utf-8") as _f:
        _partial = _f.read()
    _miss2 = write_chapter.validate_state(_partial)
    check("残缺账本(仅3节)精确报缺 4 节", len(_miss2) == 4, str(_miss2))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# ── 6. call_llm failover（不真发网络，monkeypatch）─────────────
print("\n== 6. failover 主/备用通道切换 ==")
import write_chapter as _wc
_real_post = _wc._post_chat
_calls = []


def _fake_post(base_url, api_key, payload, timeout=240):
    _calls.append((base_url, payload.get("model")))
    if "主" in base_url:
        raise OSError("主通道模拟故障")
    return {
        "choices": [{"message": {"content": "备用通道成功"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


_wc._post_chat = _fake_post
try:
    out = _wc.call_llm("主key", "http://主通道/v1", "主模型", "测试内容",
                       max_retries=0,
                       fallback_key="备key", fallback_base_url="http://备通道/v1",
                       fallback_model="备模型")
    check("主失败后返回备用结果", out == "备用通道成功", out)
    check("主通道尝试了主模型", len(_calls) >= 1 and _calls[0] == ("http://主通道/v1", "主模型"),
          str(_calls))
    has_fallback = any(url.startswith("http://备通道") and model == "备模型" for url, model in _calls)
    check("备用请求携带【备用模型名】", has_fallback, str(_calls))
finally:
    _wc._post_chat = _real_post

# deai 的 call_llm 走 urllib 直发，patch urlopen 验证备用请求带【备用模型名】（防 H1 复发）
import urllib.request as _ur
_deai_calls = []
_real_urlopen = _ur.urlopen


def _fake_urlopen(req, timeout=None):
    _deai_calls.append((req.full_url, json.loads(req.data.decode("utf-8")).get("model")))
    if "主" in req.full_url:
        raise OSError("deai 主通道模拟故障")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return ('{"choices":[{"message":{"content":"deai备用ok"},'
                    '"finish_reason":"stop"}],"usage":{}}').encode("utf-8")

    return _Resp()


_ur.urlopen = _fake_urlopen
try:
    dout = deai.call_llm("主key", "http://主通道/v1", "主模型", "测试内容",
                         max_retries=0,
                         fallback_key="备key", fallback_base_url="http://备通道/v1",
                         fallback_model="备模型")
    check("deai 主失败后切备用返回", dout == "deai备用ok", dout)
    check("deai 备用请求带备用模型名",
          any(u.startswith("http://备通道") and m == "备模型" for u, m in _deai_calls),
          str(_deai_calls))
finally:
    _ur.urlopen = _real_urlopen

# ── 7. 用量记账（R48） ─────────────────────────────────────────
print("\n== 7. 用量记账 ==")
import usage_log  # noqa: E402

_tmpdir = tempfile.mkdtemp(prefix="usage_")
_upath = os.path.join(_tmpdir, "usage_log.jsonl")
try:
    e1 = usage_log.log_usage("写正文", "模型A", 3000, 3000, book="测试书", chapter=1, path=_upath)
    e2 = usage_log.log_usage("账本更新", "模型A", 2000, 1500, book="测试书", chapter=1, path=_upath)
    usage_log.log_usage("坏数据", "模型B", "abc", None, path=_upath)  # 非 token 数字不炸
    with open(_upath, "a", encoding="utf-8") as f:
        f.write("这行不是JSON\n")
    entries = usage_log.load_entries(path=_upath)
    check("流水写入与容错读取（3 行合法 + 坏行跳过）", len(entries) == 3, str(len(entries)))
    agg = usage_log.aggregate(entries)
    check("汇总：总量=9500 且按天/按动作齐备",
          agg["total"] == 9500 and agg["calls"] == 3
          and "写正文" in agg["by_action"] and len(agg["by_day"]) >= 1, str(agg)[:160])
    check("写章平均：仅按「写正文」计（1 章 6000）",
          agg["write_count"] == 1 and agg["write_avg"] == 6000,
          f'count={agg["write_count"]} avg={agg["write_avg"]}')
    check("log_usage 失败不抛异常（坏路径返回 None）",
          usage_log.log_usage("x", "y", 1, 2, path=os.path.join(_tmpdir, "no_dir", "a.jsonl")) is None)
finally:
    shutil.rmtree(_tmpdir, ignore_errors=True)

# ── 8. 章快照（R47） ───────────────────────────────────────────
print("\n== 8. 章快照 ==")
_snapbook = tempfile.mkdtemp(prefix="snapbook_")
try:
    out = write_chapter.snapshot_state(_snapbook, 7, "## 当前时间\n- 测试账本")
    p = os.path.join(_snapbook, "_snapshots", "ch007.state.md")
    check("快照落盘且命名 chXXX.state.md", out == p and os.path.exists(p), str(out))
    with open(p, encoding="utf-8") as f:
        check("快照内容与账本一致", f.read() == "## 当前时间\n- 测试账本")
    blocker = os.path.join(_snapbook, "blocked")  # 用一个"文件"冒充目录，制造写盘失败
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("占位")
    check("快照失败不抛异常（返回空串）",
          write_chapter.snapshot_state(blocker, 1, "x") == "")
finally:
    shutil.rmtree(_snapbook, ignore_errors=True)

# ── 汇总 ───────────────────────────────────────────────────────
print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
if FAIL:
    sys.exit(1)
print("全部通过 ✅")
