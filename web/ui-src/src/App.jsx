import React, { useEffect, useState } from "react";

/* novel-ledger · React 工作台 v0.1（A′ 预构建，逐页迁移中）
   当前页：首页工作台（对齐竞品"继续的故事 + 指标 + 用量"信息架构） */

async function api(path) {
  const r = await fetch(path);
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

function TopBar({ keySet }) {
  return (
    <header className="flex items-center gap-3 border-b border-line bg-panel px-5 py-2.5 shadow-sm">
      <span className="text-lg font-bold text-brand">📖 novel-ledger</span>
      <span className="rounded-full border border-line px-2 py-0.5 text-xs text-inksoft">中文 AI 小说共创写作台</span>
      <span className="flex-1" />
      <span className={`rounded-full px-2.5 py-0.5 text-xs ${keySet ? "bg-okbg text-ok" : "bg-warnbg text-warn"}`}>
        {keySet ? "✅ Key 就绪" : "⚠ 未配 Key"}
      </span>
    </header>
  );
}

function SideNav({ active }) {
  const groups = [
    { title: "创作", items: ["工作台", "新建书"] },
    { title: "资产", items: ["章节与账本", "用量统计"] },
    { title: "系统", items: ["设置", "关于"] },
  ];
  return (
    <aside className="w-56 shrink-0 border-r border-line bg-panel p-2.5">
      {groups.map((g) => (
        <div key={g.title} className="mb-3">
          <div className="px-2 py-1 text-xs font-semibold tracking-wide text-inksoft">{g.title}</div>
          {g.items.map((it) => (
            <div key={it}
              className={`cursor-default rounded-md px-2 py-1.5 text-sm ${
                it === active ? "bg-brandbg font-semibold text-brand" : "text-ink hover:bg-line/40"}`}>
              {it === active ? "🏠 " : "· "}{it}{it !== active && it !== "工作台" ? "（迁移中）" : ""}
            </div>
          ))}
        </div>
      ))}
    </aside>
  );
}

function StatCard({ num, label }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
      <div className="text-xl font-bold text-brand">{num}</div>
      <div className="text-xs text-inksoft">{label}</div>
    </div>
  );
}

function BookCard({ name, info, onOpen }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-panel px-5 py-4 shadow-sm transition hover:border-brand2">
      <span className="text-2xl">📖</span>
      <div>
        <div className="font-semibold">{name}</div>
        <div className="text-xs text-inksoft">
          {info ? `${info.chapters.length} 章 · ${info.has_state ? "📒 账本就绪" : "⚠ 未建账本"}` : "加载中…"}
        </div>
      </div>
      <span className="flex-1" />
      <button onClick={() => onOpen(name)}
        className="rounded-lg bg-brand px-3.5 py-1.5 text-sm text-white transition hover:bg-brand2">
        继续创作 →
      </button>
    </div>
  );
}

export default function App() {
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
    <div className="flex min-h-screen flex-col">
      <TopBar keySet={keySet} />
      <div className="flex flex-1">
        <SideNav active="工作台" />
        <main className="mx-auto w-full max-w-5xl p-7">
          <h1 className="mb-1 text-2xl font-bold text-brand">继续的故事</h1>
          <p className="mb-5 text-sm text-inksoft">从上次停下的地方接着写——AI 是笔，你是作者。</p>

          {err && <div className="mb-4 rounded-lg bg-warnbg px-4 py-3 text-sm text-warn">服务连接失败：{err}</div>}

          <div className="mb-6 space-y-3">
            {books.length === 0 && !err && (
              <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
                还没有书——旧版界面点「+ 新建书」开始（建书向导迁移中）
              </div>
            )}
            {books.map((b) => (
              <BookCard key={b} name={b} info={details[b]}
                onOpen={() => alert("React 版逐页迁移中：请暂时用旧版界面（返回旧版点浏览器后退，或访问 /）")} />
            ))}
          </div>

          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard num={books.length} label="书架" />
            <StatCard num={totalChapters} label="已写章节" />
            <StatCard num={usage ? usage.total.toLocaleString() : 0} label="累计 tokens" />
            <StatCard num={usage && usage.write_avg != null ? usage.write_avg.toLocaleString() : "—"} label="平均每章 tokens" />
          </div>

          <p className="text-xs text-inksoft">
            🚧 React 工作台预览版（A′ 预构建）——逐页迁移中，完整功能请用
            <a href="/" className="mx-1 text-brand underline">旧版界面</a>。
          </p>
        </main>
      </div>
    </div>
  );
}
