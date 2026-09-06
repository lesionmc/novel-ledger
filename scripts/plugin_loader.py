#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plugin_loader.py —— 插件发现与启停（纯标准库）

插件形态：项目根 plugins/<插件名>/plugin.json（manifest），字段：
  {"name": "...", "version": "...", "description": "...", "entry": "main.py", "enabled": true}

两个工程约束（都是踩过坑的）：
- set_enabled 必须原子写：先写临时文件再 os.replace。直接覆盖写 plugin.json，
  写一半崩溃/断电会留下残缺 manifest，下次扫描整个插件列表就废了。
- scan_plugins 用进程级 mtime 快照缓存（threading.Lock 保护），拒绝纯 TTL：
  「每 N 秒过期重扫」与文件变化无关，既会拿旧数据也会空转重扫；快照里任一
  plugin.json 的 mtime 变化或增删插件目录，才真正重扫。set_enabled 写盘成功后主动失效缓存。
"""
import argparse
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_DIR = os.path.join(ROOT, "plugins")

_cache_lock = threading.Lock()
_cache = {"snapshot": None, "plugins": None}  # snapshot=None 表示缓存无效


def _manifest_path(name):
    return os.path.join(PLUGINS_DIR, name, "plugin.json")


def _scan_snapshot():
    """采集 plugins 目录的 mtime 快照：((相对路径, mtime), ...) 有序元组。
    覆盖两类变化：任一 manifest 的 mtime 变化 / manifest 增删（插件目录增删）。"""
    items = []
    if not os.path.isdir(PLUGINS_DIR):
        return tuple(items)
    for name in sorted(os.listdir(PLUGINS_DIR)):
        mf = _manifest_path(name)
        if os.path.isfile(mf):
            try:
                items.append((os.path.relpath(mf, PLUGINS_DIR), os.path.getmtime(mf)))
            except OSError:
                continue  # mtime 读不到（如竞态删除）就当没变，下次快照自然区分
    return tuple(items)


def _scan_plugins_uncached():
    """真正扫盘：读全部 manifest，坏的跳过不炸整体。"""
    plugins = []
    if not os.path.isdir(PLUGINS_DIR):
        return plugins
    for name in sorted(os.listdir(PLUGINS_DIR)):
        mf = _manifest_path(name)
        if not os.path.isfile(mf):
            continue
        try:
            with open(mf, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue  # manifest 残缺/非 JSON：跳过该插件，不让一个坏插件拖垮全部
        plugins.append({
            "name": m.get("name") or name,
            "dir": name,
            "version": m.get("version", ""),
            "description": m.get("description", ""),
            "entry": m.get("entry", ""),
            "enabled": bool(m.get("enabled", False)),
        })
    return plugins


def scan_plugins(force=False):
    """返回插件列表（每个 dict 为浅拷贝，调用方改不脏缓存）。
    快照未变直接回缓存；force=True 强制重扫。"""
    with _cache_lock:
        snap = _scan_snapshot()
        if not force and _cache["plugins"] is not None and _cache["snapshot"] == snap:
            return [dict(p) for p in _cache["plugins"]]
        plugins = _scan_plugins_uncached()
        _cache["snapshot"] = snap
        _cache["plugins"] = plugins
        return [dict(p) for p in plugins]


def invalidate_cache():
    """主动失效缓存（set_enabled 写盘成功后必须调用）。"""
    with _cache_lock:
        _cache["snapshot"] = None
        _cache["plugins"] = None


def set_enabled(name, enabled):
    """启停插件：改写 plugin.json 的 enabled 字段（临时文件 + os.replace 原子写）。
    返回写盘后的 enabled 值；插件不存在抛 FileNotFoundError。"""
    mf = _manifest_path(name)
    if not os.path.isfile(mf):
        raise FileNotFoundError(f"插件不存在：{name}（找 {mf}）")
    with open(mf, encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["enabled"] = bool(enabled)
    # 同目录临时文件 + os.replace：同盘 rename 原子生效，残缺文件不会顶替正式 manifest
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(mf), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, mf)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    invalidate_cache()  # 写盘成功 → 主动失效，下次扫描必拿新状态
    return manifest["enabled"]


def main() -> int:
    ap = argparse.ArgumentParser(description="插件发现与启停")
    ap.add_argument("command", nargs="?", default="list", choices=["list", "enable", "disable"])
    ap.add_argument("name", nargs="?", help="enable/disable 的插件目录名")
    args = ap.parse_args()

    if args.command in ("enable", "disable"):
        if not args.name:
            print(f"{args.command} 需要插件名")
            return 1
        try:
            v = set_enabled(args.name, args.command == "enable")
        except (FileNotFoundError, OSError, ValueError) as e:
            print(f"操作失败：{e}")
            return 1
        print(f"{args.name} → enabled={v}")
    for p in scan_plugins():
        mark = "✅ 启用" if p["enabled"] else "⛔ 停用"
        print(f"{mark}  {p['dir']} v{p['version'] or '?'}  {p['description']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
