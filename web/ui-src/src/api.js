/* 共享 API 工具（React 工作台） */
export async function api(path) {
  const r = await fetch(path);
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

export async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

export async function apiPut(path, body) {
  const r = await fetch(path, { method: "PUT", body: body ?? "" });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

/* 从引擎日志抠「[用量] 输入 X / 输出 Y / 总 Z tokens」 */
export function usageFromLog(log) {
  const m = (log || "").match(/\[用量\] 输入 (\d+) \/ 输出 (\d+) \/ 总 (\d+) tokens/);
  return m ? { in: +m[1], out: +m[2], total: +m[3] } : null;
}

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
