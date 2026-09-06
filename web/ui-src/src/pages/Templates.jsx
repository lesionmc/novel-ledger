import React, { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";

/* 模板库（v0.3/v0.5，v0.9.1 修复复制错位）：题材模板与模式卡浏览 + 一键复制为新书
   契约：GET  /api/templates        → {templates:[{name,docs}], mode_cards:[…]}
        GET  /api/tpl/{name}       → {name, docs:{设定,角色卡,大纲}} 内容预览
        POST /api/tpl/{name}/copy  {"name":新书名} 整库复制建新书（含账本初始化）
   注：不再用 POST /api/books——那是复制示例书，与所选模板无关（旧版会静默复制错内容）。 */

function tplList(d) {
  if (!d || typeof d !== "object") return Array.isArray(d) ? d.map((t) => ({ ...t, kind: t.kind || "题材模板" })) : [];
  const out = [];
  if (Array.isArray(d.templates)) out.push(...d.templates.map((t) => ({ ...t, kind: t.kind || "题材模板" })));
  if (Array.isArray(d.mode_cards)) out.push(...d.mode_cards.map((t) => ({ ...t, kind: t.kind || "模式卡" })));
  if (out.length) return out;
  if (Array.isArray(d)) return d;
  return [];
}
const tplName = (t) => t.name || t.title || t.id || "（未命名模板）";
const tplKind = (t) => t.kind || t.type || "题材模板";
/* docs 形态兼容：{设定,角色卡,大纲} 三件套 或 {files} 或字符串 */
const contentOf = (t) => {
  const docs = t.docs || t.files;
  if (docs && typeof docs === "object")
    return Object.entries(docs).map(([k, v]) => `# ${k}\n\n${v}`).join("\n\n---\n\n");
  return t.content || t.body || t.text || "";
};
const encTpl = (n) => n.split("/").map(encodeURIComponent).join("/"); // 模板名可含子目录（如 模式卡/xx）

export default function Templates() {
  const [list, setList] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(null); // {name, body}
  const [creating, setCreating] = useState(null); // {tpl: 模板名, name: 新书名}

  useEffect(() => {
    api("/api/templates").then((d) => setList(tplList(d))).catch((e) => { setList([]); setErr(e.message); });
  }, []);

  /* 内容预览：走 GET /api/tpl/{name}（后端实时读盘）；失败回退用列表内联内容 */
  async function showPreview(t) {
    const name = tplName(t);
    setPreview({ name, body: "加载中…" });
    try {
      const d = await api(`/api/tpl/${encTpl(name)}`);
      const body = d && d.docs && typeof d.docs === "object"
        ? Object.entries(d.docs).map(([k, v]) => `# ${k}\n\n${v}`).join("\n\n---\n\n")
        : contentOf(t);
      setPreview({ name, body: body || "（模板无内容）" });
    } catch (e) {
      const body = contentOf(t);
      if (body) setPreview({ name, body });
      else { setPreview(null); setErr(`读取模板内容失败：${e.message}`); }
    }
  }

  /* 一键复制为新书：POST /api/tpl/{name}/copy {"name":新书名}（整库复制 + 账本初始化） */
  async function copyAs(tplNameStr) {
    const name = ((creating && creating.name) || "").trim().replace(/[\\/]/g, "_");
    if (!name) { setErr("请先填新书名"); return; }
    setErr(""); setMsg("");
    try {
      await apiPost(`/api/tpl/${encTpl(tplNameStr)}/copy`, { name });
      setMsg(`已按模板「${tplNameStr}」创建新书《${name}》 ✅ 可在「章节与账本」打开`);
      setCreating(null);
    } catch (e) {
      setErr(`一键复制失败：${e.message}`);
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-xl font-bold text-ink">模板库</h1>
      <p className="mb-4 text-[13px] text-inksoft">
        开箱即用的题材模板与写法模式卡。点「一键复制为新书」即按模板整库复制出一本新书（含三件套与账本初始化）。
      </p>

      {msg && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-[13px] text-ink">{msg}</div>}
      {err && <div className="mb-3 rounded-lg bg-warnbg px-4 py-2 text-[13px] text-warn">{err}</div>}

      {list === null ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">加载中…</div>
      ) : list.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line bg-panel px-5 py-8 text-center text-sm text-inksoft">
          暂无模板（books/_templates/ 下没有含三件套的模板书）
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {list.map((t, i) => (
            <div key={tplName(t) + i} className="flex flex-col rounded-xl border border-line bg-panel px-4 py-3.5 shadow-sm">
              <div className="flex items-center gap-2">
                <span className="text-[14px] font-semibold text-ink">{tplName(t)}</span>
                <span className="rounded-full bg-brandbg px-2 py-0.5 text-[11px] text-ink">{tplKind(t)}</span>
              </div>
              <p className="mt-1 flex-1 text-[12.5px] leading-5 text-inksoft">{t.description || t.hook || "（无描述）"}</p>
              <div className="mt-3 flex gap-2">
                <button onClick={() => setCreating({ tpl: tplName(t), name: "" })}
                  className="rounded-lg bg-brand px-3 py-1.5 text-[13px] text-white hover:bg-brand2">一键复制为新书</button>
                <button onClick={() => showPreview(t)}
                  className="rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-inksoft hover:border-ink/30">查看内容</button>
              </div>
              {creating && creating.tpl === tplName(t) && (
                <div className="mt-3 flex items-center gap-2 rounded-lg bg-paper px-3 py-2">
                  <input autoFocus placeholder="新书名（如 my-novel）" value={creating.name}
                    onChange={(e) => setCreating({ ...creating, name: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && copyAs(creating.tpl)}
                    className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-ink/30" />
                  <button onClick={() => copyAs(creating.tpl)} className="rounded-lg bg-brand px-3 py-1.5 text-[12.5px] text-white hover:bg-brand2">创建</button>
                  <button onClick={() => setCreating(null)} className="rounded-lg px-2 py-1.5 text-[12.5px] text-inksoft hover:text-ink">取消</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-6" onClick={() => setPreview(null)}>
          <div className="flex max-h-[80vh] w-full max-w-3xl flex-col rounded-xl bg-panel shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="text-[14px] font-semibold text-ink">模板：{preview.name}</span>
              <div className="flex gap-2">
                <button onClick={() => navigator.clipboard.writeText(preview.body).then(() => setMsg("内容已复制到剪贴板 ✅"))}
                  className="rounded-lg bg-brand px-3 py-1.5 text-[12.5px] text-white hover:bg-brand2">复制全部</button>
                <button onClick={() => setPreview(null)} className="rounded-lg px-2 py-1.5 text-[13px] text-inksoft hover:bg-paper">关闭 ✕</button>
              </div>
            </div>
            <pre className="flex-1 overflow-auto whitespace-pre-wrap px-4 py-3 text-[12.5px] leading-6 text-ink">{preview.body}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
