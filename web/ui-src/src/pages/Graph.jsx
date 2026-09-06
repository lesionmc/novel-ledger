import React, { useEffect, useState } from "react";
import { api, apiAny, apiPost } from "../api.js";

/* 图谱与文风页（v0.8）：关系图谱（生成/查看）+ 文风指纹（学习/展示）+ 向量索引（状态/建立）。
   长任务均为一次 POST 等结果，按钮转 loading、输出文本落在区块内。 */

function tryParseJson(s) {
  if (s == null || typeof s !== "string") return s;
  try { return JSON.parse(s); } catch (e) { return null; }
}

export default function Graph() {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(null);

  const [graph, setGraph] = useState(null);        // GET graph：{json, md} 或 null（404=未生成）
  const [graphErr, setGraphErr] = useState("");
  const [graphBusy, setGraphBusy] = useState(false);
  const [graphLog, setGraphLog] = useState("");

  const [style, setStyle] = useState(null);        // 指纹 md 文本 或 null（404=未学习）
  const [styleLog, setStyleLog] = useState("");
  const [styleBusy, setStyleBusy] = useState(false);

  const [vec, setVec] = useState(null);            // GET vector 状态对象
  const [vecBusy, setVecBusy] = useState(false);
  const [vecLog, setVecLog] = useState("");

  useEffect(() => {
    api("/api/books").then(async (r) => {
      setBooks(r.books);
      if (r.books.length) pick(r.books[0]);
    }).catch(() => {});
  }, []);

  async function pick(name) {
    setBook(name);
    setGraph(null); setGraphErr(""); setGraphLog("");
    setStyle(null); setStyleLog("");
    setVec(null); setVecLog("");
    const b = encodeURIComponent(name);
    // 已有图谱 / 指纹 / 向量状态（404 = 尚未生成，静默留空）
    apiAny(`/api/book/${b}/graph`)
      .then((d) => setGraph(d && typeof d === "object" ? d : { md: String(d) }))
      .catch((e) => { if (!/^HTTP 404/.test(e.message)) setGraphErr(e.message); });
    apiAny(`/api/book/${b}/style`)
      .then((d) => setStyle(typeof d === "string" ? d : (d.content || d.md || "")))
      .catch(() => {});
    apiAny(`/api/book/${b}/vector`).then(setVec).catch(() => {});
  }

  async function genGraph() {
    if (!book || graphBusy) return;
    setGraphBusy(true); setGraphLog(""); setGraphErr("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/graph`, {});
      setGraphLog(d.log || d.report || (typeof d === "string" ? d : ""));
      const g = await apiAny(`/api/book/${encodeURIComponent(book)}/graph`);
      setGraph(g && typeof g === "object" ? g : { md: String(g) });
    } catch (e) { setGraphErr("生成图谱失败：" + e.message); }
    finally { setGraphBusy(false); }
  }

  async function learnStyle() {
    if (!book || styleBusy) return;
    setStyleBusy(true); setStyleLog("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/style-learn`, {});
      setStyleLog(d.log || d.report || (typeof d === "string" ? d : ""));
      const s = await apiAny(`/api/book/${encodeURIComponent(book)}/style`);
      setStyle(typeof s === "string" ? s : (s.content || s.md || ""));
    } catch (e) { setStyleLog("学文风失败：" + e.message); }
    finally { setStyleBusy(false); }
  }

  async function buildIndex() {
    if (!book || vecBusy) return;
    setVecBusy(true); setVecLog("");
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(book)}/vector-index`, {}, { timeout: 0 });
      setVecLog(d.log || d.report || (typeof d === "string" ? d : ""));
      setVec(await apiAny(`/api/book/${encodeURIComponent(book)}/vector`));
    } catch (e) { setVecLog("建立索引失败：" + e.message); }
    finally { setVecBusy(false); }
  }

  // 图谱数据：json 可能是对象或 JSON 字符串；节点/关系字段名做兼容
  const gj = graph ? tryParseJson(graph.json) || graph.json : null;
  const nodes = (gj && Array.isArray(gj.nodes) && gj.nodes) || [];
  const edges = (gj && (Array.isArray(gj.relations) && gj.relations || Array.isArray(gj.edges) && gj.edges)) || [];
  const edgeText = (e) => (typeof e === "string" ? e : [e.from || e.source, e.rel || e.relation || e.label, e.to || e.target].filter(Boolean).join(" —"));

  return (
    <div>
      <h1 className="mb-1 text-xl font-bold text-ink">图谱与文风</h1>
      <p className="mb-4 text-[13px] text-inksoft">
        把这本书「算」一遍：人物关系图谱、文风指纹、向量索引。都是长任务，点一次等结果即可。
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {books.map((b) => (
          <button key={b} onClick={() => pick(b)}
            className={`rounded-lg px-3 py-1.5 text-[13px] ${b === book ? "bg-brand text-white" : "border border-line bg-panel hover:border-ink/30"}`}>
            {b}
          </button>
        ))}
        {books.length === 0 && <span className="text-sm text-inksoft">还没有书，先去「新建书」。</span>}
      </div>

      {/* 关系图谱 */}
      <section className="mb-4 rounded-xl border border-line bg-panel p-4 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold text-ink">人物关系图谱</h2>
          <button onClick={genGraph} disabled={!book || graphBusy}
            className="rounded-lg bg-brand px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-brand2 disabled:opacity-40">
            {graphBusy ? "⏳ 生成中…（约 1-3 分钟）" : "生成图谱"}
          </button>
        </div>
        {graphErr && <div className="mb-2 rounded-lg bg-errbg px-3 py-2 text-[13px] text-err">{graphErr}</div>}
        {!graph && !graphBusy && !graphErr && (
          <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-inksoft">
            {book ? "尚未生成图谱，点右上角「生成图谱」。" : "先选一本书"}
          </div>
        )}
        {graph && (
          <>
            {(nodes.length > 0 || edges.length > 0) && (
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-brandbg px-3 py-1 text-xs text-ink">节点 × {nodes.length}</span>
                <span className="rounded-full bg-brandbg px-3 py-1 text-xs text-ink">关系 × {edges.length}</span>
              </div>
            )}
            {edges.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {edges.slice(0, 60).map((e, i) => (
                  <span key={i} className="rounded-full border border-line bg-paper px-2.5 py-1 text-xs text-inksoft">{edgeText(e)}</span>
                ))}
              </div>
            )}
            {graph.md && <div className="rounded-lg border border-line bg-paper p-4 text-[13.5px] leading-6"><Md text={graph.md} /></div>}
          </>
        )}
        {graphLog && (
          <details className="mt-2 rounded-lg border border-line bg-topbar p-2 text-xs text-topbarfg">
            <summary className="cursor-pointer text-inksoft">引擎日志</summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono">{graphLog}</pre>
          </details>
        )}
      </section>

      {/* 文风指纹 */}
      <section className="mb-4 rounded-xl border border-line bg-panel p-4 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold text-ink">文风指纹</h2>
          <button onClick={learnStyle} disabled={!book || styleBusy}
            className="rounded-lg border border-line px-3.5 py-1.5 text-[13px] hover:border-brand2 hover:text-brand disabled:opacity-40">
            {styleBusy ? "⏳ 学习中…（通读样章，约 2-5 分钟）" : "学文风"}
          </button>
        </div>
        {style ? (
          <div className="rounded-lg border border-line bg-paper p-4 text-[13.5px] leading-6"><Md text={style} /></div>
        ) : (
          <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-inksoft">
            {book ? "尚未学习文风（基于样章自动归纳，写章时注入保持手感一致）。" : "先选一本书"}
          </div>
        )}
        {styleLog && (
          <details className="mt-2 rounded-lg border border-line bg-topbar p-2 text-xs text-topbarfg">
            <summary className="cursor-pointer text-inksoft">引擎日志</summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono">{styleLog}</pre>
          </details>
        )}
      </section>

      {/* 向量索引 */}
      <section className="rounded-xl border border-line bg-panel p-4 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold text-ink">向量索引</h2>
          <button onClick={buildIndex} disabled={!book || vecBusy}
            className="rounded-lg border border-line px-3.5 py-1.5 text-[13px] hover:border-brand2 hover:text-brand disabled:opacity-40">
            {vecBusy ? "⏳ 建索引中…" : "建立索引"}
          </button>
        </div>
        {vec ? (
          vec.available === false ? (
            <div className="rounded-lg bg-warnbg px-3 py-2 text-[13px] text-warn">向量后端不可用（{vec.reason || "未安装/未配置"}），检索类功能降级为全文匹配。</div>
          ) : (
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(vec).map(([k, v]) => (
                <span key={k} className="rounded-full bg-brandbg px-3 py-1 text-ink">{k}: {String(v)}</span>
              ))}
            </div>
          )
        ) : (
          <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-inksoft">
            {book ? "尚未建立索引（把已写章节向量化，供检索引用）。" : "先选一本书"}
          </div>
        )}
        {vecLog && (
          <details className="mt-2 rounded-lg border border-line bg-topbar p-2 text-xs text-topbarfg">
            <summary className="cursor-pointer text-inksoft">引擎日志</summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono">{vecLog}</pre>
          </details>
        )}
      </section>
    </div>
  );
}

/* 极简 Markdown 渲染（标题/列表/粗体/分隔线/段落） */
function Md({ text }) {
  const lines = (text || "").split("\n");
  const out = [];
  let para = [];
  const flush = () => {
    if (para.length) { out.push(<p key={out.length} className="my-2 whitespace-pre-wrap">{inline(para.join("\n"))}</p>); para = []; }
  };
  const inline = (s) => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p);
  for (const raw of lines) {
    const l = raw.trimEnd();
    const h = l.match(/^(#{1,4})\s+(.*)/);
    if (h) { flush(); out.push(<div key={out.length} className={`mt-3 font-bold text-ink ${h[1].length <= 2 ? "text-[15px]" : "text-[13.5px]"}`}>{inline(h[2])}</div>); }
    else if (/^={3,}$|^---+$/.test(l)) { flush(); out.push(<hr key={out.length} className="my-3 border-line" />); }
    else if (/^[-*]\s+/.test(l)) { flush(); out.push(<div key={out.length} className="my-0.5 pl-3">· {inline(l.replace(/^[-*]\s+/, ""))}</div>); }
    else if (l === "") { flush(); }
    else { para.push(l); }
  }
  flush();
  return <div>{out}</div>;
}
