import React, { useEffect, useState } from "react";
import { api, fmt } from "../api.js";

/* 用量统计页（R48）：流水汇总 + 按天 + 每章明细 */
export default function Usage() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/api/usage").then((r) => setS(r.summary)).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="rounded-lg bg-warnbg px-4 py-3 text-sm text-warn">读取失败：{err}</div>;
  if (!s) return <div className="text-sm text-inksoft">加载中…</div>;

  const days = Object.entries(s.by_day || {}).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  const chapters = (s.chapters || []).slice(-20).reverse();
  const actions = Object.entries(s.by_action || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div>
      <h1 className="mb-1 text-2xl font-bold text-brand">📊 用量统计</h1>
      <p className="mb-5 text-sm text-inksoft">本地流水 · 不查厂商 · 不折算钱。每章平均可用于估算压测成本。</p>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card num={fmt(s.total)} label="累计 tokens" />
        <Card num={fmt(s.calls)} label="调用次数" />
        <Card num={s.write_avg != null ? fmt(s.write_avg) : "—"} label="平均每章 tokens" />
        <Card num={fmt(s.write_count)} label="已写章数" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="按天汇总">
          <Table head={["日期", "次数", "输入", "输出", "合计"]}
            rows={days.length ? days.map(([d, v]) => [d, v.calls, fmt(v.in), fmt(v.out), fmt(v.total)])
              : [["暂无记录", "", "", "", ""]]} />
        </Panel>
        <Panel title="按动作">
          <Table head={["动作", "tokens"]}
            rows={actions.length ? actions.map(([a, v]) => [a, fmt(v)]) : [["暂无记录", ""]]} />
        </Panel>
      </div>

      <Panel title="每章消耗（最近 20 章）" className="mt-5">
        <Table head={["书", "章", "tokens", "时间"]}
          rows={chapters.length ? chapters.map((c) => [c.book || "-", c.chapter ? "ch" + String(c.chapter).padStart(3, "0") : "-", fmt(c.total), c.ts])
            : [["暂无记录", "", "", ""]]} />
      </Panel>
    </div>
  );
}

function Card({ num, label }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
      <div className="text-xl font-bold text-brand">{num}</div>
      <div className="text-xs text-inksoft">{label}</div>
    </div>
  );
}

function Panel({ title, children, className = "" }) {
  return (
    <div className={`rounded-xl border border-line bg-panel p-4 shadow-sm ${className}`}>
      <h3 className="mb-2 text-sm font-semibold text-brand">{title}</h3>
      {children}
    </div>
  );
}

function Table({ head, rows }) {
  return (
    <table className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b border-line text-xs text-inksoft">
          {head.map((h) => <th key={h} className="py-1.5 pr-3 font-medium">{h}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-b border-line/60 last:border-0">
            {r.map((c, j) => <td key={j} className="py-1.5 pr-3">{c}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
