import React, { useEffect, useState } from "react";
import Home from "./pages/Home.jsx";
import Workspace from "./pages/Workspace.jsx";
import Usage from "./pages/Usage.jsx";
import Settings from "./pages/Settings.jsx";
import Snapshots from "./pages/Snapshots.jsx";
import Foreshadow from "./pages/Foreshadow.jsx";
import Graph from "./pages/Graph.jsx";
import Assistant from "./pages/Assistant.jsx";
import Tasks from "./pages/Tasks.jsx";
import Plugins from "./pages/Plugins.jsx";
import Rules from "./pages/Rules.jsx";
import Templates from "./pages/Templates.jsx";
import {
  useTheme, setTheme, getTheme,
  useCollapsed, setCollapsed,
  useWelcomed, setWelcomed,
} from "./uiStore.js";
import { useTasks, startTaskPolling } from "./tasksStore.js";

/* novel-ledger · React 工作台
   观感对齐 AI-Novel-Writing-Assistant：深藏青顶栏 + 白侧栏 + 浅灰工作台。 */

const NAV = [
  { title: "创作", items: [
    { label: "首页", view: "home" },
    { label: "AI 助手", view: "assistant" },
    { label: "章节与账本", view: "workspace" },
    { label: "任务中心", view: "tasks" },
  ] },
  { title: "资产", items: [
    { label: "模板库", view: "templates" },
    { label: "用量统计", view: "usage" },
    { label: "快照底账", view: "snapshots" },
    { label: "伏笔账本", view: "foreshadow" },
    { label: "图谱与文风", view: "graph" },
  ] },
  { title: "系统", items: [
    { label: "技能中心", view: "plugins" },
    { label: "提示词管理", view: "rules" },
    { label: "设置", view: "settings" },
  ] },
];

const THEME_CYCLE = ["", "paper", "dark"]; // "" = 冷色（默认）
const THEME_ICON = { "": "❄", paper: "📄", dark: "🌙" };
const THEME_NAME = { "": "冷色", paper: "暖纸", dark: "暗色" };

export default function App() {
  const [view, setView] = useState("home");
  const [autoBook, setAutoBook] = useState(null);
  const [bellOpen, setBellOpen] = useState(false);

  const theme = useTheme();
  const collapsed = useCollapsed();
  const welcomed = useWelcomed();
  const { changes, unseenCount, markSeen, loading: tasksLoading } = useTasks();

  const go = (v, book) => {
    if (!v) return;
    setView(v);
    setAutoBook(book || null);
    setBellOpen(false);
  };

  // 主题应用到 <html data-theme>
  useEffect(() => {
    const t = getTheme();
    if (t) document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
  }, [theme]);

  // 启动任务轮询（通知用）
  useEffect(() => { startTaskPolling(); }, []);

  const cycleTheme = () => {
    const i = THEME_CYCLE.indexOf(getTheme());
    setTheme(THEME_CYCLE[(i + 1) % THEME_CYCLE.length]);
  };

  return (
    <div className="flex min-h-screen flex-col">
      {/* 顶栏：渐变底 + 细边 */}
      <header className="topbar-grad sticky top-0 z-30 flex h-11 items-center gap-2.5 px-4 text-topbarfg">
        <span className="h-2 w-2 rounded-full bg-accent" />
        <span className="text-[14px] font-bold tracking-wide">novel-ledger</span>
        <span className="text-xs text-topbarfg/80">AI 小说创作台</span>

        <span className="flex-1" />

        {/* 三档主题切换 */}
        <button onClick={cycleTheme} title={`主题：${THEME_NAME[getTheme()]}`}
          className="flex items-center gap-1 rounded-lg bg-topbarfg/10 px-2.5 py-1 text-[12px] transition hover:bg-topbarfg/20">
          <span>{THEME_ICON[getTheme()]}</span>
          <span className="hidden sm:inline">{THEME_NAME[getTheme()]}</span>
        </button>

        {/* 任务通知铃铛 */}
        <div className="relative">
          <button onClick={() => { setBellOpen((o) => !o); if (!bellOpen) markSeen(); }}
            className="relative rounded-lg bg-topbarfg/10 px-2.5 py-1 text-[13px] transition hover:bg-topbarfg/20" title="任务通知">
            🔔
            {unseenCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-err px-1 text-[10px] font-bold text-white">
                {unseenCount > 9 ? "9+" : unseenCount}
              </span>
            )}
          </button>
          {bellOpen && (
            <div className="absolute right-0 top-9 z-40 w-72 rounded-xl border border-line bg-panel p-2 shadow-lg">
              <div className="flex items-center justify-between px-1.5 pb-1.5">
                <span className="text-[12px] font-semibold text-ink">任务动态</span>
                <button onClick={markSeen} className="text-[11px] text-inksoft hover:text-ink">全部已读</button>
              </div>
              {tasksLoading && !changes.length ? (
                <div className="px-2 py-3 text-[12px] text-inksoft">加载中…</div>
              ) : changes.length === 0 ? (
                <div className="px-2 py-3 text-[12px] text-inksoft">暂无任务变化</div>
              ) : (
                <div className="max-h-72 space-y-1 overflow-auto">
                  {changes.map((c, i) => (
                    <div key={i} className="rounded-lg bg-paper px-2.5 py-1.5 text-[12px]">
                      <div className="flex items-center gap-1.5">
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${
                          c.to === "done" ? "bg-okbg text-ok" : c.to === "failed" ? "bg-errbg text-err" : c.to === "paused" ? "bg-warnbg text-warn" : "bg-brandbg text-ink"}`}>
                          {c.to === "done" ? "完成" : c.to === "failed" ? "失败" : c.to === "paused" ? "暂停" : c.to}
                        </span>
                        <span className="font-medium text-ink">{c.book}</span>
                      </div>
                      <div className="mt-0.5 text-inksoft">{c.label}（{fmtTime(c.ts)}）</div>
                    </div>
                  ))}
                </div>
              )}
              <button onClick={() => go("tasks")}
                className="mt-1.5 w-full rounded-lg border border-line py-1.5 text-[12px] text-ink hover:border-brand2 hover:text-brand">
                前往任务中心
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="flex flex-1">
        {/* 侧栏：恒显全局导航（工作台内也直接可点，无需右上角切换）。可折叠 w-44 ↔ w-14 */}
        <aside className={`${collapsed ? "w-14" : "w-44"} shrink-0 border-r border-line bg-panel px-2.5 py-3 transition-all`}>
            {NAV.map((g) => (
              <div key={g.title} className="mb-4">
                {!collapsed && (
                  <div className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-widest text-inksoft/70">{g.title}</div>
                )}
                {g.items.map((it) => (
                  <div key={it.label} onClick={() => go(it.view)}
                    title={it.label}
                    className={`relative mb-0.5 cursor-pointer rounded-lg py-2 pl-3.5 pr-2 text-[13px] transition ${
                      it.view === view
                        ? "bg-brandbg font-semibold text-ink"
                        : "text-inksoft hover:bg-paper hover:text-ink"}`}>
                    {it.view === view && <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />}
                    {collapsed ? it.label.slice(0, 1) : it.label}
                  </div>
                ))}
              </div>
            ))}
          </aside>

        {/* 折叠手柄（侧栏底部） */}
        <div className="relative">
          <button onClick={() => setCollapsed(!collapsed)}
            className="absolute -left-3 top-1/2 z-20 hidden h-7 w-3 -translate-y-1/2 items-center justify-center rounded-l border border-line bg-panel text-[10px] text-inksoft hover:text-ink lg:flex"
            title={collapsed ? "展开侧栏" : "折叠侧栏"}>
            {collapsed ? "›" : "‹"}
          </button>
        </div>

        <main className="page-fade mx-auto w-full max-w-6xl flex-1 p-6">
          {view === "home" && <Home go={go} />}
          {view === "workspace" && <Workspace autoOpen={autoBook} />}
          {view === "usage" && <Usage />}
          {view === "settings" && <Settings go={go} />}
          {view === "snapshots" && <Snapshots />}
          {view === "foreshadow" && <Foreshadow />}
          {view === "graph" && <Graph />}
          {view === "assistant" && <Assistant go={go} />}
          {view === "tasks" && <Tasks />}
          {view === "plugins" && <Plugins />}
          {view === "rules" && <Rules />}
          {view === "templates" && <Templates />}
        </main>
      </div>

      {/* 首次引导弹窗 */}
      {!welcomed && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4" onClick={() => setWelcomed(true)}>
          <div className="w-[440px] max-w-[92vw] rounded-2xl bg-panel p-5 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-accent" />
              <h3 className="text-base font-bold text-ink">欢迎使用 novel-ledger</h3>
            </div>
            <ul className="space-y-2.5 text-[13px] leading-6 text-ink">
              <li className="flex gap-2"><span className="text-accent">🎨</span><span><b>三主题</b>：顶栏可切换冷色 / 暖纸 / 暗色，偏好本地记忆。</span></li>
              <li className="flex gap-2"><span className="text-accent">🧰</span><span><b>技能中心</b>：一致性审计、去味精判、平台自检等一键触发。</span></li>
              <li className="flex gap-2"><span className="text-accent">✍️</span><span><b>写章直播</b>：写章实时流式展示引擎输出，进度与字数即时可见。</span></li>
            </ul>
            <button onClick={() => setWelcomed(true)}
              className="btn-primary mt-4 w-full">开始创作</button>
          </div>
        </div>
      )}
    </div>
  );
}

function fmtTime(ts) {
  try {
    const d = new Date(ts);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch (e) { return ""; }
}
