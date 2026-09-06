import React, { useEffect, useRef, useState } from "react";
import { api, apiPost, apiPutJson } from "../api.js";
import Foreshadow from "./Foreshadow.jsx";

/* 设定中心 v2：
   - 选书在左侧（与 tabs 同排），默认只读，点「修改」才可编辑，改完「保存」生效
   - tabs：世界观与势力 / 人物（含可拖拽关系图）/ 大纲 / 伏笔
   - AI 起草：按类别专用提示词，草稿只填编辑器不落盘，保存权在人
   数据仍落在引擎三件套文件（设定/角色卡/大纲），零迁移。 */

const TABS = [
  { key: "设定", label: "世界观与势力", doc: "设定", aiRole: "网文世界观架构师",
    aiTask: "根据这本书的现有信息，写一份完整的世界观文档：五字段齐全（世界基本盘/超凡体系/势力格局/资源规则/禁忌限制），世界规则一行一条至少 7 条，每条规则有明确的代价与限制。输出 Markdown 文档本身。" },
  { key: "角色卡", label: "人物", doc: "角色卡", aiRole: "网文人物设计师",
    aiTask: "根据这本书的现有信息，产出 3~5 张人物卡（主角/反派/核心配角），每张四件套齐全：欲望（表层+深层）/缺陷/成长弧/声口（含口头禅），反派加答三问（为何作恶/计划/强在哪）。输出 Markdown 文档本身。" },
  { key: "大纲", label: "大纲", doc: "大纲", aiRole: "资深网文总编",
    aiTask: "根据这本书的现有信息，产出大纲：一句话卖点 → 主线起承转合（含结局）→ 分卷规划表 → 第一卷逐章章纲（每章50-150字：事件→冲突→章末钩）。输出 Markdown 文档本身。" },
];

export default function StoryAssets({ go }) {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(() => {
    try { return sessionStorage.getItem("nl.guide.book") || sessionStorage.getItem("novel-ledger.book") || ""; } catch (e) { return ""; }
  });
  const [tab, setTab] = useState("设定");
  const [body, setBody] = useState("");
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [extra, setExtra] = useState("");
  const abortRef = useRef(null);

  useEffect(() => { api("/api/books").then((r) => setBooks(r.books)).catch(() => {}); }, []);
  useEffect(() => {
    if (!book) { setBody(""); return; }
    try { sessionStorage.setItem("nl.guide.book", book); } catch (e) {}
    setMsg(""); setEditing(false); setDirty(false);
    const doc = TABS.find((t) => t.key === tab)?.doc;
    if (!doc) return; // 伏笔/关系图 tab 不加载文档
    api(`/api/book/${encodeURIComponent(book)}/doc/${doc}`).then((d) => setBody(d.content || "")).catch((e) => setMsg(e.message));
  }, [book, tab]);

  async function save() {
    if (!book || busy) return;
    const doc = TABS.find((t) => t.key === tab)?.doc;
    try {
      await apiPutJson(`/api/book/${encodeURIComponent(book)}/doc/${doc}`, body);
      setDirty(false); setEditing(false);
      setMsg("已保存 ✅ 写章时自动作为上下文注入");
    } catch (e) { setMsg("保存失败：" + e.message); }
  }

  async function aiDraft() {
    if (!book || busy) return;
    const t = TABS.find((x) => x.key === tab);
    setBusy("AI 起草"); setMsg(`${t.label}起草中…（一次模型调用，完成后你审改再保存）`);
    const ctl = new AbortController(); abortRef.current = ctl;
    try {
      const ctx = [];
      for (const d of ["设定", "角色卡", "大纲"]) {
        try { const r = await api(`/api/book/${encodeURIComponent(book)}/doc/${d}`);
          if (r.content && r.content.trim() && !r.content.includes("待补")) ctx.push(`【${d}】\n${r.content.slice(0, 2500)}`); } catch (e) {}
      }
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stream: false, temperature: 0.6, max_tokens: 8000,
          messages: [
            { role: "system", content: `你是${t.aiRole}，只输出文档本身，不要前言后语。贴合已有设定，不得自相矛盾。` },
            { role: "user", content: `书：《${book}》\n\n${ctx.join("\n\n") || "（全新书，无已有资料）"}\n\n【任务】\n${t.aiTask}\n${extra.trim() ? "【补充要求】\n" + extra.trim() : ""}` },
          ],
        }),
        signal: ctl.signal,
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
      setBody(d.content || "（空响应，重试一次）");
      setDirty(true); setEditing(true);
      setMsg("草稿已生成（未保存）——审改后点「保存」才生效");
    } catch (e) {
      setMsg(e.name === "AbortError" ? "（已停止）" : "起草失败：" + e.message);
    } finally { setBusy(""); abortRef.current = null; }
  }

  const curTab = TABS.find((t) => t.key === tab);
  const isDocTab = !!curTab;

  return (
    <div>
      <div className="mb-3">
        <h1 className="text-xl font-extrabold text-ink">设定中心</h1>
        <p className="mt-0.5 text-[13px] text-inksoft">世界观 / 人物 / 关系图 / 大纲 / 伏笔——默认只读，点「修改」才能编辑，改完记得「保存」。写章时自动注入上下文。</p>
      </div>

      {/* 选书 + tabs 同排：选书在左 */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <select value={book} onChange={(e) => setBook(e.target.value)}
          className="mr-2 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] font-semibold text-ink">
          <option value="">选择一本书</option>
          {books.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        {TABS.map((t) => (
          <button key={t.key} onClick={() => { setTab(t.key); setEditing(false); }}
            className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition ${
              tab === t.key ? "bg-brand text-white" : "border border-line text-inksoft hover:text-ink"}`}>
            {t.label}
          </button>
        ))}
        <button onClick={() => setTab("__graph")}
          className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition ${
            tab === "__graph" ? "bg-brand text-white" : "border border-line text-inksoft hover:text-ink"}`}>
          关系图
        </button>
        <button onClick={() => setTab("__foreshadow")}
          className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition ${
            tab === "__foreshadow" ? "bg-brand text-white" : "border border-line text-inksoft hover:text-ink"}`}>
          伏笔
        </button>
      </div>
      {msg && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-sm text-ink">{msg}</div>}

      {!book ? (
        <div className="flex h-[50vh] items-center justify-center rounded-xl border border-dashed border-line text-sm text-inksoft">
          ← 先在左上角选一本书（没有书？去 AI 助手聊一本）
        </div>
      ) : tab === "__graph" ? (
        <RelationGraphView book={book} go={go} />
      ) : tab === "__foreshadow" ? (
        <div className="rounded-xl border border-line bg-panel p-4 shadow-sm">
          <Foreshadow />
        </div>
      ) : (
        <>
          {/* 工具行 */}
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {!editing ? (
              <button onClick={() => setEditing(true)}
                className="rounded-lg bg-brand px-3.5 py-1.5 text-[13px] font-semibold text-white hover:bg-brand2">
                ✏ 修改
              </button>
            ) : (
              <>
                <button onClick={save} disabled={busy || !dirty}
                  className="rounded-lg bg-ok px-3.5 py-1.5 text-[13px] font-semibold text-white hover:opacity-90 disabled:opacity-40">
                  💾 保存
                </button>
                <button onClick={() => { if (dirty && !confirm("放弃未保存的修改？")) return; setEditing(false); setDirty(false); }}
                  className="rounded-lg border border-line px-3 py-1.5 text-[13px] text-inksoft hover:text-ink">
                  取消
                </button>
              </>
            )}
            <button onClick={aiDraft} disabled={busy || !editing && body && !confirm("AI 起草会替换当前内容（建议先进入修改模式确认现状）。继续？")}
              className="rounded-lg border border-line bg-panel px-3.5 py-1.5 text-[13px] font-semibold text-ink hover:border-brand2 hover:text-brand disabled:opacity-40">
              {busy === "AI 起草" ? "⏳ 起草中…" : "✨ AI 起草"}
            </button>
            {editing && (
              <input value={extra} onChange={(e) => setExtra(e.target.value)}
                placeholder="补充要求（可选）：例如「主角是法医」「力量体系要有代价」"
                className="min-w-[240px] flex-1 rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-ink" />
            )}
            <span className="flex-1" />
            {!editing && !dirty && <span className="text-xs text-inksoft/70">只读模式 · 点「修改」编辑</span>}
          </div>

          {/* 内容区：默认只读卡片，编辑时 textarea */}
          {!editing ? (
            <div className="h-[56vh] overflow-auto rounded-xl border border-line bg-panel p-4 shadow-sm">
              {(body || "").split("\n").map((l, i) => (
                <div key={i} className={`text-[14px] leading-7 ${l.startsWith("#") ? "font-bold text-ink" : "text-ink"}`}>{l || "\u00A0"}</div>
              ))}
              {!body && <div className="pt-10 text-center text-sm text-inksoft">还没有内容——点「AI 起草」或「修改」手写</div>}
            </div>
          ) : (
            <textarea value={body} onChange={(e) => { setBody(e.target.value); setDirty(true); }} spellCheck={false}
              className="h-[56vh] w-full resize-y rounded-xl border border-line bg-panel p-4 font-serif text-[14px] leading-7 text-ink focus:outline-none focus:ring-2 focus:ring-brandbg" />
          )}
        </>
      )}
    </div>
  );
}

/* 可拖拽人物关系图（读取 R38 引擎产物 chapters/关系图谱.json；节点可拖动，边随动） */
function RelationGraphView({ book }) {
  const [graph, setGraph] = useState(null);
  const [pos, setPos] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const dragRef = useRef(null); // {name, dx, dy}
  const W = 820, H = 480;

  useEffect(() => { load(); }, [book]);

  async function load() {
    try {
      const d = await api(`/api/book/${encodeURIComponent(book)}/graph`);
      setGraph(d.graph || null);
      setPos(layout(d.graph));
    } catch (e) { setMsg(e.message); }
  }

  function layout(g) {
    const out = {};
    const nodes = g?.nodes || [];
    nodes.forEach((n, i) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(nodes.length, 1);
      out[n.name] = { x: W / 2 + (W / 2 - 110) * Math.cos(a), y: H / 2 + (H / 2 - 80) * Math.sin(a) };
    });
    return out;
  }

  async function generate() {
    if (!confirm("生成/更新关系图会调用模型给共现人物标注关系（少量 token），继续？")) return;
    setBusy(true); setMsg("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/graph`, {});
      setGraph(d.graph || null);
      setPos(layout(d.graph));
      setMsg(d.ok ? "已生成 ✅（节点可拖动）" : "生成失败（详见引擎日志）");
    } catch (e) { setMsg("生成失败：" + e.message); }
    setBusy(false);
  }

  function onPointerDown(e, name) {
    e.target.setPointerCapture?.(e.pointerId);
    const pt = pos[name];
    dragRef.current = { name, dx: e.clientX - pt.x, dy: e.clientY - pt.y };
  }
  function onPointerMove(e) {
    if (!dragRef.current) return;
    const { name, dx, dy } = dragRef.current;
    setPos((s) => ({ ...s, [name]: {
      x: Math.max(30, Math.min(W - 30, e.clientX - dx)),
      y: Math.max(26, Math.min(H - 26, e.clientY - dy)),
    } }));
  }
  function onPointerUp() { dragRef.current = null; }

  const nodes = graph?.nodes || [];
  const edges = graph?.edges || [];

  return (
    <div className="rounded-xl border border-line bg-panel p-4 shadow-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[13.5px] font-bold text-ink">人物关系图</span>
        <span className="text-xs text-inksoft">节点来自角色卡/账本；每条边有同章共现背书，可拖动摆位。</span>
        <span className="flex-1" />
        <button onClick={generate} disabled={busy}
          className="rounded-lg bg-brand px-3.5 py-1.5 text-[13px] font-semibold text-white hover:bg-brand2 disabled:opacity-40">
          {busy ? "⏳ 生成中…" : graph ? "🔄 生成/更新" : "✨ 生成关系图"}
        </button>
      </div>
      {msg && <div className="mb-2 rounded-lg bg-brandbg px-3 py-1.5 text-[12.5px] text-ink">{msg}</div>}
      {nodes.length > 0 ? (
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full rounded-lg border border-line bg-paper"
          onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}>
          {edges.map((e2, i) => {
            const p1 = pos[e2.a], p2 = pos[e2.b];
            if (!p1 || !p2) return null;
            return (
              <g key={i}>
                <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke="var(--nl-line)" strokeWidth="1.5" />
                <text x={(p1.x + p2.x) / 2} y={(p1.y + p2.y) / 2 - 4} textAnchor="middle" fontSize="11" fill="var(--nl-inksoft)">{e2.rel}</text>
              </g>
            );
          })}
          {nodes.map((n) => {
            const pt = pos[n.name] || { x: W / 2, y: H / 2 };
            return (
              <g key={n.name} style={{ cursor: "grab" }}
                onPointerDown={(e) => onPointerDown(e, n.name)}>
                <circle cx={pt.x} cy={pt.y} r="16" fill="var(--nl-brand)" opacity="0.92">
                  <title>{`${n.name}：提及 ${n.chapters} 章`}</title>
                </circle>
                <text x={pt.x} y={pt.y + 30} textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--nl-ink)">{n.name}</text>
              </g>
            );
          })}
        </svg>
      ) : (
        <div className="flex h-56 items-center justify-center rounded-lg border border-dashed border-line text-sm text-inksoft">
          还没有关系图——点右上「生成关系图」（人物来自角色卡与账本）
        </div>
      )}
      {edges.length > 0 && (
        <div className="mt-3 max-h-40 overflow-auto rounded-lg border border-line bg-paper p-2.5 text-[12.5px]">
          {edges.map((e2, i) => (
            <div key={i} className="text-inksoft">{e2.a} —[{e2.rel}]— {e2.b}{e2.chapters?.length ? `（共现章 ${e2.chapters.join("、")}）` : ""}</div>
          ))}
        </div>
      )}
    </div>
  );
}
