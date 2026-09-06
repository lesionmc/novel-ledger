# -*- coding: utf-8 -*-
"""web/api_meta.py —— 元数据与 v0.8/9 扩展路由。

覆盖：status / settings（GET/PUT/test）/ usage / plugins / rules / templates /
tpl 读 / 书级 style、graph、vector、sample-chapters、privacy-scan 与
v0.9 五动作（recalc-from / cross-audit / platform-check / beta-reader / export-evidence）。

注：RULES_DIR、STYLE_LEARN、REL_GRAPH、VECTOR、WRITE_CH、read_settings 等会被
test_routes.py 以 S.xxx 打桩，一律经 server 模块在调用时动态取用（不许 from import）。
"""
import os
import re
import subprocess
import sys

from common import (BOOKS_DIR, DOC_FILE, TEMPLATES_DIR, api_error, api_ok,
                    book_path, read_text, route, valid_tpl_name, write_text)

# name → write_chapter.py 里内置默认常量的属性名（None = 该规则无内置默认）。
# 注：内置常量取 BUILTIN_*（引擎侧 prompt 常量 import 时会被 rules/ 文件内容覆盖，
# BUILTIN_* 才是真正的出厂默认）；无内置的规则（style.md/graph.md 等）默认值
# 退回当前生效值（rules/ 文件内容），响应带 {"builtin": false} 标记。
_RULE_BUILTINS = {
    "deai_rules.md": "BUILTIN_DEAI_RULES",
    "deconstruct.md": "BUILTIN_DECONSTRUCT_RULES",
    "system.md": "BUILTIN_SYSTEM_PROMPT",
    "state_updater.md": "BUILTIN_STATE_UPDATER_PROMPT",
    "audit.md": "BUILTIN_AUDIT_PROMPT",
    "plan.md": "BUILTIN_PLAN_PROMPT",
    "style.md": None,
    "graph.md": None,
}

# v0.9 引擎动作 → write_chapter.py flag
_V09 = {"recalc-from": "--recalc-from", "cross-audit": "--cross-audit",
        "platform-check": "--platform-check", "beta-reader": "--beta-reader",
        "export-evidence": "--export-evidence"}


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


# ---------------- status / settings / usage ----------------
@route("GET", "status")
def get_status(h, params):
    srv = _server()
    api_ok(h, {"ok": True, "key_set": srv.KEY_SET, "books_dir": BOOKS_DIR,
               "settings": srv.public_settings()})


@route("GET", "settings")
def get_settings(h, params):
    api_ok(h, {"settings": _server().public_settings()})


@route("PUT", "settings")
def put_settings(h, params):
    srv = _server()
    data = h._read_json()
    changes = data.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        api_error(h, 400, "需要 changes 字段")
        return
    srv.write_settings(changes)
    api_ok(h, {"ok": True, "settings": srv.public_settings(), "key_set": srv.KEY_SET})


@route("GET", "inspiration")
def get_inspiration(h, params):
    """灵感素材库：books/_templates/灵感库/*.md 的清单+全文（只读，目录白名单锁死）。"""
    lib = os.path.join(TEMPLATES_DIR, "灵感库")
    items = []
    if os.path.isdir(lib):
        for fn in sorted(os.listdir(lib)):
            if not fn.endswith(".md"):
                continue
            try:
                with open(os.path.join(lib, fn), encoding="utf-8") as f:
                    body = f.read()
            except OSError:
                continue
            # 标题 = 文件首个 # 行；预览 = 去标题后前 60 字
            head, _, rest = body.partition("\n")
            title = head.lstrip("# ").strip() or fn[:-3]
            items.append({"file": fn, "title": title,
                          "preview": rest.strip().replace("\n", " ")[:60], "content": body})
    api_ok(h, {"items": items})


@route("POST", "settings/models")
def post_settings_models(h, params):
    """配置向导第 2 步：拉 OpenAI 兼容 /models 列表（body {base_url, key}）。
    仅用户在设置页主动配置时外呼；key 只在本请求内使用，不落盘不回显。"""
    import json as _json
    import urllib.request
    data = h._read_json()
    base = (data.get("base_url") or "").strip().rstrip("/")
    key = (data.get("key") or "").strip()
    if not base:
        api_error(h, 400, "需要 base_url")
        return
    req = urllib.request.Request(base + "/models",
                                 headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        api_error(h, 502, f"拉取模型列表失败：{e}")
        return
    ids = sorted({(m or {}).get("id") or (m or {}).get("model") or ""
                  for m in (payload.get("data") or [])} - {""})
    api_ok(h, {"models": ids})


@route("POST", "settings/test")
def post_settings_test(h, params):
    srv = _server()
    cfg = srv.live_env()
    try:
        # max_tokens 给足 + 正常探测语：agnes 带推理，预算太小或 system 只给 "ping"
        # 都会只出思考不出正文（实测 sample 返回空）
        answer = srv.llm_chat([
            {"role": "system", "content": "你是连通性探测器，用一句短中文回复即可。"},
            {"role": "user", "content": "请回复：连接正常"},
        ], max_tokens=400, action="连通测试")
        api_ok(h, {"ok": True, "sample": answer, "model": cfg["model"]})
    except Exception as e:
        # 脱敏：只回异常类型名，不透传原始异常（可能含 URL/key 等内部细节）
        api_error(h, 502, f"连接失败：{type(e).__name__}（上游服务暂不可用）")


@route("GET", "usage")
def get_usage(h, params):
    # R48 用量记账：读本地流水现算汇总（零成本、零外呼）
    import usage_log
    api_ok(h, {"summary": usage_log.aggregate(usage_log.load_entries())})


# ---------------- 插件（v0.3 技能中心） ----------------
@route("GET", "plugins")
def get_plugins(h, params):
    # v0.3 插件清单：plugin_loader 扫描（含 enabled 状态，mtime 缓存）
    import plugin_loader
    plugs = plugin_loader.scan_plugins()
    api_ok(h, {"plugins": [
        {"name": p["name"], "description": p.get("description", ""),
         "enabled": bool(p.get("enabled"))}
        for p in sorted(plugs, key=lambda x: x["name"])]})


@route("POST", "plugins/{name}/toggle")
def post_plugin_toggle(h, params):
    # v0.3 插件开关（plugin_loader 落盘 + 缓存失效）
    import plugin_loader
    pname = params["name"]
    data = h._read_json()
    enabled = bool(data.get("enabled"))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pname):
        # 名字不合法直接 404，不让畸形输入落到文件系统层
        api_error(h, 404, "插件不存在: " + pname)
        return
    try:
        plugin_loader.set_enabled(pname, enabled)
    except (FileNotFoundError, ValueError):  # ValueError：残缺 manifest
        api_error(h, 404, "插件不存在: " + pname)
        return
    api_ok(h, {"ok": True, "name": pname, "enabled": enabled})


# ---------------- 提示词管理（v0.6 rules/） ----------------
def list_rules():
    """rules/ 下 *.md 文件名（.bak 等非 .md 后缀天然排除）。"""
    rd = _server().RULES_DIR
    if not os.path.isdir(rd):
        return []
    return sorted(f for f in os.listdir(rd) if f.endswith(".md"))


def builtin_rule(name):
    """取某规则的内置默认文本。返回 (text, is_builtin)：
    BUILTIN_* 常量命中 → (内置文本, True)；无内置默认的规则 →
    (当前生效值即 rules/ 文件内容, False)；文件也读不到 → (None, False)。"""
    try:
        import write_chapter as _wc
    except Exception:
        _wc = None
    attr = _RULE_BUILTINS.get(name)
    if attr and _wc is not None:
        body = getattr(_wc, attr, None)
        if body:
            return body, True
    # 无内置常量：退回当前生效值（rules/ 文件内容即引擎加载的生效值）
    return read_text(os.path.join(_server().RULES_DIR, name)), False


@route("GET", "rules")
def get_rules(h, params):
    api_ok(h, {"rules": list_rules()})


@route("GET", "rules/{name}")
def get_rule(h, params):
    # 读取规则内容（Rules.jsx 用）：白名单防穿越
    name = params["name"]
    if name not in list_rules():
        api_error(h, 404, "规则不存在: " + name)
        return
    body = read_text(os.path.join(_server().RULES_DIR, name))
    if body is None:
        api_error(h, 404, "规则文件读取失败: " + name)
        return
    api_ok(h, {"name": name, "content": body})


@route("GET", "rules/{name}/default")
def get_rule_default(h, params):
    name = params["name"]
    if name not in list_rules():
        api_error(h, 404, "规则不存在: " + name)
        return
    body, is_builtin = builtin_rule(name)
    if body is None:
        api_error(h, 404, "该规则无内置默认: " + name)
        return
    api_ok(h, {"name": name, "body": body, "builtin": is_builtin})


@route("PUT", "rules/{name}")
def put_rule(h, params):
    # v0.6 提示词保存：白名单（rules/ 真实文件名）防穿越；原内容备份 .bak
    name = params["name"]
    if name not in list_rules():
        api_error(h, 404, "规则不存在: " + name)
        return
    data = h._read_json()
    body = data.get("body")
    if not isinstance(body, str):
        api_error(h, 400, "需要 body（字符串）")
        return
    if not body.strip():
        api_error(h, 400, "内容不能为空")  # 防一键清空规则文件
        return
    fp = os.path.join(_server().RULES_DIR, name)
    backup = False
    if os.path.exists(fp):
        write_text(fp + ".bak", read_text(fp) or "")
        backup = True
    write_text(fp, body)
    api_ok(h, {"ok": True, "name": name, "backup": backup})


# ---------------- 题材模板（v0.6） ----------------
def list_templates():
    """GET /api/templates：题材模板（_templates/ 子目录，含三件套才算）+ 推进模式卡。
    目录不存在返回空数组（正常业务响应，绝不 500）。"""
    tpls = []
    if os.path.isdir(TEMPLATES_DIR):
        for d in sorted(os.listdir(TEMPLATES_DIR)):
            dp = os.path.join(TEMPLATES_DIR, d)
            if d.startswith("_") or not os.path.isdir(dp):
                continue
            docs = {k: os.path.isfile(os.path.join(dp, f))
                    for k, f in (("设定", "设定.md"), ("角色卡", "角色卡.md"), ("大纲", "大纲.md"))}
            if any(docs.values()):
                tpls.append({"name": d, "docs": docs})
    cdir = os.path.join(TEMPLATES_DIR, "模式卡")  # 模式卡目录无三件套，天然不进 tpls
    cards = sorted(f[:-3] for f in (os.listdir(cdir) if os.path.isdir(cdir) else [])
                   if f.endswith(".md"))
    return {"templates": tpls, "mode_cards": cards}


@route("GET", "templates")
def get_templates(h, params):
    api_ok(h, list_templates())


def _tpl_read(h, name):
    # 模板 read：读模板书三件套。name 重组以覆盖 ..%2F 等穿越形态，先 valid_tpl_name 再 book_path
    if not valid_tpl_name(name):
        api_error(h, 404, "模板不存在: " + name)
        return
    p = book_path(name)
    if not p:
        api_error(h, 404, "模板不存在: " + name)
        return
    api_ok(h, {"name": name,
               "docs": {k: read_text(os.path.join(p, DOC_FILE[k])) or ""
                        for k in ("设定", "角色卡", "大纲")}})


@route("GET", "tpl/{name}")
def get_tpl(h, params):
    _tpl_read(h, params["name"])


@route("GET", "tpl/{name}/{rest...}")
def get_tpl_deep(h, params):
    _tpl_read(h, params["name"] + "/" + "/".join(params["rest"]))


# ---------------- v0.8 GET：文风指纹 / 关系图谱 / 向量状态 / 样章 ----------------
_CHROMA_CACHE = None  # None=未探测；True/False=子进程探测结果（缓存，避免每次请求重导入）


def chromadb_available():
    """chromadb 是否可导入（子进程探测 + 缓存；不在 server 进程内 import，防拖慢启动）。"""
    global _CHROMA_CACHE
    if _CHROMA_CACHE is None:
        try:
            r = subprocess.run([sys.executable, "-c", "import chromadb"],
                               capture_output=True, timeout=120)
            _CHROMA_CACHE = (r.returncode == 0)
        except Exception:
            _CHROMA_CACHE = False
    return _CHROMA_CACHE


def vector_status(p):
    """GET /api/book/{b}/vector：向量召回状态。
    未装 chromadb 返回 available:false（正常业务响应，绝不 500）。"""
    index_dir = next((c for c in ("vector_index", ".vector", "chroma_db")
                      if os.path.isdir(os.path.join(p, c))), None)
    return {"available": chromadb_available(),
            "indexed": index_dir is not None,
            "index_dir": index_dir,
            "embed_configured": bool(_server().read_settings().get("EMBED_API_KEY", ""))}


@route("GET", "book/{book}/vector")
def get_book_vector(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    api_ok(h, vector_status(p))


@route("GET", "book/{book}/style")
def get_book_style(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    txt = read_text(os.path.join(p, "文风指纹.md"))
    if txt is None:
        api_error(h, 404, "尚无文风指纹——请先运行文风学习（style-learn）")
        return
    api_ok(h, {"book": params["book"], "content": txt})


@route("GET", "book/{book}/graph")
def get_book_graph(h, params):
    p = _require_book(h, params)
    if p is None:
        return
    j = read_text(os.path.join(p, "关系图谱.json"))
    md = read_text(os.path.join(p, "关系图谱.md"))
    if j is None and md is None:
        api_error(h, 404, "尚无关系图谱——请先构建（POST graph）")
        return
    api_ok(h, {"book": params["book"], "json": j, "md": md})


@route("GET", "book/{book}/sample-chapters")
def get_sample_chapters(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, "--sample-chapters"])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "log": (out + err)[-4000:]})


# ---------------- v0.8 POST：文风学习 / 关系图谱 / 向量索引 / 隐私扫描 ----------------
@route("POST", "book/{book}/style-learn")
def post_style_learn(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    r = h._run_or_502(srv.STYLE_LEARN, [srv.STYLE_LEARN, "--book", p])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "fingerprint": read_text(os.path.join(p, "文风指纹.md")),
               "log": (out + err)[-2000:]})


@route("POST", "book/{book}/graph")
def post_book_graph(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    r = h._run_or_502(srv.REL_GRAPH, [srv.REL_GRAPH, "--book", p])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok,
               "json": read_text(os.path.join(p, "关系图谱.json")),
               "md": read_text(os.path.join(p, "关系图谱.md")),
               "log": (out + err)[-2000:]})


@route("POST", "book/{book}/vector-index")
def post_vector_index(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    r = h._run_or_502(srv.VECTOR, [srv.VECTOR, "--book", p, "index"])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "status": vector_status(p), "log": (out + err)[-2000:]})


@route("POST", "book/{book}/privacy-scan")
def post_privacy_scan(h, params):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    h._read_json()
    r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, "--privacy-scan"])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "report": (out + err)[-6000:]})


# ---------------- v0.9 POST：账本重算 / 跨章审计 / 平台体检 / 试读 / 证据链 ----------------
def _v09_action(h, params, action):
    srv = _server()
    p = _require_book(h, params)
    if p is None:
        return
    data = h._read_json()
    no = h._get_no(data)
    if no is None:
        return
    if action in ("recalc-from", "cross-audit"):
        # 这两个动作会重写账本/长时读账本，与写章同书互斥
        from common import book_lock
        with book_lock(p):
            r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, _V09[action], str(no)])
    else:
        r = h._run_or_502(srv.WRITE_CH, [srv.WRITE_CH, "--book", p, _V09[action], str(no)])
    if r is None:
        return
    ok, out, err = r
    api_ok(h, {"ok": ok, "no": no, "action": action,
               "report": (out + err)[-6000:], "log": (out + err)[-2000:]})


@route("POST", "book/{book}/recalc-from")
def post_recalc_from(h, params):
    _v09_action(h, params, "recalc-from")


@route("POST", "book/{book}/cross-audit")
def post_cross_audit(h, params):
    _v09_action(h, params, "cross-audit")


@route("POST", "book/{book}/platform-check")
def post_platform_check(h, params):
    _v09_action(h, params, "platform-check")


@route("POST", "book/{book}/beta-reader")
def post_beta_reader(h, params):
    _v09_action(h, params, "beta-reader")


@route("POST", "book/{book}/export-evidence")
def post_export_evidence(h, params):
    _v09_action(h, params, "export-evidence")
