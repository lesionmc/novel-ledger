import React, { useEffect, useState } from "react";
import { api, apiPost, apiPutJson } from "../api.js";
import { useTasks } from "../tasksStore.js";

/* 首页工作台：继续的故事 + 指标（观感对齐竞品的统计卡 + 状态点） */
const norm = (s) => (s ? String(s).toLowerCase() : "pending");
const noOf = (x) => (x && typeof x === "object" ? x.no : x);

export default function Home({ go }) {
  const [keySet, setKeySet] = useState(false);
  const [books, setBooks] = useState([]);
  const [details, setDetails] = useState({});
  const [err, setErr] = useState("");
  const { tasks } = useTasks();
  const cur = (tasks || []).find((t) => ["running", "paused", "failed"].includes(norm(t.status)));
  const [menuFor, setMenuFor] = useState(null); // 打开管理菜单的书名

  function reload() {
    (async () => {
      try {
        const bl = (await api("/api/books")).books;
        setBooks(bl);
        const ds = {};
        await Promise.all(bl.map(async (b) => { try { ds[b] = await api(`/api/book/${encodeURIComponent(b)}`); } catch (e) {} }));
        setDetails(ds);
      } catch (e) {}
    })();
  }

  async function renameBook(b) {
    setMenuFor(null);
    const nn = prompt(`把《${b}》重命名为：`, b);
    if (!nn || nn.trim() === b) return;
    try {
      await apiPutJson(`/api/book/${encodeURIComponent(b)}/rename`, { new: nn.trim() });
      reload();
    } catch (e) { alert("重命名失败：" + e.message); }
  }

  async function archiveBook(b) {
    setMenuFor(null);
    if (!confirm(`把《${b}》移入存档（书架不再显示）？\n书稿不会真删除——可在 books/_archive/ 里找回。`)) return;
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(b)}/archive`, {});
      alert(`已存档 → ${d.archived_to}`);
      reload();
    } catch (e) { alert("存档失败：" + e.message); }
  }

  useEffect(() => {
    (async () => {
      try {
        const st = await api("/api/status");
        setKeySet(st.key_set);
        const bl = (await api("/api/books")).books;
        setBooks(bl);
        const ds = {};
        await Promise.all(bl.map(async (b) => { try { ds[b] = await api(`/api/book/${encodeURIComponent(b)}`); } catch (e) {} }));
        setDetails(ds);
      } catch (e) { setErr(e.message); }
    })();
  }, []);

  const totalChapters = Object.values(details).reduce((s, d) => s + (d.chapters?.length || 0), 0);

  return (
    <div>
      {err && <div className="mb-4 rounded-xl bg-warnbg px-4 py-3 text-sm text-warn">服务连接失败：{err}</div>}

      {/* 当前任务卡：有 running/paused/failed 任务时显示，点击跳任务中心 */}
      {cur && <CurrentTaskCard task={cur} onOpen={() => go("tasks")} />}

      <div className="mb-5 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">继续的故事</h1>
          <p className="mt-0.5 text-[13px] text-inksoft">从上次停下的地方接着写——AI 是笔，你是作者。</p>
        </div>
        <button onClick={() => { try { sessionStorage.setItem("nl_assistant_open_create", "1"); } catch (e) {} go("assistant"); }}
          className="rounded-lg bg-brand px-3.5 py-2 text-[13px] font-medium text-white transition hover:bg-brand2">
          ＋ 新建书
        </button>
      </div>

      <div className="mb-6 space-y-3">
        {books.length === 0 && !err && (
          <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-10 text-center text-sm text-inksoft">
            书架还是空的——点右上角「＋ 新建书」，AI 聊几句就帮你建好
          </div>
        )}
        {books.map((b) => {
          const d = details[b];
          const ready = d?.has_state;
          return (
            <div key={b} onClick={() => go("workspace", b)}
              className="flex cursor-pointer items-center gap-4 rounded-xl border border-line bg-panel px-5 py-4 shadow-sm transition hover:border-ink/25 hover:shadow">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brandbg text-[15px] font-bold text-ink">{b.slice(0, 1)}</div>
              <div>
                <div className="flex items-center gap-2 font-semibold text-ink">
                  {b}
                  <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ${
                    ready ? "bg-okbg text-ok" : "bg-warnbg text-warn"}`}>
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${ready ? "bg-ok" : "bg-warn"}`} />
                    {ready ? "账本就绪" : "未建账本"}
                  </span>
                </div>
                <div className="mt-0.5 text-xs text-inksoft">
                  {d ? `${d.chapters.length} 章 · 最近更新 ${lastTime(d)}` : "加载中…"}
                </div>
              </div>
              <span className="flex-1" />
              <span className="rounded-lg bg-brand px-3.5 py-1.5 text-[13px] font-medium text-white transition hover:bg-brand2">继续创作 →</span>
              <div className="relative" onClick={(e) => e.stopPropagation()}>
                <button onClick={() => setMenuFor(menuFor === b ? null : b)}
                  title="重命名 / 存档"
                  className="rounded-lg border border-line px-2 py-1.5 text-[13px] leading-none text-inksoft transition hover:border-brand2 hover:text-brand">⋯</button>
                {menuFor === b && (
                  <div className="absolute right-0 top-9 z-30 w-36 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
                    <button onClick={() => renameBook(b)}
                      className="block w-full rounded-lg px-3 py-2 text-left text-[13px] text-ink hover:bg-paper">✏️ 重命名</button>
                    <button onClick={() => archiveBook(b)}
                      className="block w-full rounded-lg px-3 py-2 text-left text-[13px] text-err hover:bg-errbg">🗑 存档（删除）</button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3">
        <Stat num={books.length} label="书架" />
        <Stat num={totalChapters} label="已写章节" />
      </div>

      {/* 新手流程（小白照着走：点击任意一步直达对应功能） */}
      <div className="mb-4 rounded-xl border border-line bg-panel p-4 shadow-sm">
        <div className="mb-2 text-[13px] font-bold text-ink">🧭 新手指引：从一句话想法到能发布的成书（点任意一步开始）</div>
        <div className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
          {[
            ["1 构思立意", "让 AI 给我 8 个一句话卖点供我挑选。我的初步想法：", "assistant"],
            ["2 世界观·人物", "请先扮演最挑剔的编辑拷问我的设定，再帮我把世界观（规则一行一条）和人物卡（欲望/缺陷/成长弧/声口）整理成文档。设定：", "assets"],
            ["3 大纲", "基于立项卡和人物卡：分 3~4 卷 → 第一卷展开成章纲（事件→冲突→章末钩）→ 自查因果链与伏笔。", "assets"],
            ["4 写正文", "", "workspace"],
            ["5 评审修订", "分别扮演追更读者/毒舌编审/故事医生，各挑一遍最新一章的毛病，再跑一致性检查。", "assistant"],
            ["6 去AI味·定稿", "", "plugins"],
          ].map(([label, prompt, view], i) => (
            <React.Fragment key={label}>
              <button onClick={() => {
                if (view === "assistant" && prompt) { try { sessionStorage.setItem("nl_assistant_prefill", prompt); } catch (e) {} }
                go(view);
              }}
                className="rounded-full border border-line bg-paper px-3 py-1 font-semibold text-inksoft transition hover:border-brand2 hover:text-brand">
                {label}
              </button>
              {i < 5 && <span className="text-inksoft/50">→</span>}
            </React.Fragment>
          ))}
        </div>
        <div className="mt-2 text-[11.5px] text-inksoft/80">三条保命纪律：大纲没定稿禁写正文；设定/伏笔当天记进文件；AI 初稿必须过去 AI 味 + 你终审才算完成。</div>
      </div>

      <p className="text-[12px] text-inksoft/70">
        小提示：写下一章前先「出章纲+试写」确认方向（闸口），写完记得「一致性审计 → 去味 → 应用」三连。
      </p>
    </div>
  );
}

function lastTime(d) {
  try {
    const t = d.chapters?.length ? `第 ${d.chapters[d.chapters.length - 1].no} 章` : "尚未开笔";
    return t;
  } catch (e) { return "—"; }
}

function Stat({ num, label }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3.5 shadow-sm">
      <div className="text-[11px] text-inksoft">{label}</div>
      <div className="mt-0.5 text-xl font-bold text-ink">{num}</div>
    </div>
  );
}

function CurrentTaskCard({ task, onOpen }) {
  const s = norm(task.status);
  const total = parseInt(task.count) || null;
  const doneNos = Array.isArray(task.done) ? task.done.map(noOf).filter((x) => x != null) : [];
  const pct = total ? Math.min(100, Math.max(0, Math.round((doneNos.length / total) * 100))) : 0;
  const tone = s === "failed" ? "bg-errbg text-err"
    : s === "paused" ? "bg-warnbg text-warn" : "bg-brandbg text-ink";
  const label = s === "failed" ? "失败" : s === "paused" ? "已暂停" : "运行中";
  return (
    <div onClick={onOpen} className={`mb-4 cursor-pointer rounded-xl border border-line bg-panel p-3.5 shadow-sm transition hover:-translate-y-px hover:shadow-md`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2.5 py-0.5 text-[11px] ${tone}`}>{label}</span>
        <span className="text-[13.5px] font-semibold text-ink">《{task.book}》</span>
        <span className="text-[12.5px] text-inksoft">{task.id}</span>
        <span className="flex-1" />
        <span className="text-[12px] text-inksoft">前往任务中心 →</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-line">
        <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[12px] text-inksoft">
        <span>进度：{total ? `${doneNos.length} / ${total} 章` : `${doneNos.length} 章`}</span>
        {task.pause_reason && <span className="text-warn">暂停原因：{task.pause_reason}</span>}
      </div>
    </div>
  );
}
