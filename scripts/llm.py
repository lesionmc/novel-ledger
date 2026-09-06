# -*- coding: utf-8 -*-
"""llm.py —— LLM 通道公共层（纯标准库，非流式 + 流式）

职责：把「OpenAI 兼容 chat/completions」的请求发送、重试、主备切换收敛到一处，
供 Web 聊天（SSE 流式）与后续脚本复用。约定：

- post_chat        非流式：发一次 POST，返回解析后的 JSON dict。
- post_chat_stream 流式底层：强制 stream=True，逐行解析 SSE，yield 文本增量。
- chat_stream      流式门面：首 token 前失败按线性退避重试、重试耗尽切备用通道；
                   已吐字后中断抛 StreamInterrupted 直接上抛——绝不重试、绝不切备用
                   （流式重发会让用户看到重复正文，宁可断在明处）。

配置链：参数 > 环境变量 > 项目根 .env > 内置默认（与 write_chapter/deai 同款 env_or）。
"""
import json
import os
import sys
import time
import urllib.request

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1/"
DEFAULT_MODEL = "agnes-2.5-flash"


def load_dotenv(path):
    """极简 .env 读取：每行 key=value，# 开头为注释。不存在则返回空。"""
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


# ---------------------------------------------------------------- 非流式
def post_chat(base_url, api_key, payload, timeout=240):
    """发一次 chat/completions POST（非流式），返回解析后的 JSON dict。
    header/key 处理方式与流式版本保持一致，便于 failover 时整体换通道。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- 嵌入（R39 向量层）
def post_embed(text, *, base_url=None, api_key=None, model=None, timeout=120):
    """调 /embeddings（OpenAI 兼容）返回向量。

    - text 为 str → 返回 list[float]；为 list[str] → 返回 [list[float], ...]
      （批量口 dipl 含义按 OpenAI 协议：data[].index 对齐输入顺序）。
    - 配置链：参数 > EMBED_API_KEY / EMBED_MODEL 环境变量 / 项目根 .env；
      EMBED_BASE_URL 未配置时回落 AGNES_BASE_URL，再回落内置默认。
    - EMBED_API_KEY 或 EMBED_MODEL 缺失 → 抛友好 ValueError（向量层是可选件，
      调用方应捕获后降级，绝不让它阻断写章主流程）。
    """
    api_key = api_key or env_or("EMBED_API_KEY", "EMBED_API_KEY", "")
    model = model or env_or("EMBED_MODEL", "EMBED_MODEL", "")
    if not api_key or not model:
        raise ValueError(
            "嵌入通道未配置：请在项目根 .env（或环境变量）设置 EMBED_API_KEY 与 "
            "EMBED_MODEL（可选 EMBED_BASE_URL，缺省回落 AGNES_BASE_URL）。"
            "未配置时向量召回层（R39）会自动降级，不影响写作主流程。")
    base_url = (base_url
                or env_or("EMBED_BASE_URL", "EMBED_BASE_URL", "")
                or env_or("AGNES_BASE_URL", "AGNES_BASE_URL", DEFAULT_BASE_URL))
    single = isinstance(text, str)
    texts = [text] if single else [t for t in text]
    payload = {"model": model, "input": texts}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    vecs = [d.get("embedding") or [] for d in items]
    return vecs[0] if single else vecs


# ---------------------------------------------------------------- 流式
class StreamInterrupted(Exception):
    """流式吐字后通道中断（首 token 之后断流/未收到 [DONE]）。
    专用异常：调用方与重试逻辑都不得对它重试或切备用——重发等于正文重复。"""


def _build_stream_request(base_url, api_key, payload):
    """构造流式请求（与 post_chat 同款 header/key 处理），payload 强制 stream=True。"""
    payload = dict(payload)
    payload["stream"] = True
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )


def post_chat_stream(base_url, api_key, payload, timeout=240):
    """流式调 chat/completions（SSE），yield 文本增量（str）。

    解析规则：只认 data: 行；[DONE] 结束；取 choices[0].delta.content。
    usage：任一分帧带 usage 就记一笔流水（有则记无则跳过），失败不影响输出。
    异常语义：首 token 前异常原样上抛（交给 chat_stream 重试/切换）；
    已吐字后异常（或流没等到 [DONE] 就断）包装为 StreamInterrupted 上抛。
    """
    req = _build_stream_request(base_url, api_key, payload)
    model = payload.get("model", "")
    yielded = 0
    done = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue  # SSE 注释行 / 空行 / event: 行一律跳过
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue  # 分帧残缺：跳过该帧，不让半截 JSON 炸掉整条流
                choices = obj.get("choices") or []
                delta = (choices[0].get("delta") or {}) if choices else {}
                piece = delta.get("content")
                if piece:
                    yielded += 1
                    yield piece
                usage = obj.get("usage")
                if usage:
                    try:
                        import usage_log
                        usage_log.log_usage(usage_log.ACTION_STREAM, model,
                                            usage.get("prompt_tokens"),
                                            usage.get("completion_tokens"))
                    except Exception:
                        pass  # 记账失败绝不影响主流程（R48 设计约束）
    except StreamInterrupted:
        raise
    except Exception as e:
        if yielded:
            raise StreamInterrupted(
                f"流式输出中断（已吐 {yielded} 段后断流）：{type(e).__name__}: {e}") from e
        raise  # 首 token 前失败：保持原始异常，交上层重试
    if yielded and not done:
        # 流静默结束但没收到 [DONE]：与中途断流同等对待（内容可能不完整）
        raise StreamInterrupted(f"流式输出中断（吐字 {yielded} 段后未收到 [DONE]）")


def _log_stream_ms(model, elapsed_ms):
    """记流式吐字时长（首 token → [DONE]）。失败不影响输出。"""
    try:
        import usage_log
        usage_log.log_usage(usage_log.ACTION_STREAM, model, None, None, elapsed_ms=elapsed_ms)
    except Exception:
        pass


def chat_stream(messages, *, model=None, base_url=None, api_key=None,
                max_retries=1, fallback_key=None, fallback_base_url=None,
                fallback_model=None, temperature=None, max_tokens=None, timeout=240):
    """流式对话生成器：yield 文本增量。

    - 失败语义（仅限首 token 前）：线性退避 attempt*5 秒重试 max_retries 次，
      重试耗尽切备用通道（换 base_url + key + model）；备用优先级：
      显式参数 > FALLBACK_API_KEY / FALLBACK_BASE_URL / FALLBACK_MODEL。
    - 已吐字后中断：StreamInterrupted 直接上抛，不重试、不切备用。
    - 主/备都失败：抛 RuntimeError 汇总最后一次错误。
    """
    model = model or env_or("AGNES_MODEL", "AGNES_MODEL", DEFAULT_MODEL)
    base_url = base_url or env_or("AGNES_BASE_URL", "AGNES_BASE_URL", DEFAULT_BASE_URL)
    api_key = api_key or env_or("AGNES_API_KEY", "AGNES_API_KEY", "")

    fb_key = fallback_key or env_or("FALLBACK_API_KEY", "FALLBACK_API_KEY", "")
    fb_model = fallback_model or env_or("FALLBACK_MODEL", "FALLBACK_MODEL", "")
    fb_url = fallback_base_url or env_or("FALLBACK_BASE_URL", "FALLBACK_BASE_URL", "")

    payload = {"messages": list(messages)}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    channels = [(api_key, base_url, model, "主通道")]
    if fb_key and fb_model:
        channels.append((fb_key, fb_url or base_url, fb_model, "备用通道"))

    last_err = ""
    for ch_key, ch_url, ch_model, label in channels:
        payload["model"] = ch_model  # 切通道必须连模型名一起换（防 H1 复发）
        for attempt in range(max_retries + 1):
            if attempt > 0:
                wait = attempt * 5
                print(f"  ⚠ {label} 第 {attempt} 次重试（等待 {wait}s）...", file=sys.stderr)
                time.sleep(wait)
            try:
                got_first = False
                t0 = time.perf_counter()
                for piece in post_chat_stream(ch_url, ch_key, payload, timeout=timeout):
                    if not got_first:
                        got_first = True
                        print(f"[流式] {label} {ch_model} 开始输出...", file=sys.stderr)
                    yield piece
                if got_first:
                    _log_stream_ms(ch_model, (time.perf_counter() - t0) * 1000)
                return  # 正常走完一条通道即成功
            except StreamInterrupted:
                raise  # 已吐字后中断：绝不重试、绝不切备用
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                print(f"  ⚠ {label} 请求异常：{last_err}", file=sys.stderr)
                continue  # 首 token 前失败：进入下一次重试
    raise RuntimeError(f"流式对话失败（重试 {max_retries} 次后放弃）：{last_err}")
