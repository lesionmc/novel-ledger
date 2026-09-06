/* 任务通知 store：集中轮询 GET /api/tasks（15s），容错 404 / 网络错误静默。
   检测 running → paused/failed/done 的状态变化，驱动顶栏铃铛红点与 document.title 改写。 */

import { useSyncExternalStore } from "react";

const KEY_LAST = "novel-ledger.tasks.lastStates"; // 上次状态快照（跨刷新持久化）
const KEY_SEEN = "novel-ledger.tasks.lastViewed";  // 用户最近一次查看时间

function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

let tasks = [];
let changes = [];          // [{id, book, from, to, ts, label}]
let lastStates = loadLs(); // {id: status}
let lastViewed = parseFloat(lsGet(KEY_SEEN) || "0") || 0;
let loading = true;
let polling = false;
let timer = null;

const listeners = new Set();
function emit() { _snap = buildSnap(); listeners.forEach((l) => l()); }
function subscribe(l) { listeners.add(l); return () => listeners.delete(l); }

function loadLs() { try { return JSON.parse(lsGet(KEY_LAST) || "{}") || {}; } catch (e) { return {}; } }
function norm(s) { return s ? String(s).toLowerCase() : "pending"; }
function labelOf(t) { return t.book ? `《${t.book}》${t.id || ""}` : `任务 ${t.id || ""}`; }

function buildSnap() {
  const unseen = changes.filter((c) => c.ts > lastViewed).length;
  return { tasks, changes: changes.slice(0, 20), unseenCount: unseen, markSeen, loading };
}

let _snap = buildSnap();

function updateTitle() {
  const unseenChanges = changes.filter((c) => c.ts > lastViewed);
  if (unseenChanges.length) {
    const top = unseenChanges[0];
    const map = { paused: "⏸ 任务暂停", failed: "❌ 任务失败", done: "✅ 写作完成", cancelled: "⏸ 任务已取消", canceled: "⏸ 任务已取消" };
    document.title = (map[top.to] || "🔔 任务更新") + " - novel-ledger";
  } else {
    document.title = "novel-ledger";
  }
}

async function poll() {
  let data;
  try {
    const r = await fetch("/api/tasks");
    if (!r.ok) { if (r.status === 404) data = { tasks: [] }; else return; } // 404=无任务；其它静默
    else data = await r.json().catch(() => ({ tasks: [] }));
  } catch (e) { return; } // 网络错误静默
  const arr = (data && Array.isArray(data.tasks)) ? data.tasks
    : (Array.isArray(data) ? data : []);
  apply(arr);
}

function apply(arr) {
  const next = {};
  for (const t of arr) {
    if (!t || typeof t !== "object" || !t.id) continue;
    const st = norm(t.status);
    next[t.id] = st;
    const prev = lastStates[t.id];
    if (prev && prev !== st && prev === "running" &&
        ["paused", "failed", "done", "cancelled", "canceled"].includes(st)) {
      changes.unshift({ id: t.id, book: t.book || "", from: prev, to: st, ts: Date.now(), label: labelOf(t) });
    }
  }
  for (const id of Object.keys(lastStates)) if (!(id in next)) delete lastStates[id];
  lastStates = next;
  lsSet(KEY_LAST, JSON.stringify(lastStates));
  tasks = arr.filter((t) => t && typeof t === "object");
  loading = false;
  updateTitle();
  emit();
}

export function startTaskPolling() {
  if (polling) return;
  polling = true;
  poll();
  timer = setInterval(poll, 15000);
}

export function stopTaskPolling() {
  if (timer) clearInterval(timer);
  timer = null; polling = false;
}

export function markSeen() {
  lastViewed = Date.now();
  lsSet(KEY_SEEN, String(lastViewed));
  updateTitle();
  emit();
}

export function useTasks() {
  return useSyncExternalStore(subscribe, () => _snap);
}
