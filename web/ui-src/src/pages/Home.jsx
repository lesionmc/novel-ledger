import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";

/* 首页工作台：继续的故事 + 指标（对齐竞品信息架构） */
export default function Home({ go }) {
  const [keySet, setKeySet] = useState(false);
  const [books, setBooks] = useState([]);
  const [details, setDetails] = useState({});
  const [usage, setUsage] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const st = await api("/api/status");
        setKeySet(st.key_set);
        const bl = (await api("/api/books")).books;
        setBooks(bl);
        const ds = {};
        for (const b of bl) { try { ds[b] = await api(`/api/book/${encodeURIComponent(b)}`); } catch (e) {} }
        setDetails(ds);
        try { setUsage((await api("/api/usage")).summary); } catch (e) {}
      } catch (e) { setErr(e.message); }
    })();
  }, []);

  const totalChapters = Object.values(details).reduce((s, d) => s + (d.chapters?.length || 0), 0);

  return (
    <div>
      {err && <div className="mb-4 rounded-lg bg-warnbg px-4 py-3 text-sm text-warn">服务连接失败：{err}</div>}
      <h1 className="mb-1 text-2xl font-bold text-brand">继续的故事</h1>
      <p className="mb-5 text-sm text-inksoft">从上次停下的地方接着写——AI 是笔，你是作者。</p>

      <div className="mb-6 space-y-3">
        {books.length === 0 && !err && (
          <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
            还没有书——请先用旧版界面（页头可切换）建书，建书向导迁移中
          </div>
        )}
        {books.map((b) => {
          const d = details[b];
          return (
            <div key={b} className="flex items-center gap-3 rounded-xl border border-line bg-panel px-5 py-4 shadow-sm transition hover:border-brand2">
              <span className="text-2xl">📖</span>
              <div>
                <div className="font-semibold">{b}</div>
                <div className="text-xs text-inksoft">
                  {d ? `${d.chapters.length} 章 · ${d.has_state ? "📒 账本就绪" : "⚠ 未建账本"}` : "加载中…"}
                </div>
              </div>
              <span className="flex-1" />
              <button onClick={() => go("workspace")}
                className="rounded-lg bg-brand px-3.5 py-1.5 text-sm text-white transition hover:bg-brand2">
                继续创作 →
              </button>
            </div>
          );
        })}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat num={books.length} label="书架" />
        <Stat num={totalChapters} label="已写章节" />
        <Stat num={fmt(usage?.total)} label="累计 tokens" />
        <Stat num={usage?.write_avg != null ? fmt(usage.write_avg) : "—"} label="平均每章 tokens" />
      </div>
    </div>
  );
}

function Stat({ num, label }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
      <div className="text-xl font-bold text-brand">{num}</div>
      <div className="text-xs text-inksoft">{label}</div>
    </div>
  );
}
