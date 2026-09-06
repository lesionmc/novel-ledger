import React, { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";

/* 任务中心（v0.9.1 契约重写）：真实连写任务聚合
   契约：GET /api/tasks → {"tasks":[{id,book,status,start,count,done:[{no,chars,…}|章号],failed:[…],updated}]}
        status 拼写为 "cancelled"（兼容旧 "canceled"）
        POST /api/book/{b}/task/start  {"count":N,"confirmed":true}
        POST /api/book/{b}/task/control {"id","action":"continue"|"cancel"} */

const TONE = {
  running: "bg-brandbg text-ink", done: "bg-okbg text-ok", failed: "bg-errbg text-err",
  paused: "bg-warnbg text-warn", cancelled: "bg-line/60 text-inksoft", canceled: "bg-line/60 text-inksoft", pending: "bg-brandbg text-ink",
};
const LABEL = { running: "运行中", done: "已完成", failed: "失败", paused: "已暂停", cancelled: "已取消", canceled: "已取消", pending: "排队中" };
const norm = (s) => (s ? String(s).toLowerCase() : "pending");

/* done/failed 数组兼容两种元素：{no,chars,…} 对象 或 章号数字 */
const noOf = (x) => (x && typeof x === "object" ? x.no : x);

function toTasks(d) {
  if (d && Array.isArray(d.tasks)) return d.tasks.filter((t) => t && typeof t === "object");
  if (Array.isArray(d)) return d.filter((t) => t && typeof t === "object");
  return [];
}

export default function Tasks() {
  const [tasks, setTasks] = useState(null);
  const [books, setBooks] = useState([]);
  const [nb, setNb] = useState("");      // 新建：选书
  const [count, setCount] = useState(5); // 新建：章数
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    try {
      const d = await api("/api/tasks");
      setTasks(toTasks(d));
    } catch (e) { setTasks([]); setErr(e.message); }
  }

  useEffect(() => {
    load();
    api("/api/books").then((r) => {
      setBooks(r.books || []);
      if ((r.books || []).length) setNb(r.books[0]);
    }).catch(() => {});
  }, []);

  async function control(t, action) {
    setBusy(t.id + action); setMsg(""); setErr("");
    try {
      await apiPost(`/api/book/${encodeURIComponent(t.book)}/task/control`, { id: t.id, action });
      setMsg(`任务 ${t.id} 已${action === "continue" ? "继续" : "取消"} ✅`);
      await load();
    } catch (e) { setErr(`操作失败：${e.message}`); }
    finally { setBusy(""); }
  }

  async function start() {
    const n = parseInt(count);
    if (!nb || !n || n < 1) { setErr("请先选书并填写章数（≥1）"); return; }
    if (n > 10 && !window.confirm(`连写 ${n} 章耗时较长且消耗较多 tokens，确定继续？`)) return;
    setBusy("start"); setMsg(""); setErr("");
    try {
      await apiPost(`/api/book/${encodeURIComponent(nb)}/task/start`, { count: n, confirmed: true });
      setMsg(`已提交连写任务：${nb} · ${n} 章 ✅`);
      await load();
    } catch (e) { setErr(`提交失败：${e.message}`); }
    finally { setBusy(""); }
  }

  const stat = { running: 0, done: 0, failed: 0 };
  (tasks || []).forEach((t) => { const s = norm(t.status); if (stat[s] != null) stat[s]++; });
  // 按书分组展示
  const byBook = {};
  for (const t of tasks || []) {
    const b = t.book || "（未知书）";
    (byBook[b] = byBook[b] || []).push(t);
  }

  return (
    <div>
      <h1 className="mb-1 text-xl font-bold text-ink">任务中心</h1>
      <p className="mb-4 text-[13px] text-inksoft">
        所有书的「连续写章」任务都在这里：看进度、失败了继续跑、不想跑了就取消。也可以在下面直接新建一个连写任务。
      </p>

      {/* 统计条 */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-brandbg px-3 py-1 text-xs text-ink">运行中 × {stat.running}</span>
        <span className="rounded-full bg-okbg px-3 py-1 text-xs text-ok">已完成 × {stat.done}</span>
        <span className="rounded-full bg-errbg px-3 py-1 text-xs text-err">失败 × {stat.failed}</span>
        <button onClick={load} className="ml-2 rounded-lg border border-line bg-panel px-3 py-1 text-xs text-inksoft hover:border-ink/30">刷新</button>
      </div>

      {msg && <div className="mb-3 rounded-lg bg-okbg px-4 py-2 text-[13px] text-ok">{msg}</div>}
      {err && <div className="mb-3 rounded-lg bg-warnbg px-4 py-2 text-[13px] text-warn">{err}</div>}

      {/* 任务列表 */}
      {tasks === null ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">加载中…</div>
      ) : tasks.length === 0 ? (
        <div className="mb-6 rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
          暂无任务（还没有提交过连写）
        </div>
      ) : (
        <div className="mb-6 space-y-2">
          {Object.entries(byBook).map(([b, ts]) => (
            <div key={b}>
              <div className="mb-1 mt-3 text-[13px] font-semibold text-ink">📚 {b}</div>
              {ts.map((t, i) => {
                const s = norm(t.status);
                const doneNos = Array.isArray(t.done) ? t.done.map(noOf).filter((x) => x != null) : [];
                const failNos = Array.isArray(t.failed) ? t.failed.map(noOf).filter((x) => x != null) : [];
                const start = parseInt(t.start) || null;
                const end = start && t.count ? start + parseInt(t.count) - 1 : null;
                const total = parseInt(t.count) || null;
                const pct = total ? Math.min(100, Math.max(0, Math.round((doneNos.length / total) * 100))) : 0;
                return (
                  <div key={t.id || i} className="rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={`rounded-full px-2.5 py-0.5 text-[11px] ${TONE[s] || TONE.pending}`}>{LABEL[s] || s}</span>
                          <span className="text-[13.5px] text-ink">{t.id || `任务 ${i + 1}`}</span>
                          {start && <span className="text-[12.5px] text-inksoft">第 {start} 章{end && end !== start ? ` → 第 ${end} 章` : ""}</span>}
                        </div>
                        <div className="mt-0.5 text-[12.5px] text-inksoft">
                          进度：{total ? `${doneNos.length} / ${total} 章` : `${doneNos.length} 章`}{failNos.length ? ` · 失败 ${failNos.length}` : ""}
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        {(s === "paused" || s === "failed" || s === "cancelled" || s === "canceled") && (
                          <button disabled={!!busy} onClick={() => control(t, "continue")}
                            className="rounded-lg bg-brand px-3 py-1.5 text-[13px] text-white hover:bg-brand2 disabled:opacity-50">继续</button>
                        )}
                        {(s === "running" || s === "pending" || s === "paused") && (
                          <button disabled={!!busy} onClick={() => control(t, "cancel")}
                            className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-err hover:border-err/40 disabled:opacity-50">取消</button>
                        )}
                      </div>
                    </div>
                    {/* 进度条：按 done 数 / count；overflow-hidden 防溢出，宽度封顶 100% */}
                    {total ? (
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-line">
                        <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${pct}%` }} />
                      </div>
                    ) : null}
                    {failNos.length > 0 && (
                      <div className="mt-1.5 text-[11.5px] text-err">失败章节：{failNos.map(String).join("、")}</div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {/* 新建连写 */}
      <h2 className="mb-2 text-[15px] font-bold text-ink">新建连写任务</h2>
      <div className="rounded-xl border border-line bg-panel p-4 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[13px] text-inksoft">
            书
            <select value={nb} onChange={(e) => setNb(e.target.value)}
              className="mt-1 block w-56 rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-ink">
              {books.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
          <label className="text-[13px] text-inksoft">
            章数
            <input type="number" min="1" value={count} onChange={(e) => setCount(e.target.value)}
              className="mt-1 block w-24 rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-ink" />
          </label>
          <button onClick={start} disabled={!!busy || !nb}
            className="rounded-lg bg-brand px-4 py-2 text-[13px] text-white hover:bg-brand2 disabled:opacity-50">
            {busy === "start" ? "提交中…" : "开始连写"}
          </button>
        </div>
        <p className="mt-2 text-xs text-inksoft/80">超过 10 章会弹确认（耗时与 token 消耗较大）。任务提交后可随时在上面继续/取消。</p>
      </div>
    </div>
  );
}
