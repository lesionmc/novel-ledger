import React, { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";

/* 设置页：8 个白名单键读写 + 测试连接（脱敏占位 **** 不回写）
   v0.2.1：Key 状态移入本页；每个配置项加大白话说明；两行式布局 */

const GROUPS = [
  {
    group: "主模型（写正文、聊书都用它）", items: [
      { key: "AGNES_API_KEY", label: "API Key", type: "password", ph: "sk-...", tip: "模型厂商给你的密钥，只存本机" },
      { key: "AGNES_BASE_URL", label: "接口地址 Base URL", type: "text", ph: "https://apihub.agnes-ai.com/v1/", tip: "找厂商文档里的 API 地址" },
      { key: "AGNES_MODEL", label: "模型 ID（写手）", type: "text", ph: "agnes-2.5-flash", tip: "写正文的主力模型，质量优先" },
      { key: "PLANNER_MODEL", label: "策划模型", type: "text", ph: "留空 = 用写手模型", tip: "只负责出章纲——想省钱就填个便宜模型" },
      { key: "REVIEWER_MODEL", label: "审校模型", type: "text", ph: "留空 = 用写手模型", tip: "只负责查前后矛盾——想更稳就填个推理强的模型" },
    ],
  },
  {
    group: "备用模型（写手挂了自动切过去）", items: [
      { key: "FALLBACK_API_KEY", label: "备用 API Key", type: "password", ph: "另一家厂商的 key（可选）", tip: "建议和主模型不同厂商，避免一起挂" },
      { key: "FALLBACK_BASE_URL", label: "备用接口地址", type: "text", ph: "https://open.bigmodel.cn/api/paas/v4/", tip: "" },
      { key: "FALLBACK_MODEL", label: "备用模型 ID", type: "text", ph: "glm-4.5-flash", tip: "" },
    ],
  },
];

export default function Settings({ go }) {
  const [vals, setVals] = useState(null);
  const [keySet, setKeySet] = useState(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/settings").then((r) => setVals(r.settings)).catch((e) => setStatus("读取失败：" + e.message));
    api("/api/status").then((r) => setKeySet(!!r.key_set)).catch(() => {});
  }, []);

  function set(k, v) { setVals((s) => ({ ...s, [k]: v })); }

  async function save() {
    setBusy(true); setStatus("");
    try {
      const changes = {};
      for (const g of GROUPS) for (const f of g.items) {
        const v = (vals[f.key] || "").trim();
        if (v && v !== "****") changes[f.key] = v;  // 脱敏占位符不许写回覆盖真值
      }
      const r = await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ changes }) }).then((x) => x);
      const rr = typeof r === "object" && "key_set" in r ? r : await api("/api/status");
      setKeySet(!!rr.key_set);
      setStatus("已保存 ✅" + (rr.key_set ? "" : "（⚠ 还没配 Key）"));
    } catch (e) { setStatus("保存失败：" + e.message); }
    finally { setBusy(false); }
  }

  async function testConn() {
    setBusy(true); setStatus("测试连接中…（消耗约 4 tokens）");
    try {
      const r = await apiPost("/api/settings/test", {});
      setStatus(`✅ 连接正常，当前模型：${r.model}` + (r.sample ? `，回复示例：「${r.sample}」` : ""));
    } catch (e) { setStatus("❌ 连接失败：" + e.message); }
    finally { setBusy(false); }
  }

  if (!vals) return <div className="text-sm text-inksoft">{status || "加载中…"}</div>;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-xl font-bold text-ink">设置</h1>
      <p className="mb-4 text-[13px] text-inksoft">修改保存后实时生效，无需重启。</p>

      {/* Key 状态卡（从顶栏移过来的） */}
      <div className="mb-5 flex items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
        <span className={`h-2.5 w-2.5 rounded-full ${keySet ? "bg-ok" : "bg-warn"}`} />
        <div className="flex-1">
          <div className="text-[13px] font-semibold text-ink">{keySet ? "API Key 已配置" : "还没配 API Key"}</div>
          <div className="text-xs text-inksoft">{keySet ? "可以正常写作；连接异常时点下方「测试连接」排查" : "在下方填入 API Key 并保存，才能开始写作"}</div>
        </div>
      </div>

      {GROUPS.map((g) => (
        <div key={g.group} className="mb-5 rounded-xl border border-line bg-panel p-5 shadow-sm">
          <h3 className="mb-4 text-[13px] font-semibold text-ink">{g.group}</h3>
          {g.items.map((f) => (
            <div key={f.key} className="mb-4 last:mb-0">
              <div className="text-[13px] font-medium text-ink">{f.label}</div>
              {f.tip && <div className="mt-0.5 text-xs text-inksoft">{f.tip}</div>}
              <input type={f.type} placeholder={f.ph} value={vals[f.key] || ""}
                onChange={(e) => set(f.key, e.target.value)}
                className="mt-1.5 block w-full text-sm" />
            </div>
          ))}
        </div>
      ))}

      {status && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-[13px] text-ink">{status}</div>}
      <div className="flex gap-2">
        <button onClick={save} disabled={busy} className="rounded-lg bg-brand px-5 py-2 text-[13px] font-medium text-white hover:bg-brand2 disabled:opacity-40">保存</button>
        <button onClick={testConn} disabled={busy} className="rounded-lg border border-line bg-panel px-4 py-2 text-[13px] hover:border-ink/30 disabled:opacity-40">测试连接</button>
        <span className="flex-1" />
        <button onClick={() => go("usage")} className="rounded-lg border border-line bg-panel px-4 py-2 text-[13px] hover:border-ink/30">查看用量</button>
      </div>
      <p className="mt-4 text-xs text-inksoft">Key 只存本机 .env 文件——不上传、不进 git、不出本机。</p>
    </div>
  );
}
