import React, { useEffect, useState } from "react";
import { api } from "../api.js";

/* 创作向导：把《AI 协作写小说操作手册》的七阶段流程落到本工作台的功能上。
   每阶段一张卡：人做什么 / AI 做什么 / 一键跳转 / 一键把提示词送进 AI 助手。
   阶段完成勾选状态存 localStorage（按书记忆，选了书就分书记录）。 */

const STAGES = [
  {
    n: 0, title: "准备", who: "建项目骨架：立项卡、设定文档、风格样本",
    ai: "帮你把模板一次建好、填好表头",
    jump: [["去灵感库抄模板", "inspiration"], ["去设定中心建档", "assets"]],
    prompt: "",
    tip: "产出=项目骨架。验收：每个文档都有模板和示例注释。",
  },
  {
    n: 1, title: "构思立意", who: "回答「我到底想写什么」，完成一句话卖点",
    ai: "给 8 个一句话卖点供你挑（不要让 AI 替你选）",
    jump: [["填写立项卡模板", "inspiration"]],
    prompt: "我要写一本【题材】小说。给我 8 个一句话卖点，要求：每个都有明确的主角欲望+障碍+反转空间；每个卖点后标注核心爽点类型（打脸/解谜/逆袭/情感）。我的初步想法：",
    tip: "产出=立项卡第一版。验收：一句话卖点能让你自己心跳加速。",
  },
  {
    n: 2, title: "世界观 + 人物", who: "拍板核心规则：力量上限、主角欲望+缺陷、反派为何非坏不可",
    ai: "先扮演挑剔编辑拷问你的设定（列 10 个会被问倒的问题），修补后再扩写成正式文档",
    jump: [["去设定中心写世界观/人物", "assets"]],
    prompt: "这是我的核心设定：【】。请你扮演最挑剔的编辑，列出 10 个这个设定会被读者问倒的问题（逻辑漏洞、滥用风险、边界情况）。",
    tip: "产出=世界观文档（规则一行一条≥7条）+ 人物卡四件套齐全。验收：遮住名字读对白，能认出是谁。",
  },
  {
    n: 3, title: "大纲", who: "定主线骨架（起承转合）、定结局（结局必须先定）、砍掉平淡分支",
    ai: "三步法：卷纲 → 逐卷章纲 → 因果链自查",
    jump: [["去设定中心写大纲", "assets"]],
    prompt: "基于我的立项卡和人物卡：①把这本书分成 3~4 卷，每卷给出卷名/主要冲突/开卷事件/卷末爆点/主角变化；②把第一卷展开成 15 个章纲（每章50-100字：事件→冲突→章末钩）；③最后自查因果链、伏笔有无埋无收、有无连续 3 章无冲突升级。",
    tip: "产出=全书章纲。验收：通读不无聊、结局闭环没有「待续感」。铁律：大纲没确认前不写正文。",
  },
  {
    n: 4, title: "分章写作", who: "每章写规格（事件/人物/禁写/章末钩），循环：规格→生成→自检→改方向→回写",
    ai: "按规格+前情写初稿，逐条自检报告偏差",
    jump: [["去工作台写下一章", "workspace"], ["连写多章去任务中心", "tasks"]],
    prompt: "",
    tip: "一章一循环，别一上头写 5 章再检查——错误会滚雪球。不满意先说局部（第3段节奏太慢），永远好过「重写一遍」。",
  },
  {
    n: 5, title: "评审修订", who: "只处理你自己读着也「咯噔」的意见——终审权在你",
    ai: "角色轮审（追更读者/毒舌编审/故事医生）+ 一致性专项审计",
    jump: [["技能中心跑审计/评分", "plugins"], ["AI 模拟读者试读", "assistant"]],
    prompt: "分别扮演【追更读者/毒舌编审/故事医生】三个角色，各挑一遍我这本书最新一章的毛病；再跑一次一致性检查（时间线、称谓、物件位置、人物知识边界）。",
    tip: "意见里通常 1/3 真问题、1/3 口味、1/3 AI 过度严谨。",
  },
  {
    n: 6, title: "去 AI 味 + 定稿", who: "最后一遍朗读通读——拗口处就是最后的问题；核对平台红线",
    ai: "红灯词扫描、AI 套词替换、句长错落改造、AI 占比自证材料",
    jump: [["技能中心跑体检/去味", "plugins"], ["平台自检+证据包", "assistant"]],
    prompt: "",
    tip: "发布铁律：红灯词清零 + 人工终审 + AI 参与占比按平台要求标注。",
  },
];

const LS_DONE = "nl.guide.done";

export default function Guide({ go }) {
  const [books, setBooks] = useState([]);
  const [book, setBook] = useState(() => { try { return sessionStorage.getItem("nl.guide.book") || ""; } catch (e) { return ""; } });
  const [done, setDone] = useState({});

  useEffect(() => { api("/api/books").then((r) => setBooks(r.books)).catch(() => {}); }, []);
  useEffect(() => {
    try { sessionStorage.setItem("nl.guide.book", book); } catch (e) {}
    const key = LS_DONE + ":" + (book || "_");
    try { setDone(JSON.parse(localStorage.getItem(key) || "{}")); } catch (e) { setDone({}); }
  }, [book]);

  function toggle(n) {
    const next = { ...done, [n]: !done[n] };
    setDone(next);
    try { localStorage.setItem(LS_DONE + ":" + (book || "_"), JSON.stringify(next)); } catch (e) {}
  }

  function jumpWithPrompt(prompt) {
    try {
      if (prompt) sessionStorage.setItem("nl_assistant_prefill", prompt);
      if (book) sessionStorage.setItem("nl_assistant_prefill_book", book);
    } catch (e) {}
    go("assistant");
  }

  const finished = STAGES.filter((s) => done[s.n]).length;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-extrabold text-ink">创作向导</h1>
          <p className="mt-0.5 text-[13px] text-inksoft">AI 是施工队，你是总设计师——七阶段从一句话想法到能发布的成书。AI 负责所有苦力，你负责所有决策。</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={book} onChange={(e) => setBook(e.target.value)}
            className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-[13px] text-ink">
            <option value="">（未选书 · 通用流程）</option>
            {books.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <span className="rounded-full bg-brandbg px-3 py-1 text-xs font-semibold text-ink">进度 {finished}/7</span>
        </div>
      </div>

      {/* 流程总览条 */}
      <div className="mb-5 flex flex-wrap items-center gap-1.5 rounded-xl border border-line bg-panel px-4 py-3 text-[12px] shadow-sm">
        {STAGES.map((s, i) => (
          <React.Fragment key={s.n}>
            <button onClick={() => document.getElementById("stage-" + s.n)?.scrollIntoView({ behavior: "smooth", block: "center" })}
              className={`rounded-full px-2.5 py-1 font-semibold transition ${done[s.n] ? "bg-okbg text-ok" : "bg-paper text-inksoft hover:text-ink"}`}>
              {s.n === 0 ? "阶段0" : "阶段" + s.n} {s.title}{done[s.n] ? " ✓" : ""}
            </button>
            {i < STAGES.length - 1 && <span className="text-inksoft/50">→</span>}
          </React.Fragment>
        ))}
        <span className="flex-1" />
        <span className="text-inksoft">阶段4/5 循环直到过关</span>
      </div>

      <div className="space-y-3">
        {STAGES.map((s) => (
          <div key={s.n} id={"stage-" + s.n}
            className={`rounded-xl border bg-panel p-4 shadow-sm transition ${done[s.n] ? "border-ok/40" : "border-line"}`}>
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={() => toggle(s.n)} title="标记完成"
                className={`flex h-6 w-6 items-center justify-center rounded-full border text-[12px] font-bold transition ${
                  done[s.n] ? "border-ok bg-ok text-white" : "border-line text-inksoft hover:border-brand2"}`}>
                {done[s.n] ? "✓" : s.n}
              </button>
              <span className="text-[15px] font-bold text-ink">
                阶段{s.n} · {s.title}
              </span>
              <span className="flex-1" />
              {s.jump.map(([label, view]) => (
                <button key={label} onClick={() => go(view, view === "workspace" ? book : undefined)}
                  className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink transition hover:border-brand2 hover:text-brand">
                  {label} →
                </button>
              ))}
              {s.prompt && (
                <button onClick={() => jumpWithPrompt(s.prompt)}
                  className="rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand2">
                  在 AI 助手中开始 →
                </button>
              )}
            </div>
            <div className="mt-2.5 grid gap-2 text-[13px] leading-6 md:grid-cols-2">
              <div className="rounded-lg bg-paper px-3 py-2">
                <span className="font-semibold text-ink">你做：</span><span className="text-inksoft">{s.who}</span>
              </div>
              <div className="rounded-lg bg-paper px-3 py-2">
                <span className="font-semibold text-ink">AI 做：</span><span className="text-inksoft">{s.ai}</span>
              </div>
            </div>
            <div className="mt-2 text-xs text-inksoft">📌 {s.tip}</div>
          </div>
        ))}
      </div>

      <p className="mt-4 text-[12px] text-inksoft/80">
        三条保命纪律：大纲没定稿禁写正文；每个设定/伏笔当天录进文件（AI 的记忆 = 你喂的文件）；AI 初稿必须过去 AI 味 + 人工终审才叫完成。
      </p>
    </div>
  );
}
