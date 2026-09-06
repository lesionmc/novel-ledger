import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import {
  useRailBook, useRailChapter, setRailBook, setRailChapter, getRailBook, getRailChapter, setReportNote,
} from "../uiStore.js";

/* 书内 Rail（进入「章节与账本」且创作导航模式下替换全局侧栏）
   五件套：①书切换 ②章节树 ③体检单入口 ④字数进度 ⑤伏笔速览。 */

export default function BookRail({ go, collapsed }) {
  const book = useRailBook();
  const chapter = useRailChapter();
  const [books, setBooks] = useState([]);
  const [info, setInfo] = useState(null);
  const [reports, setReports] = useState([]);

  // 书列表
  useEffect(() => {
    api("/api/books").then((r) => {
      const bl = r.books || [];
      setBooks(bl);
      if (!getRailBook() && bl.length) setRailBook(bl[0]);
    }).catch(() => {});
  }, []);

  // 当前书的账本 / 报告（伏笔速览复用 /api/book 的 overdue 字段，避免额外端点请求）
  useEffect(() => {
    if (!book) { setInfo(null); setReports([]); return; }
    api(`/api/book/${encodeURIComponent(book)}`).then(setInfo).catch(() => setInfo(null));
    api(`/api/book/${encodeURIComponent(book)}/files`)
      .then((fd) => setReports((fd.files || []).filter((f) => f.file.includes("体检") || f.file.includes("审计") || f.file.endsWith(".diff.json"))))
      .catch(() => setReports([]));
  }, [book]);

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-2 py-3">
        <div className="h-8 w-8 rounded-lg bg-brandbg text-[14px] font-bold leading-8 text-ink">{book ? book.slice(0, 1) : "·"}</div>
        <div className="text-[11px] text-inksoft">{info ? info.chapters.length : 0}章</div>
      </div>
    );
  }

  const totalChars = info && Array.isArray(info.chapters)
    ? info.chapters.reduce((s, c) => s + (c.size || c.chars || c.words || 0), 0)
    : 0;

  return (
    <div className="flex h-full flex-col py-3 pl-2.5 pr-2">
      {/* ① 书切换下拉 */}
      <div className="mb-3">
        <div className="mb-1 px-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/70">本书</div>
        <select value={book || ""} onChange={(e) => { setRailBook(e.target.value); setRailChapter(""); }}
          className="w-full rounded-lg border border-line bg-panel px-2 py-1.5 text-[13px] text-ink">
          {books.map((b) => <option key={b} value={b}>{b}</option>)}
          {!books.length && <option value="">（无书）</option>}
        </select>
      </div>

      <div className="flex-1 space-y-3 overflow-auto">
        {/* ② 章节树 */}
        <div>
          <div className="mb-1 flex items-center justify-between px-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/70">
            <span>章节</span><span className="normal-case tracking-normal">{info ? info.chapters.length : 0}</span>
          </div>
          {info && info.chapters.map((c) => (
            <div key={c.no} onClick={() => setRailChapter(c.no)}
              title={c.title || `第 ${c.no} 章`}
              className={`mb-0.5 cursor-pointer truncate rounded-md px-2 py-1 text-[12.5px] transition ${
                String(chapter) === String(c.no) ? "bg-brandbg font-semibold text-ink" : "text-inksoft hover:bg-paper hover:text-ink"}`}>
              {c.no} {c.title || ""}
            </div>
          ))}
          {!info && <div className="px-2 py-1 text-[12px] text-inksoft">加载中…</div>}
        </div>

        {/* ③ 体检单入口 */}
        {reports.length > 0 && (
          <div>
            <div className="mb-1 px-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/70">体检单</div>
            {reports.map((f) => (
              <div key={f.file} onClick={() => { setReportNote((book ? book + "::" : "") + f.file); go("plugins"); }}
                title={`打开技能中心查看：${f.file}`}
                className="mb-0.5 cursor-pointer truncate rounded-md px-2 py-1 text-[12px] text-inksoft transition hover:bg-paper hover:text-ink">
                📋 {f.file.replace("chapters/", "")}
              </div>
            ))}
          </div>
        )}

        {/* ⑤ 伏笔速览（复用 /api/book 的 overdue 字段；无则引导去伏笔账本页） */}
        <div>
          <div className="mb-1 px-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/70">伏笔速览</div>
          {info && Array.isArray(info.overdue) && info.overdue.length > 0 ? (
            <div className="space-y-0.5">
              {info.overdue.slice(0, 6).map((x, i) => (
                <div key={i} className="truncate rounded-md px-2 py-1 text-[12px] text-inksoft" title={x.text}>
                  <span className="mr-1 text-warn">●</span>
                  {x.text ? x.text.slice(0, 18) : `伏笔 ${i + 1}`}
                  <span className="ml-1 text-[11px] text-warn">（超期 {x.overdue_by} 章）</span>
                </div>
              ))}
            </div>
          ) : (
            <div onClick={() => go("foreshadow")} className="cursor-pointer rounded-md px-2 py-1 text-[12px] text-info hover:underline">
              → 去伏笔账本页查看
            </div>
          )}
        </div>
      </div>

      {/* ④ 字数进度 */}
      <div className="mt-2 rounded-lg bg-brandbg px-3 py-2 text-[12px]">
        <div className="font-semibold text-ink">{totalChars ? `${totalChars.toLocaleString()} 字` : "—"}</div>
        <div className="text-inksoft">{info ? `${info.chapters.length} 章` : "—"}</div>
      </div>
    </div>
  );
}
