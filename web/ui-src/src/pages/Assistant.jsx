import React, { useEffect, useRef, useState } from "react";
import { api, apiPut } from "../api.js";

/* AI 助手：全局对话页——可选一本书作为上下文，聊剧情/查矛盾/改稿。
   改稿：选中章节后，AI 的回复可一键替换该章正文（有确认）。
   会话持久化 sessionStorage（切页/刷新不丢）。 */

const SS_KEY = "nl_assistant_v1";
const HELLO = "我是你的写作助手。选一本书（或直接聊），可以让我：总结剧情 / 查前后矛盾 / 给后续章节点子 / 重写某一段 / 把你的想法整理成设定。";

function loadState() {
  try {
    const d = JSON.parse(sessionStorage.getItem(SS_KEY) || "null");
    if (d && Array.isArray(d.msgs)) return d;
  } catch (e) {}
  return { msgs: [{ role: "assistant", content: HELLO }], book: "", ch: "", keepState: true };
}

const QUICK = ["用三句话总结目前已写的剧情", "检查已写章节有没有前后矛盾，列出来", "给下一章出 3 个可行的剧情方向", "目前哪些伏笔拖太久了？怎么收？"];

export default function Assistant({ go }) {
  const saved = loadState();
  const [msgs, setMsgs] = useState(saved.msgs);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(saved.book || "");
  const [ch, setCh] = useState(saved.ch || "");
  const [chapters, setChapters] = useState([]);
  const [chText, setChText] = useState("");
  const [keepState, setKeepState] = useState(saved.keepState !== false);
  const logRef = useRef(null);

  useEffect(() => {
    try { sessionStorage.setItem(SS_KEY, JSON.stringify({ msgs, book, ch, keepState })); } catch (e) {}
  }, [msgs, book, ch, keepState]);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [msgs, streaming]);

  useEffect(() => {
    api("/api/books").then((r) => setBooks(r.books)).catch(() => {});
  }, []);
  useEffect(() => {
    if (!book) { setChapters([]); setCh(""); return; }
    api(`/api/book/${encodeURIComponent(book)}`).then((d) => setChapters(d.chapters || [])).catch(() => {});
  }, [book]);
  useEffect(() => {
    if (!book || !ch) { setChText(""); return; }
    api(`/api/book/${encodeURIComponent(book)}/ch/${ch}`).then((d) => setChText(d.content || "")).catch(() => setChText(""));
  }, [book, ch]);

  // 组上下文：书资料（可选账本）+ 选中的章节正文
  async function buildContext() {
    if (!book) return null;
    const parts = [`当前讨论的书：《${book}》`];
    for (const doc of ["设定", "角色卡", "大纲"]) {
      try {
        const t = (await api(`/api/book/${encodeURIComponent(book)}/doc/${doc}`)).content;
        if (t && t.trim()) parts.push(`【${doc}】\n${t.trim().slice(0, 3000)}`);
      } catch (e) {}
    }
    if (keepState) {
      try {
        const t = (await api(`/api/book/${encodeURIComponent(book)}/doc/state`)).content;
        if (t && t.trim()) parts.push(`【记忆账本（截至最新章的事实/伏笔/时间线）】\n${t.trim().slice(0, 9000)}`);
      } catch (e) {}
    }
    if (ch && chText) parts.push(`【正在讨论的章节：第 ${ch} 章全文】\n${chText}`);
    return "你是这本书的写作助手。下方是书籍资料，回答要贴合已设定的事实，不得编造与资料矛盾的设定。\n\n" + parts.join("\n\n");
  }

  async function send(text) {
    const t = (text || input).trim();
    if (!t || streaming) return;
    setInput(""); setStreaming(true);
    const next = [...msgs, { role: "user", content: t }, { role: "assistant", content: "" }];
    setMsgs(next);
    const i = next.length - 1;
    try {
      const ctx = await buildContext();
      const sys = ctx ? { role: "system", content: ctx } : { role: "system", content: "你是中文网文写作助手，回答简洁实用。" };
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream: true, temperature: 0.7, max_tokens: 4000, messages: [sys, ...next.slice(0, -1)] }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n"); buf = parts.pop();
        for (const ln of parts) {
          if (!ln.startsWith("data: ")) continue;
          try {
            const delta = (((JSON.parse(ln.slice(6)).choices || [{}])[0]).delta || {}).content || "";
            if (delta) setMsgs((m) => { const c = [...m]; c[i] = { ...c[i], content: c[i].content + delta }; return c; });
          } catch (e) {}
        }
      }
    } catch (e) {
      setMsgs((m) => { const c = [...m]; c[i] = { ...c[i], content: "（调用失败：" + e.message + "）" }; return c; });
    } finally { setStreaming(false); }
  }

  // 把最后一条 AI 回复写回选中章节（改稿落地）
  async function applyToChapter() {
    const last = [...msgs].reverse().find((m) => m.role === "assistant");
    const t = (last?.content || "").trim();
    if (!t || !book || !ch) return;
    if (!confirm(`用这条回复替换《${book}》第 ${ch} 章正文？\n（原文会被覆盖，建议先备份）`)) return;
    try {
      await apiPut(`/api/book/${encodeURIComponent(book)}/ch/${ch}`, t);
      setMsgs((m) => [...m, { role: "assistant", content: `（已把回复写入第 ${ch} 章 ✅ 可在「章节与账本」里查看）` }]);
    } catch (e) { alert("写入失败：" + e.message); }
  }

  const lastAssistant = [...msgs].reverse().find((m) => m.role === "assistant" && m.content);

  return (
    <div className="mx-auto flex h-[calc(100vh-6.5rem)] max-w-4xl flex-col">
      <h1 className="mb-1 text-xl font-bold text-ink">AI 助手</h1>
      <p className="mb-3 text-[13px] text-inksoft">带着书的记忆聊：总结剧情、查矛盾、出点子、改稿。选中章节后，AI 的回复可以一键写回正文。</p>

      {/* 上下文选择条 */}
      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2 shadow-sm">
        <select value={book} onChange={(e) => setBook(e.target.value)}
          className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px]">
          <option value="">不选书（纯聊）</option>
          {books.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        {book && chapters.length > 0 && (
          <select value={ch} onChange={(e) => setCh(e.target.value)}
            className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px]">
            <option value="">不改稿（仅讨论）</option>
            {chapters.map((c) => <option key={c.no} value={c.no}>第 {c.no} 章 {c.title || ""}</option>)}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-xs text-inksoft">
          <input type="checkbox" checked={keepState} onChange={(e) => setKeepState(e.target.checked)} />
          附带记忆账本
        </label>
        <span className="flex-1" />
        {book && go && (
          <button onClick={() => go("workspace", book)}
            className="rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand2">
            去工作台写下一章 →
          </button>
        )}
        <button onClick={() => { if (confirm("清空对话？")) { setMsgs([{ role: "assistant", content: HELLO }]); } }}
          className="text-xs text-inksoft hover:text-ink">清空对话</button>
      </div>

      {/* 对话区 */}
      <div ref={logRef} className="flex-1 overflow-auto rounded-xl border border-line bg-panel p-4 shadow-sm">
        {msgs.map((m, i) => (
          <div key={i} className={`mb-3 max-w-[92%] rounded-lg px-3.5 py-2.5 text-[13.5px] leading-6 ${m.role === "user" ? "ml-auto bg-brandbg" : "bg-paper"}`}>
            {m.role !== "user" && <div className="mb-0.5 text-[11px] text-inksoft">AI</div>}
            {m.content ? m.content.split("\n").map((l, j) => <div key={j}>{l || "\u00A0"}</div>)
              : <span className="inline-flex items-center gap-1.5 text-inksoft"><span className="h-1.5 w-1.5 animate-ping rounded-full bg-accent" />AI 生成中…</span>}
          </div>
        ))}
        {!streaming && lastAssistant && book && ch && (
          <div className="mb-3 flex justify-end">
            <button onClick={applyToChapter}
              className="rounded-lg border border-line px-3 py-1.5 text-xs hover:border-ink/30">
              把上面的回复替换第 {ch} 章正文
            </button>
          </div>
        )}
      </div>

      {/* 快捷提问 */}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUICK.map((q) => (
          <button key={q} onClick={() => send(q)} disabled={streaming}
            className="rounded-full border border-line bg-panel px-3 py-1 text-xs text-inksoft hover:border-ink/30 hover:text-ink disabled:opacity-40">
            {q}
          </button>
        ))}
      </div>

      {/* 输入区 */}
      <div className="mt-2">
        <textarea value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="和 AI 聊这本书…（Enter 发送，Shift+Enter 换行）"
          className="h-20 w-full resize-none" />
        <div className="mt-2 flex justify-end">
          <button onClick={() => send()} disabled={streaming || !input.trim()}
            className="rounded-lg bg-brand px-5 py-2 text-[13px] font-medium text-white hover:bg-brand2 disabled:opacity-40">发送</button>
        </div>
      </div>
    </div>
  );
}
