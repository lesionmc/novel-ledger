import React, { useEffect, useState } from "react";
import { api, apiPutJson } from "../api.js";

/* 提示词管理（v0.3）：rules/*.md 可视化编辑
   契约：GET /api/rules → 列表（兼容 [name] / [{name}] / {rules|files:[…]}）
        GET  /api/rules/{name}       → {content|body} 当前内容
        PUT  /api/rules/{name}       {"body"} 保存
        GET  /api/rules/{name}/default → 内置默认（「载入内置默认」填充编辑器，不自动保存） */

function names(d) {
  const arr = Array.isArray(d) ? d : (d && (d.rules || d.files)) || [];
  return arr.map((x) => (typeof x === "string" ? x : x.name || x.file)).filter(Boolean);
}
const pickBody = (d) => (d && (d.body ?? d.content ?? d.text)) || (typeof d === "string" ? d : "");

export default function Rules() {
  const [list, setList] = useState([]);
  const [sel, setSel] = useState(null);
  const [body, setBody] = useState("");
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/rules").then((d) => {
      const ns = names(d);
      setList(ns);
      if (ns.length) open(ns[0]);
    }).catch((e) => setErr(e.message));
  }, []);

  async function open(name) {
    setSel(name); setBody(""); setDirty(false); setMsg(""); setErr("");
    try {
      const d = await api(`/api/rules/${encodeURIComponent(name)}`);
      setBody(pickBody(d));
    } catch (e) { setErr(`读取失败：${e.message}`); }
  }

  async function save() {
    if (!sel || busy) return;
    setBusy(true); setMsg(""); setErr("");
    try {
      await apiPutJson(`/api/rules/${encodeURIComponent(sel)}`, { body });
      setDirty(false); setMsg("已保存 ✅");
    } catch (e) { setMsg(`保存失败：${e.message}`); }
    finally { setBusy(false); }
  }

  async function loadDefault() {
    if (!sel) return;
    setMsg(""); setErr("");
    try {
      const d = await api(`/api/rules/${encodeURIComponent(sel)}/default`);
      setBody(pickBody(d));
      setDirty(true);
      setMsg("已载入内置默认（尚未保存，确认后点「保存」）");
    } catch (e) { setMsg(`载入默认失败：${e.message}`); }
  }

  return (
    <div>
      <h1 className="mb-1 text-xl font-bold text-ink">提示词管理</h1>
      <p className="mb-4 text-[13px] text-inksoft">
        引擎各环节用的提示词都在 rules/ 目录：左边选一个，右边直接改，保存后下一次写作立即生效。改坏了可以「载入内置默认」恢复。
      </p>

      {msg && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-[13px] text-ink">{msg}</div>}
      {err && <div className="mb-3 rounded-lg bg-warnbg px-4 py-2 text-[13px] text-warn">{err}</div>}

      <div className="flex gap-4">
        {/* 左列表 */}
        <div className="w-52 shrink-0">
          <div className="rounded-xl border border-line bg-panel p-1.5 shadow-sm">
            {list.length === 0 ? (
              <div className="px-3 py-6 text-center text-[13px] text-inksoft">暂无提示词（后端 /api/rules 未就绪）</div>
            ) : list.map((n) => (
              <div key={n} onClick={() => open(n)}
                className={`mb-0.5 cursor-pointer rounded-lg px-3 py-2 text-[13px] ${n === sel ? "bg-brandbg font-semibold text-ink" : "text-inksoft hover:bg-paper hover:text-ink"}`}>
                {n}
              </div>
            ))}
          </div>
        </div>

        {/* 右编辑器 */}
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-[14px] font-semibold text-ink">{sel || "（未选择）"}</span>
            {dirty && <span className="rounded-full bg-warnbg px-2 py-0.5 text-[11px] text-warn">未保存</span>}
            <div className="ml-auto flex gap-2">
              <button onClick={loadDefault} disabled={!sel}
                className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-inksoft hover:border-ink/30 disabled:opacity-50">载入内置默认</button>
              <button onClick={save} disabled={!sel || busy || !dirty || !body.trim()}
                className="rounded-lg bg-brand px-4 py-1.5 text-[13px] text-white hover:bg-brand2 disabled:opacity-50">
                {busy ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
          <textarea value={body} onChange={(e) => { setBody(e.target.value); setDirty(true); }}
            spellCheck={false}
            placeholder={sel ? "" : "先在左侧选择一个提示词文件"}
            className="h-[62vh] w-full resize-y rounded-xl border border-line bg-panel px-4 py-3 font-mono text-[12.5px] leading-6 text-ink outline-none focus:border-ink/30" />
        </div>
      </div>
    </div>
  );
}
