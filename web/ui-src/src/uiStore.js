/* 轻量共享 store：主题 / 侧栏折叠 / 书内导航（书+章）持久化。
   用 useSyncExternalStore 让各组件在状态变化时重渲染。 */

import { useSyncExternalStore } from "react";

const KEY_THEME = "novel-ledger.theme";        // localStorage
const KEY_COLLAPSE = "novel-ledger.sidebar.collapsed"; // localStorage
const KEY_BOOK = "novel-ledger.book";          // sessionStorage（书内导航）
const KEY_CH = "novel-ledger.chapter";         // sessionStorage（书内导航）
const KEY_WELCOME = "novel-ledger.welcomed";   // localStorage
const KEY_MODE = "novel-ledger.mode";          // localStorage（Workspace 双模式）
const KEY_REPORT = "novel-ledger.report-note"; // sessionStorage（BookRail→技能中心提示文件名）

function ssGet(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
function ssSet(k, v) { try { if (v == null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (e) {} }
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

const listeners = new Set();
function emit() { listeners.forEach((l) => l()); }
export function subscribe(l) { listeners.add(l); return () => listeners.delete(l); }

let _theme = lsGet(KEY_THEME) || "";
let _collapsed = lsGet(KEY_COLLAPSE) === "1";
let _book = ssGet(KEY_BOOK) || "";
let _chapter = ssGet(KEY_CH) || "";
let _welcomed = lsGet(KEY_WELCOME) === "1";
let _mode = lsGet(KEY_MODE) || "simple";
let _report = ssGet(KEY_REPORT) || "";

/* —— 主题 —— */
export function getTheme() { return _theme; }
export function setTheme(v) { _theme = v || ""; if (_theme) lsSet(KEY_THEME, _theme); emit(); }

/* —— 侧栏折叠 —— */
export function getCollapsed() { return _collapsed; }
export function setCollapsed(v) { _collapsed = !!v; lsSet(KEY_COLLAPSE, _collapsed ? "1" : "0"); emit(); }

/* —— 书内导航 —— */
export function getRailBook() { return _book; }
export function setRailBook(v) { _book = v || ""; ssSet(KEY_BOOK, _book); emit(); }
export function getRailChapter() { return _chapter; }
export function setRailChapter(v) { _chapter = v == null ? "" : String(v); ssSet(KEY_CH, _chapter); emit(); }

/* —— 引导弹窗 —— */
export function getWelcomed() { return _welcomed; }
export function setWelcomed(v) { _welcomed = !!v; lsSet(KEY_WELCOME, _welcomed ? "1" : "0"); emit(); }

/* —— Workspace 双模式 —— */
export function getMode() { return _mode; }
export function setMode(v) { _mode = v === "pro" ? "pro" : "simple"; lsSet(KEY_MODE, _mode); emit(); }

/* —— BookRail→技能中心 报告文件名提示 —— */
export function getReportNote() { return _report; }
export function setReportNote(v) { _report = v || ""; ssSet(KEY_REPORT, _report); emit(); }

/* —— hooks —— */
export function useTheme() { return useSyncExternalStore(subscribe, getTheme); }
export function useCollapsed() { return useSyncExternalStore(subscribe, getCollapsed); }
export function useRailBook() { return useSyncExternalStore(subscribe, getRailBook); }
export function useRailChapter() { return useSyncExternalStore(subscribe, getRailChapter); }
export function useWelcomed() { return useSyncExternalStore(subscribe, getWelcomed); }
export function useMode() { return useSyncExternalStore(subscribe, getMode); }
export function useReportNote() { return useSyncExternalStore(subscribe, getReportNote); }
