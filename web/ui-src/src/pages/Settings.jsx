import React, { useEffect, useState } from "react";
import { api, apiPost, apiPutJson } from "../api.js";

/* 设置页 v0.9.4：顶部「模型配置向导」（3 步：选厂商 → 连接模型 → 检测完成，
   对齐主流 AI 工具的首跑配置体验），下方保留高级配置（备用/策划/审校模型）。
   修改保存后实时生效；Key 只存本机 .env。 */

const PRESETS = [
  { name: "Agnes", base: "https://apihub.agnes-ai.com/v1/", hint: "注册送额度 · flash 系便宜快稳" },
  { name: "智谱 GLM", base: "https://open.bigmodel.cn/api/paas/v4/", hint: "glm-4.5-flash 有免费额度" },
  { name: "DeepSeek", base: "https://api.deepseek.com/v1/", hint: "deepseek-chat" },
  { name: "自定义", base: "", hint: "任意 OpenAI 兼容网关" },
];

const GROUPS = [
  {
    group: "角色分工模型（可选，留空用主模型）", items: [
      { key: "PLANNER_MODEL", label: "策划模型", type: "text", ph: "留空 = 用写手模型", tip: "只负责出章纲——想省钱就填个便宜模型" },
      { key: "REVIEWER_MODEL", label: "审校模型", type: "text", ph: "留空 = 用写手模型", tip: "只负责查前后矛盾——想更稳就填个推理强的模型" },
    ],
  },
  {
    group: "备用模型（写手挂了自动切过去，建议异构厂商）", items: [
      { key: "FALLBACK_API_KEY", label: "备用 API Key", type: "password", ph: "另一家厂商的 key（可选）", tip: "" },
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
  // 向导状态（步骤从 1 计：0 会让三步卡片全部不渲染）
  const [step, setStep] = useState(1);
  const [vendor, setVendor] = useState(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [key, setKey] = useState("");
  const [models, setModels] = useState(null);
  const [model, setModel] = useState("");
  const [wizMsg, setWizMsg] = useState("");

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
        if (v && v !== "****") changes[f.key] = v;
      }
      const r = await apiPutJson("/api/settings", { changes });
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

  /* —— 向导动作 —— */
  function pickVendor(p) {
    setVendor(p.name);
    setBaseUrl(p.base);
    setModels(null); setModel(""); setWizMsg("");
    setStep(2);
  }
  async function fetchModels() {
    setWizMsg("拉取模型列表中…"); setModels(null);
    try {
      const r = await apiPost("/api/settings/models", { base_url: baseUrl, key }, { timeout: 30000 });
      setModels(r.models || []);
      setWizMsg((r.models || []).length ? `找到 ${(r.models).length} 个可用模型，点选一个作为主模型` : "该网关没返回模型列表——手动填模型 ID 即可");
    } catch (e) { setWizMsg("❌ " + e.message + "（检查地址与 Key，或手动填模型 ID）"); }
  }
  async function finishWizard() {
    setBusy(true); setWizMsg("检测中…（消耗约 4 tokens）");
    try {
      const changes = { AGNES_BASE_URL: baseUrl, AGNES_MODEL: model };
      if (key && key !== "****") changes.AGNES_API_KEY = key;
      await apiPutJson("/api/settings", { changes });
      const r = await apiPost("/api/settings/test", {});
      setVals((s) => ({ ...s, AGNES_BASE_URL: baseUrl, AGNES_MODEL: model }));
      setKeySet(true);
      setWizMsg(`✅ 检测通过：${r.model}` + (r.sample ? ` · 回复示例「${r.sample}」` : "") + " —— 配置完成，已实时生效");
      setStep(3);
    } catch (e) { setWizMsg("❌ 检测失败：" + e.message + "（返回上一步检查地址/Key/模型名）"); }
    finally { setBusy(false); }
  }

  if (!vals) return <div className="text-sm text-inksoft">{status || "加载中…"}</div>;

  const steps = ["选择厂商", "连接模型", "检测完成"];

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-1 text-xl font-extrabold text-ink">设置</h1>
      <p className="mb-4 text-[13px] text-inksoft">修改保存后实时生效，无需重启。Key 只存本机 .env——不上传、不进 git、不出本机。</p>

      {/* Key 状态卡 */}
      <div className="mb-5 flex items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
        <span className={`h-2.5 w-2.5 rounded-full ${keySet ? "bg-ok" : "bg-warn"}`} />
        <div className="flex-1">
          <div className="text-[13px] font-semibold text-ink">{keySet ? "API Key 已配置" : "还没配 API Key"}</div>
          <div className="text-xs text-inksoft">{keySet ? "可以正常写作；异常时用下方向导或「测试连接」排查" : "用下方向导 3 步配好，或手动填 API Key 并保存"}</div>
        </div>
      </div>

      {/* 模型配置向导 */}
      <div className="mb-5 rounded-xl border border-line bg-panel p-5 shadow-sm">
        <div className="mb-1 text-[15px] font-bold text-ink">让 AI 创作环境先跑起来</div>
        <div className="mb-4 text-[12.5px] text-inksoft">只需配置一个文本模型，系统会自动备好规划、正文、审校和修复所需的任务路由。</div>

        {/* 步骤条 */}
        <div className="mb-4 grid grid-cols-3 gap-2">
          {steps.map((label, i) => {
            const n = i + 1;
            const state = step === n ? "cur" : step > n ? "done" : "todo";
            return (
              <button key={label} onClick={() => { if (n < step) setStep(n); }}
                className={`flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-[12.5px] transition ${
                  state === "cur" ? "border-brand bg-brandbg font-semibold text-ink"
                  : state === "done" ? "border-ok/40 bg-okbg text-ok"
                  : "border-line text-inksoft"}`}>
                <span className={`flex h-4.5 w-4.5 items-center justify-center rounded-full border px-1 text-[10px] ${state === "done" ? "border-ok text-ok" : "border-current"}`}>
                  {state === "done" ? "✓" : n}
                </span>
                {label}
              </button>
            );
          })}
        </div>

        {step === 1 && (
          <div>
            <div className="mb-2 text-[13px] font-semibold text-ink">添加第三方厂商</div>
            <div className="mb-3 text-xs text-inksoft">API Key 只会保存到本机 .env，不会出现在完成结果中。</div>
            <div className="grid grid-cols-2 gap-2.5">
              {PRESETS.map((p) => (
                <button key={p.name} onClick={() => pickVendor(p)}
                  className="rounded-xl border border-line bg-paper p-3.5 text-left transition hover:border-brand2 hover:shadow-sm">
                  <div className="text-[13.5px] font-bold text-ink">{p.name}</div>
                  <div className="mt-0.5 text-[11.5px] text-inksoft">{p.hint}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {step >= 2 && (
          <div>
            <div className="mb-3 text-[13px] font-semibold text-ink">厂商：{vendor}</div>
            <label className="mb-3 block text-[13px] font-semibold text-ink">
              API Key（只存本机）
              <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-…（已配置过可留空沿用）"
                className="mt-1 block w-full text-sm" />
            </label>
            <label className="mb-3 block text-[13px] font-semibold text-ink">
              API 地址
              <input type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1/"
                className="mt-1 block w-full text-sm" />
            </label>
            <button onClick={fetchModels} disabled={!baseUrl || busy}
              className="rounded-lg border border-line bg-paper px-3.5 py-2 text-[13px] font-semibold text-ink hover:border-brand2 hover:text-brand disabled:opacity-40">
              📡 获取模型列表
            </button>
            {models && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {models.slice(0, 24).map((m) => (
                  <button key={m} onClick={() => setModel(m)}
                    className={`rounded-full border px-3 py-1 text-[12px] transition ${
                      model === m ? "border-brand bg-brandbg font-semibold text-ink" : "border-line text-inksoft hover:border-brand2 hover:text-brand"}`}>
                    {m}
                  </button>
                ))}
                {models.length > 24 && <span className="self-center text-[11px] text-inksoft">…共 {models.length} 个</span>}
              </div>
            )}
            <label className="mt-3 block text-[13px] font-semibold text-ink">
              文本模型（写正文主力）
              <input type="text" value={model} onChange={(e) => setModel(e.target.value)} placeholder="agnes-2.5-flash / glm-4.5-flash / deepseek-chat"
                className="mt-1 block w-full text-sm" />
            </label>
            <div className="mt-3 rounded-lg border border-line bg-paper px-3 py-2 text-xs text-inksoft">
              完成后，这个模型会作为规划、正文、审核、修复、重规划和摘要等核心任务的初始默认值。
            </div>
            {wizMsg && <div className="mt-3 rounded-lg bg-brandbg px-3.5 py-2 text-[12.5px] text-ink">{wizMsg}</div>}
            <div className="mt-4 flex items-center justify-between">
              <button onClick={() => setStep(1)} className="rounded-lg px-3 py-2 text-[13px] text-inksoft hover:text-ink">← 返回选择</button>
              <button onClick={finishWizard} disabled={!model || busy}
                className="rounded-lg bg-brand px-4 py-2 text-[13px] font-semibold text-white hover:bg-brand2 disabled:opacity-40">
                检测并完成配置 🚀
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 高级配置 */}
      <details className="mb-5 rounded-xl border border-line bg-panel p-5 shadow-sm">
        <summary className="cursor-pointer text-[13px] font-semibold text-ink">高级配置（角色分工 / 备用模型）</summary>
        {GROUPS.map((g) => (
          <div key={g.group} className="mt-4 border-t border-line pt-4 first:border-0 first:pt-0">
            <h3 className="mb-3 text-[13px] font-semibold text-ink">{g.group}</h3>
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
      </details>

      {status && <div className="mb-3 rounded-lg bg-brandbg px-4 py-2 text-[13px] text-ink">{status}</div>}
      <div className="flex gap-2">
        <button onClick={save} disabled={busy} className="rounded-lg bg-brand px-5 py-2 text-[13px] font-semibold text-white hover:bg-brand2 disabled:opacity-40">保存</button>
        <button onClick={testConn} disabled={busy} className="rounded-lg border border-line bg-panel px-4 py-2 text-[13px] hover:border-ink/30 disabled:opacity-40">测试连接</button>
        <span className="flex-1" />
        <button onClick={() => go("usage")} className="rounded-lg border border-line bg-panel px-4 py-2 text-[13px] hover:border-ink/30">查看用量</button>
      </div>
    </div>
  );
}
