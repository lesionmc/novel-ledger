import React, { useEffect, useState } from "react";
import { api, apiPost, apiPut, usageFromLog, fmt } from "../api.js";

/* 章节与账本页（工作台核心）：书树 | 编辑器/报告 | 动作面板 */

const DOCS = ["设定", "角色卡", "大纲", "state"];
const DOC_LABEL = { 设定: "📄 设定.md", 角色卡: "👤 角色卡.md", 大纲: "🗺 大纲.md", state: "📒 记忆账本" };

export default function Workspace({ autoOpen = null }) {
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
  const [outline, setOutline] = useState(null); // R32 闸口：{no, text}
  const [autoBk, setAutoBk] = useState(false);  // R34③：写完本章自动备份全书
  const [lastWrite, setLastWrite] = useState(null); // R31：{no, words, chars} 超限时出加长/精简按钮

  useEffect(() => { api("/api/books").then((r) => setBooks(r.books)).catch(() => {}); }, []);

  // 建书向导创建新书后跳转过来：自动打开该书（E2E 曾因此按钮全禁用，2026-09-04 修复）
  useEffect(() => {
    if (autoOpen && !book && books.includes(autoOpen)) openBook(autoOpen);
  }, [autoOpen, books]);

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

  async function runWrite(words) {
    // R31+R32：写下一章（可选字数；账本目录有 chXXX.章纲.md 时引擎自动遵循）
    if (busy || !book) return;
    if (sel && sel.kind === "ch") await save().catch(() => {});
    setBusy("写下一章"); setLog(""); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/write`, { words: words || undefined, auto_backup: autoBk });
      if (!d.ok) { setMsg("写章失败"); setLog(d.log || "引擎失败"); return; }
      setLastWrite({ no: d.no, words: d.words || 3000, chars: d.chars });
      const u = usageFromLog(d.log);
      const over = d.words && Math.abs(d.chars - d.words) / d.words > 0.30;
      setMsg(`✅ 第 ${d.no} 章（${fmt(d.chars)} 字${d.words ? ` / 目标 ${fmt(d.words)}` : ""}${d.plan_used ? " · 已按章纲" : ""}）`
        + (u ? ` · 消耗 ${fmt(u.total)} tokens` : "")
        + (over ? " · ⚠ 超 ±30%，可用下方按钮校正" : ""));
      setLog(d.log || "");
      await openBook(book); setSel({ kind: "ch", no: d.no }); setBody(d.body || ""); setDirty(false);
    } catch (e) { setMsg("写章失败：" + e.message); }
    finally { setBusy(""); }
  }

  function writeWithWords() {
    const w = prompt("本章目标字数（1000–10000，确定=默认 3000）", "3000");
    if (w === null) return;
    runWrite(w === "" ? undefined : Number(w));
  }

  async function doBackup() {
    if (busy || !book) return;
    setBusy("备份全书"); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/backup`, {});
      setMsg(d.ok ? `📦 备份完成 → ${d.path}` : "备份失败：" + (d.log || ""));
    } catch (e) { setMsg("备份失败：" + e.message); }
    finally { setBusy(""); }
  }

  async function resize(mode) {
    if (!lastWrite || busy) return;
    setBusy(mode === "expand" ? "加长" : "精简"); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/resize`,
        { no: lastWrite.no, target: lastWrite.words, mode });
      setMsg(`${mode === "expand" ? "加长" : "精简"}完成：第 ${d.no} 章 ${fmt(d.chars)} 字`);
      await openSel({ kind: "ch", no: d.no });
    } catch (e) { setMsg("调整失败：" + e.message); }
    finally { setBusy(""); }
  }

  async function genOutline() {
    if (busy || !info) return;
    setBusy("出章纲"); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/plan`, { no: info.next_no, words: 3000 });
      setOutline({ no: d.no, text: d.outline || "" });
      setMsg(`ch${String(d.no).padStart(3, "0")} 章纲已落盘，请确认（R32 闸口）`);
      await openBook(book);
    } catch (e) { setMsg("出章纲失败：" + e.message); }
    finally { setBusy(""); }
  }

  async function savePlan() {
    if (!outline) return;
    try {
      await apiPost(`/api/book/${encodeURIComponent(book)}/plan-save`, { no: outline.no, text: outline.text });
      setMsg(`ch${String(outline.no).padStart(3, "0")} 章纲已保存 ✅`);
    } catch (e) { setMsg("保存失败：" + e.message); }
  }

  async function writeFromPlan() {
    const no = outline.no;
    setOutline(null);
    await runWriteAt(no);
  }

  async function runWriteAt(no) {
    if (busy) return;
    if (sel && sel.kind === "ch") await save().catch(() => {});
    setBusy("写下一章"); setLog(""); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/write`, { no, auto_backup: autoBk });
      if (!d.ok) { setMsg("写章失败"); setLog(d.log || ""); return; }
      setLastWrite({ no: d.no, words: d.words || 3000, chars: d.chars });
      setMsg(`✅ 第 ${d.no} 章（${fmt(d.chars)} 字 · 已按章纲）`);
      setLog(d.log || "");
      await openBook(book); setSel({ kind: "ch", no: d.no }); setBody(d.body || ""); setDirty(false);
    } catch (e) { setMsg("写章失败：" + e.message); }
    finally { setBusy(""); }
  }

  const chapterNo = sel && sel.kind === "ch" ? sel.no : null;
  const actions = [
    { label: "✍ 写下一章", primary: true, fn: writeWithWords, need: null },
    { label: "🧭 出章纲+试写", fn: genOutline, need: null },
    { label: "📦 备份全书", fn: doBackup, need: null },
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
      {lastWrite && Math.abs(lastWrite.chars - lastWrite.words) / lastWrite.words > 0.30 && (
        <div className="mb-3 flex items-center gap-2 rounded-lg bg-warnbg px-4 py-2 text-sm text-warn">
          ⚠ 本章 {fmt(lastWrite.chars)} 字，超出目标 {fmt(lastWrite.words)} 的 ±30%。校正：
          <button onClick={() => resize("shrink")} disabled={!!busy}
            className="rounded-md border border-warn px-2 py-0.5 text-xs hover:bg-panel">➖ 精简到目标</button>
          <button onClick={() => resize("expand")} disabled={!!busy}
            className="rounded-md border border-warn px-2 py-0.5 text-xs hover:bg-panel">➕ 加长到目标</button>
        </div>
      )}

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
            <details className="mt-2 rounded-lg border border-line bg-topbar p-2 text-xs text-[#d5d9e0]">
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
          <label className="mt-2 flex items-center gap-2 text-xs text-inksoft">
            <input type="checkbox" checked={autoBk} onChange={(e) => setAutoBk(e.target.checked)} />
            写完本章自动备份全书 zip（R34③，backups/ 留最近 10 份）
          </label>
          {outline && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50" onClick={() => setOutline(null)}>
              <div className="w-[760px] max-w-[94vw] rounded-2xl bg-panel p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-brand">🧭 闸口确认 · ch{String(outline.no).padStart(3, "0")} 章纲 + 试写（R32）</h3>
                  <button onClick={() => setOutline(null)} className="text-sm text-inksoft hover:text-ink">✕</button>
                </div>
                {info && info.overdue && info.overdue.length > 0 && (
                  <div className="mb-2 rounded-lg bg-errbg p-2.5 text-xs text-err">
                    ⚠ 伏笔超期告警（本章应优先安排回收或标失效）：
                    {info.overdue.map((o, i) => (
                      <div key={i}>· {o.text.slice(0, 50)}（埋设于第{o.planted}章，已 {o.overdue_by} 章未回收）</div>
                    ))}
                  </div>
                )}
                <textarea value={outline.text} onChange={(e) => setOutline({ ...outline, text: e.target.value })}
                  className="h-[42vh] w-full resize-none font-mono text-[13px]" />
                <div className="mt-3 flex items-center gap-2">
                  <button onClick={savePlan} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-brand2">💾 保存章纲修改</button>
                  <button onClick={writeFromPlan} disabled={busy}
                    className="rounded-lg bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand2 disabled:opacity-40">✅ 按此章纲写正文</button>
                  <span className="flex-1" />
                  <button onClick={() => setOutline(null)} className="text-sm text-inksoft hover:text-ink">稍后再说</button>
                </div>
                <p className="mt-2 text-[11px] text-inksoft">
                  写正文时本章纲自动注入并强制遵循（R32）；保存的章纲进入创作痕迹链（R46）。
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
