/* 共享 API 工具（React 工作台）
   v0.9.1：所有请求默认 30s 超时（AbortController）——长任务端点传 { timeout: 0 } 关闭；
   api(path, optsOrBody) 兼容两种第二参：带 method/headers/body 键按 fetch opts 处理，否则当请求体。 */

const DEFAULT_TIMEOUT = 30000;

function isOpts(x) {
  return !!x && typeof x === "object" && !Array.isArray(x) &&
    ("method" in x || "headers" in x || "body" in x || "signal" in x || "timeout" in x);
}

async function request(path, opts = {}) {
  const { timeout = DEFAULT_TIMEOUT, ...rest } = opts;
  const ctl = timeout > 0 ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeout) : null;
  try {
    return await fetch(path, { ...rest, signal: ctl ? ctl.signal : rest.signal });
  } catch (e) {
    if (e.name === "AbortError") throw new Error(`请求超时（${Math.round(timeout / 1000)}s），后端可能未响应`);
    throw e;
  } finally { if (timer) clearTimeout(timer); }
}

async function toJson(r) {
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error((d && d.error) || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return d;
}

/* 响应兼容：JSON 对象优先，纯文本包成 { log }（v0.8/v0.9 端点契约是「引擎输出文本」） */
async function parseAny(r) {
  const t = await r.text();
  try { return JSON.parse(t); } catch (e) { return { log: t }; }
}

/* GET（兼容 JSON 与纯文本；错误对象带 .status，如 404=资源不存在） */
export async function apiAny(path, opts = {}) {
  const r = await request(path, opts);
  const d = await parseAny(r);
  if (!r.ok) {
    const err = new Error((d && d.error) || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return d;
}

/* GET（仅 JSON）。第二参可传 fetch opts（method/headers/body/timeout），或直接传请求体 */
export async function api(path, optsOrBody) {
  const opts = isOpts(optsOrBody)
    ? optsOrBody
    : (optsOrBody == null ? {} : { body: typeof optsOrBody === "string" ? optsOrBody : JSON.stringify(optsOrBody) });
  const r = await request(path, opts);
  return toJson(r);
}

export function apiPost(path, body, opts = {}) {
  return request(path, {
    ...opts,
    method: "POST",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    body: JSON.stringify(body || {}),
  }).then(toJson);
}

/* PUT + 原文 body（契约是「引擎输出文本」的端点，如 /api/book/{b}/ch/{no}） */
export async function apiPut(path, body) {
  const r = await request(path, { method: "PUT", body: body ?? "" });
  return toJson(r);
}

/* PUT + JSON 体（契约要求 JSON 的端点：PUT /api/settings {"changes"}、PUT /api/book/{b}/rename {"new"}、PUT /api/rules/{name} {"body"}） */
export function apiPutJson(path, body) {
  return request(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }).then(toJson);
}

/* 从引擎日志抠「[用量] 输入 X / 输出 Y / 总 Z tokens」 */
export function usageFromLog(log) {
  const m = (log || "").match(/\[用量\] 输入 (\d+) \/ 输出 (\d+) \/ 总 (\d+) tokens/);
  return m ? { in: +m[1], out: +m[2], total: +m[3] } : null;
}

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
