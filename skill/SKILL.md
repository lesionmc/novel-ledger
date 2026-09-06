---
name: novel-ledger
description: 中文 AI 小说共创写作台——结构化滚动账本管记忆，AI 是笔、人是作者。支持连载写章、断点连写、全书去 AI 味、一致性质检与一键备份，书稿永远在你自己的硬盘上。
---

# novel-ledger · 中文 AI 小说共创写作台

定位一句话：**AI 是笔、人是作者**。所有决策（章纲确认、伏笔取舍、账本核对）由人拍板，
AI 只负责拟稿与执行；记忆由结构化滚动账本 `story_state.md` 管理，不靠模型"自觉"。

前置：项目根即工作目录，Python 3.10+，零第三方依赖，密钥放 `.env`（参考 `.env.example`）。

## 场景一：写下一章

```bash
# ① 开书跑一次：按 设定/角色卡/大纲 三件套初始化记忆账本
python scripts/write_chapter.py --book books/雾城档案 --init-state
# ② （推荐）先出章纲+试写，落盘 chapters/chNNN.章纲.md，人工确认后写章自动遵循
python scripts/write_chapter.py --book books/雾城档案 --chapter 34 --plan
# ③ 写第 34 章（写完自动更新账本；--auto-backup 可顺带全书备份）
python scripts/write_chapter.py --book books/雾城档案 --chapter 34 --words 4000
# 字数不满意一键微调：--adjust --target 4000 --mode expand|shrink
```

## 场景二：断点连写

CLI 没有 `--chain` 之类的连写参数——连写调度在 Web 服务端（后台线程逐章过账本闸口）：

- **推荐**：启动 `python web/server.py`，浏览器打开「任务中心」→ 选书、填章数 → 开始连写；任务卡上可随时继续/取消。
- 或直接调 task API：

```bash
# 提交：从下一章起连写 N 章（>10 章需 confirmed:true）
curl -X POST http://127.0.0.1:8801/api/book/雁回刀/task/start \
  -d '{"count":5,"confirmed":true}'
# 控制：{"action":"continue"|"cancel"}；进度读 GET /api/tasks
curl -X POST http://127.0.0.1:8801/api/book/雁回刀/task/control \
  -d '{"id":"<任务id>","action":"cancel"}'
```

## 场景三：全书去 AI 味

```bash
# L1 全书词表硬筛（零 token）
python scripts/deai.py --scan books/雾城档案
# L2 单章 AI 精判：出人读报告 + 机读 diff JSON（不改正文）
python scripts/deai.py --polish books/雾城档案 --chapter 35
# 按 diff 应用改写（只改 hard 级硬伤，原稿自动备份 .apply.bak.md）
python scripts/deai.py --apply books/雾城档案 --chapter 35
# 复查：改前 .bak.md vs 改后 L1 指数差值报告（零 token）
python scripts/deai.py --book books/雾城档案 --compare 35
```

## 场景四：质检体检

```bash
# 三步全跑：一致性审计（调模型）+ AI 腔 L1 评估 + 发布前检查（后两步零 token）
python scripts/checkup.py --book books/雁回刀 --chapter 35 --full
# 或单跑一步：--audit / --evaluate / --publish-check
python scripts/checkup.py --book books/雁回刀 --chapter 35 --audit
```

## 场景五：学文风

```bash
# 通读样章归纳文风指纹（写章时注入，保持手感一致）；--chapters N 控制取样章数
python scripts/style_learn.py --book books/雾城档案
```

守卫与桌面壳（可选）：

```bash
python scripts/guard_push.py --once   # cron 单轮：任务状态/新章变化推 webhook
python launch_webview.py              # pywebview 桌面窗口（pip install pywebview）
```

记住三件事：① 每章生成后必看账本 diff；② 修复后立即 `git push`（教训见 docs/13）；③ 书稿必须入库。
