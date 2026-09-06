import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";
import { useTasks } from "../tasksStore.js";

/* 首页工作台：继续的故事 + 指标（观感对齐竞品的统计卡 + 状态点） */
const norm = (s) => (s ? String(s).toLowerCase() : "pending");
const noOf = (x) => (x && typeof x === "object" ? x.no : x);

export default function Home({ go }) {
  const [keySet, setKeySet] = useState(false);
  const [books, setBooks] = useState([]);
  const [details, setDetails] = useState({});
  const [usage, setUsage] = useState(null);
  const [err, setErr] = useState("");
  const { tasks } = useTasks();
  const cur = (tasks || []).find((t) => ["running", "paused", "failed"].includes(norm(t.status)));

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
      {err && <div className="mb-4 rounded-xl bg-warnbg px-4 py-3 text-sm text-warn">服务连接失败：{err}</div>}

      {/* 当前任务卡：有 running/paused/failed 任务时显示，点击跳任务中心 */}
      {cur && <CurrentTaskCard task={cur} onOpen={() => go("tasks")} />}

      <div className="mb-5 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">继续的故事</h1>
          <p className="mt-0.5 text-[13px] text-inksoft">从上次停下的地方接着写——AI 是笔，你是作者。</p>
        </div>
        <button onClick={() => go("newbook")}
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
