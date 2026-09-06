import React, { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";
import { getReportNote, setReportNote } from "../uiStore.js";

/* 技能中心（v0.5）：插件开关 + 体检单/评分报告浏览
   契约：GET /api/plugins → [{name, description, enabled}]
        POST /api/plugins/{name}/toggle {enabled:bool}
        报告走既有 GET /api/book/{b}/files + /api/book/{b}/file/{rel} */

const TONE = { ok: "bg-okbg text-ok", err: "bg-errbg text-err" };

export default function Plugins() {
  const [plugins, setPlugins] = useState(null); // null=加载中
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState("");
  const [reports, setReports] = useState([]);
  const [preview, setPreview] = useState(null); // {file, body}
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [note, setNote] = useState(""); // BookRail 体检单入口跳转携带的报告文件名

  useEffect(() => {
    api("/api/plugins").then((d) => setPlugins(Array.isArray(d) ? d : d.plugins || [])).catch((e) => { setPlugins([]); setErr(e.message); });
    api("/api/books").then((r) => {
      setBooks(r.books || []);
      if ((r.books || []).length) setBook(r.books[0]);
    }).catch(() => {});
    const n = getReportNote();
    if (n) setNote(n);
  }, []);

  // 书内导航跳来：自动定位到对应书的报告文件并打开
  useEffect(() => {
    if (!note) return;
    const [b, f] = note.split("::");
    if (b && f && books.includes(b)) {
      pickBook(b).then(() => openReport(f)).catch(() => {});
      setNote(""); setReportNote("");
    }
  }, [books, note]);

  async function toggle(p) {
    setMsg("");
    try {
      await apiPost(`/api/plugins/${encodeURIComponent(p.name)}/toggle`, { enabled: !p.enabled });
      setPlugins((ps) => ps.map((x) => (x.name === p.name ? { ...x, enabled: !p.enabled } : x)));
      setMsg(`${p.name} 已${!p.enabled ? "启用" : "停用"} ✅`);
    } catch (e) { setMsg(`切换失败：${e.message}`); }
  }

  async function pickBook(name) {
    setBook(name); setReports([]); setPreview(null); setErr("");
    try {
      const d = await api(`/api/book/${encodeURIComponent(name)}/files`);
      setReports((d.files || []).filter((f) => (f.file || f).includes("体检") || (f.file || f).includes("评分") || (f.file || f).includes("审计")));
    } catch (e) { setErr(e.message); }
  }

  async function openReport(file) {
    setPreview(null); setMsg("");
    try {
      const d = await api(`/api/book/${encodeURIComponent(book)}/file/${encodeURIComponent(file)}`);
      setPreview({ file, body: d.content || d.log || String(d) });
    } catch (e) { setMsg(`打开失败：${e.message}`); }
  }

  return (
    <div>
      <h1 className="mb-1 text-xl font-bold text-ink">技能中心</h1>
      <p className="mb-4 text-[13px] text-inksoft">
        引擎的「技能插件」总开关：启用后写作流程会自动调用对应技能（体检、评分等）。下面还能浏览每本书产出的体检单/评分报告。
      </p>

      {msg && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-[13px] text-ink">{msg}</div>}
      {err && <div className="mb-3 rounded-lg bg-warnbg px-4 py-2 text-[13px] text-warn">读取失败：{err}</div>}
      {note && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-info/30 bg-info/10 px-4 py-2 text-[13px] text-ink">
          <span className="text-info">📋 来自书内导航：</span>
          <span className="font-medium">{note.includes("::") ? note.split("::")[1] : note}</span>
          <span className="flex-1" />
          <button onClick={() => { setNote(""); setReportNote(""); }} className="text-[12px] text-inksoft hover:text-ink">关闭</button>
        </div>
      )}

      {/* 插件卡片 */}
      {plugins === null ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">加载中…</div>
      ) : plugins.length === 0 ? (
        <div className="mb-6 rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
          暂无插件（后端 /api/plugins 未就绪或无插件）
        </div>
      ) : (
        <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-2">
          {plugins.map((p) => (
            <div key={p.name} className="flex items-start justify-between gap-3 rounded-xl border border-line bg-panel px-4 py-3.5 shadow-sm">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[14px] font-semibold text-ink">{p.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] ${TONE[p.enabled ? "ok" : "err"]}`}>{p.enabled ? "已启用" : "已停用"}</span>
                </div>
                <div className="mt-1 text-[12.5px] leading-5 text-inksoft">{p.description || "（无描述）"}</div>
              </div>
              <button onClick={() => toggle(p)}
                className={`shrink-0 rounded-lg px-3 py-1.5 text-[13px] ${p.enabled ? "border border-line bg-panel text-inksoft hover:border-err/40 hover:text-err" : "bg-brand text-white hover:bg-brand2"}`}>
                {p.enabled ? "停用" : "启用"}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 体检单/报告浏览 */}
      <h2 className="mb-2 text-[15px] font-bold text-ink">体检单 / 评分报告</h2>
      <div className="mb-3 flex flex-wrap gap-2">
        {books.map((b) => (
          <button key={b} onClick={() => pickBook(b)}
            className={`rounded-lg px-3 py-1.5 text-[13px] ${b === book ? "bg-brand text-white" : "border border-line bg-panel hover:border-ink/30"}`}>
            {b}
          </button>
        ))}
        {books.length === 0 && <span className="text-[13px] text-inksoft">（暂无书）</span>}
      </div>
      {reports.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-6 text-center text-sm text-inksoft">
          {book ? "这本书暂无体检单/评分报告（先在「章节与账本」跑一次体检/审计）" : "选一本书查看报告"}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {reports.map((f, i) => {
            const file = typeof f === "string" ? f : f.file;
            return (
              <button key={i} onClick={() => openReport(file)}
                className="rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-ink hover:border-ink/40">
                📄 {file}
              </button>
            );
          })}
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-6" onClick={() => setPreview(null)}>
          <div className="flex max-h-[80vh] w-full max-w-3xl flex-col rounded-xl bg-panel shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="text-[14px] font-semibold text-ink">{preview.file}</span>
              <button onClick={() => setPreview(null)} className="rounded-lg px-2 py-1 text-[13px] text-inksoft hover:bg-paper">关闭 ✕</button>
            </div>
            <pre className="flex-1 overflow-auto whitespace-pre-wrap px-4 py-3 text-[12.5px] leading-6 text-ink">{preview.body}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
