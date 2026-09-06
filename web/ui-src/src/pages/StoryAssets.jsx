import React, { useEffect, useRef, useState } from "react";
import { api, apiPost, apiPutJson } from "../api.js";

/* 设定中心：一本书的「世界观 / 人物 / 大纲」分页编辑 + AI 起草 + 套模板。
   数据仍落在引擎的三件套文件（设定.md / 角色卡.md / 大纲.md），零迁移；
   伏笔走独立「伏笔账本」页。所有 AI 起草只填草稿不落盘，保存权在人。 */

const TABS = [
  { key: "设定", label: "世界观与势力", icon: "🌍", doc: "设定", aiRole: "网文世界观架构师", aiTask: "根据这本书的现有信息，写一份完整的世界观文档：五字段齐全（世界基本盘/超凡体系/势力格局/资源规则/禁忌限制），世界规则一行一条至少 7 条，每条规则有明确的代价与限制。输出 Markdown 文档本身。" },
  { key: "角色卡", label: "人物", icon: "🧑", doc: "角色卡", aiRole: "网文人物设计师", aiTask: "根据这本书的现有信息，产出 3~5 张人物卡（主角/反派/核心配角），每张四件套齐全：欲望（表层+深层）/缺陷/成长弧/声口（含口头禅），反派加答三问（为何作恶/计划/强在哪）。输出 Markdown 文档本身。" },
  { key: "大纲", label: "大纲", icon: "🗺", doc: "大纲", aiRole: "资深网文总编", aiTask: "根据这本书的现有信息，产出大纲：一句话卖点 → 主线起承转合（含结局）→ 分卷规划表 → 第一卷逐章章纲（每章50-150字：事件→冲突→章末钩）。输出 Markdown 文档本身。" },
];

export default function StoryAssets({ go }) {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(() => { try { return sessionStorage.getItem("nl.guide.book") || sessionStorage.getItem("novel-ledger.book") || ""; } catch (e) { return ""; } });
  const [tab, setTab] = useState(TABS[0].key);
  const [body, setBody] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [extra, setExtra] = useState(""); // 给 AI 的补充要求
  const abortRef = useRef(null);

  useEffect(() => { api("/api/books").then((r) => setBooks(r.books)).catch(() => {}); }, []);
  useEffect(() => {
    if (!book) { setBody(""); return; }
    try { sessionStorage.setItem("nl.guide.book", book); } catch (e) {}
    setMsg(""); setDirty(false);
    const doc = TABS.find((t) => t.key === tab).doc;
    api(`/api/book/${encodeURIComponent(book)}/doc/${doc}`).then((d) => setBody(d.content || "")).catch((e) => setMsg(e.message));
  }, [book, tab]);

  async function save() {
    if (!book || busy) return;
    const doc = TABS.find((t) => t.key === tab).doc;
    try {
      await apiPutJson(`/api/book/${encodeURIComponent(book)}/doc/${doc}`, body);
      setDirty(false); setMsg("已保存 ✅ 写章时自动作为上下文注入");
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
      setDirty(true);
      setMsg("草稿已生成（未保存）——审改后点「保存」才生效");
    } catch (e) {
      setMsg(e.name === "AbortError" ? "（已停止）" : "起草失败：" + e.message);
    } finally { setBusy(""); abortRef.current = null; }
  }

  function applyTpl(t) {
    setBody((b) => (b && b.trim() && !window.confirm("当前内容会被模板覆盖（建议先保存一份），继续？") ? b : t.content));
    setDirty(true);
  }

  const curTab = TABS.find((t) => t.key === tab);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-extrabold text-ink">设定中心</h1>
          <p className="mt-0.5 text-[13px] text-inksoft">世界观 / 人物 / 大纲 分页管理——AI 起草草稿，你审改拍板。写章时自动注入上下文。</p>
        </div>
        <select value={book} onChange={(e) => setBook(e.target.value)}
          className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink">
          <option value="">选择一本书</option>
          {books.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      </div>
      {msg && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-sm text-ink">{msg}</div>}

      {!book ? (
        <div className="flex h-[50vh] items-center justify-center rounded-xl border border-dashed border-line text-sm text-inksoft">
          ← 先选一本书（没有书？去 AI 助手聊一本，或从模板建一本）
        </div>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition ${
                  tab === t.key ? "bg-brand text-white" : "border border-line text-inksoft hover:text-ink"}`}>
                {t.icon} {t.label}
              </button>
            ))}
            <button onClick={() => go("foreshadow")}
              className="rounded-lg border border-line px-3.5 py-1.5 text-[13px] text-inksoft transition hover:text-ink">
              🔗 伏笔（独立页）→
            </button>
            <span className="flex-1" />
            {dirty && <span className="text-xs text-warn">未保存</span>}
          </div>

          <div className="mb-2 flex flex-wrap items-center gap-2">
            <button onClick={aiDraft} disabled={busy}
              className="rounded-lg bg-brand px-3.5 py-1.5 text-[13px] font-semibold text-white hover:bg-brand2 disabled:opacity-40">
              {busy === "AI 起草" ? "⏳ 起草中…" : `✨ AI 起草${curTab.label}`}
            </button>
            {busy === "AI 起草" && (
              <button onClick={() => abortRef.current?.abort()} className="rounded-lg border border-err/40 px-3 py-1.5 text-xs text-err hover:bg-errbg">■ 停止</button>
            )}
            <input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="补充要求（可选）：例如「主角是法医」「力量体系要有代价」"
              className="min-w-[260px] flex-1 rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-ink" />
            <button onClick={save} disabled={busy || !dirty}
              className="rounded-lg border border-line bg-panel px-4 py-1.5 text-[13px] font-semibold text-ink hover:border-brand2 hover:text-brand disabled:opacity-40">
              保存{dirty ? " *" : ""}
            </button>
          </div>

          <textarea value={body} onChange={(e) => { setBody(e.target.value); setDirty(true); }} spellCheck={false}
            placeholder={`${curTab.label}内容（Markdown）——可手写、可 AI 起草、可从灵感库套模板`}
            className="h-[56vh] w-full resize-y rounded-xl border border-line bg-panel p-4 font-serif text-[14px] leading-7 text-ink focus:outline-none focus:ring-2 focus:ring-brandbg" />
        </>
      )}
    </div>
  );
}
