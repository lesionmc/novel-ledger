import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/* 伏笔账本（R35 UI 壳）：解析 story_state.md 的「## 伏笔账本」小节，状态可视化
   状态机：已埋(待回收) → 推进中 → 已回收 / 已失效（失效=模型建议+人确认，引擎接线在 R35）
   v0.2.1：大白话说明 + 超期文案瘦身（重复的"建议尽快…"只在顶部说一次）+ 统计徽章配色修复 */

function parseForeshadows(stateText) {
  const m = stateText.match(/## 伏笔账本[^\n]*\n([\s\S]*?)(?=\n## |\Z)/);
  if (!m) return [];
  return m[1].split("\n").map((l) => l.trim()).filter((l) => l.startsWith("- ") && l !== "- （空）")
    .map((l) => {
      let text = l.replace(/^-\s*/, "");
      // 超期长文案 → 瘦身成「超期 N 章」（"建议尽快安排回收或标失效"放页顶统一说）
      const over = text.match(/(?:已|超期(?:\s*：)?)\s*(\d+)\s*章未回收/);
      text = text.replace(/[（(][^）)]*章未回收[^）)]*[）)]/g, "").replace(/⚠?\s*超期[（(][^）)]*[）)]/g, "").replace(/\s{2,}/g, " ").trim();
      let status = "待回收", tone = "warn";
      if (text.includes("已回收")) { status = "已回收"; tone = "ok"; }
      else if (text.includes("失效")) { status = "已失效"; tone = "gray"; }
      else if (text.includes("⚠冲突")) { status = "待裁决"; tone = "err"; }
      else if (/推进|发展中/.test(text)) { status = "推进中"; tone = "info"; }
      return { text, status, tone, overdue: over ? parseInt(over[1]) : 0 };
    });
}

const TONE = {
  ok: "bg-okbg text-ok", warn: "bg-warnbg text-warn",
  err: "bg-errbg text-err", gray: "bg-line/60 text-inksoft", info: "bg-brandbg text-ink",
};
const STATUS_TONE = { "已回收": "ok", "待回收": "warn", "已失效": "gray", "待裁决": "err", "推进中": "info" };

export default function Foreshadow() {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(null);
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/api/books").then(async (r) => {
      setBooks(r.books);
      if (r.books.length) pick(r.books[0]);
    }).catch(() => {});
  }, []);

  async function pick(name) {
    setBook(name); setItems([]); setErr("");
    try {
      const d = await api(`/api/book/${encodeURIComponent(name)}/doc/state`);
      setItems(parseForeshadows(d.content));
    } catch (e) { setErr(e.message); }
  }

  const counts = items.reduce((a, i) => { a[i.status] = (a[i.status] || 0) + 1; return a; }, {});
  const overdueCount = items.filter((i) => i.overdue > 0).length;

  return (
    <div>
      <h1 className="mb-1 text-xl font-bold text-ink">伏笔账本</h1>
      <p className="mb-1 text-[13px] text-inksoft">
        这本书埋的所有「钩子」的总览：埋了什么、收回没有、拖了多久。AI 每写完一章自动更新这里。
      </p>
      <p className="mb-4 text-xs text-inksoft/80">
        看不懂状态？<b className="text-ink">待回收</b> = 埋了还没引爆；<b className="text-ink">已回收</b> = 剧情里用掉了；<b className="text-ink">已失效</b> = 决定不用了；超过 3 章没回收的会标红提示你安排。
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {books.map((b) => (
          <button key={b} onClick={() => pick(b)}
            className={`rounded-lg px-3 py-1.5 text-[13px] ${b === book ? "bg-brand text-white" : "border border-line bg-panel hover:border-ink/30"}`}>
            {b}
          </button>
        ))}
      </div>

      {err && <div className="mb-3 rounded-lg bg-warnbg px-4 py-2 text-[13px] text-warn">读取失败：{err}</div>}
      {items.length === 0 && !err ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
          {book ? "账本里暂无伏笔条目（或尚未建账本）" : "先选一本书"}
        </div>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {Object.entries(counts).map(([k, v]) => (
              <span key={k} className={`rounded-full px-3 py-1 text-xs ${TONE[STATUS_TONE[k] || "info"]}`}>{k} × {v}</span>
            ))}
            {overdueCount > 0 && (
              <span className="ml-2 text-xs text-err">其中 {overdueCount} 条超期（3 章以上没回收）——建议尽快安排回收或标失效</span>
            )}
          </div>
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="flex items-start gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
                <span className={`mt-0.5 shrink-0 rounded-full px-2.5 py-0.5 text-xs ${TONE[it.tone] || TONE.info}`}>{it.status}</span>
                <span className="text-[13.5px] leading-6 text-ink">
                  {it.text}
                  {it.overdue > 0 && it.status !== "已回收" && it.status !== "已失效" && (
                    <span className="ml-2 whitespace-nowrap rounded bg-errbg px-1.5 py-0.5 text-[11px] text-err">超期 {it.overdue} 章</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
