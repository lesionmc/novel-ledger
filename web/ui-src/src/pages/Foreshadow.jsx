import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/* 伏笔账本（R35 UI 壳）：解析 story_state.md 的「## 伏笔账本」小节，状态可视化
   状态机：已埋(待回收) → 推进中 → 已回收 / 已失效（失效=模型建议+人确认，引擎接线在 R35） */

function parseForeshadows(stateText) {
  const m = stateText.match(/## 伏笔账本[^\n]*\n([\s\S]*?)(?=\n## |\Z)/);
  if (!m) return [];
  return m[1].split("\n").map((l) => l.trim()).filter((l) => l.startsWith("- ") && l !== "- （空）")
    .map((l) => {
      const text = l.replace(/^-\s*/, "");
      let status = "待回收", tone = "warn";
      if (text.includes("已回收")) { status = "已回收"; tone = "ok"; }
      else if (text.includes("失效")) { status = "已失效"; tone = "gray"; }
      else if (text.includes("⚠冲突")) { status = "⚠ 待裁决"; tone = "err"; }
      else if (/推进|发展中/.test(text)) { status = "推进中"; tone = "info"; }
      return { text, status, tone };
    });
}

const TONE = {
  ok: "bg-okbg text-ok", warn: "bg-warnbg text-warn",
  err: "bg-errbg text-err", gray: "bg-line/60 text-inksoft", info: "bg-brandbg text-brand",
};

export default function Foreshadow() {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(null);
  const [items, setItems] = useState([]);
  const [raw, setRaw] = useState("");

  useEffect(() => {
    api("/api/books").then(async (r) => {
      setBooks(r.books);
      if (r.books.length) pick(r.books[0]);
    }).catch(() => {});
  }, []);

  async function pick(name) {
    setBook(name); setItems([]); setRaw("");
    try {
      const d = await api(`/api/book/${encodeURIComponent(name)}/doc/state`);
      setRaw(d.content);
      setItems(parseForeshadows(d.content));
    } catch (e) {}
  }

  const counts = items.reduce((a, i) => { a[i.status] = (a[i.status] || 0) + 1; return a; }, {});

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold text-brand">🧵 伏笔账本</h1>
      <p className="mb-5 text-sm text-inksoft">
        从记忆账本实时解析（只读视图）。状态机与超期告警由 R35 引擎接线后自动推进，失效需人工确认。
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {books.map((b) => (
          <button key={b} onClick={() => pick(b)}
            className={`rounded-lg px-3 py-1.5 text-sm ${b === book ? "bg-brand text-white" : "border border-line bg-panel hover:border-brand2"}`}>
            📖 {b}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
          {book ? "账本里暂无伏笔条目（或尚未建账本）" : "先选一本书"}
        </div>
      ) : (
        <>
          <div className="mb-4 flex gap-2">
            {Object.entries(counts).map(([k, v]) => (
              <span key={k} className={`rounded-full px-3 py-1 text-xs ${TONE[k in TONE ? k : "info"]}`}>{k} × {v}</span>
            ))}
          </div>
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="flex items-start gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
                <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs ${TONE[it.tone] || TONE.info}`}>{it.status}</span>
                <span className="text-[13.5px] leading-6">{it.text}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
