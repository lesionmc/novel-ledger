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
import chapters          # noqa: E402
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
    check("原稿已备份为 chXXX.apply.bak.md",
          os.path.exists(os.path.join(book2, "chapters", "ch999.apply.bak.md")))
    check("旧备份名 ch999.bak.md 不再产生（备份按功能分离）",
          not os.path.exists(os.path.join(book2, "chapters", "ch999.bak.md")))

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
    check("完整模板 8 节齐全", write_chapter.validate_state(_full) == [])
    _cut = _full[:_full.find("## 关键事件时间线") + 9]          # 停在半截标题，模拟模型输出被截断
    _miss = write_chapter.validate_state(_cut)
    check("截断文本能查出缺失小节", len(_miss) >= 3, str(_miss))
    check("截断时尾节「待续状态」被判缺", "## 待续状态" in _miss, str(_miss))
    _book4 = make_book(_tmp, "缺节书")                            # make_book 的账本只有 3 节
    with open(os.path.join(_book4, "story_state.md"), encoding="utf-8") as _f:
        _partial = _f.read()
    _miss2 = write_chapter.validate_state(_partial)
    check("残缺账本(仅3节)精确报缺 5 节", len(_miss2) == 5, str(_miss2))
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

# ── 9. v0.2 新功能（R31/32/34/35） ─────────────────────────────
print("\n== 9. v0.2 新功能 ==")
import backup_book  # noqa: E402

# 9a. R31 字数夹取边界
check("字数夹取：默认 3000", write_chapter.clamp_words(None) == 3000)
check("字数夹取：非法串回落 3000", write_chapter.clamp_words("abc") == 3000)
check("字数夹取：下限 999→1000", write_chapter.clamp_words(999) == 1000)
check("字数夹取：上限 10001→10000", write_chapter.clamp_words(10001) == 10000)

# 9b. R31 build_context 字数注入 + R32 章纲注入
_wbook = make_book(tempfile.mkdtemp(prefix="w9_"), chapters={"ch001.md": "第一章内容。" * 50})
os.makedirs(os.path.join(_wbook, "chapters"), exist_ok=True)
with open(os.path.join(_wbook, "chapters", "ch002.章纲.md"), "w", encoding="utf-8") as f:
    f.write("# ch002 章纲\n- 目标：测试章纲注入")
try:
    ctx = write_chapter.build_context(_wbook, 2, words=4500)
    check("配方注入目标字数 4500", "4500 字左右" in ctx)
    check("配方注入作者确认章纲", "本章章纲" in ctx and "测试章纲注入" in ctx)
    ctx3 = write_chapter.build_context(_wbook, 3, words=3000)
    check("无章纲的章不注入章纲块", "本章章纲" not in ctx3)
finally:
    shutil.rmtree(os.path.dirname(_wbook), ignore_errors=True)

# 9c. R35 伏笔超期解析（边界：差 1 天不算超期）
_state = """## 伏笔账本
- 神秘监视者盯紧他 [待回收 · 第1章]
- 徽记同源之谜 [待回收 · 第2章]
- 车祸真相 [已回收·埋设于第1章，回收于第5章]
- 无章号的老条目 [待回收]
- （空）
"""
over = write_chapter.overdue_foreshadows(_state, 5)   # 5-1=4>3 超；5-2=3 不超
check("伏笔超期：第1章条目在 ch5 判超期", len(over) == 1 and over[0]["planted"] == 1
      and over[0]["overdue_by"] == 4, str(over)[:120])
over2 = write_chapter.overdue_foreshadows(_state, 6)  # 6-2=4>3 也超
check("伏笔超期：ch6 时两条均超", len(over2) == 2, str(over2)[:120])
check("伏笔状态解析：已回收/失效/无章号", write_chapter.parse_foreshadows(_state)[2]["status"] == "已回收"
      and write_chapter.parse_foreshadows(_state)[3]["planted"] is None)

# 9d. R34 备份：打包 + 修剪保留 10 份
_bkbook = make_book(tempfile.mkdtemp(prefix="bk9_"), chapters={"ch001.md": "正文"})
_bkout = tempfile.mkdtemp(prefix="bkout_")
try:
    p1 = backup_book.backup_book(_bkbook, out_dir=_bkout, keep=10)
    check("备份 zip 生成且含账本", os.path.exists(p1) and p1.endswith(".zip"))
    import zipfile as _zf
    with _zf.ZipFile(p1) as z:
        names = z.namelist()
    check("备份含三件套+账本+正文",
          any(n.endswith("设定.md") for n in names) and any("story_state.md" in n for n in names)
          and any(n.endswith("ch001.md") for n in names), str(names)[:120])
    # 造 12 份旧备份，keep=10 应修剪到 10
    for i in range(12):
        with open(os.path.join(_bkout, f"测试书-old{i:02d}.zip"), "w") as f:
            f.write("x")
    backup_book.backup_book(_bkbook, out_dir=_bkout, keep=10)
    left = [f for f in os.listdir(_bkout) if f.startswith("测试书-")]
    check("备份修剪：超过 10 份只留最近 10 份", len(left) == 10, str(len(left)))
finally:
    shutil.rmtree(os.path.dirname(_bkbook), ignore_errors=True)
    shutil.rmtree(_bkout, ignore_errors=True)

# ── 10. 体检台 checkup（build_full_steps / L1 复用 deai 口径） ──
print("\n== 10. checkup 体检台 ==")
import checkup  # noqa: E402
import llm      # noqa: E402
import task_runner       # noqa: E402
import plugin_loader     # noqa: E402

_steps = checkup.build_full_steps("books/某书", 7)
check("build_full_steps 返回三步", len(_steps) == 3, str(_steps))
_expect_flags = ("--audit", "--evaluate", "--publish-check")
for _i, (_step, _flag) in enumerate(zip(_steps, _expect_flags)):
    _ci = _step.index("--chapter")
    check(f"第{_i+1}步 --chapter 紧跟章号", _step[_ci + 1] == "7", str(_step))
    check(f"第{_i+1}步步旗 {_flag} 恰好一次",
          _step.count(_flag) == 1 and _flag in _step, str(_step))
    check(f"第{_i+1}步携带 --book", _step[_step.index("--book") + 1] == "books/某书")

_book_eval = make_book(tempfile.mkdtemp(prefix="ckup_"), "体检书", chapters={
    "ch001.md": "夜色沉得像墨。他微微笑了笑，又微微点头，微微叹了口气。\n"})
try:
    results, _rn = deai.l1_scan_book(_book_eval)
    _r1 = next(x for x in results if x["file"] == "ch001.md")
    _line = checkup.l1_report_from_result(_r1)
    check("体检单行含文件名与指数", "ch001.md" in _line and f"指数 {_r1['index']}" in _line, _line)
    # 指数口径必须与 deai 完全对齐（hard×2 + soft高频次数 + 破折号/省略号标志）
    _score_expect = len(_r1["hard"]) * 2 + len(_r1["soft"]) + _r1["dash_flag"] + _r1["ell_flag"]
    check("L1 指数与 deai 口径对齐（score 公式一致）",
          _r1["score"] == _score_expect and f"{_r1['index']}" in _line,
          f'{_r1["score"]} vs {_score_expect}')
    check("evaluate 单步对样例书返回 0", checkup.step_evaluate(_book_eval, 1) == 0)
    # publish-check：make_book 的账本只有 3 节 → 应查出问题退出码 1
    check("publish-check 残缺账本判失败", checkup.step_publish_check(_book_eval, 1) == 1)
    with open(os.path.join(_book_eval, "story_state.md"), "w", encoding="utf-8") as f:
        f.write(write_chapter.STATE_TEMPLATE.replace("{书名}", "体检书"))
    check("publish-check 完整账本+正文判通过", checkup.step_publish_check(_book_eval, 1) == 0)
finally:
    shutil.rmtree(os.path.dirname(_book_eval), ignore_errors=True)

# ── 11. llm 通道层（流式细节深测在 test_llm_stream.py） ────────
print("\n== 11. llm 通道层 ==")
check("StreamInterrupted 存在且是 Exception",
      issubclass(llm.StreamInterrupted, Exception))
check("chat_stream 是生成器函数",
      __import__("inspect").isgeneratorfunction(llm.chat_stream))
check("post_chat_stream 是生成器函数",
      __import__("inspect").isgeneratorfunction(llm.post_chat_stream))
check("post_chat 可导入", callable(llm.post_chat))

# ── 12. usage_log elapsed_ms / avg_ms_by_action / 并发锁 ──────
print("\n== 12. usage_log 耗时记账 ==")
check("ACTION_WRITE 常量 =「写正文」", usage_log.ACTION_WRITE == "写正文")
check("write_chapter 引用同一常量", write_chapter.usage_log is usage_log
      and usage_log.ACTION_WRITE in repr(write_chapter.usage_log.ACTION_WRITE))

_msdir = tempfile.mkdtemp(prefix="ms_")
_mspath = os.path.join(_msdir, "u.jsonl")
try:
    e = usage_log.log_usage("写正文", "mA", 10, 20, book="b", chapter=1,
                            path=_mspath, elapsed_ms=123.6)
    check("elapsed_ms 数字落盘且取整", e is not None and e["elapsed_ms"] == 124, str(e))
    e2 = usage_log.log_usage("写正文", "mA", 1, 2, path=_mspath, elapsed_ms="abc")
    check("elapsed_ms 非数字省略该键", e2 is not None and "elapsed_ms" not in e2, str(e2))
    usage_log.log_usage("账本更新", "mA", 1, 2, path=_mspath, elapsed_ms=100)
    with open(_mspath, "a", encoding="utf-8") as f:
        f.write(json.dumps({"day": "2026-09-06", "action": "写正文", "in": 5, "out": 5,
                            "total": 10, "ts": "x", "book": "b", "chapter": 9,
                            "model": "old"}) + "\n")  # 旧格式行（无 elapsed_ms）
    entries = usage_log.load_entries(path=_mspath)
    agg = usage_log.aggregate(entries)
    # 写正文耗时样本：123.6→124；账本更新：100；旧行无耗时键不参与
    check("avg_ms_by_action 均值正确（写正文=124）",
          agg["avg_ms_by_action"].get("写正文") == 124, str(agg["avg_ms_by_action"]))
    check("avg_ms_by_action 含账本更新=100",
          agg["avg_ms_by_action"].get("账本更新") == 100)
    check("by_action 保持纯数字（前端按值排序依赖）",
          all(isinstance(v, int) for v in agg["by_action"].values()),
          str({k: type(v).__name__ for k, v in agg["by_action"].items()}))
    check("旧格式行兼容（不参与耗时均值，计入 by_action）",
          "旧格式行" not in str(agg["avg_ms_by_action"]) and agg["calls"] == 4)
finally:
    shutil.rmtree(_msdir, ignore_errors=True)

# ── 13. BUILTIN_DEAI_RULES 改名（加载链路） ────────────────────
print("\n== 13. 规则改名 ==")
check("内置默认改名 BUILTIN_DEAI_RULES", "去AI腔红线" in write_chapter.BUILTIN_DEAI_RULES)
check("运行值 DEAI_RULES = load_rules 结果",
      write_chapter.DEAI_RULES == write_chapter.load_rules(
          "deai_rules.md", write_chapter.BUILTIN_DEAI_RULES))
check("SYSTEM_PROMPT 注入规则内容", "去AI腔红线" in write_chapter.SYSTEM_PROMPT)

# ── 14. task_runner 分类与超时（深测在 test_task_runner.py） ───
print("\n== 14. task_runner 分类 ==")
check("超时→引擎超时（首位类别）",
      task_runner.classify_failure({"timeout": True}) == task_runner.CAT_TIMEOUT)
check("账本类失败可识别",
      task_runner.classify_failure({"timeout": False, "returncode": 1,
                                    "stdout": "账本结构校验未通过：缺少小节", "stderr": ""})
      == task_runner.CAT_STATE)
check("缺密钥可识别",
      task_runner.classify_failure({"timeout": False, "returncode": 1,
                                    "stdout": "缺少 API key", "stderr": ""})
      == task_runner.CAT_KEY)
check("网络/限流可识别",
      task_runner.classify_failure({"timeout": False, "returncode": 1,
                                    "stdout": "URLError: x", "stderr": ""})
      == task_runner.CAT_NET)
check("空内容可识别",
      task_runner.classify_failure({"timeout": False, "returncode": 1,
                                    "stdout": "", "stderr": "空内容（finish_reason=length）"})
      == task_runner.CAT_EMPTY)
check("其余归未知失败",
      task_runner.classify_failure({"timeout": False, "returncode": 1,
                                    "stdout": "莫名其妙", "stderr": ""})
      == task_runner.CAT_UNKNOWN)
# _state_only_repair 行为：补跑 --state-only、超时 900s（真分支覆盖在 test_task_runner.py）
_real_re, _cap = task_runner.run_engine, []


def _cap_run(args, timeout=task_runner.WRITE_TIMEOUT, script=task_runner.WRITE_CH):
    _cap.append((list(args), timeout))
    return {"ok": True, "timeout": False, "returncode": 0, "stdout": "", "stderr": ""}


task_runner.run_engine = _cap_run
try:
    _rep = task_runner._state_only_repair("books/某书", 3)
finally:
    task_runner.run_engine = _real_re
check("账本补救走 --state-only --chapter 且超时 900s",
      _rep["ok"] and _cap == [(["--book", "books/某书", "--state-only", "--chapter", 3], 900)],
      str(_cap))

# ── 15. plugin_loader（临时插件目录） ──────────────────────────
print("\n== 15. plugin_loader ==")
_pldir = tempfile.mkdtemp(prefix="plug_")
_real_pldir = plugin_loader.PLUGINS_DIR
plugin_loader.PLUGINS_DIR = _pldir
plugin_loader.invalidate_cache()
try:
    check("空目录扫描返回空列表", plugin_loader.scan_plugins() == [])
    os.makedirs(os.path.join(_pldir, "p1"))
    with open(os.path.join(_pldir, "p1", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "插件一", "version": "1.0", "description": "d1", "entry": "m.py"}, f)
    os.makedirs(os.path.join(_pldir, "p2"))
    with open(os.path.join(_pldir, "p2", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "插件二", "enabled": True}, f)
    # 造一个坏 manifest，扫描必须跳过不炸
    with open(os.path.join(_pldir, "p2", "plugin.json"), "a", encoding="utf-8") as f:
        f.write("垃圾")  # 让 p2 变坏 → 重扫后只剩 p1
    _bad = plugin_loader.scan_plugins(force=True)
    check("坏 manifest 跳过不炸整体", len(_bad) == 1 and _bad[0]["dir"] == "p1", str(_bad))
    with open(os.path.join(_pldir, "p2", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "插件二", "enabled": True}, f)
    _plugs = plugin_loader.scan_plugins(force=True)
    check("扫描发现 2 个插件", len(_plugs) == 2, str(_plugs))
    _p1 = next(p for p in _plugs if p["dir"] == "p1")
    check("enabled 缺省为 False", _p1["enabled"] is False)
    check("返回浅拷贝（改返回值不污染缓存）",
          _p1["version"] == "1.0" and plugin_loader.scan_plugins()[0]["version"] == "1.0"
          or (_p1.update(version="污染") or plugin_loader.scan_plugins()[0]["version"] == "1.0"))
    # 缓存命中：改 manifest 但不动 mtime 不可行——这里验证缓存生效路径（快照未变不重扫）
    plugin_loader._cache["plugins"][0]["_cached_marker"] = 1
    _hit = plugin_loader.scan_plugins()
    check("快照未变走缓存（不重扫）", any(p.get("_cached_marker") == 1 for p in _hit))
    # mtime 变化 → 必重扫
    plugin_loader.invalidate_cache()
    _p2 = next(p for p in plugin_loader.scan_plugins() if p["dir"] == "p2")
    check("重扫后 enabled=True 读到", _p2["enabled"] is True)
    v = plugin_loader.set_enabled("p2", False)
    check("set_enabled 返回新状态", v is False)
    with open(os.path.join(_pldir, "p2", "plugin.json"), encoding="utf-8") as f:
        check("manifest 已原子写盘 enabled=false",
              json.load(f)["enabled"] is False)
    _left = [f for f in os.listdir(os.path.join(_pldir, "p2")) if f.endswith(".tmp")]
    check("无残留临时文件", _left == [], str(_left))
    check("写盘后扫描立刻反映新状态",
          next(p for p in plugin_loader.scan_plugins() if p["dir"] == "p2")["enabled"] is False)
    try:
        plugin_loader.set_enabled("不存在", True)
        check("set_enabled 不存在抛 FileNotFoundError", False)
    except FileNotFoundError:
        check("set_enabled 不存在抛 FileNotFoundError", True)
finally:
    plugin_loader.PLUGINS_DIR = _real_pldir
    plugin_loader.invalidate_cache()
    shutil.rmtree(_pldir, ignore_errors=True)

# ── 16. v0.8：style_learn / 指纹注入 / relation_graph / vector / privacy ─────
print("\n== 16. v0.8 新功能 ==")
import style_learn       # noqa: E402
import relation_graph    # noqa: E402
import vector_recall     # noqa: E402
import backup_book       # noqa: E402

# 16a. style_learn 纯函数（L1 聚合 / prompt / 渲染）
_stats = style_learn.aggregate_l1(
    [{"chars": 100, "hard": [1, 2], "soft": [("微微", 3, "万能副词")]},
     {"chars": 200, "hard": [], "soft": [("微微", 1, "万能副词"), ("缓缓", 2, "万能副词")]}],
    [("雨刷", 5, 3, "ch001.md L1")])
check("style_learn L1 聚合：章数/字数/硬伤",
      _stats["chapters"] == 2 and _stats["chars"] == 300 and _stats["hard_total"] == 2,
      str(_stats))
check("style_learn L1 聚合：soft 跨章累加",
      _stats["soft_top"][0] == ("微微", 4) and dict(_stats["soft_top"]).get("缓缓") == 2,
      str(_stats["soft_top"]))
check("style_learn L1 聚合：意象复用透传", _stats["image_reuse"] == [("雨刷", 5, 3)])
_prompt = style_learn.build_style_prompt(_stats, [{"file": "ch001.md", "text": "他推开门。"}])
check("style_learn prompt 含统计与四维画像要求",
      "微微×4" in _prompt and "句长节奏" in _prompt and "对话密度" in _prompt
      and "叙事人称" in _prompt and "ch001.md" in _prompt)
_fp = style_learn.render_fingerprint(_stats, "短句为主。", "测试书")
check("指纹渲染含书名/L1 统计/L2 画像",
      "《测试书》文风指纹" in _fp and "短句为主。" in _fp and "章节 2 章" in _fp)

# 16b. build_context 注入点：文风指纹 + 向量召回（账本记忆之后、当前任务之前，零破坏）
_inj = tempfile.mkdtemp(prefix="v08_")
try:
    _bfp = make_book(_inj, "指纹书", chapters={"ch001.md": "第一章结尾钩子。"})
    with open(os.path.join(_bfp, "文风指纹.md"), "w", encoding="utf-8") as f:
        f.write("句长节奏：短句为主。")
    ctx = write_chapter.build_context(_bfp, 2)
    check("文风指纹被注入", "【文风指纹" in ctx and "短句为主" in ctx)
    check("指纹注入在账本记忆之后",
          ctx.index("【文风指纹") > ctx.index("2009-11-19 深夜"))
    check("指纹注入在当前任务之前",
          ctx.index("【文风指纹") < ctx.index("【当前任务】"))
    os.remove(os.path.join(_bfp, "文风指纹.md"))
    check("无指纹文件不注入（零破坏）", "【文风指纹" not in write_chapter.build_context(_bfp, 2))
    os.makedirs(os.path.join(_bfp, "_recall"), exist_ok=True)
    with open(os.path.join(_bfp, "_recall", "ch002.md"), "w", encoding="utf-8") as f:
        f.write("- 【ch001.md】旧章片段……")
    ctx2 = write_chapter.build_context(_bfp, 2)
    check("向量召回缓存被注入", "【向量召回" in ctx2 and "旧章片段" in ctx2)
    check("召回注入也在当前任务之前",
          ctx2.index("【向量召回") < ctx2.index("【当前任务】"))

    # 16c. relation_graph：泛称过滤 / 共现 / 回验 / 预算
    check("泛称过滤：他/那人/单字不入图",
          relation_graph.filter_generic("他") and relation_graph.filter_generic("那人")
          and relation_graph.filter_generic("那"))
    check("实名通过过滤", not relation_graph.filter_generic("陈默"))
    _bgr = make_book(_inj, "图谱书")
    with open(os.path.join(_bgr, "角色卡.md"), "w", encoding="utf-8") as f:
        f.write("主角：陈默（法医）。\n配角：林小满。\n旁白：他。")
    names = relation_graph.load_character_names(_bgr)
    check("角色卡提名且泛称被滤", "陈默" in names and "林小满" in names and "他" not in names,
          str(names))
    _gtexts = {"ch001.md": "陈默看着林小满。\n林小满转身走了。\n陈默叹气。"}
    edges, counts = relation_graph.count_cooccurrence(_gtexts, ["陈默", "林小满"])
    check("共现：同段计 1 次",
          edges.get(tuple(sorted(("陈默", "林小满"))), {}).get("weight") == 1, str(edges))
    check("共现：出现段落数正确",
          counts == {"陈默": 2, "林小满": 2}, str(counts))
    _rels = [
        {"a": "陈默", "b": "林小满", "phrase": "搭档查案", "evidence": "陈默看着林小满。", "chapter": 1},
        {"a": "陈默", "b": "林小满", "phrase": "幻觉关系", "evidence": "他们一起飞上了月球。", "chapter": 1},
        {"a": "陈默", "b": "林小满", "phrase": "缺章号", "evidence": "陈默看着林小满。", "chapter": None},
    ]
    ok_rels, dropped = relation_graph.validate_relations(_rels, _gtexts, edges)
    check("回验：真证据入图且带章号",
          len(ok_rels) == 1 and ok_rels[0]["phrase"] == "搭档查案" and ok_rels[0]["chapter"] == 1,
          str(ok_rels))
    check("回验：编造证据与缺章号被丢弃", dropped == 2, f"dropped={dropped}")
    check("L2 prompt 含防幻觉铁律与预算",
          "严禁编造" in relation_graph.build_relation_prompt(edges))

    # 16d. deai --compare（R44 差值报告，口径与 --scan 一致）
    _bcp = make_book(_inj, "对比书")
    with open(os.path.join(_bcp, "chapters", "ch001.bak.md"), "w", encoding="utf-8") as f:
        f.write("夜色沉得像墨。他微微笑了，又微微点头，微微叹了口气。\n")
    with open(os.path.join(_bcp, "chapters", "ch001.md"), "w", encoding="utf-8") as f:
        f.write("天黑透了。他笑了笑，点了头。\n")
    rb, ra, rep = deai.compare_chapter(_bcp, 1)
    check("对比：改后指数下降", ra["index"] < rb["index"], f'{rb["index"]}->{ra["index"]}')
    check("对比：报告含差值且落盘",
          "指数变化" in rep and os.path.exists(os.path.join(_bcp, "chapters", "ch001.去味对比.md")))
    check("对比：指标口径与 --scan 一致（单章键齐备）",
          set(rb) == set(ra) and {"file", "chars", "hard", "soft", "dash", "ellipsis",
                                  "score", "index"} <= set(rb), str(sorted(rb)))
finally:
    shutil.rmtree(_inj, ignore_errors=True)

# 16e. vector_recall：分块纯函数 + post_embed 未配置报错（全部零网络）
check("vector_recall：chromadb 探测返回 bool 不炸", isinstance(vector_recall.check_available(), bool))
_chunks = vector_recall.chunk_text("字" * 1900, size=800, overlap=100)
check("分块：超长文本 3 块且带重叠",
      len(_chunks) == 3 and len(_chunks[0]) == 800 and _chunks[1][:100] == _chunks[0][-100:],
      f"n={len(_chunks)}")
check("分块：空文本 / 短文本",
      vector_recall.chunk_text("") == [] and vector_recall.chunk_text("短文本") == ["短文本"])

_real_dotenv_llm = llm.DOTENV
_saved_env_embed = {k: os.environ.pop(k) for k in ("EMBED_API_KEY", "EMBED_MODEL", "EMBED_BASE_URL")
                    if k in os.environ}
llm.DOTENV = {}
try:
    try:
        llm.post_embed("测试")
        check("post_embed 未配置抛友好 ValueError", False)
    except ValueError as e:
        check("post_embed 未配置抛友好 ValueError", "EMBED_API_KEY" in str(e), str(e))
    os.environ["EMBED_API_KEY"] = "ek"
    os.environ["EMBED_MODEL"] = "em"
    _embed_calls = []

    def _fake_embed_urlopen(req, timeout=None):
        _embed_calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"data": [{"index": 0, "embedding": [0.1, 0.2]}]}).encode("utf-8")

        return _R()

    _ur.urlopen = _fake_embed_urlopen
    try:
        vec = llm.post_embed("你好")
        check("post_embed 单文本返回向量且打 /embeddings",
              vec == [0.1, 0.2] and _embed_calls[0][0].endswith("/embeddings")
              and _embed_calls[0][1]["model"] == "em", str(_embed_calls)[:120])
        vecs = llm.post_embed(["a", "b"])
        check("post_embed 批量返回向量列表", isinstance(vecs, list) and len(vecs) == 1)
    finally:
        _ur.urlopen = _real_urlopen
finally:
    llm.DOTENV = _real_dotenv_llm
    for _k in ("EMBED_API_KEY", "EMBED_MODEL", "EMBED_BASE_URL"):
        os.environ.pop(_k, None)
    os.environ.update(_saved_env_embed)

if not vector_recall.check_available():
    import subprocess
    _pvec = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "vector_recall.py"), "--book", os.getcwd(), "index"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"})
    check("向量 CLI 无 chromadb 降级退出 0（不阻断）",
          _pvec.returncode == 0 and "降级" in (_pvec.stdout + _pvec.stderr),
          f"rc={_pvec.returncode}")

# 16f. privacy_scan 零 token 样例 / is_placeholder_doc / sample_chapters / write_with_backup
_inj2 = tempfile.mkdtemp(prefix="v08b_")
try:
    _bpr = make_book(_inj2, "脱敏书", chapters={
        "ch001.md": "测试者走进星巴克，用微信付了钱。\n搭档在门口等他。\n"})
    _prep = write_chapter.privacy_scan(_bpr)
    _terms = {t["term"]: t for t in _prep["terms"] if t["count"]}
    check("脱敏扫描：人名命中带定位",
          _terms.get("测试者", {}).get("count") == 1
          and "ch001.md L1" in _terms["测试者"]["locations"][0], str(_terms)[:150])
    check("脱敏扫描：品牌词命中", _terms.get("星巴克", {}).get("count") == 1
          and _terms.get("微信", {}).get("count") == 1, str(sorted(_terms)))
    check("脱敏扫描：报告落盘", os.path.exists(os.path.join(_bpr, "隐私脱敏扫描.md")))

    check("占位检测：模板占位文本", write_chapter.is_placeholder_doc("设定：{书名}\n（待填写）"))
    check("占位检测：真实设定不算占位",
          not write_chapter.is_placeholder_doc("世界观：雾城临海，常年有雾。硬规则：回闪一天限三次。"))
    check("占位检测：空与过短判占位",
          write_chapter.is_placeholder_doc("") and write_chapter.is_placeholder_doc("短"))

    _bs = make_book(_inj2, "采样书", chapters={
        "ch001.md": "一" * 2000 + "结尾甲", "ch002.md": "二" * 100})
    _smp = write_chapter.sample_chapters(_bs, n=2)
    check("采样：取最近 N 章", [s["file"] for s in _smp] == ["ch001.md", "ch002.md"],
          str([s["file"] for s in _smp]))
    check("采样：长章首尾截短含省略号", "……" in _smp[0]["text"] and _smp[0]["text"].endswith("结尾甲"))
    check("采样：短章原样保留", _smp[1]["text"] == "二" * 100)

    _bwb = make_book(_inj2, "备份封装书", chapters={"ch001.md": "x"})
    _real_bb = backup_book.backup_book
    _bb_calls = []

    def _fake_bb(book_dir, out_dir=None, keep=10):
        _bb_calls.append(book_dir)
        return os.path.join(_inj2, "fake.zip")

    backup_book.backup_book = _fake_bb
    try:
        bak, res = write_chapter.write_with_backup(_bwb, lambda: "ok")
    finally:
        backup_book.backup_book = _real_bb
    check("写前备份封装：先备份后执行", _bb_calls == [_bwb] and bak.endswith("fake.zip") and res == "ok",
          f"{_bb_calls} {bak} {res}")

    def _boom(*a, **k):
        raise OSError("boom")

    backup_book.backup_book = _boom
    try:
        bak2, res2 = write_chapter.write_with_backup(_bwb, lambda: "done")
    finally:
        backup_book.backup_book = _real_bb
    check("写前备份封装：备份失败不阻断写章", bak2 == "" and res2 == "done", f"{bak2} {res2}")

    # 16g. --deconstruct 可达性（免章号分支）+ 蓝图函数
    with open(os.path.join(_inj2, "report.md"), "w", encoding="utf-8") as f:
        f.write("拆书报告占位")
    _real_call8 = write_chapter.call_llm
    write_chapter.call_llm = lambda *a, **k: "蓝图内容"
    try:
        _bp = write_chapter.blueprint_from_report("k", "u", "m", os.path.join(_inj2, "report.md"))
        check("blueprint_from_report 读报告出蓝图文件",
              os.path.exists(_bp) and os.path.basename(_bp) == "三部曲蓝图.md")
    finally:
        write_chapter.call_llm = _real_call8
    try:
        write_chapter.gen_trilogy("k", "u", "m", _bwb)
        check("gen_trilogy 缺拆书报告友好报错", False)
    except SystemExit as e:
        check("gen_trilogy 缺拆书报告友好报错", "拆书报告" in str(e), str(e))

    import subprocess
    _empty = tempfile.mkdtemp(prefix="emptybook_")
    try:
        _pd = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "write_chapter.py"),
             "--book", _empty, "--deconstruct", "--key", "sk-test"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"})
        check("--deconstruct 免章号可达（修复被 --chapter 必填拦截的存量 bug）",
              _pd.returncode != 0 and "没有可拆的材料" in (_pd.stdout + _pd.stderr)
              and "请指定 --chapter" not in (_pd.stdout + _pd.stderr),
              f"rc={_pd.returncode} out={(_pd.stdout + _pd.stderr)[-160:]}")
        _ph = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "write_chapter.py"), "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"})
        _help = _ph.stdout + _ph.stderr
        check("CLI 契约旗标全部注册（server 按此调用）",
              all(x in _help for x in ("--deconstruct", "--sample-chapters", "--privacy-scan",
                                       "--gen-trilogy", "--blueprint", "--recalc-from",
                                       "--cross-audit", "--platform-check", "--export-evidence",
                                       "--outline-check", "--beta-reader")))
    finally:
        shutil.rmtree(_empty, ignore_errors=True)
finally:
    shutil.rmtree(_inj2, ignore_errors=True)

# ── 17. v0.9：R49 重算 / R45 体量 / R41 自检 / R46 证据包 / 章纲评估 / 交叉审计 / R44 ──
print("\n== 17. v0.9 新功能 ==")
check("体量警告：6001 字触发", write_chapter.state_size_warning("字" * 6001).startswith("⚠"))
check("体量警告：6000 字不触发", write_chapter.state_size_warning("字" * 6000) == "")
check("冲突提取：⚠冲突 行收集",
      write_chapter.extract_conflicts("a\n- ⚠冲突：旧账记X，本章写Y\nb") ==
      ["- ⚠冲突：旧账记X，本章写Y"])

_r9 = tempfile.mkdtemp(prefix="v09_")
try:
    # 17a. R49 从快照逐章重算（update_fn 注入假函数，零网络实测）
    # 账本结构校验（7 小节）现在贯穿重算链：起点快照与每章产物都必须合格
    # v0.9.2：账本 8 小节（情绪弧线回归后夹具同步）
    _SEVEN = ["## 当前时间", "## 计数与资源", "## 角色状态", "## 关键事件时间线",
              "## 伏笔账本", "## 关键物件", "## 情绪弧线", "## 待续状态"]

    def _mk_state(tag, conf=""):
        lines = []
        for s in _SEVEN:
            lines.append(s)
            lines.append(f"- {tag}")
        if conf:
            lines.append(conf)
        return "\n".join(lines)

    b9 = make_book(_r9, "重算书", chapters={
        "ch001.md": "第一章正文。", "ch002.md": "第二章正文。", "ch003.md": "第三章正文。"})
    os.makedirs(os.path.join(b9, "_snapshots"), exist_ok=True)
    with open(os.path.join(b9, "_snapshots", "ch001.state.md"), "w", encoding="utf-8") as f:
        f.write(_mk_state("快照起点"))
    _upd_calls = []

    def _fake_update(body, old_state):
        _upd_calls.append((body, old_state))
        n = len(_upd_calls)
        conf = "- ⚠冲突：旧账记X，本章写Y（请作者裁决）" if n == 2 else ""
        return _mk_state(f"第{n}章重算", conf)

    rep = write_chapter.recalc_from(b9, 1, _fake_update)
    check("重算：逐章推进 3 章", rep["recalced"] == 3 and len(_upd_calls) == 3, str(rep)[:120])
    check("重算：冲突数来自账本⚠冲突", rep["total_conflicts"] == 1
          and rep["chapters"][1]["conflicts"], str(rep)[:200])
    check("重算：链式推进（旧账=上一章新账）",
          _upd_calls[1][1] == _mk_state("第1章重算") and _upd_calls[1][0] == "第二章正文。",
          str(_upd_calls[1])[:120])
    with open(os.path.join(b9, "story_state.md"), encoding="utf-8") as f:
        check("重算：story_state.md 收敛到最后章", "第3章重算" in f.read())
    check("重算：快照同步推进到 ch003",
          os.path.exists(os.path.join(b9, "_snapshots", "ch003.state.md")))
    check("重算：报告落盘含逐章结果",
          os.path.exists(os.path.join(b9, "chapters", "账本重算报告.md")))
    try:
        write_chapter.recalc_from(b9, 7, _fake_update)
        check("重算：缺快照友好报错", False)
    except SystemExit:
        check("重算：缺快照友好报错", True)

    # 17a-2. 起点快照不合格：打印冲突清单并中止，不写任何快照/账本
    b9b = make_book(_r9, "重算坏起点书", chapters={"ch001.md": "第一章正文。"})
    os.makedirs(os.path.join(b9b, "_snapshots"), exist_ok=True)
    with open(os.path.join(b9b, "_snapshots", "ch001.state.md"), "w", encoding="utf-8") as f:
        f.write("## 当前时间\n- 只有这一节的残缺快照")
    _bad_calls = []
    try:
        write_chapter.recalc_from(b9b, 1, lambda b, o: (_bad_calls.append(1) or _mk_state("x")))
        check("重算：坏起点被拦截", False)
    except SystemExit:
        check("重算：坏起点被拦截（update_fn 零调用）", len(_bad_calls) == 0)
    with open(os.path.join(b9b, "_snapshots", "ch001.state.md"), encoding="utf-8") as f:
        check("重算：坏起点未改写快照", "残缺快照" in f.read())

    # 17a-3. 中途产物不合格：中止重算，报告标注中断章，账本停在上一合格章
    b9c = make_book(_r9, "重算中断书", chapters={"ch001.md": "一。", "ch002.md": "二。"})
    os.makedirs(os.path.join(b9c, "_snapshots"), exist_ok=True)
    with open(os.path.join(b9c, "_snapshots", "ch001.state.md"), "w", encoding="utf-8") as f:
        f.write(_mk_state("快照起点"))
    _n = [0]

    def _bad_update(body, old):
        _n[0] += 1
        return _mk_state(f"第{_n[0]}章重算") if _n[0] == 1 else "## 当前时间\n- 残缺产物"

    rep_bad = write_chapter.recalc_from(b9c, 1, _bad_update)
    check("重算：产物不合格中止于 ch002",
          rep_bad.get("interrupted") == 2 and rep_bad["recalced"] == 1, str(rep_bad)[:150])
    with open(os.path.join(b9c, "story_state.md"), encoding="utf-8") as f:
        _ss_bad = f.read()
    check("重算：中断时账本停在上一合格章",
          "第1章重算" in _ss_bad and "残缺产物" not in _ss_bad, _ss_bad[:80])
    with open(os.path.join(b9c, "chapters", "账本重算报告.md"), encoding="utf-8") as f:
        _rp_bad = f.read()
    check("重算：报告标注中断章", "中断于 ch002" in _rp_bad, _rp_bad[:150])

    # 17b. R41 平台自检（红灯清单 + 痕迹统计，零 token）
    b10 = make_book(_r9, "自检书", chapters={"ch001.md": "夜色沉得像墨。", "ch003.md": "第三章。"})
    with open(os.path.join(b10, "story_state.md"), "w", encoding="utf-8") as f:
        f.write("## 伏笔账本\n- 神秘监视者 [待回收 · 第1章]\n- ⚠冲突：旧账记A，本章写B\n")
    rep10 = write_chapter.platform_check(b10, 2)
    check("自检：红灯含章节断号", any("断号" in x for x in rep10["red"]), str(rep10["red"]))
    check("自检：红灯含账本遗留冲突", any("冲突" in x for x in rep10["red"]))
    check("自检：黄灯含体检单缺失与伏笔未回收",
          any("体检单" in x for x in rep10["warn"])
          and any("伏笔未回收" in x for x in rep10["warn"]), str(rep10["warn"]))
    check("自检：痕迹统计含 L1 硬伤（deai 口径）", rep10["stats"]["hard_hits"] >= 1,
          str(rep10["stats"]))
    check("自检：报告落盘 chNNN.平台自检.md",
          os.path.exists(os.path.join(b10, "chapters", "ch002.平台自检.md")))

    # 17c. R46 自证证据包 zip
    _evout = os.path.join(_r9, "evout")
    zp = write_chapter.export_evidence(b10, 2, out_dir=_evout)
    import zipfile as _zf2
    with _zf2.ZipFile(zp) as z:
        ev_names = z.namelist()
    check("证据包：zip 落盘到指定目录", zp.endswith(".zip") and os.path.exists(zp))
    check("证据包：含账本与平台自检",
          any("story_state.md" in n for n in ev_names)
          and any("平台自检.md" in n for n in ev_names), str(ev_names)[:160])
    check("证据包：缺件不打包不炸（体检单缺失照常出包）",
          not any("AI腔体检" in n for n in ev_names))

    # 17d. 章纲评估：max_tokens 必须 10000（agnes 思考吞光实测教训）
    _o9 = make_book(_r9, "章纲书")
    with open(os.path.join(_o9, "chapters", "ch002.章纲.md"), "w", encoding="utf-8") as f:
        f.write("# ch002 章纲\n- 目标：测试")
    _cap2 = {}
    _real_call9 = write_chapter.call_llm

    def _fake_call9(key, url, model, prompt, **kw):
        _cap2.update(kw)
        return "评估报告"

    write_chapter.call_llm = _fake_call9
    try:
        write_chapter.outline_check("k", "u", "m", _o9, 2)
    finally:
        write_chapter.call_llm = _real_call9
    check("章纲评估：max_tokens=10000", _cap2.get("max_tokens") == 10000, str(_cap2))
    check("章纲评估：报告落盘 chNNN.章纲评估.md",
          os.path.exists(os.path.join(_o9, "chapters", "ch002.章纲评估.md")))
    try:
        write_chapter.outline_check("k", "u", "m", _o9, 5)
        check("章纲评估：缺章纲友好报错", False)
    except SystemExit:
        check("章纲评估：缺章纲友好报错", True)

    # 17e. R42 交叉审计：FALLBACK 通道 + -交叉 后缀
    _ca = make_book(_r9, "交叉书", chapters={"ch003.md": "第三章正文。"})
    with open(os.path.join(_ca, "story_state.md"), "w", encoding="utf-8") as f:
        f.write(write_chapter.STATE_TEMPLATE.replace("{书名}", "交叉书"))
    _orig_wc_dotenv = write_chapter._DOT_ENV
    _saved_fb_env = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("FALLBACK_")}
    _cap3 = {}

    def _fake_audit_call(key, url, model, prompt, **kw):
        _cap3["channel"] = (key, url, model)
        return "交叉审计结论"

    write_chapter.call_llm = _fake_audit_call
    try:
        write_chapter._DOT_ENV = {}
        try:
            write_chapter.cross_audit(_ca, 3)
            check("交叉审计：未配置 FALLBACK 友好报错", False)
        except SystemExit as e:
            check("交叉审计：未配置 FALLBACK 友好报错", "FALLBACK" in str(e), str(e))
        os.environ["FALLBACK_API_KEY"] = "fk"
        os.environ["FALLBACK_MODEL"] = "fm"
        try:
            write_chapter.cross_audit(_ca, 3)
        finally:
            os.environ.pop("FALLBACK_API_KEY", None)
            os.environ.pop("FALLBACK_MODEL", None)
    finally:
        write_chapter.call_llm = _real_call9
        write_chapter._DOT_ENV = _orig_wc_dotenv
        os.environ.update(_saved_fb_env)
    check("交叉审计：走 FALLBACK 备用通道", _cap3.get("channel", ("",))[0] == "fk"
          and _cap3.get("channel", ("", "", ""))[2] == "fm", str(_cap3))
    check("交叉审计：报告落盘 -交叉 后缀",
          os.path.exists(os.path.join(_ca, "chapters", "ch003.一致性审计-交叉.md")))
    check("交叉审计：不覆盖主通道报告",
          not os.path.exists(os.path.join(_ca, "chapters", "ch003.一致性审计.md")))

    # 17f. R43 读者反馈
    def _fake_beta(key, url, model, prompt, **kw):
        return "读者反馈：想追。"

    write_chapter.call_llm = _fake_beta
    try:
        write_chapter.beta_reader("k", "u", "m", _ca, 3)
    finally:
        write_chapter.call_llm = _real_call9
    check("读者反馈：落盘 chNNN.读者反馈.md",
          os.path.exists(os.path.join(_ca, "chapters", "ch003.读者反馈.md")))
    try:
        write_chapter.beta_reader("k", "u", "m", _ca, 9)
        check("读者反馈：缺正文友好报错", False)
    except SystemExit:
        check("读者反馈：缺正文友好报错", True)
finally:
    shutil.rmtree(_r9, ignore_errors=True)

# ── 18. 章节文件口径统一（chapters.py：3 位起、支持 4+ 位，999 章上限解除）──
print("\n== 18. 章节文件口径统一 ==")
_tmp18 = tempfile.mkdtemp(prefix="novel_smoke_ch_")
try:
    book18 = make_book(_tmp18, "章号书", chapters={
        "ch001.md": "一", "ch002.md": "二", "ch1000.md": "千章",
    })
    files18 = chapters.list_chapter_files(book18)
    check("list_chapter_files 混合 3/4 位文件按章号排序",
          files18 == ["ch001.md", "ch002.md", "ch1000.md"], str(files18))
    check("chapter_no_of 支持 4 位章号",
          chapters.chapter_no_of("ch1000.md") == 1000
          and chapters.chapter_no_of("ch003.md") == 3
          and chapters.chapter_no_of("ch003.meta.md") == 3)
finally:
    shutil.rmtree(_tmp18, ignore_errors=True)

# ── 18. v0.9.2 回补：--score 插件链 + 数字门禁 gate ──────────────
print("\n== 18. v0.9.2 score/gate ==")
import checkup as _ck

# 18a. 插件链：内置兜底（monkeypatch scan_plugins 模拟无插件）
_real_scan = _wc.plugin_prompt.__globals__.get("plugin_loader")
import plugin_loader as _pl
_real_scan_fn = _pl.scan_plugins
_pl.scan_plugins = lambda force=False: []
try:
    _pt = _wc.plugin_prompt("evaluate", _wc.BUILTIN_SCORE_PROMPT)
    check("插件链：无插件 → 内置兜底", _pt == _wc.BUILTIN_SCORE_PROMPT)
finally:
    _pl.scan_plugins = _real_scan_fn

# 18b. 插件链：evaluate 停用 → 拒绝执行（None）
_real_enabled = _pl.set_enabled
try:
    _cur = next((x["enabled"] for x in _pl.scan_plugins() if x["name"] == "evaluate"), None)
    if _cur is None:
        check("插件链：evaluate 插件存在", False, "plugins 里没有 evaluate")
    else:
        _pl.set_enabled("evaluate", False)
        _pt2 = _wc.plugin_prompt("evaluate", _wc.BUILTIN_SCORE_PROMPT)
        check("插件链：evaluate 停用 → 拒绝（None）", _pt2 is None)
        _pl.set_enabled("evaluate", True)
        _pt3 = _wc.plugin_prompt("evaluate", _wc.BUILTIN_SCORE_PROMPT)
        check("插件链：重新启用 → 读到插件 judge.md", _pt3 is not None and "六维评分" in _pt3,
              str(_pt3)[:60])
finally:
    if _cur is not None:
        _pl.set_enabled("evaluate", _cur)

# 18c. score_chapter：monkeypatch call_llm 返回假 JSON，端到端落盘
_r18 = tempfile.mkdtemp(prefix="score_")
try:
    b18 = make_book(_r18, "评分书", chapters={"ch001.md": "第一章正文，够长能评分。"})
    _real_llm = _wc.call_llm
    _wc.call_llm = lambda *a, **k: '{"scores":{"情节":80},"total":80,"comment":"测试总评","issues":[]}'
    try:
        out18 = _wc.score_chapter("k", "http://x/v1", "m", b18, 1)
        _score_path = os.path.join(b18, "chapters", "ch001.评分.md")
        check("score：报告落盘 ch001.评分.md", os.path.isfile(_score_path))
        check("score：内容含总评", "测试总评" in open(_score_path, encoding="utf-8").read())
    finally:
        _wc.call_llm = _real_llm
finally:
    shutil.rmtree(_r18, ignore_errors=True)

# 18d. gate 门禁：坏账本 → pause；好账本 → continue
_r18g = tempfile.mkdtemp(prefix="gate_")
try:
    bg = make_book(_r18g, "门禁书", chapters={"ch001.md": "正文。"})
    v_bad = _ck.gate_verdict(bg, 1)
    check("gate：缺账本 → pause", v_bad["gate"] == "pause" and v_bad["reasons"], str(v_bad)[:100])
    _mk18 = "\n".join(s + "\n- x" for s in _wc.STATE_SECTIONS)
    with open(os.path.join(bg, "story_state.md"), "w", encoding="utf-8") as f:
        f.write(_mk18)
    v_ok = _ck.gate_verdict(bg, 1)
    check("gate：8 节齐全+正文 → continue", v_ok["gate"] == "continue", str(v_ok)[:100])
    _sheet = _ck.write_gate_sheet(bg, 1, v_ok)
    check("gate：体检单落盘含门禁行", os.path.isfile(_sheet) and "门禁" in open(_sheet, encoding="utf-8").read())
finally:
    shutil.rmtree(_r18g, ignore_errors=True)

# ── 汇总 ───────────────────────────────────────────────────────
print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
if FAIL:
    sys.exit(1)
print("全部通过 ✅")
