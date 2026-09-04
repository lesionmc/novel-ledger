import React, { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";

/* 设置页：6 个白名单键读写 + 测试连接（脱敏占位 **** 不回写） */
const FIELDS = [
  { group: "主模型", items: [
    { key: "AGNES_API_KEY", label: "API Key", type: "password", ph: "sk-..." },
    { key: "AGNES_BASE_URL", label: "Base URL", type: "text", ph: "https://apihub.agnes-ai.com/v1/" },
    { key: "AGNES_MODEL", label: "Model ID（写手）", type: "text", ph: "agnes-2.5-flash" },
    { key: "PLANNER_MODEL", label: "策划模型（可选，留空=写手）", type: "text", ph: "出章纲用，留空回落写手" },
    { key: "REVIEWER_MODEL", label: "审校模型（可选，留空=写手）", type: "text", ph: "一致性审计用，留空回落写手" },
  ]},
  { group: "备用模型（主失败自动切换）", items: [
    { key: "FALLBACK_API_KEY", label: "Fallback API Key", type: "password", ph: "备用厂商 key（可选）" },
    { key: "FALLBACK_BASE_URL", label: "Fallback Base URL", type: "text", ph: "https://open.bigmodel.cn/api/paas/v4/" },
    { key: "FALLBACK_MODEL", label: "Fallback Model ID", type: "text", ph: "glm-4.5-flash" },
  ]},
];

export default function Settings({ go }) {
  const [vals, setVals] = useState(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/settings").then((r) => setVals(r.settings)).catch((e) => setStatus("读取失败：" + e.message));
  }, []);

  function set(k, v) { setVals((s) => ({ ...s, [k]: v })); }

  async function save() {
    setBusy(true); setStatus("");
    try {
      const changes = {};
      for (const g of FIELDS) for (const f of g.items) {
        const v = (vals[f.key] || "").trim();
        if (v && v !== "****") changes[f.key] = v;  // 脱敏占位符不许写回覆盖真值
      }
      const r = await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ changes }) }).then((x) => x);
      const rr = typeof r === "object" && "key_set" in r ? r : await api("/api/status");
      setStatus("已保存 ✅" + (rr.key_set ? "" : "（⚠ 未配 Key）"));
    } catch (e) { setStatus("保存失败：" + e.message); }
    finally { setBusy(false); }
  }

  async function testConn() {
    setBusy(true); setStatus("测试连接中…（消耗约 4 tokens）");
    try {
      const r = await apiPost("/api/settings/test", {});
      setStatus(`✅ 连接正常（模型 ${r.model}）示例：${r.sample || "（空）"}`);
    } catch (e) { setStatus("❌ 连接失败：" + e.message); }
    finally { setBusy(false); }
  }

  if (!vals) return <div className="text-sm text-inksoft">{status || "加载中…"}</div>;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-2xl font-bold text-brand">⚙ 设置 · API 与模型</h1>
      <p className="mb-5 text-sm text-inksoft">修改后实时生效（无需重启）。主备请选两家不同厂商——同厂商会连坐。</p>

      {FIELDS.map((g) => (
        <div key={g.group} className="mb-5 rounded-xl border border-line bg-panel p-4 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-brand">{g.group}</h3>
          {g.items.map((f) => (
            <label key={f.key} className="mb-3 block text-xs text-inksoft">
              {f.label}
              <input type={f.type} placeholder={f.ph} value={vals[f.key] || ""}
                onChange={(e) => set(f.key, e.target.value)}
                className="mt-1 block w-full text-sm" />
            </label>
          ))}
        </div>
      ))}

      {status && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-sm text-brand">{status}</div>}
      <div className="flex gap-2">
        <button onClick={save} disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm text-white hover:bg-brand2 disabled:opacity-40">💾 保存</button>
        <button onClick={testConn} disabled={busy} className="rounded-lg border border-line bg-panel px-4 py-2 text-sm hover:border-brand2 disabled:opacity-40">🔌 测试连接</button>
        <span className="flex-1" />
        <button onClick={() => go("usage")} className="rounded-lg border border-line bg-panel px-4 py-2 text-sm hover:border-brand2">📊 查看用量</button>
      </div>
      <p className="mt-4 text-xs text-inksoft">Key 只存本机 .env，不入 git、不出本机（数据红线）。</p>
    </div>
  );
}
