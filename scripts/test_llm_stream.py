# -*- coding: utf-8 -*-
"""test_llm_stream.py —— llm.py 流式通道专项测试（零网络、零第三方依赖）

monkeypatch urllib.request.urlopen 返回假 SSE 流，覆盖：
  SSE 解析/拼接、stream=True 强制、Authorization 头
  failover 换模型名、重试计数、StreamInterrupted 不重试不切备用
  FALLBACK_* 环境变量生效、usage/elapsed_ms 记账打桩

运行：python scripts/test_llm_stream.py（失败退出码 1）
"""
import inspect
import json
import os
import sys
import urllib.request

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)

import llm        # noqa: E402
import usage_log  # noqa: E402

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


# ── 假 SSE 基建 ────────────────────────────────────────────────
class FakeStream:
    """可迭代字节行的上下文管理器；boom 在吐完 lines 后抛（模拟吐字中断）。"""

    def __init__(self, lines, boom=None):
        self.lines = lines
        self.boom = boom

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        yield from self.lines
        if self.boom:
            raise self.boom


CALLS = []          # [(url, payload_dict, auth_header)]
BEHAVIORS = []      # 每次 urlopen 弹出一个行为：Exception → raise；否则当 FakeStream lines


def fake_urlopen(req, timeout=None):
    payload = json.loads(req.data.decode("utf-8"))
    CALLS.append((req.full_url, payload, req.get_header("Authorization")))
    b = BEHAVIORS.pop(0)
    if isinstance(b, Exception):
        raise b
    return FakeStream(b)


def sse(*deltas, usage=None, done=True):
    """构造 SSE 分帧字节行列表。"""
    lines = []
    for d in deltas:
        obj = {"choices": [{"delta": {"content": d}}]}
        lines.append(("data: " + json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        lines.append(b"\n")
    if usage:
        lines.append(("data: " + json.dumps({"choices": [], "usage": usage},
                                            ensure_ascii=False) + "\n").encode("utf-8"))
        lines.append(b"\n")
    if done:
        lines.append(b"data: [DONE]\n\n")
    return lines


def drain(gen):
    """消费生成器；返回 (文本增量列表, 捕获的异常)。"""
    pieces, err = [], None
    try:
        for p in gen:
            pieces.append(p)
    except Exception as e:
        err = e
    return pieces, err


_real_urlopen = urllib.request.urlopen
_real_sleep = llm.time.sleep
llm.time.sleep = lambda s: None  # 重试退避不等真 5s
urllib.request.urlopen = fake_urlopen

# ── 1. SSE 解析 / 拼接 / 请求形态 ─────────────────────────────
print("== 1. SSE 解析与请求形态 ==")
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.append(sse("你好", "，世界"))
pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                    base_url="http://主/v1", api_key="k1", model="主模型",
                                    max_retries=0))
check("SSE 解析拼接完整", err is None and "".join(pieces) == "你好，世界",
      f"{pieces} {err}")
check("yield 的是逐段文本增量", len(pieces) == 2, str(len(pieces)))
check("payload 强制 stream=True", CALLS and CALLS[0][1].get("stream") is True,
      str(CALLS[0][1] if CALLS else None))
check("Authorization: Bearer <key>", CALLS and CALLS[0][2] == "Bearer k1",
      str(CALLS[0][2] if CALLS else None))

# ── 2. failover：主通道挂 → 备用换 URL+key+model ──────────────
print("\n== 2. failover 换模型名 ==")
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.append(OSError("主通道模拟故障"))
BEHAVIORS.append(sse("备用正文"))
pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                    base_url="http://主/v1", api_key="主key", model="主模型",
                                    max_retries=0,
                                    fallback_key="备key", fallback_base_url="http://备/v1",
                                    fallback_model="备模型"))
check("主挂后备用返回正文", err is None and "".join(pieces) == "备用正文", str(err))
check("备用请求换了备用 URL 与备用模型名",
      len(CALLS) == 2 and CALLS[1][0].startswith("http://备/v1") and CALLS[1][1]["model"] == "备模型",
      str([(c[0], c[1].get("model")) for c in CALLS]))
check("备用请求带备用 key", CALLS[1][2] == "Bearer 备key", str(CALLS[1][2]))

# ── 3. 重试计数（线性退避 attempt*5） ─────────────────────────
print("\n== 3. 重试计数 ==")
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.extend([OSError("x"), OSError("x"), sse("第三次成功")])
pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                    base_url="http://主/v1", api_key="k", model="m",
                                    max_retries=2))
check("失败 2 次后第 3 次成功（共 3 次尝试）", err is None and len(CALLS) == 3,
      str(len(CALLS)))
check("重试都在主通道（未提前切备用）",
      all(c[0].startswith("http://主/v1") for c in CALLS))

# ── 4. StreamInterrupted：吐字后中断 → 不重试不切备用 ─────────
print("\n== 4. StreamInterrupted ==")
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.append(FakeStream(sse("第一段", done=False), boom=OSError("吐字后断流")))
pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                    base_url="http://主/v1", api_key="k", model="m",
                                    max_retries=1,
                                    fallback_key="bk", fallback_base_url="http://备/v1",
                                    fallback_model="备模型"))
check("吐字后中断抛 StreamInterrupted", isinstance(err, llm.StreamInterrupted), repr(err))
check("不重试不切备用（仅主通道 1 次请求）", len(CALLS) == 1, str(len(CALLS)))
check("已吐出的增量保留在消费端", pieces == ["第一段"], str(pieces))

# ── 5. 未收到 [DONE] 静默断流同判中断 ─────────────────────────
print("\n== 5. 缺 [DONE] ==")
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.append(sse("半截", done=False))
pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                    base_url="http://主/v1", api_key="k", model="m",
                                    max_retries=0))
check("流结束无 [DONE] → StreamInterrupted", isinstance(err, llm.StreamInterrupted), repr(err))

# ── 6. FALLBACK_* 环境变量生效 ────────────────────────────────
print("\n== 6. FALLBACK_* 环境变量 ==")
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.append(OSError("主挂"))
BEHAVIORS.append(sse("环境变量备用成功"))
_env = {k: os.environ.get(k) for k in ("AGNES_API_KEY", "AGNES_BASE_URL", "AGNES_MODEL",
                                       "FALLBACK_API_KEY", "FALLBACK_BASE_URL", "FALLBACK_MODEL")}
os.environ.update({"AGNES_API_KEY": "env主key", "AGNES_BASE_URL": "http://env主/v1",
                   "AGNES_MODEL": "env主模型", "FALLBACK_API_KEY": "env备key",
                   "FALLBACK_BASE_URL": "http://env备/v1", "FALLBACK_MODEL": "env备模型"})
try:
    pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}], max_retries=0))
    check("环境变量主通道生效（首请求带 env 主模型）",
          CALLS and CALLS[0][1]["model"] == "env主模型"
          and CALLS[0][0].startswith("http://env主/v1"),
          str([(c[0], c[1].get("model")) for c in CALLS]))
    check("环境变量备用通道生效", err is None and "".join(pieces) == "环境变量备用成功"
          and CALLS[1][0].startswith("http://env备/v1") and CALLS[1][1]["model"] == "env备模型",
          str([(c[0], c[1].get("model")) for c in CALLS]))
finally:
    for k, v in _env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

# ── 7. 记账：elapsed_ms > 0 且 usage 记流水 ───────────────────
print("\n== 7. usage_log 打桩 ==")
LOG = []
_real_log = usage_log.log_usage
usage_log.log_usage = lambda *a, **kw: LOG.append((a, kw))
try:
    CALLS.clear()
    BEHAVIORS.clear()
    BEHAVIORS.append(sse("记账正文", usage={"prompt_tokens": 11, "completion_tokens": 22,
                                            "total_tokens": 33}))
    pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                        base_url="http://主/v1", api_key="k", model="m",
                                        max_retries=0))
    check("流式正常完成无异常", err is None, repr(err))
    dur = [kw.get("elapsed_ms") for a, kw in LOG if kw.get("elapsed_ms") is not None]
    check("记流式吐字时长且 elapsed_ms > 0", bool(dur) and dur[0] > 0, str(LOG))
    check("时长记账 action=流式对话",
          any(a and a[0] == "流式对话" for a, kw in LOG), str(LOG))
    tok = [a for a, kw in LOG if len(a) >= 4 and a[2] == 11 and a[3] == 22]
    check("SSE usage 帧记 token 流水（有则记）", bool(tok), str(LOG))
finally:
    usage_log.log_usage = _real_log

# usage 缺省时「无则跳过」
LOG.clear()
CALLS.clear()
BEHAVIORS.clear()
BEHAVIORS.append(sse("无usage"))
usage_log.log_usage = lambda *a, **kw: LOG.append((a, kw))
try:
    pieces, err = drain(llm.chat_stream([{"role": "user", "content": "hi"}],
                                        base_url="http://主/v1", api_key="k", model="m",
                                        max_retries=0))
    check("无 usage 帧：不记 token 流水（只记时长或全部跳过）",
          err is None and all(not (len(a) >= 4 and isinstance(a[2], int)) for a, kw in LOG),
          str(LOG))
finally:
    usage_log.log_usage = _real_log

urllib.request.urlopen = _real_urlopen
llm.time.sleep = _real_sleep

print(f"\n{'=' * 40}\n结果：{PASS} 通过 / {FAIL} 失败")
if FAIL:
    sys.exit(1)
print("全部通过 ✅")
