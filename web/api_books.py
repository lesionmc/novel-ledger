# -*- coding: utf-8 -*-
"""web/api_books.py —— 书 CRUD / 章读写 / doc / export / rename / import-txt / 模板建书。

书级路由一律先做书存在性校验（原 if 链口径：书不存在优先于 no route），
唯一例外 import-txt（建书动作本身不要求书已存在）与 tpl/copy（从模板建书）。
"""
import json
import os
import re
import shutil
import time
import urllib.parse

from common import (BOOKS_DIR, BOOK_ROOT_FILES, DOC_FILE, DOCS, SAMPLE_DIR,
                    api_error, api_ok, book_path, chapter_list, chapter_title,
                    list_books, next_chapter_no, read_text, route,
                    valid_tpl_name, write_text)


def _server():
    import server
    return server


def _require_book(h, params):
    """书存在性校验（原 if 链口径：书不存在优先于一切子路由判断）。"""
    p = book_path(params["book"])
    if not p:
        api_error(h, 404, "书不存在: " + params["book"])
        return None
    return p


# ---------------- 书列表 / 建书 ----------------
@route("GET", "books")
def get_books(h, params):
    api_ok(h, {"books": list_books()})


@route("POST", "books")
def post_books(h, params):
    srv = _server()
    data = h._read_json()
    name = (data.get("name") or "").strip()
    if not name or re.search(r"[/\\]", name):
        api_error(h, 400, "书名非法（不能含 / 或 \\）")
        return
    if os.path.exists(os.path.join(BOOKS_DIR, name)):
        api_error(h, 400, "同名书已存在")
        return
    shutil.copytree(SAMPLE_DIR, os.path.join(BOOKS_DIR, name))
    ok, _, _ = srv.run_engine([srv.WRITE_CH, "--book", os.path.join(BOOKS_DIR, name), "--init-state"])
    api_ok(h, {"ok": ok, "name": name})


@route("POST", "tpl/{name...}/copy")
def post_tpl_copy(h, params):
    # 从模板书复制建新书：先 valid_tpl_name 再 isdir（原版只查 isdir，可被 ..\..\ 穿越出 books/）
    # tpl 名用 "/" 重组（穿越形态 ..%2F、..%5C 会散成多段），交给 valid_tpl_name 一票拒绝
    srv = _server()
    tpl = "/".join(params["name"])
    if not valid_tpl_name(tpl):
        api_error(h, 404, "模板不存在: " + tpl)
        return
    tp = book_path(tpl)
    if not tp or not os.path.isdir(tp):
        api_error(h, 404, "模板不存在: " + tpl)
        return
    data = h._read_json()
    name = (data.get("name") or "").strip()
    if not name or re.search(r"[/\\]", name):
        api_error(h, 400, "书名非法（不能含 / 或 \\）")
        return
    if os.path.exists(os.path.join(BOOKS_DIR, name)):
        api_error(h, 400, "同名书已存在")
        return
    shutil.copytree(tp, os.path.join(BOOKS_DIR, name))
    ok, _, _ = srv.run_engine([srv.WRITE_CH, "--book", os.path.join(BOOKS_DIR, name), "--init-state"])
    api_ok(h, {"ok": ok, "name": name, "from": tpl})


@route("POST", "book/from-chat")
def post_book_from_chat(h, params):
    srv = _server()
    data = h._read_json()
    name = (data.get("name") or "").strip()
    files = data.get("files") or {}
    if not name or re.search(r"[/\\]", name):
        api_error(h, 400, "书名非法")
        return
    if not all(k in files for k in ("设定", "角色卡", "大纲")):
        api_error(h, 400, "files 需要包含 设定/角色卡/大纲 三份")
        return
    if os.path.exists(os.path.join(BOOKS_DIR, name)):
        api_error(h, 400, "同名书已存在")
        return
    try:
        shutil.copytree(SAMPLE_DIR, os.path.join(BOOKS_DIR, name))
        for k in ("设定", "角色卡", "大纲"):
            if k not in files:
                raise RuntimeError(f"缺少 {k} 文件内容")
            write_text(os.path.join(BOOKS_DIR, name, DOC_FILE[k]), files[k])
        ok, _, _ = srv.run_engine([srv.WRITE_CH, "--book",
                                   os.path.join(BOOKS_DIR, name), "--init-state"])
    except Exception as e:
        api_error(h, 500, f"建书失败：{e}")
        return
    api_ok(h, {"ok": ok, "name": name})


@route("POST", "book/{book}/import-txt")
def post_import_txt(h, params):
    # 导入 txt 建书（按「第X章」自动拆章；导出 txt 的逆操作）——建书动作，不要求书已存在
    name = params["book"]
    if re.search(r"[\\/]", name) or name in (".", "..") or name.startswith("_"):
        api_error(h, 400, "书名不合法")
        return
    fp = os.path.join(BOOKS_DIR, name)
    if os.path.exists(fp):
        api_error(h, 400, "已存在同名书: " + name)
        return
    data = h._read_json()
    text = (data.get("text") or "").replace("\r\n", "\n").strip()
    if len(text) < 50:
        api_error(h, 400, "文本太短，无法导入")
        return
    pat = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千零两]+章[^\n]*)$", re.M)
    marks = [(m.start(), m.group(1).strip()) for m in pat.finditer(text)]
    chs = []
    if marks:
        for i, (pos, t) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            body_i = text[pos:end].strip()
            body_i = body_i.split("\n", 1)[1].strip() if "\n" in body_i else ""
            chs.append((t, body_i))
    else:
        chs = [("第一章", text)]
    chs = chs[:500]
    os.makedirs(os.path.join(fp, "chapters"), exist_ok=True)
    for i, (t, body_i) in enumerate(chs, 1):
        write_text(os.path.join(fp, "chapters", f"ch{i:03d}.md"), f"# {t}\n\n{body_i}\n")
    write_text(os.path.join(fp, "设定.md"), "# 设定\n\n（导入书——请让 AI 助手根据正文补全设定/角色卡/大纲）\n")
    write_text(os.path.join(fp, "角色卡.md"), "# 角色卡\n\n（导入书，待补）\n")
    write_text(os.path.join(fp, "大纲.md"), "# 大纲\n\n（导入书，待补）\n")
    api_ok(h, {"ok": True, "name": name, "chapters": len(chs)})


# ---------------- 书详情 / 导出 ----------------
@route("GET", "book/{book}")
def get_book_detail(h, params):
    name = params["book"]
    p = _require_book(h, params)
    if p is None:
        return
    snap_dir = os.path.join(p, "_snapshots")
    snaps = sorted(f for f in (os.listdir(snap_dir) if os.path.isdir(snap_dir) else [])
                   if re.match(r"ch\d+\.state\.md$", f))
    # R35 伏笔超期：以最近已写章为"当前章"计算
    import write_chapter as _wc
    chs = chapter_list(p)
    cur = chs[-1][0] if chs else 0
    try:
        overdue = _wc.overdue_foreshadows(read_text(os.path.join(p, "story_state.md")), cur)
    except Exception:
        overdue = []
    api_ok(h, {
        "name": name,
        "chapters": [{"no": n, "file": f, "title": chapter_title(p, f),
                      "size": os.path.getsize(os.path.join(p, "chapters", f))}
                     for n, f in chs],
        "next_no": next_chapter_no(p),
        "has_state": os.path.exists(os.path.join(p, "story_state.md")),
        "snapshots": snaps,          # R47 章快照底账
        "overdue": [{"text": o["text"], "planted": o["planted"],
                     "overdue_by": o["overdue_by"]} for o in overdue],  # R35
    })


@route("GET", "book/{book}/export")
def get_book_export(h, params):
    # 导出全书：所有章节按序合并为一个 txt 下载
    name = params["book"]
    p = _require_book(h, params)
    if p is None:
        return
    chs = chapter_list(p)
    parts = [f"《{name}》\n导出时间：{time.strftime('%Y-%m-%d %H:%M')}\n共 {len(chs)} 章\n"]
    for n, f in chs:
        body = read_text(os.path.join(p, "chapters", f)) or ""
        title = chapter_title(p, f)
        parts.append(f"\n\n{'=' * 24}\n第 {n} 章  {title}\n{'=' * 24}\n\n{body.strip()}")
    data = "\n".join(parts).encode("utf-8")
    h.send_response(200)
    h.send_header("Content-Type", "text/plain; charset=utf-8")
    h.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(name + '-全书.txt')}")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


# ---------------- doc / ch 读写 ----------------
@route("GET", "book/{book}/doc/{doc}")
def get_book_doc(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    doc = params["doc"]
    if doc not in DOCS:
        api_error(h, 404, "doc 必须是 " + "|".join(DOCS))
        return
    txt = read_text(os.path.join(p, DOC_FILE[doc]))
    if txt is None:
        api_error(h, 404, "文件不存在")
        return
    api_ok(h, {"doc": doc, "content": txt})


@route("PUT", "book/{book}/doc/{doc}")
def put_book_doc(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    raw = h.rfile.read(int(h.headers.get("Content-Length") or 0)).decode("utf-8")
    doc = params["doc"]
    if doc not in DOCS:
        api_error(h, 404, "doc 必须是 " + "|".join(DOCS))
        return
    write_text(os.path.join(p, DOC_FILE[doc]), raw)
    api_ok(h, {"ok": True})


@route("GET", "book/{book}/ch/{no}")
def get_book_ch(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    if not re.fullmatch(r"(\d+)", params["no"]):
        api_error(h, 400, "章号格式错误")
        return
    no = int(params["no"])
    txt = read_text(os.path.join(p, "chapters", f"ch{no:03d}.md"))
    if txt is None:
        api_error(h, 404, "该章不存在")
        return
    api_ok(h, {"no": no, "content": txt})


@route("PUT", "book/{book}/ch/{no}")
def put_book_ch(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    raw = h.rfile.read(int(h.headers.get("Content-Length") or 0)).decode("utf-8")
    if not re.fullmatch(r"(\d+)", params["no"]):
        api_error(h, 400, "章号格式错误")
        return
    no = int(params["no"])
    os.makedirs(os.path.join(p, "chapters"), exist_ok=True)
    write_text(os.path.join(p, "chapters", f"ch{no:03d}.md"), raw)
    api_ok(h, {"ok": True, "no": no})


# ---------------- 产物文件 / 清单 / 重命名 ----------------
@route("GET", "book/{book}/file/{rel...}")
def get_book_file(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    rel = "/".join(params["rel"])
    if (not re.fullmatch(r"chapters/[^/]+\.(md|json)", rel)
            and rel != "story_state.md"
            and rel not in BOOK_ROOT_FILES  # v0.8：文风指纹/关系图谱落盘在书根
            and not re.fullmatch(r"_snapshots/ch\d+\.state\.md", rel)):  # R47 快照底账可读
        api_error(h, 403, "只允许读 chapters/ 下的文件或账本")
        return
    txt = read_text(os.path.join(p, rel))
    if txt is None:
        api_error(h, 404, "文件不存在: " + rel)
        return
    api_ok(h, {"file": rel, "content": txt})


@route("GET", "book/{book}/files")
def get_book_files(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    ch_dir = os.path.join(p, "chapters")
    out = []
    if os.path.isdir(ch_dir):
        for f in sorted(os.listdir(ch_dir)):
            if re.match(r"ch\d+\.(md|json)$", f) or "体检" in f or "审计" in f:
                out.append({"file": "chapters/" + f,
                            "size": os.path.getsize(os.path.join(ch_dir, f))})
    api_ok(h, {"files": out})


@route("PUT", "book/{book}/rename")
def put_book_rename(h, params):
    # 书名（文件夹名）重命名：快照/备份等随目录一起走
    p = _require_book(h, params)
    if p is None:
        return
    data = json.loads(h.rfile.read(int(h.headers.get("Content-Length") or 0)).decode("utf-8") or "{}")
    new = (data.get("new") or "").strip()
    if not new or re.search(r"[\\/]", new) or new in (".", "..") or new.startswith("_"):
        api_error(h, 400, "新名字不合法（不能含斜杠/下划线开头）")
        return
    if os.path.exists(os.path.join(BOOKS_DIR, new)):
        api_error(h, 400, "已存在同名书: " + new)
        return
    os.rename(p, os.path.join(BOOKS_DIR, new))
    api_ok(h, {"ok": True, "name": new})
