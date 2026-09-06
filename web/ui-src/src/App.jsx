import React, { useEffect, useState } from "react";
import Home from "./pages/Home.jsx";
import Workspace from "./pages/Workspace.jsx";
import Usage from "./pages/Usage.jsx";
import Settings from "./pages/Settings.jsx";
import Snapshots from "./pages/Snapshots.jsx";
import Foreshadow from "./pages/Foreshadow.jsx";
import Graph from "./pages/Graph.jsx";
import Assistant from "./pages/Assistant.jsx";
import Guide from "./pages/Guide.jsx";
import StoryAssets from "./pages/StoryAssets.jsx";
import Inspiration from "./pages/Inspiration.jsx";
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

/* 线性描边图标（stroke 风格，对齐主流工具侧栏；不用 emoji） */
const ICON_PATHS = {
  home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5.5 9.5V20h13V9.5" /></>,
  chat: <><path d="M4 5.5h16v11H9l-5 4v-15Z" /></>,
  book: <><path d="M4 4.5h7a2 2 0 0 1 2 2V20a2.5 2.5 0 0 0-2.5-2H4v-13.5Z" /><path d="M20 4.5h-7a2 2 0 0 0-2 2V20a2.5 2.5 0 0 1 2.5-2H20v-13.5Z" /></>,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3.5" /><path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3" /></>,
  grid: <><rect x="4" y="4" width="6.5" height="6.5" rx="1" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1" /></>,
  chart: <><path d="M4 20V10M10 20V4M16 20v-7M21 20H3.5" /></>,
  archive: <><rect x="3.5" y="4" width="17" height="4.5" rx="1" /><path d="M5.5 8.5V19a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V8.5M10 12.5h4" /></>,
  link: <><path d="M9.5 14.5 14.5 9.5" /><path d="M7.5 12 5 14.5a3.2 3.2 0 0 0 4.5 4.5L12 16.5" /><path d="M16.5 12 19 9.5A3.2 3.2 0 0 0 14.5 5L12 7.5" /></>,
  graph: <><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="7" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8 7.2 15.5 7M7 8.2l3.7 7.5M16.8 9.2l-3.4 6.5" /></>,
  puzzle: <><path d="M9 4h6v3.5a2 2 0 1 0 0 4V15H9v-3.5a2 2 0 1 1 0-4V4Z" transform="rotate(0 12 9.5)" /><path d="M4 15h5v3.5a1.8 1.8 0 1 0 3.6 0V15H20v-5h-3.5" /></>,
  rules: <><rect x="5" y="3.5" width="14" height="17" rx="1.5" /><path d="M8.5 8h7M8.5 12h7M8.5 16h4.5" /></>,
  settings: <><path d="M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9" /><circle cx="15" cy="7.5" r="2.2" /><circle cx="9" cy="16.5" r="2.2" /></>,
  compass: <><circle cx="12" cy="12" r="8.5" /><path d="m15.5 8.5-2.2 5-5 2.2 2.2-5 5-2.2Z" /></>,
  world: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.8 2.3 4 5.2 4 8.5s-1.2 6.2-4 8.5c-2.8-2.3-4-5.2-4-8.5s1.2-6.2 4-8.5Z" /></>,
  bulb: <><path d="M9.5 18h5M10.5 21h3" /><path d="M12 3.5a5.5 5.5 0 0 1 3 10.1c-.6.4-1 1.1-1 1.9h-4c0-.8-.4-1.5-1-1.9A5.5 5.5 0 0 1 12 3.5Z" /></>,
};

function NavIcon({ name }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[name] || ICON_PATHS.grid}
    </svg>
  );
}

const NAV = [
  { title: "创作", items: [
    { label: "首页", view: "home", icon: "home" },
    { label: "创作向导", view: "guide", icon: "compass" },
    { label: "AI 助手", view: "assistant", icon: "chat" },
    { label: "设定中心", view: "assets", icon: "world" },
    { label: "章节与账本", view: "workspace", icon: "book" },
    { label: "任务中心", view: "tasks", icon: "target" },
  ] },
  { title: "资产", items: [
    { label: "灵感素材库", view: "inspiration", icon: "bulb" },
    { label: "模板库", view: "templates", icon: "grid" },
    { label: "快照底账", view: "snapshots", icon: "archive" },
    { label: "伏笔账本", view: "foreshadow", icon: "link" },
    { label: "图谱与文风", view: "graph", icon: "graph" },
  ] },
  { title: "系统", items: [
    { label: "技能中心", view: "plugins", icon: "puzzle" },
    { label: "提示词管理", view: "rules", icon: "rules" },
    { label: "设置", view: "settings", icon: "settings" },
  ] },
];

const VERSION = "v0.9.3";
const GITHUB_URL = "https://github.com/lesionmc/novel-ledger";
const GITHUB_SVG = (
  <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true">
    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
  </svg>
);

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
      {/* 顶栏：渐变底 + 细边。左上角 = logo 块 + 双行标题 + 版本徽章 + GitHub 链接 */}
      <header className="topbar-grad sticky top-0 z-30 flex h-14 items-center gap-3 px-4 text-topbarfg">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-topbarfg/15 shadow-sm">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 5h7a2 2 0 0 1 2 2v13a2.5 2.5 0 0 0-2.5-2H4V5Z" />
            <path d="M20 5h-7a2 2 0 0 0-2 2v13a2.5 2.5 0 0 1 2.5-2H20V5Z" />
          </svg>
        </span>
        <div className="leading-tight">
          <div className="flex items-center gap-1.5">
            <span className="text-[15px] font-extrabold tracking-wide">AI 小说创作工作台</span>
            <span className="rounded-md bg-topbarfg/15 px-1.5 py-0.5 text-[10px] font-bold">{VERSION}</span>
          </div>
          <div className="text-[10.5px] text-topbarfg/70">AI Novel Production Engine · novel-ledger</div>
        </div>
        <a href={GITHUB_URL} target="_blank" rel="noreferrer" title="打开 GitHub 仓库"
          className="flex items-center gap-1.5 rounded-lg bg-topbarfg/10 px-2 py-1.5 text-[12px] font-semibold transition hover:bg-topbarfg/20">
          {GITHUB_SVG}
          <span className="hidden sm:inline">GitHub</span>
        </a>

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
            className="relative rounded-lg bg-topbarfg/10 px-2.5 py-1.5 transition hover:bg-topbarfg/20" title="任务通知">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9.5a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" />
              <path d="M10 19.5a2.2 2.2 0 0 0 4 0" />
            </svg>
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
        <aside className={`${collapsed ? "w-14" : "w-48"} shrink-0 border-r border-line bg-panel px-2.5 py-3 transition-all`}>
            {NAV.map((g) => (
              <div key={g.title} className="mb-4">
                {!collapsed && (
                  <div className="px-2.5 pb-1 text-[11px] font-bold uppercase tracking-widest text-inksoft/80">{g.title}</div>
                )}
                {g.items.map((it) => (
                  <div key={it.label} onClick={() => go(it.view)}
                    title={it.label}
                    className={`relative mb-0.5 flex cursor-pointer items-center gap-2 rounded-lg py-2 pl-3 pr-2 text-[13.5px] font-semibold transition ${
                      it.view === view
                        ? "bg-brandbg font-bold text-ink"
                        : "text-inksoft hover:bg-paper hover:text-ink"}`}>
                    {it.view === view && <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />}
                    <span className="flex w-5 shrink-0 items-center justify-center"><NavIcon name={it.icon} /></span>
                    {!collapsed && <span className="truncate">{it.label}</span>}
                  </div>
                ))}
              </div>
            ))}
          </aside>

        {/* 折叠手柄（侧栏中部，常显可回收） */}
        <div className="relative">
          <button onClick={() => setCollapsed(!collapsed)}
            className="absolute -left-3 top-1/2 z-20 flex h-7 w-3 -translate-y-1/2 items-center justify-center rounded-l border border-line bg-panel text-[10px] text-inksoft hover:text-ink"
            title={collapsed ? "展开侧栏" : "收起侧栏"}>
            {collapsed ? "›" : "‹"}
          </button>
        </div>

        <main className="page-fade mx-auto w-full max-w-6xl flex-1 p-6">
          {view === "home" && <Home go={go} />}
          {view === "workspace" && <Workspace autoOpen={autoBook} />}
          {view === "guide" && <Guide go={go} />}
          {view === "assets" && <StoryAssets go={go} />}
          {view === "inspiration" && <Inspiration />}
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
