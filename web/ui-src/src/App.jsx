import React, { useEffect, useState } from "react";
import Home from "./pages/Home.jsx";
import Workspace from "./pages/Workspace.jsx";
import Usage from "./pages/Usage.jsx";
import NewWizard from "./pages/NewWizard.jsx";
import Settings from "./pages/Settings.jsx";
import Snapshots from "./pages/Snapshots.jsx";
import Foreshadow from "./pages/Foreshadow.jsx";

/* novel-ledger · React 工作台（A′ 预构建）
   观感对齐 AI-Novel-Writing-Assistant：深藏青顶栏 + 白侧栏 + 浅灰工作台。 */

const NAV = [
  { title: "创作", items: [
    { label: "工作台", view: "home", icon: "⌂" },
    { label: "章节与账本", view: "workspace", icon: "▤" },
    { label: "新建书", view: "newbook", icon: "✦" },
  ] },
  { title: "资产", items: [
    { label: "用量统计", view: "usage", icon: "◍" },
    { label: "快照底账", view: "snapshots", icon: "⎘" },
    { label: "伏笔账本", view: "foreshadow", icon: "◇" },
  ] },
  { title: "系统", items: [
    { label: "设置", view: "settings", icon: "⚙" },
  ] },
];

export default function App() {
  const [view, setView] = useState("home");
  const [keySet, setKeySet] = useState(false);
  const [autoBook, setAutoBook] = useState(null); // 建书向导创建后自动在新工作台打开该书

  useEffect(() => {
    fetch("/api/status").then((r) => r.json()).then((d) => setKeySet(!!d.key_set)).catch(() => {});
  }, []);

  const go = (v, book) => {
    if (!v) return;
    setView(v);
    setAutoBook(book || null);
  };

  return (
    <div className="flex min-h-screen flex-col">
      {/* 深藏青顶栏（对齐竞品） */}
      <header className="sticky top-0 z-10 flex h-12 items-center gap-3 bg-topbar px-4 text-white">
        <span className="flex items-center gap-2 text-[15px] font-bold">
          <span className="inline-block h-2 w-2 rounded-full bg-accent" />
          novel-ledger
        </span>
        <span className="hidden text-xs text-white/50 md:inline">AI Novel Production Engine · 中文 AI 小说共创写作台</span>
        <span className="flex-1" />
        <span className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs ${
          keySet ? "border-ok/40 text-ok" : "border-warn/50 text-warn"}`}>
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${keySet ? "bg-ok" : "bg-warn"}`} />
          {keySet ? "Key 就绪" : "未配 Key"}
        </span>
        <a href="/legacy" className="rounded-md border border-white/25 px-2.5 py-1 text-xs text-white/80 transition hover:border-white/60 hover:text-white">
          旧版界面
        </a>
      </header>

      <div className="flex flex-1">
        {/* 白色侧栏：小节标签 + 图标 + 激活胶囊 */}
        <aside className="w-52 shrink-0 border-r border-line bg-panel px-2.5 py-3">
          {NAV.map((g) => (
            <div key={g.title} className="mb-4">
              <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/80">{g.title}</div>
              {g.items.map((it) => (
                <div key={it.label} onClick={() => go(it.view)}
                  className={`mb-0.5 flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition ${
                    it.view === view
                      ? "bg-brandbg font-semibold text-ink"
                      : "text-inksoft hover:bg-paper hover:text-ink"}`}>
                  <span className={`w-4 text-center text-[13px] ${it.view === view ? "text-accent" : "text-inksoft/70"}`}>{it.icon}</span>
                  {it.label}
                </div>
              ))}
            </div>
          ))}
          <div className="mt-8 px-2.5 text-[11px] leading-4 text-inksoft/60">
            AI 是笔，人是作者<br />纯本地 · 零依赖 · MIT
          </div>
        </aside>

        <main className="mx-auto w-full max-w-6xl flex-1 p-6">
          {view === "home" && <Home go={go} />}
          {view === "workspace" && <Workspace autoOpen={autoBook} />}
          {view === "usage" && <Usage />}
          {view === "newbook" && <NewWizard go={go} />}
          {view === "settings" && <Settings go={go} />}
          {view === "snapshots" && <Snapshots />}
          {view === "foreshadow" && <Foreshadow />}
        </main>
      </div>
    </div>
  );
}
