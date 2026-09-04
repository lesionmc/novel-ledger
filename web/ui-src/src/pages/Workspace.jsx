import React, { useEffect, useState } from "react";
import { api, apiPost, apiPut, usageFromLog, fmt } from "../api.js";

/* 章节与账本页（工作台核心）：书树 | 编辑器/报告 | 动作面板 */

const DOCS = ["设定", "角色卡", "大纲", "state"];
const DOC_LABEL = { 设定: "📄 设定.md", 角色卡: "👤 角色卡.md", 大纲: "🗺 大纲.md", state: "📒 记忆账本" };

export default function Workspace() {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(null);        // 当前书名
  const [info, setInfo] = useState(null);        // /api/book/{name}
  const [reports, setReports] = useState([]);    // 产物文件
  const [sel, setSel] = useState(null);          // {kind:'ch'|'doc'|'report', no?, doc?, file?}
  const [body, setBody] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [log, setLog] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => { api("/api/books").then((r) => setBooks(r.books)).catch(() => {}); }, []);

  async function openBook(name) {
    setBook(name); setSel(null); setBody(""); setLog("");
    try {
      const d = await api(`/api/book/${encodeURIComponent(name)}`);
      setInfo(d);
      try {
        const fd = await api(`/api/book/${encodeURIComponent(name)}/files`);
        setReports((fd.files || []).filter((f) => f.file.includes("体检") || f.file.includes("审计") || f.file.endsWith(".diff.json")));
      } catch (e) { setReports([]); }
    } catch (e) { setMsg(e.message); }
  }

  async function openSel(s) {
    setSel(s); setLog(""); setMsg("");
    try {
      if (s.kind === "ch") setBody((await api(`/api/book/${encodeURIComponent(book)}/ch/${s.no}`)).content);
      else if (s.kind === "doc") setBody((await api(`/api/book/${encodeURIComponent(book)}/doc/${s.doc}`)).content);
      else setBody((await api(`/api/book/${encodeURIComponent(book)}/file/${encodeURIComponent(s.file)}`)).content);
      setDirty(false);
    } catch (e) { setMsg(e.message); }
  }

  async function save() {
    if (!sel || busy) return;
    try {
      if (sel.kind === "ch") await apiPut(`/api/book/${encodeURIComponent(book)}/ch/${sel.no}`, body);
      else if (sel.kind === "doc") await apiPut(`/api/book/${encodeURIComponent(book)}/doc/${sel.doc}`, body);
      else return;
      setDirty(false); setMsg("已保存 ✅");
    } catch (e) { setMsg("保存失败：" + e.message); }
  }

  async function run(action, fn) {
    if (busy) return;
    if (sel && sel.kind === "ch") await save().catch(() => {});
    setBusy(action); setLog(""); setMsg("");
    try {
      const d = await fn();
      setLog(d.log || d.report || "");
      const u = usageFromLog(d.log);
      setMsg(`${action}完成 ✅` + (u ? ` · 消耗 ${fmt(u.total)} tokens（入 ${fmt(u.in)} / 出 ${fmt(u.out)}）` : ""));
      if (action === "写下一章") { await openBook(book); setSel({ kind: "ch", no: d.no }); setBody(d.body || ""); setDirty(false); }
      if (action === "一致性审计") setSel({ kind: "report", file: `chapters/ch${String(d.no).padStart(3, "0")}.一致性审计.md` });
      if (action === "去味精判") { setSel({ kind: "report", file: `chapters/ch${String(d.no).padStart(3, "0")}.AI腔体检.md` }); }
      if (action === "应用改写") { await openBook(book); setSel({ kind: "ch", no: d.no || (sel && sel.no) }); }
    } catch (e) { setMsg(`${action}失败：${e.message}`); }
    finally { setBusy(""); }
  }

  const chapterNo = sel && sel.kind === "ch" ? sel.no : null;
  const actions = [
    { label: "✍ 写下一章", primary: true, fn: () => run("写下一章", () => apiPost(`/api/book/${encodeURIComponent(book)}/write`, {})), need: null },
    { label: "🧾 一致性审计", fn: () => run("一致性审计", () => apiPost(`/api/book/${encodeURIComponent(book)}/audit`, { no: chapterNo })), need: "ch" },
    { label: "🔬 全书体检", fn: () => run("全书体检", () => apiPost(`/api/book/${encodeURIComponent(book)}/scan`, {})), need: null },
    { label: "🪄 去味精判", fn: () => run("去味精判", () => apiPost(`/api/book/${encodeURIComponent(book)}/polish`, { no: chapterNo })), need: "ch" },
    { label: "✂️ 应用改写", fn: () => { if (confirm("应用改写会修改正文（自动备份到 .bak.md）。继续？")) return run("应用改写", () => apiPost(`/api/book/${encodeURIComponent(book)}/apply`, { no: chapterNo })); }, need: "ch" },
  ];

  function title() {
    if (!sel) return book ? "从左侧选择章节或文档" : "从左侧选择一本书";
    if (sel.kind === "ch") return `ch${String(sel.no).padStart(3, "0")}.md · ${fmt(body.length)} 字`;
    if (sel.kind === "doc") return DOC_LABEL[sel.doc] + ` · ${fmt(body.length)} 字`;
    return "🧾 " + sel.file.replace("chapters/", "");
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold text-brand">章节与账本</h1>
      <p className="mb-4 text-sm text-inksoft">写章 → 审计 → 去味 → 定稿，全在这一个工作台里。AI 是笔，你是作者。</p>
      {msg && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-sm text-brand">{msg}</div>}

      <div className="grid grid-cols-12 gap-4">
        {/* 左：书/章节/产物 树 */}
        <div className="col-span-3 rounded-xl border border-line bg-panel p-3 shadow-sm">
          <div className="mb-1 text-xs font-semibold text-inksoft">📚 我的书</div>
          {books.map((b) => (
            <div key={b} onClick={() => openBook(b)}
              className={`cursor-pointer rounded-md px-2 py-1 text-sm ${b === book ? "bg-brandbg font-semibold text-brand" : "hover:bg-line/40"}`}>
              📖 {b}
            </div>
          ))}
          {book && info && (
            <>
              <div className="mb-1 mt-3 text-xs font-semibold text-inksoft">📑 章节（{info.chapters.length}）</div>
              {info.chapters.map((c) => (
                <div key={c.no} onClick={() => openSel({ kind: "ch", no: c.no })}
                  className={`cursor-pointer rounded-md px-2 py-1 text-[13px] ${sel && sel.kind === "ch" && sel.no === c.no ? "bg-brandbg text-brand" : "hover:bg-line/40"}`}>
                  ch{String(c.no).padStart(3, "0")}
                </div>
              ))}
              <div className="mb-1 mt-3 text-xs font-semibold text-inksoft">📄 文档</div>
              {DOCS.map((d) => (
                <div key={d} onClick={() => openSel({ kind: "doc", doc: d })}
                  className={`cursor-pointer rounded-md px-2 py-1 text-[13px] ${sel && sel.kind === "doc" && sel.doc === d ? "bg-brandbg text-brand" : "hover:bg-line/40"}`}>
                  {DOC_LABEL[d]}
                </div>
              ))}
              {reports.length > 0 && (
                <>
                  <div className="mb-1 mt-3 text-xs font-semibold text-inksoft">🧾 报告/产物</div>
                  <div className="max-h-40 overflow-auto">
                    {reports.map((f) => (
                      <div key={f.file} onClick={() => openSel({ kind: "report", file: f.file })}
                        className={`cursor-pointer rounded-md px-2 py-1 text-[12px] ${sel && sel.kind === "report" && sel.file === f.file ? "bg-brandbg text-brand" : "hover:bg-line/40"}`}>
                        {f.file.replace("chapters/", "")}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {/* 中：编辑器/报告 */}
        <div className="col-span-6 rounded-xl border border-line bg-panel p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-semibold">{title()}</div>
            {sel && (sel.kind === "ch" || sel.kind === "doc") && (
              <button onClick={save} disabled={busy || !dirty}
                className="rounded-lg border border-line px-3 py-1 text-xs disabled:opacity-40 hover:border-brand2 hover:text-brand">
                💾 保存{dirty ? " *" : ""}
              </button>
            )}
          </div>
          {sel && (sel.kind === "ch" || sel.kind === "doc") ? (
            <textarea value={body} spellCheck={false}
              onChange={(e) => { setBody(e.target.value); setDirty(true); }}
              className="h-[62vh] w-full resize-y rounded-lg border border-line bg-paper p-4 font-serif text-[15px] leading-8 focus:outline-none focus:ring-2 focus:ring-brandbg" />
          ) : sel && sel.kind === "report" ? (
            <pre className="h-[62vh] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-paper p-4 text-[13px] leading-6">{body}</pre>
          ) : (
            <div className="flex h-[62vh] items-center justify-center text-sm text-inksoft">← 先选一本书，再选章节或文档</div>
          )}
          {log && (
            <details className="mt-2 rounded-lg border border-line bg-ink/95 p-2 text-xs text-[#e8e3d8]">
              <summary className="cursor-pointer text-inksoft">引擎日志</summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono">{log}</pre>
            </details>
          )}
        </div>

        {/* 右：动作面板 */}
        <div className="col-span-3 rounded-xl border border-line bg-panel p-3 shadow-sm">
          <div className="mb-2 text-xs font-semibold text-inksoft">⚡ 动作</div>
          <div className="flex flex-col gap-2">
            {actions.map((a) => {
              const disabled = !!busy || !book || (a.need === "ch" && !chapterNo);
              return (
                <button key={a.label} onClick={a.fn} disabled={disabled}
                  className={`rounded-lg px-3 py-2 text-sm transition disabled:opacity-40 ${a.primary ? "bg-brand text-white hover:bg-brand2" : "border border-line hover:border-brand2 hover:text-brand"}`}>
                  {busy === a.label.replace(/^\S+\s/, "") || busy === a.label ? "⏳ " : ""}{a.label}
                </button>
              );
            })}
          </div>
          {busy && (
            <div className="mt-3 rounded-lg bg-warnbg px-3 py-2 text-xs text-warn">
              ⏳ {busy}中…（写章约 1-3 分钟，请勿关闭）
            </div>
          )}
          <div className="mt-4 rounded-lg bg-paper p-3 text-[11px] leading-5 text-inksoft">
            规矩：先审计后去味；apply 后必须重新体检；账本冲突（⚠）要人工裁决后才能续写。
          </div>
        </div>
      </div>
    </div>
  );
}
