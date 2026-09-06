#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup_book.py —— R34 一键备份：一本书的全家桶 zip（纯标准库）

打包内容（拍板 Q21 全家桶）：设定/角色卡/大纲 + story_state.md + chapters/（正文+体检/审计/章纲/bak）+ _snapshots/
排除：_vector/ 与 _recall/（向量召回产物，可能含 chromadb 巨型二进制库，不进 zip）
存放位置：项目根 backups/（拍板 Q22：保留最近 --keep 份，默认 10；配合每周手动拷一份到外部存储）
"""
import argparse
import os
import sys
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 不进 zip 的子目录：向量库/召回产物（可能含 chromadb 巨型二进制库，体积不可控）
EXCLUDE_DIRS = {"_vector", "_recall"}


def backup_book(book_dir: str, out_dir: str = None, keep: int = 10) -> str:
    """打包一本书 → backups/<书名>-<时间戳>.zip；修剪旧备份，返回 zip 路径。"""
    book = os.path.abspath(book_dir)
    if not os.path.isdir(book):
        raise SystemExit(f"书目录不存在：{book}")
    name = os.path.basename(book.rstrip("/\\"))
    out_dir = out_dir or os.path.join(ROOT, "backups")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(out_dir, f"{name}-{stamp}.zip")

    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(book):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]  # 原地剪枝，整棵子目录不进 zip
            for fn in files:
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, book)
                z.write(full, os.path.join(name, rel))
                n += 1
    print(f"[backup] 已生成 → {zip_path}（{n} 个文件）")

    zips = sorted(f for f in os.listdir(out_dir)
                  if f.startswith(name + "-") and f.endswith(".zip"))
    removed = 0
    if keep > 0:
        for old in zips[:-keep]:
            os.remove(os.path.join(out_dir, old))
            removed += 1
    if removed:
        print(f"[backup] 已修剪旧备份 {removed} 份（保留最近 {keep} 份）")
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="R34 一键备份：打包一本书的全家桶 zip")
    ap.add_argument("--book", required=True, help="书目录路径")
    ap.add_argument("--keep", type=int, default=10, help="保留最近几份（默认 10，0=不修剪）")
    args = ap.parse_args()
    backup_book(args.book, keep=args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
