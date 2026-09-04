import React, { useEffect, useState } from "react";
import Home from "./pages/Home.jsx";
import Workspace from "./pages/Workspace.jsx";
import Usage from "./pages/Usage.jsx";
import NewWizard from "./pages/NewWizard.jsx";
import Settings from "./pages/Settings.jsx";
import Snapshots from "./pages/Snapshots.jsx";
import Foreshadow from "./pages/Foreshadow.jsx";

/* novel-ledger · React 工作台（A′ 预构建）
   已迁移：首页 / 章节与账本 / 用量 / 建书向导 / 设置 / 快照底账 / 伏笔账本。 */

const NAV = [
  { title: "创作", items: [{ label: "工作台", view: "home" }, { label: "章节与账本", view: "workspace" }, { label: "新建书", view: "newbook" }] },
  { title: "资产", items: [{ label: "用量统计", view: "usage" }, { label: "快照底账", view: "snapshots" }, { label: "伏笔账本", view: "foreshadow" }] },
  { title: "系统", items: [{ label: "设置", view: "settings" }, { label: "关于", view: null }] },
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
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-panel px-5 py-2.5 shadow-sm">
        <span className="text-lg font-bold text-brand">📖 novel-ledger</span>
        <span className="rounded-full border border-line px-2 py-0.5 text-xs text-inksoft">中文 AI 小说共创写作台</span>
        <span className="flex-1" />
        <span className={`rounded-full px-2.5 py-0.5 text-xs ${keySet ? "bg-okbg text-ok" : "bg-warnbg text-warn"}`}>
          {keySet ? "✅ Key 就绪" : "⚠ 未配 Key"}
        </span>
        <a href="/" className="rounded-lg border border-line px-3 py-1 text-xs hover:border-brand2 hover:text-brand">
          旧版界面
        </a>
      </header>

      <div className="flex flex-1">
        <aside className="w-52 shrink-0 border-r border-line bg-panel p-2.5">
          {NAV.map((g) => (
            <div key={g.title} className="mb-3">
              <div className="px-2 py-1 text-xs font-semibold tracking-wide text-inksoft">{g.title}</div>
              {g.items.map((it) => (
                <div key={it.label} onClick={() => go(it.view)}
                  className={`rounded-md px-2 py-1.5 text-sm ${it.view ? "cursor-pointer" : "cursor-default text-inksoft/70"} ${
                    it.view === view ? "bg-brandbg font-semibold text-brand" : "hover:bg-line/40"}`}>
                  {it.view === view ? "🏠 " : "· "}{it.label}{!it.view ? "（迁移中）" : ""}
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
        </main>
      </div>
    </div>
  );
}
