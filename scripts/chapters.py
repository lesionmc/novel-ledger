#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chapters.py —— 章节文件命名与枚举的单一事实源（纯标准库）

文件命名口径（全仓统一，禁止各处自带正则）：
  正文章节 = chNNN.md，N 为 3 位起（ch001）、支持 4+ 位扩展（ch1000），
  历史实现的「999 章上限」由此解除。
  附属文件（chXXX.meta.md / chXXX.apply.bak.md / chXXX.AI腔diff.json 等）一律不算正文章。

枚举入口只有两个：list_chapter_files（列文件，按章号升序）与 chapter_no_of（取章号）。
deai / write_chapter / vector_recall / relation_graph / guard_push 等全部走这里，
新增枚举点不要再写 `re.match(r"ch\\d{3}\\.md$")` 之类的散装正则。
"""
import os
import re

# 3 位起、支持 4+ 位（ch001.md ~ ch1000.md…）；不匹配 chXXX.meta.md 等附属文件
CH_RE = re.compile(r"ch(\d{3,})\.md$")


def chapter_no_of(fname: str) -> int:
    """从文件名取章节号：ch003.md → 3、ch1000.md → 1000、ch003.meta.md → 3；
    不是章节文件返回 -1。（兼容 3 位与 4+ 位；保留 .meta.md 兼容旧调用方）"""
    m = re.match(r"ch(\d{3,})(?:\.meta)?\.md$", fname)
    return int(m.group(1)) if m else -1


def chapter_dir(book_dir: str) -> str:
    """返回章节实际所在目录：书目录下的 chapters/ 优先，
    不存在则回落 book_dir 本身（兼容直接指到含 chXXX.md 的目录）。"""
    d = os.path.join(book_dir, "chapters")
    return d if os.path.isdir(d) else book_dir


def list_chapter_files(book_dir: str) -> list:
    """列出正文章节文件名（chNNN.md），按章号升序。
    book_dir 可以是书目录（自动找 chapters/ 子目录），也可以直接是含 chNNN.md 的目录。
    目录不存在/没有章节时返回空列表，不抛异常。"""
    d = chapter_dir(book_dir)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted((f for f in names if CH_RE.match(f)), key=chapter_no_of)
