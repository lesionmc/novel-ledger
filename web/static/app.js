/* novel-ledger · Web 工作台前端 v3 */
"use strict";

const API = {
  get(u) { return fetch(u).then(async (r) => { const t = await r.text(); const d = t ? JSON.parse(t) : {}; if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`); return d; }); },
  post(u, body) { return fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(handleResp); },
  put(u, body) { return fetch(u, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(handleResp); },
};
async function handleResp(r) {
  const t = await r.text();
  let d = {};
  try { d = t ? JSON.parse(t) : {}; } catch (e) { d = { error: t }; }
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const state = {
  books: [],
  currentBook: null, book: null,
  current: null, editor: null,
  chat: { msgs: [], brief: null, files: null, name: null, abort: null },
  view: "hero",  // hero | book | chat
};

const DOC_LABEL = { 设定: "📄 设定.md", 角色卡: "👤 角色卡.md", 大纲: "🗺 大纲.md", state: "📒 记忆账本" };

/* ---------------- 工具 ---------------- */
function esc(s) { return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function renderMD(src) {
  if (!src) return "";
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let out = "", inPre = false, codeBuf = [], inUl = false;
  const inline = (t) => t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\*([^*]+)\*/g, "<i>$1</i>");
  const fUl = () => { if (inUl) { out += "</ul>"; inUl = false; } };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]; const t = l.trim();
    if (t.startsWith("```")) { if (inPre) { out += "<pre>" + esc(codeBuf.join("\n")) + "</pre>"; codeBuf = []; inPre = false; } else { fUl(); inPre = true; } continue; }
    if (inPre) { codeBuf.push(l); continue; }
    if (!t) { fUl(); continue; }
    let m;
    if ((m = t.match(/^(#{1,4})\s+(.*)/))) { fUl(); const h = m[1].length + 1; out += `<h${h}>${inline(esc(m[2]))}</h${h}>`; }
    else if (t.startsWith("---")) { fUl(); out += "<hr>"; }
    else if ((m = t.match(/^[-*]\s+(.*)/))) { if (!inUl) { out += "<ul>"; inUl = true; } out += `<li>${inline(esc(m[1]))}</li>`; }
    else if (t.startsWith(">")) { fUl(); out += `<blockquote>${inline(esc(t.replace(/^>\s?/, "")))}</blockquote>`; }
    else if (t.startsWith("|") && i + 1 < lines.length && /^\|[\s:|-]+\|$/.test(lines[i + 1].trim())) {
      fUl(); const head = t.split("|").filter((c) => c.trim() !== "").map((c) => `<th>${esc(c.trim())}</th>`).join("");
      out += "<table><tr>" + head + "</tr>"; i++;
      while (i + 1 < lines.length && lines[i + 1].trim().startsWith("|")) {
        i++; const cs = lines[i].split("|").filter((c) => c.trim() !== "");
        out += "<tr>" + cs.map((c) => `<td>>${esc(c.trim())}</td>`).join("") + "</tr>";
      }
      out += "</table>";
    } else { fUl(); out += `<p>${inline(esc(t))}</p>`; }
  }
  fUl();
  return out;
}
function toast(msg, kind) {
  const el = $("#toast"); el.textContent = msg; el.className = "toast " + (kind || "");
  el.classList.remove("hidden"); clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 2400);
}
function statusBar(kind, text, log) {
  const sb = $("#statusBar");
  sb.className = "status-bar " + (kind || "");
  $("#sbDot").textContent = kind === "ok" ? "●" : (kind === "err" ? "●" : "○");
  $("#sbText").textContent = text || "";
  $("#sbLog").textContent = log || "";
}

/* ---------------- 状态条 ---------------- */
async function refreshHeader() {
  try {
    const s = await API.get("/api/status");
    const p = $("#keyPill");
    if (s.key_set) { p.textContent = "✅ Key 就绪"; p.className = "pill ok"; }
    else { p.textContent = "⚠ 未配 Key"; p.className = "pill warn"; }
    statusBar(s.key_set ? "ok" : "err", s.key_set ? "已连接（Key 就绪）" : "未配置 Key → ⚙ 设置里填",
              s.key_set ? "模型 /api/settings 可查" : "");
  } catch (e) { statusBar("err", "服务未连接", e.message); }
}

/* ---------------- 视图切换 ---------------- */
function showView(name) {
  state.view = name;
  $("#hero").classList.toggle("hidden", name !== "hero");
  $("#work").classList.toggle("hidden", name !== "book" && name !== "chat");
  $("#homeBtn").classList.toggle("active", name !== "hero");
}
function goHome() {
  showView("hero");
  refreshAll();
}

/* ---------------- 书树/首页 ---------------- */
async function refreshAll() {
  await refreshHeader();
  const r = await API.get("/api/books");
  state.books = r.books;
  renderBookTree();
  renderHomeBooks();
  if (state.view === "book" && state.currentBook && state.books.includes(state.currentBook)) {
    await openBook(state.currentBook);
  }
}
function renderBookTree() {
  const t = $("#bookTree"); t.innerHTML = "";
  if (!state.books.length) { t.innerHTML = '<div class="tree-empty">还没有书，点右上角「+ 新建书」</div>'; return; }
  for (const name of state.books) {
    const div = document.createElement("div");
    div.className = "tree-node book"; div.textContent = "📚 " + name;
    div.onclick = () => openBook(name);
    t.appendChild(div);
  }
}
function renderHomeBooks() {
  const wrap = $("#bookListHome"); wrap.innerHTML = "";
  if (!state.books.length) return;
  const head = document.createElement("div");
  head.className = "muted"; head.style.margin = "8px 4px 12px"; head.style.fontSize = "13px";
  head.textContent = "已建书：" + state.books.length + " 本";
  wrap.appendChild(head);
  const grid = document.createElement("div"); grid.className = "book-cards"; wrap.appendChild(grid);
  for (const name of state.books) {
    const c = document.createElement("div");
    c.className = "book-card";
    c.innerHTML = `<div class="b-icon">📖</div><div class="b-name">${esc(name)}</div><div class="b-state no">加载中…</div>`;
    c.onclick = () => openBook(name);
    grid.appendChild(c);
    API.get(`/api/book/${encodeURIComponent(name)}`).then((b) => {
      const st = c.querySelector(".b-state");
      st.className = "b-state" + (b.has_state ? "" : " no");
      st.textContent = b.has_state ? "📒 账本就绪" : "⚠ 未建账本";
      const meta = document.createElement("div");
      meta.className = "b-meta"; meta.textContent = b.chapters.length + " 章";
      c.appendChild(meta);
    }).catch(() => { c.querySelector(".b-state").textContent = "加载失败"; });
  }
}

/* ---------------- 打开书 ---------------- */
async function openBook(name) {
  state.currentBook = name;
  showView("book");
  try { state.book = await API.get(`/api/book/${encodeURIComponent(name)}`); }
  catch (e) { toast("打开失败：" + e.message, "err"); goHome(); return; }
  const secCh = $("#chapterSection"), trCh = $("#chapterTree");
  const secRp = $("#reportSection"), trRp = $("#reportTree");
  trCh.innerHTML = ""; trRp.innerHTML = "";
  for (const ch of state.book.chapters) {
    const c = document.createElement("div");
    c.className = "tree-node child";
    c.innerHTML = `ch${String(ch.no).padStart(3, "0")}.md <span class="meta">${ch.size ? Math.round(ch.size / 100) / 10 + "K" : ""}</span>`;
    c.onclick = () => openChapter(ch.no);
    trCh.appendChild(c);
  }
  $("#chapterCount").textContent = `(${state.book.chapters.length} 章)`;
  secCh.style.display = state.book.chapters.length ? "" : "none";
  try {
    const fd = await API.get(`/api/book/${encodeURIComponent(name)}/files`);
    const reports = fd.files.filter((f) => f.file.includes("体检") || f.file.includes("审计") || f.file.endsWith(".diff.json"));
    for (const f of reports) {
      const n = document.createElement("div");
      n.className = "tree-node child";
      n.textContent = "🧾 " + f.file.replace("chapters/", "");
      n.onclick = () => openReport(f.file);
      trRp.appendChild(n);
    }
    secRp.style.display = reports.length ? "" : "none";
  } catch (e) {}
  $$(".tree-node.book").forEach((n) => n.classList.toggle("active", n.textContent.includes(name)));
  openDoc("设定");
}

/* ---------------- 打开节点 ---------------- */
function chapterActions() {
  const no = state.current && state.current.kind === "ch" ? state.current.no : null;
  return [
    { label: "✍ 写下一章", cls: "primary", handler: writeNext },
    { label: "🧾 一致性审计", handler: () => auditChapter(no) },
    { label: "🔬 全书体检", handler: () => scan() },
    { label: "🪄 去味精判", handler: () => polish(no) },
    { label: "✂️ 应用改写", handler: () => apply(no) },
    { label: "💾 保存", handler: () => saveCurrent(false) },
  ];
}
async function openChapter(no) {
  $$(".tree-node.child").forEach((n) => n.classList.remove("active"));
  const d = await API.get(`/api/book/${encodeURIComponent(state.currentBook)}/ch/${no}`);
  state.editor = { kind: "ch", book: state.currentBook, no, body: d.content };
  state.current = { kind: "ch", no };
  $("#fileTitle").innerHTML = `📚 ${esc(state.currentBook)} <span class="meta">·</span> ch${String(no).padStart(3, "0")}.md <span class="meta">· ${d.content.length} 字</span>`;
  $("#workBody").innerHTML = `<textarea id="editor" class="editor" spellcheck="false"></textarea>
    <div class="progress hidden" id="busy"></div>
    <div class="ai-assist"><details><summary>💬 AI 助手（基于当前内容问/建议）</summary>
      <div class="ai-history" id="aiHistory"></div>
      <div class="ai-input"><textarea id="aiQ" placeholder="比如：这段有没有 AI 腔？/ 帮我想一句开头钩子"></textarea>
        <button class="btn sm" id="aiSendBtn">问 AI</button></div>
    </details></div>`;
  const ed = $("#editor"); ed.value = d.content; ed.oninput = () => state.editor.body = ed.value;
  setActions(chapterActions());
  bindAiAssist("ch", no, d.content);
}
async function openDoc(doc) {
  $$(".tree-node.child").forEach((n) => n.classList.remove("active"));
  const d = await API.get(`/api/book/${encodeURIComponent(state.currentBook)}/doc/${doc}`);
  state.editor = { kind: "doc", book: state.currentBook, doc, body: d.content };
  state.current = { kind: "doc", doc };
  $("#fileTitle").innerHTML = `📚 ${esc(state.currentBook)} <span class="meta">·</span> ${esc(DOC_LABEL[doc])} <span class="meta">· ${d.content.length} 字</span>`;
  $("#workBody").innerHTML = `<textarea id="editor" class="editor" spellcheck="false"></textarea>
    <div class="progress hidden" id="busy"></div>
    <div class="ai-assist"><details><summary>💬 AI 助手（针对此文档问/建议）</summary>
      <div class="ai-history" id="aiHistory"></div>
      <div class="ai-input"><textarea id="aiQ" placeholder="比如：帮我想一句卖点/这个角色够不够立体"></textarea>
        <button class="btn sm" id="aiSendBtn">问 AI</button></div>
    </details></div>`;
  const ed = $("#editor"); ed.value = d.content; ed.oninput = () => state.editor.body = ed.value;
  const isState = doc === "state";
  setActions([
    { label: isState ? "📒 刷新" : "✍ 写下一章", cls: "primary",
      handler: () => (isState ? openDoc("state") : writeNext()) },
    { label: "🔬 全书体检", handler: () => scan() },
    { label: "💾 保存", handler: saveCurrent },
  ]);
  bindAiAssist("doc", doc, d.content);
}
async function openReport(file) {
  $$(".tree-node.child").forEach((n) => n.classList.remove("active"));
  const d = await API.get(`/api/book/${encodeURIComponent(state.currentBook)}/file/${encodeURIComponent(file)}`);
  state.current = { kind: "report", file };
  $("#fileTitle").innerHTML = `📚 ${esc(state.currentBook)} <span class="meta">·</span> 🧾 ${esc(file.replace("chapters/", ""))}`;
  $("#workBody").innerHTML = `<div class="${file.endsWith(".json") ? "monospace" : "markdown"}" id="report"></div>`;
  const el = $("#report");
  if (file.endsWith(".json")) { try { el.textContent = JSON.stringify(JSON.parse(d.content), null, 2); } catch (e) { el.textContent = d.content; } }
  else el.innerHTML = renderMD(d.content);
  setActions([]);
}

/* ---------------- AI 助手（每页底部可折叠） ---------------- */
function bindAiAssist(kind, key, content) {
  const btn = $("#aiSendBtn"), hist = $("#aiHistory"), q = $("#aiQ");
  if (!btn) return;
  btn.onclick = async () => {
    const ask = q.value.trim(); if (!ask) return;
    q.value = ""; btn.disabled = true;
    hist.insertAdjacentHTML("beforeend", `<div class="ai-msg user"><b>你：</b>${esc(ask)}</div>`);
    const resp = document.createElement("div"); resp.className = "ai-msg ai";
    resp.innerHTML = "<b>AI：</b><span class='cursor'>▍</span>";
    hist.appendChild(resp); hist.scrollTop = hist.scrollHeight;
    try {
      const r = await fetch("/api/chat", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stream: true,
          temperature: 0.7,
          messages: [
            { role: "system", content: `你是中文网文资深编辑，简洁、犀利、给出可执行建议。当前文档类型：${kind}（${key}）。文档原文如下：\n\n${content.slice(0, 4000)}` },
            { role: "user", content: ask },
          ],
        }) });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let acc = "", buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const ln of lines) {
          if (!ln.startsWith("data: ")) continue;
          const raw = ln.slice(6);
          let delta = "";
          try { delta = JSON.parse(raw); } catch (e) { continue; }
          const piece = (delta.choices && delta.choices[0] && delta.choices[0].delta && delta.choices[0].delta.content) || "";
          if (piece) { acc += piece; resp.innerHTML = "<b>AI：</b>" + esc(acc).replace(/\n/g, "<br>") + "<span class='cursor'>▍</span>"; hist.scrollTop = hist.scrollHeight; }
        }
      }
      resp.innerHTML = "<b>AI：</b>" + esc(acc).replace(/\n/g, "<br>");
    } catch (e) {
      resp.innerHTML = "<b>AI：</b>（" + esc(e.message) + "）";
    }
    btn.disabled = false;
  };
}

/* ---------------- 写章/审计/polish/apply/scan ---------------- */
function busy(msg) {
  const b = $("#busy"); if (b) { b.classList.remove("hidden"); b.innerHTML = `<span class="spinner"></span><span>${esc(msg)}</span>`; }
  document.body.style.cursor = "wait";
}
function idle() { const b = $("#busy"); if (b) { b.classList.add("hidden"); } document.body.style.cursor = ""; }
function showLog(log) { $("#workBody").innerHTML = `<div class="log-box">${esc(log || "无日志")}</div>`; }
function setActions(list) {
  const a = $("#actions"); a.innerHTML = "";
  for (const b of list) { const btn = document.createElement("button"); btn.className = "btn " + (b.cls || ""); btn.textContent = b.label; btn.onclick = b.handler; a.appendChild(btn); }
}

async function writeNext() {
  if (!confirm("写下一章会调模型生成约 3000 字并更新记忆账本，约 1-3 分钟。开始？")) return;
  await saveCurrent(true); busy("模型写作中（约 1-3 分钟，请勿关闭页面）…");
  statusBar("ok", "正在写章…", "可能 1-3 分钟");
  try {
    const d = await API.post(`/api/book/${encodeURIComponent(state.currentBook)}/write`, {});
    if (!d.ok) { showLog(d.log || "引擎失败"); statusBar("err", "写章失败", ""); toast("写章失败", "err"); return; }
    toast(`✅ 第 ${d.no} 章（${d.chars} 字）`, "ok"); statusBar("ok", `第 ${d.no} 章已生成（${d.chars} 字）`, "");
    await openChapter(d.no); refreshAll();
  } catch (e) { toast("写章失败：" + e.message, "err"); statusBar("err", "写章失败", e.message); }
  finally { idle(); }
}
async function auditChapter(n) {
  await saveCurrent(true); busy("审计中…"); statusBar("ok", "审计中…", "约 1 分钟");
  try {
    const d = await API.post(`/api/book/${encodeURIComponent(state.currentBook)}/audit`, { no: n });
    if (!d.ok && !d.report) { showLog(d.log); toast("审计失败", "err"); return; }
    await openReport(`chapters/ch${String(n).padStart(3, "0")}.一致性审计.md`);
    toast("审计完成", "ok"); statusBar("ok", "审计完成", "");
  } catch (e) { toast("审计失败：" + e.message, "err"); statusBar("err", "审计失败", e.message); }
  finally { idle(); }
}
async function scan() {
  await saveCurrent(true); busy("体检中…"); statusBar("ok", "体检中…", "本地秒级");
  try {
    const d = await API.post(`/api/book/${encodeURIComponent(state.currentBook)}/scan`, {});
    if (!d.ok) { toast("体检失败", "err"); return; }
    $("#workBody").innerHTML = `<div class="log-box">${esc(d.report)}</div>`;
    setActions([{ label: "🔙 返回", handler: () => openDoc("设定") }]);
    toast("体检完成", "ok"); statusBar("ok", "体检完成", "查看左侧→AI 腔指数");
  } catch (e) { toast("体检失败：" + e.message, "err"); statusBar("err", "体检失败", e.message); }
  finally { idle(); }
}
async function polish(n) {
  await saveCurrent(true); busy("去味中…");
  try {
    const d = await API.post(`/api/book/${encodeURIComponent(state.currentBook)}/polish`, { no: n });
    if (!d.ok) { showLog(d.log); toast("去味失败", "err"); return; }
    await openReport(`chapters/ch${String(n).padStart(3, "0")}.AI腔体检.md`);
    toast("体检报告已出（diff 报告在左侧）", "ok"); refreshAll();
  } catch (e) { toast("去味失败：" + e.message, "err"); }
  finally { idle(); }
}
async function apply(n) {
  if (!confirm("应用改写会修改正文（自动备份到 .bak.md）。继续？")) return;
  busy("应用改写…");
  try {
    const d = await API.post(`/api/book/${encodeURIComponent(state.currentBook)}/apply`, { no: n });
    if (!d.ok) { showLog(d.log); toast("应用失败", "err"); return; }
    toast("✅ 改写已应用", "ok"); await openChapter(n); refreshAll();
  } catch (e) { toast("应用失败：" + e.message, "err"); }
  finally { idle(); }
}
async function saveCurrent(silent) {
  if (!state.editor) return;
  const ed = $("#editor"); if (ed) state.editor.body = ed.value;
  try {
    if (state.editor.kind === "ch") await API.put(`/api/book/${encodeURIComponent(state.editor.book)}/ch/${state.editor.no}`, state.editor.body || "");
    else if (state.editor.kind === "doc") await API.put(`/api/book/${encodeURIComponent(state.editor.book)}/doc/${state.editor.doc}`, state.editor.body || "");
    if (!silent) toast("已保存", "ok"); statusBar("ok", "已保存", "");
  } catch (e) { if (!silent) toast("保存失败：" + e.message, "err"); }
}

/* ---------------- 设置 ---------------- */
function openSettings() {
  API.get("/api/settings").then((s) => {
    openModal("⚙ 设置 · API 与模型", `
    <p class="muted">修改后实时生效（无需重启）。建议最小授权：FALLBACK 留两家不同厂商。</p>
    <div class="form-section"><h4>主模型</h4>
      <label>API Key<input type="password" id="sKey" placeholder="sk-..." value="${esc(s.settings.AGNES_API_KEY || "")}"></label>
      <label>Base URL<input type="text" id="sBase" placeholder="https://apihub.agnes-ai.com/v1/" value="${esc(s.settings.AGNES_BASE_URL || "")}"></label>
      <label>Model ID<input type="text" id="sModel" placeholder="agnes-2.5-flash" value="${esc(s.settings.AGNES_MODEL || "")}"></label>
    </div>
    <div class="form-section"><h4>备用模型（主失败自动切换）</h4>
      <label>Fallback API Key<input type="password" id="sFk" placeholder="备用厂商 key（可选）" value="${esc(s.settings.FALLBACK_API_KEY || "")}"></label>
      <label>Fallback Base URL<input type="text" id="sFbase" placeholder="https://open.bigmodel.cn/api/paas/v4/" value="${esc(s.settings.FALLBACK_BASE_URL || "")}"></label>
      <label>Fallback Model ID<input type="text" id="sFmodel" placeholder="glm-4.5-flash" value="${esc(s.settings.FALLBACK_MODEL || "")}"></label>
    </div>
    <style>.form-section{margin-bottom:4px} .form-section h4{margin:0 0 6px;color:var(--brand);font-size:13px} .form-section label{display:block;margin-bottom:6px;font-size:12px;color:var(--ink-soft)} .form-section input{margin-top:2px}</style>
    `, `<button class="btn" onclick="window.novelApp.closeModal()">取消</button>
    <button class="btn" onclick="window.novelApp.testConn()">🔌 测试连接</button>
    <button class="btn primary" onclick="window.novelApp.saveSettings()">💾 保存</button>`);
  });
}
function openModal(title, html, body, onClose) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modalFoot").innerHTML = body || "";
  $("#modal").classList.remove("hidden");
}
function closeModal() {
  $("#modal").classList.add("hidden");
  $("#modalBody").innerHTML = "";
  $("#modalFoot").innerHTML = "";
}
window.onclick = (e) => { if (e.target === $("#modal")) closeModal(); };

async function saveSettings() {
  const changes = {
    AGNES_API_KEY: $("#sKey").value.trim(),
    AGNES_BASE_URL: $("#sBase").value.trim(),
    AGNES_MODEL: $("#sModel").value.trim(),
    FALLBACK_API_KEY: $("#sFk").value.trim(),
    FALLBACK_BASE_URL: $("#sFbase").value.trim(),
    FALLBACK_MODEL: $("#sFmodel").value.trim(),
  };
  for (const k of Object.keys(changes)) {
    if (!changes[k]) delete changes[k];
    else if (changes[k] === "****") delete changes[k];  // 脱敏占位符：未改动过的 key 不许写回覆盖真值
  }
  try {
    const r = await API.put("/api/settings", { changes });
    toast("已保存" + (r.key_set ? "" : "（⚠ 未配 Key）"), r.key_set ? "ok" : "warn");
    closeModal(); refreshHeader();
  } catch (e) { toast("保存失败：" + e.message, "err"); }
}
async function testConn() {
  statusBar("ok","测试连接中…", "消耗 4 token");
  try {
    const r = await API.post("/api/settings/test", {});
    statusBar("ok", "连接正常 ✅", "模型 " + r.model + " · 示例 " + (r.sample || "（空）"));
    toast("✅ 连接正常（" + r.model + "）", "ok");
  } catch (e) { statusBar("err", "连接失败 ❌", e.message); toast("❌ " + e.message, "err"); }
}

/* ---------------- 新建书：嵌入主视图 ---------------- */
function openNewBookView() {
  state.chat = { msgs: [], brief: null, files: null, name: null, abort: null };
  showView("chat");
  $("#fileTitle").innerHTML = `✨ 新建书 · 和 AI 聊你的故事 <span class="meta">· 第 1/2 步</span>`;
  $("#workBody").innerHTML = `
    <div class="chat-w-w">
      <div class="chat-w-wchat">
        <h4 style="margin:0 0 8px;color:var(--brand)">💬 跟 AI 聊</h4>
        <div class="chat-log" id="chatLog"></div>
        <div class="chat-input">
          <textarea id="chatInput" placeholder="说说你想写什么故事（Ctrl+Enter 发送）"></textarea>
          <button class="btn primary" id="chatSendBtn">发送 ▶</button>
        </div>
      </div>
      <div class="chat-w-wprev">
        <h4 style="margin:0 0 8px;color:var(--brand)">📑 三件套预览</h4>
        <div class="brief-card" id="briefCard">点击右下方 <b>💡 让 AI 提取书名/卖点</b> 后，此处会显示摘要…</div>
        <div class="preview-editor" id="previewEditor" style="display:none">
          <div class="tabs-t" id="tabsT">
            <button data-tab="设定" class="active">📄 设定</button>
            <button data-tab="角色卡">👤 角色卡</button>
            <button data-tab="大纲">🗺 大纲</button>
          </div>
          <input type="text" id="bookNameInput" placeholder="书文件夹名（拼音/英文）">
          <textarea id="fileEdit"></textarea>
        </div>
      </div>
    </div>
  `;
  $("#actions").innerHTML = `
    <button class="btn" onclick="window.novelApp.goHome()">← 返回首页</button>
    <button class="btn" id="genBriefBtn" onclick="window.novelApp.genBrief()">💡 让 AI 提取书名/卖点</button>
    <button class="btn" id="genFilesBtn" onclick="window.novelApp.genFiles()" style="display:none">🧬 生成三件套</button>
    <button class="btn primary" id="createBookBtn" onclick="window.novelApp.createBookFromChat()" style="display:none">📚 创建并初始化</button>
  `;
  bindWizard();
  state.chat.msgs.push(
 { role: "system", content: "你是中文网文资深策划/编辑，擅长把零碎灵感梳理成可执行的三件套（设定/角色卡/大纲）。对话风格简洁温和，多用「好的/嗯/有意思/继续」等口头词，每次回复不超过 80 字，多用 1-2 个追问推进用户表达。" },
 { role: "assistant", content: "好的，咱们开始聊书。说说你心里这个故事大概是讲什么的？什么题材？有什么想写但一直没人陪你想透的点？" }
);
  renderChat();
}
function bindWizard() {
  const input = $("#chatInput"), btn = $("#chatSendBtn");
  if (!input) return;
  btn.onclick = () => sendChat(input);
  input.onkeydown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") sendChat(input); };
  $$("#tabsT button").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));
}
function switchTab(tab) {
  $$("#tabsT button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  const fe = $("#fileEdit");
  fe.value = (state.chat.files && state.chat.files[tab]) || "";
  fe.dataset.tab = tab;
  fe.oninput = () => { state.chat.files[tab] = fe.value; };
}
function renderChat() {
  const log = $("#chatLog"); if (!log) return;
  log.innerHTML = state.chat.msgs
 .filter((m) => m.role !== "system")
 .map((m) => `<div class="chat-msg ${m.role}"><div class="role">${m.role === "user" ? "你" : "AI"}</div>${esc(m.content).replace(/\n/g, "<br>")}</div>`)
 .join("");
  log.scrollTop = log.scrollHeight;
}
async function sendChat(input) {
  const t = input.value.trim();
 if (!t) return;
  state.chat.msgs.push({ role: "user", content: t });
  input.value = "";
  renderChat();
  input.disabled = true;
  statusBar("ok", "AI 正在回复…", "流式生成中");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stream: true, temperature: 0.8, messages: state.chat.msgs }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    state.chat.msgs.push({ role: "assistant", content: "" });
    const i = state.chat.msgs.length - 1;
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const seg = buf.split("\n"); buf = seg.pop();
      for (const ln of seg) {
        if (!ln.startsWith("data: ")) continue;
        const raw = ln.slice(6);
        try {
          const obj = JSON.parse(raw);
          const delta = (((obj.choices || [{}])[0]).delta || {}).content || "";
          if (delta) {
            state.chat.msgs[i].content += delta;
            renderChat();
            statusBar("ok", "AI 生成中", "+" + state.chat.msgs[i].content.length + " 字");
          }
        } catch (e) {}
      }
    }
    statusBar("ok", "AI 回复完成", state.chat.msgs[i].content.length + " 字");
  } catch (e) {
    state.chat.msgs.push({ role: "assistant", content: "（" + e.message + "）" });
    renderChat();
    statusBar("err", "AI 调用失败", e.message);
  } finally { input.disabled = false; input.focus(); }
}
async function genBrief() {
  const sys = { role: "system", content: "你是中文网文资深策划。阅读对话，提取新书三要素：英文/拼音书名、题材、一句话卖点。严格返回 JSON：{name, genre, hook}。" };
  const msgs = [sys, ...state.chat.msgs.filter((m) => m.role !== "system")];
  statusBar("ok","提取书名中…", "");
  try {
    const r = await API.post("/api/chat", { messages: msgs, temperature: 0.4 });
    let parsed = { name: "my_novel", genre: "未指定", hook: "" };
    try { const m = r.content.match(/\{[\s\S]*\}/); if (m) Object.assign(parsed, JSON.parse(m[0])); } catch (e) {}
    state.chat.brief = parsed;
    state.chat.name = parsed.name || "my_novel";
    renderBrief();
    toast("已提取书名/卖点", "ok");
    $("#genFilesBtn").style.display = "";
  } catch (e) { toast("提取失败：" + e.message, "err"); }
}
function renderBrief() {
  const c = $("#briefCard"); if (!c || !state.chat.brief) return;
  const b = state.chat.brief;
  c.innerHTML = `<b>书名：</b>${esc(b.name || "-")}<br><b>题材：</b>${esc(b.genre || "-")}<br><b>卖点：</b>${esc(b.hook || "-")}<br><i style="font-size:11px;color:var(--ink-soft)">可继续聊，提取按钮可重复点</i>`;
  $("#bookNameInput").value = state.chat.name || "";
}
async function genFiles() {
  if (!state.chat.brief) await genBrief();
  const sys = { role: "system", content: "你是中文网文资深编辑。根据对话 + 简报，直接输出 3 个 markdown 文件内容：\n1) 设定.md（世界观/类型/一句话卖点/硬规则）\n2) 角色卡.md（主角 + 主要对手 + 关键配角，含身份/性格/称呼）\n3) 大纲.md（全书主线 + 第一卷 3-5 章细纲，每章目标/事件/钩子）\n严格用三个 markdown 块，块首分别用 `=== 设定.md ===`、`=== 角色卡.md ===`、`=== 大纲.md ===` 标记。" };
  const msgs = [sys, ...state.chat.msgs.filter((m) => m.role !== "system")];
  statusBar("ok","生成三件套中…", "模型设计设定/角色/大纲");
  try {
    const r = await API.post("/api/chat", { messages: msgs, temperature: 0.6 });
    const text = r.content;
    state.chat.files = {};
    const blocks = text.split(/===\s*(.*?)\.md\s*===/);
    for (let i = 1; i < blocks.length; i += 2) {
      const k = blocks[i]; const body = (blocks[i + 1] || "").trim();
      if (k === "设定") state.chat.files["设定"] = body;
      else if (k === "角色卡") state.chat.files["角色卡"] = body;
      else if (k === "大纲") state.chat.files["大纲"] = body;
    }
    if (!state.chat.files["设定"] && text.trim()) state.chat.files["设定"] = text;
    $("#previewEditor").style.display = "";
    switchTab("设定");
    $("#createBookBtn").style.display = "";
    $("#genFilesBtn").style.display = "none";
    toast("三件套已生成 → 右侧可编辑", "ok");
    statusBar("ok", "三件套已生成", "右侧编辑→创建并初始化");
  } catch (e) { toast("生成失败：" + e.message, "err"); }
}
async function createBookFromChat() {
  const name = ($("#bookNameInput").value || state.chat.name || "my_novel").trim().replace(/[\\/]/g, "_");
  if (!name || !state.chat.files) { toast("先生成三件套", "warn"); return; }
  statusBar("ok","创建中…", name);
  try {
    const r = await API.post("/api/book/from-chat", { name, files: state.chat.files });
    toast("✅ 《" + name + "》已建好并初始化", "ok"); statusBar("ok", "新书已创建", name);
    await refreshAll(); openBook(name);
  } catch (e) { toast("创建失败：" + e.message, "err"); statusBar("err", "创建失败", e.message); }
}
async function createBookFromTemplate() {
  const name = prompt("新书文件夹名（拼音/英文）");
  if (!name) return;
  try { await API.post("/api/books", { name });
    toast("✅ 《" + name + "》已建好并初始化", "ok");
    await refreshAll(); openBook(name);
  } catch (e) { toast("创建失败：" + e.message, "err"); }
}

/* ---------------- 入口 ---------------- */
window.novelApp = { refreshAll, goHome, closeModal, saveSettings, testConn, genBrief, genFiles, createBookFromChat, sendChat };
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveCurrent(false); }
});
$("#homeBtn").onclick = goHome;
$("#settingsBtn").onclick = openSettings;
$("#newBookBtn").onclick = openNewBookView;
$("#cardNewBook").onclick = openNewBookView;
$("#cardSample").onclick = createBookFromTemplate;
refreshAll().catch((e) => { statusBar("err", "初始化失败", e.message); console.error(e); });