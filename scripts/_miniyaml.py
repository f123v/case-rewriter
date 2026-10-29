#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 YAML 子集解析器（零依赖）。

只覆盖本 skill 配置文件所需的语法：
  - 注释 `#`
  - `key: value` 映射（按缩进嵌套）
  - `- item` 序列
  - 行内列表 `[a, b]`
  - 引号字符串、true/false、整数、浮点、null

若环境中已安装 PyYAML，则优先使用 PyYAML（行为是它的超集）。
"""
from __future__ import annotations

__all__ = ["load", "loads", "loads_mini"]


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out)


def _tokenize(text: str):
    toks = []
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        toks.append((indent, line.strip()))
    return toks


def _scalar(s: str):
    if s == "":
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [] if not inner else [_scalar(x.strip()) for x in inner.split(",")]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse(toks, i: int, indent: int):
    if i >= len(toks):
        return None, i

    is_seq = toks[i][1] == "-" or toks[i][1].startswith("- ")
    if is_seq:
        seq = []
        while i < len(toks) and toks[i][0] == indent and (
            toks[i][1] == "-" or toks[i][1].startswith("- ")
        ):
            body = toks[i][1][1:].strip()
            i += 1
            if body == "":
                if i < len(toks) and toks[i][0] > indent:
                    val, i = _parse(toks, i, toks[i][0])
                else:
                    val = None
                seq.append(val)
            elif ":" in body and not body.startswith(("[", "{", '"', "'")):
                k, _, v = body.partition(":")
                item = {k.strip(): _scalar(v.strip())}
                if i < len(toks) and toks[i][0] > indent:
                    more, i = _parse(toks, i, toks[i][0])
                    if isinstance(more, dict):
                        item.update(more)
                seq.append(item)
            else:
                seq.append(_scalar(body))
        return seq, i

    mapping = {}
    while i < len(toks) and toks[i][0] == indent:
        key, sep, rest = toks[i][1].partition(":")
        if not sep:
            i += 1
            continue
        key, rest = key.strip(), rest.strip()
        i += 1
        if rest == "":
            if i < len(toks) and toks[i][0] > indent:
                val, i = _parse(toks, i, toks[i][0])
            else:
                val = None
        else:
            val = _scalar(rest)
        mapping[key] = val
    return mapping, i


def loads_mini(text: str):
    """强制使用内置解析器（便于测试与确定性输出）。"""
    toks = _tokenize(text)
    if not toks:
        return {}
    val, _ = _parse(toks, 0, toks[0][0])
    return {} if val is None else val


def loads(text: str):
    try:
        import yaml  # type: ignore
    except ImportError:
        return loads_mini(text)
    return yaml.safe_load(text) or {}


def load(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return loads(f.read())
