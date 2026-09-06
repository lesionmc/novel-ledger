import React, { useEffect, useRef, useState } from "react";
import { api, apiPost, apiPut } from "../api.js";

/* AI 助手 · WorkBuddy/Codex 风格会话工作台
   ┌ 会话列表（左侧，localStorage 持久化） ├ 聊天主区（气泡带边框，三主题可读） ┐
   新建书也在这里：快捷卡「新建一本书」→ 填书名/选模板 → 建书成功直接挂上下文开聊。 */

const LS_KEY = "nl_assistant_sessions_v1";
const HELLO = "我是你的写作助手。上方选一本书（或不选直接聊），可以让我：总结剧情 / 查前后矛盾 / 出章节点子 / 重写某一段 / 把想法整理成设定。也可以直接下指令：交叉审计第 N 章 / 重算账本 / 平台自检 / 读者试读 / 导出证据包。想开新书就点左下角「＋ 新建一本书」。";

function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

function loadSessions() {
  try {
    const arr = JSON.parse(localStorage.getItem(LS_KEY) || "null");
    if (Array.isArray(arr) && arr.length) return arr;
  } catch (e) {}
  return [newSession()];
}

function newSession() {
  return { id: uid(), title: "新对话", book: "", ch: "", keepState: true,
           msgs: [{ role: "assistant", content: HELLO }], ts: Date.now() };
}

function saveSessions(arr) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(arr.slice(0, 50))); } catch (e) {}
}

const QUICK = ["用三句话总结目前已写的剧情", "检查已写章节有没有前后矛盾，列出来", "给下一章出 3 个可行的剧情方向", "目前哪些伏笔拖太久了？怎么收？"];

/* v0.9 意图路由：命中关键词直接调引擎端点（不进聊天流），风险动作先 confirm */
const INTENTS = [
  { re: /交叉审计|交叉核验/, ep: "cross-audit", label: "交叉审计", risk: false },
  { re: /重算账本|账本重算|重算/, ep: "recalc-from", label: "重算账本", risk: true },
  { re: /平台自检|平台检查|平台适配/, ep: "platform-check", label: "平台自检", risk: false },
  { re: /读者试读|试读反馈|试读/, ep: "beta-reader", label: "读者试读", risk: false },
  { re: /导出证据|证据包/, ep: "export-evidence", label: "导出证据包", risk: true },
];

function parseIntent(text) {
  for (const it of INTENTS) {
    if (it.re.test(text)) {
      const m = text.match(/第\s*(\d+)\s*章/) || text.match(/(\d{1,4})\s*章/);
      return { ...it, no: m ? parseInt(m[1]) : null };
    }
  }
  return null;
}

export default function Assistant({ go }) {
  const [sessions, setSessions] = useState(loadSessions);
  const [activeId, setActiveId] = useState(() => loadSessions()[0].id);
  const cur = sessions.find((s) => s.id === activeId) || sessions[0];

  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [books, setBooks] = useState([]);
  const [chapters, setChapters] = useState([]);
  const [chText, setChText] = useState("");
  const [templates, setTemplates] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const abortRef = useRef(null);
  const logRef = useRef(null);

  const msgs = cur.msgs;

  function patchCur(patch) {
    setSessions((arr) => arr.map((s) => (s.id === activeId ? { ...s, ...patch, ts: Date.now() } : s)));
  }
  function setMsgs(updater) {
    setSessions((arr) => arr.map((s) => (s.id === activeId
      ? { ...s, msgs: typeof updater === "function" ? updater(s.msgs) : updater, ts: Date.now() } : s)));
  }

  useEffect(() => { saveSessions(sessions); }, [sessions]);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [msgs, streaming]);

  useEffect(() => {
    api("/api/books").then((r) => setBooks(r.books)).catch(() => {});
    api("/api/templates").then((d) => setTemplates(d.templates || [])).catch(() => {});
    // 首页「＋ 新建书」跳转过来时自动展开建书卡
    try {
      if (sessionStorage.getItem("nl_assistant_open_create") === "1") {
        setShowCreate(true);
        sessionStorage.removeItem("nl_assistant_open_create");
      }
    } catch (e) {}
  }, []);
  useEffect(() => {
    if (!cur.book) { setChapters([]); patchCur({ ch: "" }); return; }
    api(`/api/book/${encodeURIComponent(cur.book)}`).then((d) => setChapters(d.chapters || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur.book]);
  useEffect(() => {
    if (!cur.book || !cur.ch) { setChText(""); return; }
    api(`/api/book/${encodeURIComponent(cur.book)}/ch/${cur.ch}`).then((d) => setChText(d.content || "")).catch(() => setChText(""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur.book, cur.ch]);

  function addMsgs(pair) {
    setMsgs((m) => [...m, ...pair]);
  }
  function say(content) { setMsgs((m) => [...m, { role: "assistant", content }]); }

  // 组上下文：书资料（可选账本）+ 选中的章节正文
  async function buildContext(session) {
    if (!session.book) return null;
    const parts = [`当前讨论的书：《${session.book}》`];
    for (const doc of ["设定", "角色卡", "大纲"]) {
      try {
        const t = (await api(`/api/book/${encodeURIComponent(session.book)}/doc/${doc}`)).content;
        if (t && t.trim()) parts.push(`【${doc}】\n${t.trim().slice(0, 3000)}`);
      } catch (e) {}
    }
    if (session.keepState) {
      try {
        const t = (await api(`/api/book/${encodeURIComponent(session.book)}/doc/state`)).content;
        if (t && t.trim()) parts.push(`【记忆账本（截至最新章的事实/伏笔/时间线）】\n${t.trim().slice(0, 9000)}`);
      } catch (e) {}
    }
    if (session.ch && chText) parts.push(`【正在讨论的章节：第 ${session.ch} 章全文】\n${chText}`);
    return "你是这本书的写作助手。下方是书籍资料，回答要贴合已设定的事实，不得编造与资料矛盾的设定。\n\n" + parts.join("\n\n");
  }

  // 意图路由：命中操作词 → 直接调引擎端点并把输出贴回对话（可随时「停止」）
  async function runIntent(intent, text) {
    if (!cur.book) { say(`（请先在上方选择一本书，再使用「${intent.label}」）`); return; }
    const no = intent.no || parseInt(cur.ch) || (chapters.length ? chapters[chapters.length - 1].no : null);
    if (!no) { say(`（无法确定章号：请在指令里带上章号，例如「${intent.label}第 3 章」，或先在上方选中一章）`); return; }
    if (intent.risk && !confirm(`「${intent.label}」对《${cur.book}》从第 ${no} 章起执行，可能改写账本/生成产物。继续？`)) return;
    addMsgs([{ role: "user", content: text }, { role: "assistant", content: "" }]);
    setStreaming(true);
    const ctl = new AbortController();
    abortRef.current = ctl;
    try {
      const d = await apiPost(`/api/book/${encodeURIComponent(cur.book)}/${intent.ep}`, { no }, { timeout: 0, signal: ctl.signal });
      const out = (d && (d.log || d.report || d.content)) || (typeof d === "string" ? d : "") || "（引擎无输出）";
      setMsgs((m) => { const c = [...m]; c[c.length - 1] = { role: "assistant", content: `【${intent.label} · 第 ${no} 章】\n${out}` }; return c; });
    } catch (e) {
      const msg = e.name === "AbortError" || /abort/i.test(e.message || "") ? "（已停止）" : `（${intent.label}失败：${e.message}）`;
      setMsgs((m) => { const c = [...m]; c[c.length - 1] = { role: "assistant", content: msg }; return c; });
    } finally { setStreaming(false); abortRef.current = null; }
  }

  async function send(text) {
    const t = (text || input).trim();
    if (!t || streaming) return;
    const intent = parseIntent(t);
    if (intent) { setInput(""); await runIntent(intent, t); return; }
    setInput(""); setStreaming(true);
    addMsgs([{ role: "user", content: t }, { role: "assistant", content: "" }]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    try {
      const ctx = await buildContext(cur);
      const sys = ctx ? { role: "system", content: ctx } : { role: "system", content: "你是中文网文写作助手，回答简洁实用。" };
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream: true, temperature: 0.7, max_tokens: 4000, messages: [sys, ...msgs.slice(0, -1)] }),
        signal: ctl.signal,
      });
      if (!r.ok) throw new Error(r.status === 502 ? "上游模型波动，请点重试（已自动多次尝试）" : "HTTP " + r.status);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "", ev = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n"); buf = parts.pop();
        for (const ln of parts) {
          if (ln.startsWith("event: ")) { ev = ln.slice(7).trim(); continue; }
          if (!ln.startsWith("data: ")) continue;
          let v;
          try { v = JSON.parse(ln.slice(6)); } catch (e) { continue; }
          if (ev === "error") {
            setMsgs((m) => { const c = [...m]; c[c.length - 1] = { role: "assistant", content: "（调用失败：" + (typeof v === "string" ? v : (v && v.error) || "未知错误") + "）" }; return c; });
          } else if (typeof v === "string") {
            if (v) setMsgs((m) => { const c = [...m]; const last = c[c.length - 1]; c[c.length - 1] = { ...last, content: last.content + v }; return c; });
          } else {
            const delta = (((v.choices || [{}])[0]).delta || {}).content || "";
            if (delta) setMsgs((m) => { const c = [...m]; const last = c[c.length - 1]; c[c.length - 1] = { ...last, content: last.content + delta }; return c; });
          }
          ev = "";
        }
      }
    } catch (e) {
      const aborted = e.name === "AbortError" || /abort/i.test(e.message || "");
      setMsgs((m) => { const c = [...m]; const last = c[c.length - 1];
        c[c.length - 1] = { ...last, content: last.content || (aborted ? "（已停止）" : "（调用失败：" + e.message + "）") }; return c; });
    } finally { setStreaming(false); abortRef.current = null; }
  }

  function stop() { if (abortRef.current) abortRef.current.abort(); }

  // 把最后一条 AI 回复写回选中章节（改稿落地）
  async function applyToChapter() {
    const last = [...msgs].reverse().find((m) => m.role === "assistant");
    const t = (last?.content || "").trim();
    if (!t || !cur.book || !cur.ch) return;
    if (!confirm(`用这条回复替换《${cur.book}》第 ${cur.ch} 章正文？\n（原文会被覆盖，建议先备份）`)) return;
    try {
      await apiPut(`/api/book/${encodeURIComponent(cur.book)}/ch/${cur.ch}`, t);
      say(`（已把回复写入第 ${cur.ch} 章 ✅ 可在「章节与账本」里查看）`);
    } catch (e) { alert("写入失败：" + e.message); }
  }

  function newChat() {
    const s = newSession();
    setSessions((arr) => [s, ...arr]);
    setActiveId(s.id);
    setShowCreate(false);
  }
  function delChat(id) {
    if (!confirm("删除这条会话记录？")) return;
    setSessions((arr) => {
      const left = arr.filter((s) => s.id !== id);
      const next = left.length ? left : [newSession()];
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  // 新建书（合并原「新建书」页）：从模板复制 → 建账 → 直接挂上下文开聊
  async function createBook(form) {
    const name = (form.name || "").trim();
    if (!name) return;
    if (books.includes(name)) { say(`（书架已有同名书《${name}》，换一个名字）`); return; }
    say(`正在为你建书《${name}》${form.tpl ? `（模板：${form.tpl}）` : ""}，初始化账本中…`);
    try {
      if (form.tpl) {
        await apiPost(`/api/tpl/${encodeURIComponent(form.tpl)}/copy`, { name }, { timeout: 0 });
      } else {
        await apiPost("/api/books", { name }, { timeout: 0 });
      }
      const r = await api("/api/books");
      setBooks(r.books);
      patchCur({ book: name, ch: "" });
      setShowCreate(false);
      say(`✅ 《${name}》已建好并选为当前书。可以直接对我说：\n- 「写第 1 章」或「先出第 1 章章纲」\n- 「把设定改成…」「大纲加一条…」（我改完你到 章节与账本 里保存确认）\n- 「导入 txt」请到 章节与账本 → 我的书，或把文本直接粘给我。`);
    } catch (e) { say(`（建书失败：${e.message}）`); }
  }

  const lastAssistant = [...msgs].reverse().find((m) => m.role === "assistant" && m.content);

  return (
    <div className="flex h-[calc(100vh-3.5rem-1.5rem)] gap-3">
      {/* ── 会话列表（WorkBuddy 风格侧栏） ── */}
      <aside className="flex w-56 shrink-0 flex-col rounded-xl border border-line bg-panel shadow-sm">
        <button onClick={newChat}
          className="mx-2.5 mt-2.5 rounded-lg bg-brand px-3 py-2 text-[13px] font-medium text-white transition hover:bg-brand2">
          ＋ 新对话
        </button>
        <button onClick={() => { setShowCreate(true); }}
          className="mx-2.5 mt-2 rounded-lg border border-dashed border-line px-3 py-2 text-[13px] text-inksoft transition hover:border-brand2 hover:text-brand">
          📖 新建一本书
        </button>
        <div className="mt-2 flex-1 overflow-auto px-2 pb-2">
          {sessions.map((s) => (
            <div key={s.id} onClick={() => setActiveId(s.id)}
              className={`group mb-1 cursor-pointer rounded-lg px-2.5 py-2 text-[13px] transition ${
                s.id === activeId ? "bg-brandbg text-ink" : "text-inksoft hover:bg-paper hover:text-ink"}`}>
              <div className="flex items-center gap-1.5">
                <span className="truncate">{s.title || "新对话"}</span>
                <span className="flex-1" />
                <button onClick={(e) => { e.stopPropagation(); delChat(s.id); }}
                  title="删除会话"
                  className="hidden rounded px-1 text-[11px] text-inksoft hover:text-err group-hover:block">✕</button>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-inksoft/80">
                {s.book && <span className="truncate rounded bg-paper px-1.5 py-0.5">{s.book}</span>}
                <span className="shrink-0">{new Date(s.ts).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="border-t border-line px-3 py-2 text-[11px] text-inksoft/70">会话本地保存 · 最近 50 条</div>
      </aside>

      {/* ── 聊天主区 ── */}
      <section className="flex min-w-0 flex-1 flex-col rounded-xl border border-line bg-panel shadow-sm">
        {/* 上下文选择条 */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <select value={cur.book} onChange={(e) => patchCur({ book: e.target.value, ch: "" })}
            className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink">
            <option value="">不选书（纯聊）</option>
            {books.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          {cur.book && chapters.length > 0 && (
            <select value={cur.ch} onChange={(e) => patchCur({ ch: e.target.value })}
              className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink">
              <option value="">不改稿（仅讨论）</option>
              {chapters.map((c) => <option key={c.no} value={c.no}>第 {c.no} 章 {c.title || ""}</option>)}
            </select>
          )}
          <label className="flex items-center gap-1.5 text-xs text-inksoft">
            <input type="checkbox" checked={cur.keepState !== false}
              onChange={(e) => patchCur({ keepState: e.target.checked })} />
            附带记忆账本
          </label>
          <span className="flex-1" />
          {cur.book && go && (
            <button onClick={() => go("workspace", cur.book)}
              className="rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand2">
              去工作台写下一章 →
            </button>
          )}
        </div>

        {/* 消息区 */}
        <div ref={logRef} className="flex-1 overflow-auto px-4 py-4">
          {showCreate && (
            <CreateBookCard templates={templates} onCancel={() => setShowCreate(false)} onCreate={createBook} />
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`chat-row ${m.role === "user" ? "chat-row-user" : "chat-row-ai"}`}>
              <div className="chat-avatar">{m.role === "user" ? "我" : "AI"}</div>
              <div className={`chat-bubble ${m.role === "user" ? "chat-bubble-user" : "chat-bubble-ai"}`}>
                {m.content
                  ? m.content.split("\n").map((l, j) => <div key={j}>{l || "\u00A0"}</div>)
                  : <span className="inline-flex items-center gap-1.5 text-inksoft"><span className="h-1.5 w-1.5 animate-ping rounded-full bg-accent" />生成中…</span>}
              </div>
            </div>
          ))}
          {!streaming && lastAssistant && cur.book && cur.ch && (
            <div className="mb-3 flex justify-end pr-1">
              <button onClick={applyToChapter}
                className="rounded-lg border border-line bg-panel px-3 py-1.5 text-xs text-ink hover:border-brand2 hover:text-brand">
                把上面的回复替换第 {cur.ch} 章正文
              </button>
            </div>
          )}
        </div>

        {/* 快捷提问 */}
        <div className="flex flex-wrap gap-1.5 border-t border-line px-3 pt-2">
          {QUICK.map((q) => (
            <button key={q} onClick={() => send(q)} disabled={streaming}
              className="rounded-full border border-line bg-panel px-3 py-1 text-xs text-inksoft transition hover:border-brand2 hover:text-brand disabled:opacity-40">
              {q}
            </button>
          ))}
        </div>

        {/* 输入区 */}
        <div className="p-3">
          <div className="rounded-xl border border-line bg-paper p-2 transition focus-within:border-brand2">
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="和 AI 聊这本书，或直接下指令…（Enter 发送，Shift+Enter 换行）"
              className="h-16 w-full resize-none bg-transparent text-[13.5px] text-ink focus:outline-none" />
            <div className="flex items-center justify-end gap-2">
              {streaming && (
                <button onClick={stop} className="rounded-lg border border-err/40 px-3 py-1.5 text-xs text-err hover:bg-errbg">■ 停止</button>
              )}
              <button onClick={() => send()} disabled={streaming || !input.trim()}
                className="rounded-lg bg-brand px-5 py-1.5 text-[13px] font-medium text-white hover:bg-brand2 disabled:opacity-40">发送</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

/* 新建书内嵌卡片（原「新建书」页的对话式替代） */
function CreateBookCard({ templates, onCancel, onCreate }) {
  const [name, setName] = useState("");
  const [tpl, setTpl] = useState("");
  return (
    <div className="chat-row">
      <div className="chat-avatar">AI</div>
      <div className="chat-bubble chat-bubble-ai w-[420px] max-w-[90%]">
        <div className="mb-2 font-semibold text-ink">新建一本书</div>
        <label className="mb-2 block text-xs text-inksoft">
          书名
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：雁回刀"
            className="mt-1 w-full rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink" />
        </label>
        <label className="mb-3 block text-xs text-inksoft">
          题材模板（可选）
          <select value={tpl} onChange={(e) => setTpl(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink">
            <option value="">空白书（通用三件套）</option>
            {(templates || []).map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
        </label>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-line px-3 py-1.5 text-xs text-inksoft hover:text-ink">取消</button>
          <button onClick={() => onCreate({ name, tpl })} disabled={!name.trim()}
            className="rounded-lg bg-brand px-4 py-1.5 text-xs font-medium text-white hover:bg-brand2 disabled:opacity-40">建书并开聊</button>
        </div>
      </div>
    </div>
  );
}
