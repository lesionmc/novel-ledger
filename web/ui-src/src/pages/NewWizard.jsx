import React, { useEffect, useRef, useState } from "react";
import { api, apiPost } from "../api.js";

/* AI 建书向导：左聊天(SSE 流式) + 右三件套预览/编辑（对齐旧版交互） */

const SYS_PROMPT = "你是中文网文资深策划/编辑，擅长把零碎灵感梳理成可执行的三件套（设定/角色卡/大纲）。对话风格简洁温和，多用「好的/嗯/有意思/继续」等口头词，每次回复不超过 80 字，多用 1-2 个追问推进用户表达。";
const HELLO = "好的，咱们开始聊书。说说你心里这个故事大概是讲什么的？什么题材？有什么想写但一直没人陪你想透的点？";

export default function NewWizard({ go }) {
  const [msgs, setMsgs] = useState([
    { role: "system", content: SYS_PROMPT },
    { role: "assistant", content: HELLO },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [brief, setBrief] = useState(null);
  const [files, setFiles] = useState(null);
  const [tab, setTab] = useState("设定");
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [done, setDone] = useState(false);
  const logRef = useRef(null);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [msgs]);

  async function send() {
    const t = input.trim();
    if (!t || streaming) return;
    setInput(""); setStreaming(true); setStatus("AI 正在回复…");
    const next = [...msgs, { role: "user", content: t }, { role: "assistant", content: "" }];
    setMsgs(next);
    const i = next.length - 1;
    try {
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream: true, temperature: 0.8, messages: next.slice(0, -1) }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const ln of lines) {
          if (!ln.startsWith("data: ")) continue;
          try {
            const obj = JSON.parse(ln.slice(6));
            const delta = (((obj.choices || [{}])[0]).delta || {}).content || "";
            if (delta) setMsgs((m) => { const c = [...m]; c[i] = { ...c[i], content: c[i].content + delta }; return c; });
          } catch (e) {}
        }
      }
      setStatus("");
    } catch (e) {
      setMsgs((m) => { const c = [...m]; c[i] = { role: "assistant", content: "（" + e.message + "）" }; return c; });
      setStatus("AI 调用失败");
    } finally { setStreaming(false); }
  }

  async function genBrief() {
    setStatus("提取书名中…");
    try {
      const sys = { role: "system", content: "你是中文网文资深策划。阅读对话，提取新书三要素：英文/拼音书名、题材、一句话卖点。严格返回 JSON：{name, genre, hook}。" };
      const r = await apiPost("/api/chat", { messages: [sys, ...msgs.filter((m) => m.role !== "system")], temperature: 0.4 });
      let parsed = { name: "my_novel", genre: "未指定", hook: "" };
      const m = (r.content || "").match(/\{[\s\S]*\}/);
      if (m) { try { Object.assign(parsed, JSON.parse(m[0])); } catch (e) {} }
      setBrief(parsed); setName(parsed.name || "my_novel");
      setStatus("已提取书名/卖点 ✅");
    } catch (e) { setStatus("提取失败：" + e.message); }
  }

  async function genFiles() {
    setStatus("生成三件套中…（模型设计设定/角色/大纲）");
    try {
      if (!brief) await genBrief();
      const sys = { role: "system", content: "你是中文网文资深编辑。根据对话 + 简报，直接输出 3 个 markdown 文件内容：\n1) 设定.md（世界观/类型/一句话卖点/硬规则）\n2) 角色卡.md（主角 + 主要对手 + 关键配角，含身份/性格/称呼）\n3) 大纲.md（全书主线 + 第一卷 3-5 章细纲，每章目标/事件/钩子）\n严格用三个 markdown 块，块首分别用 `=== 设定.md ===`、`=== 角色卡.md ===`、`=== 大纲.md ===` 标记。" };
      const r = await apiPost("/api/chat", { messages: [sys, ...msgs.filter((m) => m.role !== "system")], temperature: 0.6, max_tokens: 8000 });
      const text = r.content || "";
      const f = {};
      const blocks = text.split(/===\s*(.*?)\.md\s*===/);
      for (let i = 1; i < blocks.length; i += 2) {
        const k = blocks[i], body2 = (blocks[i + 1] || "").trim();
        if (k === "设定") f["设定"] = body2;
        else if (k === "角色卡") f["角色卡"] = body2;
        else if (k === "大纲") f["大纲"] = body2;
      }
      if (!f["设定"] && text.trim()) f["设定"] = text;
      setFiles(f); setTab("设定"); setStatus("三件套已生成 → 右侧可编辑 ✅");
    } catch (e) { setStatus("生成失败：" + e.message); }
  }

  async function createBook() {
    const n = (name || "my_novel").trim().replace(/[\\/]/g, "_");
    if (!files) { setStatus("先生成三件套"); return; }
    setStatus("创建中…（含账本初始化）");
    try {
      await apiPost("/api/book/from-chat", { name: n, files });
      setStatus(`✅ 《${n}》已建好并初始化`);
      setDone(true);
      setTimeout(() => go("workspace", n), 1200);
    } catch (e) { setStatus("创建失败：" + e.message); }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-xl font-bold text-ink">新建书 · 和 AI 聊你的故事</h1>
        <span className="flex-1" />
        <button onClick={genBrief} disabled={streaming} className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] hover:border-ink/30 disabled:opacity-40">提取书名/卖点</button>
        {brief && !files && (
          <button onClick={genFiles} disabled={streaming} className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] hover:border-ink/30 disabled:opacity-40">生成三件套</button>
        )}
        {files && (
          <button onClick={createBook} disabled={streaming || done} className="rounded-lg bg-brand px-3.5 py-1.5 text-[13px] text-white hover:bg-brand2 disabled:opacity-40">创建并初始化</button>
        )}
      </div>
      {status && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-[13px] text-ink">{status}</div>}

      <div className="grid gap-4 lg:grid-cols-5">
        {/* 左：聊天 */}
        <div className="flex flex-col rounded-xl border border-line bg-panel p-4 shadow-sm lg:col-span-3">
          <h3 className="mb-2 text-[13px] font-semibold text-inksoft">跟 AI 聊</h3>
          <div ref={logRef} className="h-[50vh] overflow-auto rounded-lg border border-line bg-paper p-3 text-[13.5px] leading-6">
            {msgs.filter((m) => m.role !== "system").map((m, i) => (
              <div key={i} className={`mb-2.5 max-w-[92%] rounded-lg px-3 py-2 ${m.role === "user" ? "ml-auto bg-brandbg" : m.role === "assistant" ? "bg-line/40" : ""}`}>
                {m.role !== "user" && <div className="mb-0.5 text-[11px] text-inksoft">AI</div>}
                {m.content ? m.content.split("\n").map((l, j) => <div key={j}>{l}</div>)
                  : <span className="inline-flex items-center gap-1.5 text-inksoft"><span className="h-1.5 w-1.5 animate-ping rounded-full bg-accent" />AI 生成中…</span>}
              </div>
            ))}
          </div>
          <div className="mt-2">
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="说说你想写什么故事…（Enter 发送，Shift+Enter 换行）"
              className="h-24 w-full resize-none" />
            <div className="mt-2 flex justify-end">
              <button onClick={send} disabled={streaming || !input.trim()}
                className="rounded-lg bg-brand px-5 py-2 text-[13px] font-medium text-white hover:bg-brand2 disabled:opacity-40">发送</button>
            </div>
          </div>
        </div>

        {/* 右：三件套预览/编辑 */}
        <div className="flex flex-col rounded-xl border border-line bg-panel p-4 shadow-sm lg:col-span-2">
          <h3 className="mb-2 text-[13px] font-semibold text-inksoft">三件套预览</h3>
          <div className="mb-3 rounded-lg border border-line bg-paper p-3 text-[13px]">
            {brief ? (
              <>
                <div><b className="text-ink">书名：</b>{brief.name || "-"}</div>
                <div><b className="text-ink">题材：</b>{brief.genre || "-"}</div>
                <div><b className="text-ink">卖点：</b>{brief.hook || "-"}</div>
                <div className="mt-1 text-[11px] text-inksoft">可继续聊，「提取书名/卖点」可重复点</div>
              </>
            ) : (
              <span className="text-inksoft">点右上「提取书名/卖点」后，此处显示摘要…</span>
            )}
          </div>
          {files ? (
            <>
              <div className="mb-2 flex gap-1">
                {["设定", "角色卡", "大纲"].map((t) => (
                  <button key={t} onClick={() => setTab(t)}
                    className={`rounded-md px-3 py-1.5 text-[13px] ${tab === t ? "bg-panel font-semibold text-brand shadow-sm" : "text-inksoft"}`}>{t}</button>
                ))}
              </div>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="书文件夹名（拼音/英文）"
                className="mb-2 w-full text-sm" />
              <textarea value={files[tab] || ""} onChange={(e) => setFiles({ ...files, [tab]: e.target.value })}
                className="h-[36vh] w-full resize-none font-mono text-[13px]" />
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-xs text-inksoft">生成三件套后，此处出现编辑器</div>
          )}
        </div>
      </div>
    </div>
  );
}
