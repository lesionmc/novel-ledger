import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/* 快照底账（R47）：每章账本的历史存档，R49「从第 N 章重算」的起点 */
export default function Snapshots() {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(null);
  const [snaps, setSnaps] = useState([]);
  const [content, setContent] = useState("");
  const [sel, setSel] = useState("");

  useEffect(() => {
    api("/api/books").then(async (r) => {
      setBooks(r.books);
      if (r.books.length) pick(r.books[0]);
    }).catch(() => {});
  }, []);

  async function pick(name) {
    setBook(name); setSnaps([]); setContent(""); setSel("");
    try {
      const d = await api(`/api/book/${encodeURIComponent(name)}`);
      setSnaps(d.snapshots || []);
    } catch (e) {}
  }

  async function openSnap(f) {
    setSel(f); setContent("加载中…");
    try {
      setContent((await api(`/api/book/${encodeURIComponent(book)}/file/_snapshots/${f}`)).content);
    } catch (e) { setContent("读取失败：" + e.message); }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold text-brand">🗄 快照底账</h1>
      <p className="mb-5 text-sm text-inksoft">
        每章账本更新成功后自动存档（R47，永不清理）。将来「从第 N 章重算」（R49）拿它当起点。
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {books.map((b) => (
          <button key={b} onClick={() => pick(b)}
            className={`rounded-lg px-3 py-1.5 text-sm ${b === book ? "bg-brand text-white" : "border border-line bg-panel hover:border-brand2"}`}>
            📖 {b}
          </button>
        ))}
      </div>

      {book && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="rounded-xl border border-line bg-panel p-3 shadow-sm">
            <div className="mb-2 text-xs font-semibold text-inksoft">快照列表（{snaps.length}）</div>
            {snaps.length === 0 && <div className="px-1 py-2 text-xs text-inksoft">还没有快照——写下一章（账本校验通过）后自动生成</div>}
            {snaps.map((f) => (
              <div key={f} onClick={() => openSnap(f)}
                className={`cursor-pointer rounded-md px-2 py-1.5 text-[13px] ${sel === f ? "bg-brandbg font-semibold text-brand" : "hover:bg-line/40"}`}>
                🗄 {f}
              </div>
            ))}
          </div>
          <div className="lg:col-span-2">
            {sel ? (
              <pre className="h-[62vh] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-panel p-4 font-mono text-[12.5px] leading-6 shadow-sm">{content}</pre>
            ) : (
              <div className="flex h-[62vh] items-center justify-center rounded-xl border border-dashed border-line text-sm text-inksoft">← 点左侧快照查看当时账本</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
