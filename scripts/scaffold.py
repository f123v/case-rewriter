#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""case-rewriter :: scaffold.py —— 按改写配置生成文体骨架（零依赖）

用法
----
    python scaffold.py --format soap -o my-case.md
    python scaffold.py --format soap --config examples/rewrite.yaml -o my-case.md

生成后需要填写全部 `【待填写】`，再用 lint_case.py 校验。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR.parent / "references" / "templates"

FORMATS = {
    "soap": "soap.md",
    "admission": "admission.md",
    "exam-question": "exam-question.md",
}

HEADING_ALIASES = {
    "soap": ["基本信息"],
    "admission": ["一般项目"],
    "exam-question": [],
}


def _replace_section_body(text: str, aliases, new_body: str) -> str:
    """把命中 aliases 的标题下的内容整体替换为 new_body。"""
    lines = text.splitlines()
    heads = []
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            heads.append((idx, m.group(2).strip()))
    for i, (idx, title) in enumerate(heads):
        if any(a in title for a in aliases):
            end = heads[i + 1][0] if i + 1 < len(heads) else len(lines)
            return "\n".join(lines[:idx + 1] + ["", new_body, ""] + lines[end:])
    return text


def _basic_block(fmt: str, cfg: dict) -> str:
    ident = cfg.get("identity") or {}
    code = ident.get("patient_code") or "患者A"
    sex = ident.get("sex") or "【待填写】"
    age = ident.get("age")
    age_s = f"{age} 岁" if age not in (None, "") else "【待填写】"
    occ = ident.get("occupation") or "【待填写】"
    inst = cfg.get("institution") or {}
    level = inst.get("level") or ""
    region = inst.get("region") or ""

    if fmt == "soap":
        return "\n".join([
            f"- 患者代号：{code}",
            f"- 性别：{sex}　年龄：{age_s}",
            f"- 职业：{occ}",
            "- 就诊时间：【待填写：相对时间或平移后日期，不写真实日期】",
            "- 就诊科室：【待填写】",
            "- 就诊方式：【待填写：步行 / 轮椅 / 平车 / 转诊】",
        ])

    if fmt == "admission":
        parts = [f"患者代号 {code}，{sex}，{age_s}"]
        if occ != "【待填写】":
            parts.append(f"职业 {occ}")
        if level:
            parts.append(f"就诊于某{level}医院")
        elif region:
            parts.append(f"就诊于{region}某医院")
        parts.append("入院时间【待填写：相对时间或平移后日期】")
        parts.append("病史陈述者【待填写】及可靠程度【待填写】")
        return "，".join(parts) + "。"

    return ""


def _print_plan(cfg: dict, fmt: str, out: Path):
    meta = cfg.get("meta") or {}
    ident = cfg.get("identity") or {}
    tl = cfg.get("timeline") or {}
    inst = cfg.get("institution") or {}
    lab = cfg.get("lab") or {}
    clin = cfg.get("clinical") or {}

    print("改写要求")
    print("-" * 44)
    print(f"  文体      {meta.get('format') or fmt}")
    if meta.get("target_length"):
        print(f"  目标字数  {meta['target_length']}")
    who = " · ".join(str(x) for x in [ident.get("age"), ident.get("sex"),
                                      ident.get("occupation")] if x)
    if who:
        print(f"  人物      {who}")
    if tl.get("mode") == "shift":
        d = tl.get("delta_days", 0)
        print(f"  时间轴    整体平移 {'+' if d >= 0 else ''}{d} 天（相对间隔不变）")
    if inst.get("level") or inst.get("region"):
        print(f"  机构      {inst.get('level') or ''} {inst.get('region') or ''}".rstrip())
    if lab.get("mode") == "jitter":
        print(f"  数值      参考区间内扰动 ≤{lab.get('max_delta_pct', 20)}%")
    if clin.get("diagnosis"):
        print(f"  诊断      {clin['diagnosis']}")
    print("-" * 44)
    print(f"已生成：{out}")
    print(f"下一步：填写全部【待填写】→ python scripts/lint_case.py {out.name} "
          f"--format {fmt}" + (f" --target {meta['target_length']}" if meta.get("target_length") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="scaffold.py",
        description="按改写配置生成病例骨架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python scaffold.py --format soap --config examples/rewrite.yaml -o my-case.md",
    )
    ap.add_argument("--format", required=True, choices=sorted(FORMATS), help="文体")
    ap.add_argument("--config", help="改写配置（YAML/JSON），用于预填基本信息")
    ap.add_argument("-o", "--out", required=True, help="输出文件")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    args = ap.parse_args(argv)

    tpl = TEMPLATE_DIR / FORMATS[args.format]
    if not tpl.exists():
        print(f"错误：找不到模板 {tpl}", file=sys.stderr)
        return 2

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"错误：{out} 已存在，加 --force 覆盖", file=sys.stderr)
        return 2

    text = tpl.read_text(encoding="utf-8")
    # 去掉模板自身的标题与用法说明，从第一个二级标题开始
    tpl_lines = text.splitlines()
    for i, line in enumerate(tpl_lines):
        if re.match(r"^##\s+", line):
            text = "\n".join(tpl_lines[i:])
            break
    cfg = {}
    if args.config:
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            import _miniyaml
            cfg = _miniyaml.load(args.config)
        except Exception as e:  # noqa: BLE001
            print(f"错误：配置读取失败（{e}）", file=sys.stderr)
            return 2
        aliases = HEADING_ALIASES.get(args.format) or []
        if aliases:
            block = _basic_block(args.format, cfg)
            if block:
                text = _replace_section_body(text, aliases, block)

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"错误：无法写入 {out}（{e}）", file=sys.stderr)
        return 2

    if cfg:
        _print_plan(cfg, args.format, out)
    else:
        print(f"已生成：{out}（未指定 --config，基本信息保留占位符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
