import React, { useEffect, useRef, useState } from "react";
import { api, apiPost, apiPut, usageFromLog, fmt } from "../api.js";

/* 章节与账本页（工作台核心）：书树 | 编辑器/报告 | 动作面板 */

const DOCS = ["设定", "角色卡", "大纲", "state"];
const DOC_LABEL = { 设定: "设定.md", 角色卡: "角色卡.md", 大纲: "大纲.md", state: "记忆账本" };

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
  const [fold, setFold] = useState({ ch: false, doc: false, rep: true }); // 树分组折叠
  const [batch, setBatch] = useState(null);     // 批量写章弹窗：{start, count, words, running, done, fail}
  const [preview, setPreview] = useState(false); // 编辑器 md 预览模式
  const [liveLines, setLiveLines] = useState([]); // 写章实时直播日志
  const liveRef = useRef(null);

  useEffect(() => { api("/api/books").then((r) => setBooks(r.books)).catch(() => {}); }, []);

  // 直播日志自动滚底
  useEffect(() => {
    if (liveRef.current) liveRef.current.scrollTop = liveRef.current.scrollHeight;
  }, [liveLines]);

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




  async function doBackup() {
    if (busy || !book) return;
    setBusy("备份全书"); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/backup`, {});
      setMsg(d.ok ? `备份完成 → ${d.path}` : "备份失败：" + (d.log || ""));
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
    await writeOne(no, null);
  }


  // 写章实时流（SSE）：逐行接收引擎输出，直播在右栏；返回最终结果
  async function streamWrite(payload, onLine) {
    const r = await fetch(`/api/book/${encodeURIComponent(book)}/write-stream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok || !r.body) throw new Error("HTTP " + r.status);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "", final = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n"); buf = parts.pop();
      for (const blk of parts) {
        if (!blk.startsWith("data: ")) continue;
        try {
          const obj = JSON.parse(blk.slice(6));
          if (obj.phase === "done") final = obj;
          else if (onLine) onLine(obj.line || "");
        } catch (e) {}
      }
    }
    if (!final) throw new Error("写章流意外中断");
    return final;
  }

  // 写单章（含直播），完成后刷新书与编辑器
  async function writeOne(no, words) {
    setLiveLines([]);
    setBusy("写下一章"); setLog(""); setMsg("");
    try {
      const d = await streamWrite({ no, words, auto_backup: autoBk },
        (line) => setLiveLines((ls) => [...ls.slice(-200), line]));
      setBusy(""); setLog(d.log || "");
      if (d.ok === false || d.error) {
        setMsg(`第 ${no} 章失败${d.error ? "：" + d.error : ""}`);
        return { ok: false };
      }
      setLastWrite({ no: d.no, words: d.words || words || 3000, chars: d.chars });
      const u = d.usage ? ` · 消耗 ${fmt(d.usage.total)} tokens` : "";
      const over = d.words && Math.abs(d.chars - d.words) / d.words > 0.30;
      setMsg(`✅ 第 ${d.no} 章（${fmt(d.chars)} 字${d.words ? ` / 目标 ${fmt(d.words)}` : ""}${d.plan_used ? " · 已按章纲" : ""}）${u}` + (over ? " · ⚠ 超 ±30%，可校正" : ""));
      await openBook(book); setSel({ kind: "ch", no: d.no }); setBody(d.body || ""); setDirty(false);
      return { ok: true, d };
    } catch (e) {
      setBusy(""); setMsg("写章失败：" + e.message);
      return { ok: false };
    }
  }

  // 批量连写：从 start 起连写 count 章，每章 words 字（逐章走实时流）
  async function runBatch(start, count, words) {
    setBatch((b) => ({ ...b, running: true, done: 0, fail: 0, current: start }));
    let fail = 0;
    for (let i = 0; i < count; i++) {
      setBatch((b) => ({ ...b, current: start + i, done: i }));
      const r = await writeOne(start + i, words);
      if (!r.ok) fail += 1;
      setBatch((b) => ({ ...b, done: i + 1, fail }));
    }
    setBusy("");
    setMsg(`批量写章结束：完成 ${count - fail}/${count} 章` + (fail ? `（${fail} 章失败，详见直播日志）` : " ✅"));
    setTimeout(() => setBatch(null), 900);
  }


  async function renameBook() {
    const nn = prompt(`把《${book}》重命名为：`, book);
    if (!nn || nn.trim() === book) return;
    try {
      await api(`/api/book/${encodeURIComponent(book)}/rename`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new: nn.trim() }),
      });
      setMsg(`已重命名为《${nn.trim()}》`);
      setBook(null); setInfo(null); setSel(null); setBody("");
      const r = await api("/api/books"); setBooks(r.books);
    } catch (e) { setMsg("重命名失败：" + e.message); }
  }

  const chapterNo = sel && sel.kind === "ch" ? sel.no : null;
  const actions = [
    { label: "写下一章", primary: true, fn: () => setBatch({ start: info?.next_no || 1, count: 1, words: 3000 }), need: null },
    { label: "出章纲+试写", fn: genOutline, need: null },
    { label: "备份全书", fn: doBackup, need: null },
    { label: "导出全书 txt", fn: () => { window.open(`/api/book/${encodeURIComponent(book)}/export`, "_blank"); }, need: null },
    { label: "一致性审计", fn: () => run("一致性审计", () => apiPost(`/api/book/${encodeURIComponent(book)}/audit`, { no: chapterNo })), need: "ch" },
    { label: "全书体检", fn: () => run("全书体检", () => apiPost(`/api/book/${encodeURIComponent(book)}/scan`, {})), need: null },
    { label: "去味精判", fn: () => run("去味精判", () => apiPost(`/api/book/${encodeURIComponent(book)}/polish`, { no: chapterNo })), need: "ch" },
    { label: "应用改写", fn: () => { if (confirm("应用改写会修改正文（自动备份到 .bak.md）。继续？")) return run("应用改写", () => apiPost(`/api/book/${encodeURIComponent(book)}/apply`, { no: chapterNo })); }, need: "ch" },
  ];

  function title() {
    if (!sel) return book ? "从左侧选择章节或文档" : "从左侧选择一本书";
    if (sel.kind === "ch") return `ch${String(sel.no).padStart(3, "0")}.md · ${fmt(body.length)} 字`;
    if (sel.kind === "doc") return DOC_LABEL[sel.doc] + ` · ${fmt(body.length)} 字`;
    return sel.file.replace("chapters/", "");
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
        {/* 左：书/章节/产物 树（分组可折叠，章节显示「N 标题」） */}
        <div className="col-span-3 rounded-xl border border-line bg-panel p-3 shadow-sm">
          <div className="mb-1 flex items-center justify-between text-xs font-semibold text-inksoft">
            我的书
            {book && <button onClick={renameBook} className="text-[11px] font-normal text-inksoft hover:text-ink">重命名</button>}
          </div>
          {books.map((b) => (
            <div key={b} onClick={() => openBook(b)}
              className={`cursor-pointer rounded-md px-2 py-1 text-sm ${b === book ? "bg-brandbg font-semibold text-ink" : "hover:bg-line/40"}`}>
              {b}
            </div>
          ))}
          {book && info && (
            <>
              <div onClick={() => setFold((f) => ({ ...f, ch: !f.ch }))}
                className="mb-1 mt-3 flex cursor-pointer select-none items-center justify-between text-xs font-semibold text-inksoft hover:text-ink">
                <span>章节（{info.chapters.length}）</span><span className="text-[10px]">{fold.ch ? "▸" : "▾"}</span>
              </div>
              {!fold.ch && (
                <div className="max-h-[42vh] overflow-auto">
                  {info.chapters.map((c) => (
                    <div key={c.no} onClick={() => openSel({ kind: "ch", no: c.no })}
                      className={`cursor-pointer truncate rounded-md px-2 py-1 text-[13px] ${sel && sel.kind === "ch" && sel.no === c.no ? "bg-brandbg text-brand" : "hover:bg-line/40"}`}
                      title={c.title || ""}>
                      {c.no} {c.title || ""}
                    </div>
                  ))}
                </div>
              )}
              <div onClick={() => setFold((f) => ({ ...f, doc: !f.doc }))}
                className="mb-1 mt-3 flex cursor-pointer select-none items-center justify-between text-xs font-semibold text-inksoft hover:text-ink">
                <span>文档</span><span className="text-[10px]">{fold.doc ? "▸" : "▾"}</span>
              </div>
              {!fold.doc && DOCS.map((d) => (
                <div key={d} onClick={() => openSel({ kind: "doc", doc: d })}
                  className={`cursor-pointer rounded-md px-2 py-1 text-[13px] ${sel && sel.kind === "doc" && sel.doc === d ? "bg-brandbg text-brand" : "hover:bg-line/40"}`}>
                  {DOC_LABEL[d]}
                </div>
              ))}
              {reports.length > 0 && (
                <>
                  <div onClick={() => setFold((f) => ({ ...f, rep: !f.rep }))}
                    className="mb-1 mt-3 flex cursor-pointer select-none items-center justify-between text-xs font-semibold text-inksoft hover:text-ink">
                    <span>报告/产物（{reports.length}）</span><span className="text-[10px]">{fold.rep ? "▸" : "▾"}</span>
                  </div>
                  {!fold.rep && (
                    <div className="max-h-40 overflow-auto">
                      {reports.map((f) => (
                        <div key={f.file} onClick={() => openSel({ kind: "report", file: f.file })}
                          className={`cursor-pointer rounded-md px-2 py-1 text-[12px] ${sel && sel.kind === "report" && sel.file === f.file ? "bg-brandbg text-brand" : "hover:bg-line/40"}`}>
                          {f.file.replace("chapters/", "")}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>

        {/* 中：编辑器/报告 */}
        <div className="col-span-6 rounded-xl border border-line bg-panel p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-semibold">{title()}</div>
            <div className="flex items-center gap-1.5">
              {sel && (sel.kind === "ch" || sel.kind === "doc") && (
                <button onClick={() => setPreview((p) => !p)}
                  className="rounded-lg border border-line px-2.5 py-1 text-xs hover:border-ink/30">
                  {preview ? "编辑" : "预览"}
                </button>
              )}
              {sel && (sel.kind === "ch" || sel.kind === "doc") && (
                <button onClick={save} disabled={busy || !dirty}
                  className="rounded-lg border border-line px-3 py-1 text-xs disabled:opacity-40 hover:border-ink/30">
                  保存{dirty ? " *" : ""}
                </button>
              )}
            </div>
          </div>
          {sel && (sel.kind === "ch" || sel.kind === "doc") ? (
            preview ? (
              <div className="h-[62vh] overflow-auto rounded-lg border border-line bg-paper p-5 text-[15px] leading-8">
                <MdLite text={body} />
              </div>
            ) : (
              <textarea value={body} spellCheck={false}
                onChange={(e) => { setBody(e.target.value); setDirty(true); }}
                className="h-[62vh] w-full resize-y rounded-lg border border-line bg-paper p-4 font-serif text-[15px] leading-8 focus:outline-none focus:ring-2 focus:ring-brandbg" />
            )
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
          <div className="mb-2 text-xs font-semibold text-inksoft">动作</div>
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
      ⏳ {busy}中…（每章约 1-3 分钟：写正文 + 更新账本）
    </div>
  )}
  {busy && liveLines.length > 0 && (
    <div ref={liveRef} className="mt-2 h-48 overflow-auto rounded-lg bg-topbar p-2 font-mono text-[11px] leading-5 text-[#c7cdd8]">
      {liveLines.map((l, i) => (
        <div key={i} className={l.includes("⚠") ? "text-warn" : l.includes("用量") ? "text-ok" : ""}>{l}</div>
      ))}
      <span className="inline-block h-3 w-1.5 animate-pulse bg-accent" />
    </div>
  )}
          <label className="mt-3 flex items-start gap-2 text-xs text-inksoft">
            <input type="checkbox" checked={autoBk} onChange={(e) => setAutoBk(e.target.checked)} className="mt-0.5" />
            写完本章自动备份全书 zip
          </label>
          {outline && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50" onClick={() => setOutline(null)}>
              <div className="w-[760px] max-w-[94vw] rounded-2xl bg-panel p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-brand">闸口确认 · ch{String(outline.no).padStart(3, "0")} 章纲 + 试写（R32）</h3>
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
                  <button onClick={savePlan} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-brand2">保存章纲修改</button>
                  <button onClick={writeFromPlan} disabled={busy}
                    className="rounded-lg bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand2 disabled:opacity-40">按此章纲写正文</button>
                  <span className="flex-1" />
                  <button onClick={() => setOutline(null)} className="text-sm text-inksoft hover:text-ink">稍后再说</button>
                </div>
                <p className="mt-2 text-[11px] text-inksoft">
                  写正文时本章纲自动注入并强制遵循；保存的章纲进入创作痕迹链。
                </p>
              </div>
            </div>
          )}

          {/* 批量写章弹窗：从第 N 章起连写 M 章，每章 X 字 */}
          {batch && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50" onClick={() => !batch.running && setBatch(null)}>
              <div className="w-[400px] max-w-[92vw] rounded-2xl bg-panel p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
                {batch.running ? (
                  <>
                    <h3 className="mb-3 text-sm font-bold text-ink">批量写章中…</h3>
                    <div className="mb-3 h-2 overflow-auto rounded-full bg-line">
                      <div className="h-full bg-brand transition-all" style={{ width: `${Math.round((batch.done / batch.count) * 100)}%` }} />
                    </div>
                    <div className="text-[13px] text-inksoft">
                      正在写第 {batch.current} 章（{batch.done}/{batch.count}）{batch.fail ? ` · 失败 ${batch.fail}` : ""}
                    </div>
                    <div className="mt-2 text-xs text-inksoft/70">每章约 1-3 分钟（正文 + 账本更新），期间请勿关闭页面</div>
                  </>
                ) : (
                  <>
                    <h3 className="mb-1 text-sm font-bold text-ink">写下一章</h3>
                    <p className="mb-4 text-xs text-inksoft">可以一次连写多章（逐章过账本闸口，速度约 2-4 分钟/章）</p>
                    <label className="mb-3 block text-[13px] text-ink">
                      从第几章开始
                      <input type="number" min="1" value={batch.start} onChange={(e) => setBatch({ ...batch, start: parseInt(e.target.value) || 1 })}
                        className="mt-1 w-full" />
                    </label>
                    <label className="mb-3 block text-[13px] text-ink">
                      连写几章（1-10）
                      <input type="number" min="1" max="10" value={batch.count} onChange={(e) => setBatch({ ...batch, count: Math.max(1, Math.min(10, parseInt(e.target.value) || 1)) })}
                        className="mt-1 w-full" />
                    </label>
                    <label className="mb-4 block text-[13px] text-ink">
                      每章目标字数（1000-10000）
                      <input type="number" min="1000" max="10000" step="500" value={batch.words} onChange={(e) => setBatch({ ...batch, words: Math.max(1000, Math.min(10000, parseInt(e.target.value) || 3000)) })}
                        className="mt-1 w-full" />
                    </label>
                    <div className="flex justify-end gap-2">
                      <button onClick={() => setBatch(null)} className="rounded-lg border border-line px-3.5 py-1.5 text-[13px] hover:border-ink/30">取消</button>
                      <button onClick={() => runBatch(batch.start, batch.count, batch.words)}
                        className="rounded-lg bg-brand px-4 py-1.5 text-[13px] font-medium text-white hover:bg-brand2">开写</button>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* 极简 Markdown 渲染（标题/粗体/引用/分隔线/段落），够看小说与三件套 */
function MdLite({ text }) {
  const lines = (text || "").split("\n");
  const out = [];
  let para = [];
  const flush = () => {
    if (para.length) { out.push(<p key={out.length} className="my-3 whitespace-pre-wrap">{inline(para.join("\n"))}</p>); para = []; }
  };
  const inline = (s) => {
    const parts = s.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
    return parts.map((p, i) =>
      p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : (p.startsWith("*") && p.endsWith("*") && p.length > 2 ? <i key={i}>{p.slice(1, -1)}</i> : p));
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    const h = l.match(/^(#{1,4})\s+(.*)/);
    if (h) { flush(); const lv = h[1].length; out.push(
      lv === 1 ? <h2 key={out.length} className="mb-3 mt-5 text-xl font-bold text-ink">{inline(h[2])}</h2>
      : lv === 2 ? <h3 key={out.length} className="mb-2 mt-4 text-[17px] font-bold text-ink">{inline(h[2])}</h3>
      : <h4 key={out.length} className="mb-2 mt-3 text-[15px] font-semibold text-ink">{inline(h[2])}</h4>);
    } else if (/^={3,}$|^---+$/.test(l)) { flush(); out.push(<hr key={out.length} className="my-4 border-line" />); }
    else if (l.startsWith(">")) { flush(); out.push(<blockquote key={out.length} className="my-2 border-l-2 border-line pl-3 text-inksoft">{inline(l.replace(/^>\s?/, ""))}</blockquote>); }
    else if (l === "") { flush(); }
    else { para.push(l); }
  }
  flush();
  return <div>{out}</div>;
}
