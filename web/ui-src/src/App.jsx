import React, { useEffect, useState } from "react";
import Home from "./pages/Home.jsx";
import Workspace from "./pages/Workspace.jsx";
import Usage from "./pages/Usage.jsx";
import NewWizard from "./pages/NewWizard.jsx";
import Settings from "./pages/Settings.jsx";
import Snapshots from "./pages/Snapshots.jsx";
import Foreshadow from "./pages/Foreshadow.jsx";
import Assistant from "./pages/Assistant.jsx";

/* novel-ledger · React 工作台（A′ 预构建）
   观感对齐 AI-Novel-Writing-Assistant：深藏青顶栏 + 白侧栏 + 浅灰工作台。 */

const NAV = [
  { title: "创作", items: [
    { label: "首页", view: "home" },
    { label: "新建书", view: "newbook" },
    { label: "章节与账本", view: "workspace" },
    { label: "AI 助手", view: "assistant" },
  ] },
  { title: "资产", items: [
    { label: "用量统计", view: "usage" },
    { label: "快照底账", view: "snapshots" },
    { label: "伏笔账本", view: "foreshadow" },
  ] },
  { title: "系统", items: [
    { label: "设置", view: "settings" },
  ] },
];

export default function App() {
  const [view, setView] = useState("home");
  const [autoBook, setAutoBook] = useState(null); // 建书向导创建后自动在新工作台打开该书

  const go = (v, book) => {
    if (!v) return;
    setView(v);
    setAutoBook(book || null);
  };

  return (
    <div className="flex min-h-screen flex-col">
      {/* 浅色顶栏 */}
      <header className="sticky top-0 z-10 flex h-11 items-center gap-2.5 border-b border-line bg-panel px-4 text-ink">
        <span className="h-2 w-2 rounded-full bg-accent" />
        <span className="text-[14px] font-bold tracking-wide">novel-ledger</span>
        <span className="text-xs text-inksoft/80">AI 小说创作台</span>
      </header>

      <div className="flex flex-1">
        {/* 白色侧栏：无图标，激活项左橙条 */}
        <aside className="w-44 shrink-0 border-r border-line bg-panel px-2.5 py-3">
          {NAV.map((g) => (
            <div key={g.title} className="mb-4">
              <div className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/70">{g.title}</div>
              {g.items.map((it) => (
                <div key={it.label} onClick={() => go(it.view)}
                  className={`relative mb-0.5 cursor-pointer rounded-lg py-2 pl-3.5 pr-2 text-[13px] transition ${
                    it.view === view
                      ? "bg-brandbg font-semibold text-ink"
                      : "text-inksoft hover:bg-paper hover:text-ink"}`}>
                  {it.view === view && <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />}
                  {it.label}
                </div>
              ))}
            </div>
          ))}
        </aside>

        <main className="mx-auto w-full max-w-6xl flex-1 p-6">
          {view === "home" && <Home go={go} />}
          {view === "workspace" && <Workspace autoOpen={autoBook} />}
          {view === "usage" && <Usage />}
          {view === "newbook" && <NewWizard go={go} />}
          {view === "settings" && <Settings go={go} />}
          {view === "snapshots" && <Snapshots />}
          {view === "foreshadow" && <Foreshadow />}
          {view === "assistant" && <Assistant go={go} />}
        </main>
      </div>
    </div>
  );
}
