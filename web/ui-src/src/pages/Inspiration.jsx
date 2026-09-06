import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/* 灵感素材库：立项卡 / 人物卡 / 世界观 / 势力 / 伏笔表 / 大纲章纲 / 风格指令块 等
   开箱模板（源自《AI 协作写小说操作手册》），可复制全文去别处粘贴使用。 */

export default function Inspiration() {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(null);
  const [copied, setCopied] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/api/inspiration").then((d) => setItems(d.items || [])).catch((e) => setErr(e.message));
  }, []);

  async function copy(it) {
    try {
      await navigator.clipboard.writeText(it.content);
      setCopied(it.file);
      setTimeout(() => setCopied(""), 1500);
    } catch (e) {
      // 剪贴板不可用（非 https 等）：降级为选中文本
      const ta = document.createElement("textarea");
      ta.value = it.content; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); document.body.removeChild(ta);
      setCopied(it.file); setTimeout(() => setCopied(""), 1500);
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-xl font-extrabold text-ink">灵感素材库</h1>
      <p className="mb-4 text-[13px] text-inksoft">开箱即用的创作模板：立项卡 / 人物卡 / 世界观 / 势力组织 / 伏笔追踪表 / 大纲章纲 / 风格指令块。点开查看，一键复制，到设定中心或 AI 助手里用。</p>
      {err && <div className="mb-3 rounded-lg bg-errbg px-4 py-2 text-sm text-err">{err}</div>}

      <div className="grid gap-3 md:grid-cols-2">
        {items.map((it) => (
          <div key={it.file} className="rounded-xl border border-line bg-panel p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-[15px] font-bold text-ink">{it.title}</span>
              <span className="flex-1" />
              <button onClick={() => setOpen(open === it.file ? null : it.file)}
                className="rounded-lg border border-line px-2.5 py-1 text-xs text-inksoft hover:text-ink">
                {open === it.file ? "收起" : "查看"}
              </button>
              <button onClick={() => copy(it)}
                className="rounded-lg bg-brand px-2.5 py-1 text-xs font-medium text-white hover:bg-brand2">
                {copied === it.file ? "已复制 ✓" : "复制全文"}
              </button>
            </div>
            <p className="mt-1.5 text-xs leading-5 text-inksoft">{it.preview}…</p>
            {open === it.file && (
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-paper p-3 text-[12.5px] leading-6 text-ink">{it.content}</pre>
            )}
          </div>
        ))}
        {!items.length && !err && <div className="text-sm text-inksoft">加载中…（灵感库目录为空也会显示这里）</div>}
      </div>
    </div>
  );
}
