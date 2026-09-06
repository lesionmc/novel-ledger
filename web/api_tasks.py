# -*- coding: utf-8 -*-
"""web/api_tasks.py —— v0.6 连写任务系统（tasks.json 落书目录）。

引擎侧 task_runner 无 start/control，调度在 Web 侧实现：后台线程逐章
run_engine，cancel 用 Event 通知。共享状态（_TASK_LOCK/_TASK_STOP/_TASKS）在
common.py；run_engine/WRITE_CH 会被 test_routes.py 以 S.xxx 打桩，经 server
模块在调用时动态取用（不许 from import）。
"""
import json
import os
import threading
import time

from common import (_TASK_LOCK, _TASKS, _TASK_STOP, BOOKS_DIR, api_error,
                    api_ok, book_path, next_chapter_no, read_text, route,
                    write_text)


def _server():
    import server
    return server


def _task_file(p):
    return os.path.join(p, "tasks.json")


def _load_tasks(p):
    d = read_text(_task_file(p))
    try:
        v = json.loads(d) if d else []
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _persist_task(p, task):
    """按 id upsert 一条任务到 tasks.json（调用方需已持 _TASK_LOCK）。"""
    tasks = [t for t in _load_tasks(p) if t.get("id") != task.get("id")]
    tasks.append(task)
    write_text(_task_file(p), json.dumps(tasks, ensure_ascii=False, indent=1))


def recover_stale_tasks():
    """启动恢复：服务崩溃/重启残留的 status==running 任务改为 paused，
    防止幽灵 running 永久锁死该书（start 端点会拒绝 running 书）。"""
    if not os.path.isdir(BOOKS_DIR):
        return
    for d in os.listdir(BOOKS_DIR):
        p = os.path.join(BOOKS_DIR, d)
        if not os.path.isdir(p) or not os.path.isfile(_task_file(p)):
            continue
        try:
            tasks = _load_tasks(p)
            changed = False
            for t in tasks:
                if t.get("status") == "running":
                    t["status"] = "paused"
                    t["last_error"] = "服务重启"
                    changed = True
            if changed:
                write_text(_task_file(p), json.dumps(tasks, ensure_ascii=False, indent=1))
        except Exception:
            pass  # 残缺 tasks.json 不阻塞启动


def _task_worker(p, task, start, end):
    """后台连写：从 start 逐章写到 end（含），进度实时落 tasks.json。
    每章开跑前检查 cancel Event：被置位则直接落盘退出，绝不把状态翻回 running。"""
    srv = _server()
    stop = _TASK_STOP.get(task["id"])
    no = start
    while no <= end:
        with _TASK_LOCK:
            if stop and stop.is_set():
                break
            task["status"] = "running"
            task["current"] = no
            _persist_task(p, task)
        ok, out, err = srv.run_engine([srv.WRITE_CH, "--book", p, "--chapter", str(no)], timeout=1800)
        with _TASK_LOCK:
            (task["done"] if ok else task["failed"]).append(no)
            task["current"] = None
            _persist_task(p, task)
        no += 1
    with _TASK_LOCK:
        task["status"] = "cancelled" if (stop and stop.is_set()) else "done"
        _persist_task(p, task)


# ---------------- 任务查询 ----------------
@route("GET", "tasks")
def get_tasks(h, params):
    # 连写任务聚合：遍历各书 tasks.json 原样透传（新任务在前），附书名字段。
    # 供前端 Tasks.jsx 消费；status 拼写统一为 "cancelled"。
    tasks = []
    for d in (sorted(os.listdir(BOOKS_DIR)) if os.path.isdir(BOOKS_DIR) else []):
        if d.startswith("_") or d.startswith("."):
            continue
        p = os.path.join(BOOKS_DIR, d)
        if not os.path.isdir(p):
            continue
        with _TASK_LOCK:
            ts = _load_tasks(p)
        for t in reversed(ts):  # 后创建的任务排前面
            t = dict(t)
            t["book"] = d
            if t.get("status") == "canceled":
                t["status"] = "cancelled"
            tasks.append(t)
    api_ok(h, {"tasks": tasks})


@route("GET", "book/{book}/task")
def get_book_task(h, params):
    # v0.6 连写任务：读该书 tasks.json 最新一条
    p = book_path(params["book"])
    if not p:
        api_error(h, 404, "书不存在: " + params["book"])
        return
    with _TASK_LOCK:
        ts = _load_tasks(p)
    api_ok(h, {"task": ts[-1] if ts else None})


# ---------------- 任务 start / control ----------------
@route("POST", "book/{book}/task/start")
def post_task_start(h, params):
    name = params["book"]
    p = book_path(name)
    if not p:
        api_error(h, 404, "书不存在: " + name)
        return
    data = h._read_json()
    try:
        count = int(data.get("count") or 1)
    except (TypeError, ValueError):
        count = 0
    if count < 1:
        api_error(h, 400, "count 需为正整数")
        return
    if count > 30:
        api_error(h, 400, "单任务上限 30 章")
        return
    if count > 10 and not data.get("confirmed"):
        api_error(h, 400,
                  f"批量连写 {count} 章预计消耗约 {count * 5000} tokens"
                  "（写作+账本），确认后请带 confirmed=true 重试")
        return
    # 查重 → 落盘 → 派发全程持锁，杜绝两个并发 start 同时通过查重（TOCTOU）
    with _TASK_LOCK:
        if any(t.get("status") == "running" for t in _load_tasks(p)):
            api_error(h, 400, "该书已有连写任务在跑，请先取消或等它结束")
            return
        try:
            start = int(data.get("start") or 0) or next_chapter_no(p)
        except (TypeError, ValueError):
            start = next_chapter_no(p)
        task = {"id": "task-%d" % int(time.time() * 1000), "book": name,
                "start": start, "count": count, "status": "running",
                "current": None, "done": [], "failed": [],
                "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        _TASKS[task["id"]] = task   # worker/cancel 共享同一对象，防落盘互相覆盖
        _persist_task(p, task)
        _TASK_STOP[task["id"]] = threading.Event()
        threading.Thread(target=_task_worker, args=(p, task, start, start + count - 1),
                         daemon=True).start()
    api_ok(h, {"ok": True, "task": task})


@route("POST", "book/{book}/task/control")
def post_task_control(h, params):
    name = params["book"]
    p = book_path(name)
    if not p:
        api_error(h, 404, "书不存在: " + name)
        return
    data = h._read_json()
    act = data.get("action")
    if act not in ("continue", "cancel"):
        api_error(h, 400, "action 必须是 continue|cancel")
        return
    tid = data.get("id") or ""
    with _TASK_LOCK:
        task = next((t for t in _load_tasks(p) if t.get("id") == tid), None)
        live = _TASKS.get(tid)
        if live is not None:
            task = live  # 有活线程时以共享对象为准（done/failed 是实时的）
        if not task:
            api_error(h, 404, "任务不存在: " + tid)
            return
        if act == "cancel":
            if task.get("status") == "running":
                ev = _TASK_STOP.get(tid)
                if ev:
                    ev.set()  # 当前章跑完后 worker 停机
                task["status"] = "cancelled"
                _persist_task(p, task)
            api_ok(h, {"ok": True, "task": task})
            return
        # continue：从第一个未完成章续跑到原定终点
        # （不能用 max(done+failed)+1：那会永久跳过起点前失败的章）
        if task.get("status") == "running":
            api_error(h, 400, "任务还在跑，无需 continue")
            return
        end = int(task["start"]) + int(task["count"]) - 1
        # 只把 done 视为已完成：failed 章在 continue 时必须重试
        # （否则模型瞬时故障的章会被永久跳过，任务假 done）
        finished = set(task.get("done") or [])
        missing = sorted(set(range(int(task["start"]), end + 1)) - finished)
        if not missing:
            api_error(h, 400, "任务章节已全部跑完，无需续跑")
            return
        nxt = missing[0]
        _TASKS[tid] = task
        _TASK_STOP[tid] = threading.Event()
        task["status"] = "running"
        _persist_task(p, task)
        threading.Thread(target=_task_worker, args=(p, task, nxt, end),
                         daemon=True).start()
    api_ok(h, {"ok": True, "task": task})
