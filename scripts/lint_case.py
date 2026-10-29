#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""case-rewriter :: lint_case.py —— 病例一致性校验（零依赖）

检查项
------
    structure         文体必填章节是否齐全              error
    placeholder       是否残留【待填写】/TODO/XXX        error
    pii               是否残留可识别个人信息             error
    chief_complaint   主诉时长是否与现病史一致           warn
    timeline          现病史时间线是否单调不倒序         warn
    diagnosis_support 诊断能否在体征/检查中找到支撑      warn
    length            字数是否落在目标 ±20%              warn
    judgement         是否含评价性/追责性表述            warn
    absolute_date     是否残留未平移的绝对日期           info

用法
----
    python lint_case.py case.md --format soap --target 900
    python lint_case.py case.md --json

退出码
------
    0  通过（可含警告）
    1  存在 error
    2  文件或参数错误
"""
from __future__ import annotations

import argparse
import json
import re
import sys

try:
    from deid import RE_DATE_CN, RE_DATE_SEP, RE_DATE_YM, scan
except ImportError:  # 作为包被导入时
    from .deid import RE_DATE_CN, RE_DATE_SEP, RE_DATE_YM, scan  # type: ignore

# ---------------------------------------------------------------- 文体预设

PRESETS = {
    "soap": [
        ("主诉", ["主诉"]),
        ("现病史", ["现病史"]),
        ("体格检查", ["体格检查", "查体", "专科检查"]),
        ("辅助检查", ["辅助检查", "实验室检查", "检查结果", "影像"]),
        ("诊断", ["诊断"]),
        ("计划", ["计划", "处理", "治疗方案", "诊疗计划"]),
    ],
    "admission": [
        ("主诉", ["主诉"]),
        ("现病史", ["现病史"]),
        ("既往史", ["既往史"]),
        ("体格检查", ["体格检查", "专科检查"]),
        ("辅助检查", ["辅助检查"]),
        ("初步诊断", ["初步诊断", "诊断"]),
        ("诊疗计划", ["诊疗计划", "计划"]),
    ],
    "exam-question": [
        ("题干", ["题干"]),
        ("问题", ["问题"]),
        ("参考答案", ["参考答案", "答案"]),
    ],
}

UNIT_HOURS = {"分钟": 1 / 60, "小时": 1, "天": 24, "周": 24 * 7, "月": 24 * 30, "年": 24 * 365}
RE_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(分钟|小时|天|周|月|年)")
RE_DURATION_AGO = re.compile(r"(\d+(?:\.\d+)?)\s*(分钟|小时|天|周|月|年)\s*前")

QUALIFIERS = [
    "急性", "亚急性", "慢性", "复发性", "继发性", "原发性", "双侧", "左侧", "右侧", "单侧",
    "轻度", "中度", "重度", "早期", "晚期", "化脓性", "单纯性", "坏疽性", "穿孔性", "局限性",
    "弥漫性", "活动性", "稳定性", "陈旧性", "难治性", "可疑", "考虑", "符合", "型",
]

SUPPORT_HINTS = {
    "腹膜炎": ["反跳痛", "肌紧张", "板状腹", "腹膜刺激征"],
    "休克": ["血压", "脉压", "意识", "尿量", "乳酸"],
    "贫血": ["Hb", "血红蛋白", "红细胞", "面色苍白"],
    "黄疸": ["胆红素", "巩膜黄染", "皮肤黄染"],
    "梗阻": ["呕吐", "腹胀", "气液平", "排便排气"],
    "糖尿病": ["血糖", "糖化血红蛋白", "多饮", "多尿"],
    "肺炎": ["湿啰音", "斑片影", "实变", "咳嗽", "咳痰"],
    "心力衰竭": ["BNP", "射血分数", "水肿", "颈静脉", "湿啰音"],
    "肾功能不全": ["肌酐", "尿素氮", "尿量", "eGFR"],
    "脓毒症": ["体温", "WBC", "PCT", "CRP", "血压", "乳酸"],
    "阑尾炎": ["麦氏点", "右下腹", "阑尾"],
    "胆囊炎": ["Murphy", "右上腹", "胆囊"],
    "肠梗阻": ["气液平", "肠鸣音", "腹胀", "排便排气"],
    "心肌梗死": ["肌钙蛋白", "ST 段", "ST段", "胸痛", "心电图"],
}

JUDGEMENT_WORDS = [
    "处理不当", "延误治疗", "延误了", "误诊为", "医疗差错", "医疗事故",
    "不负责任", "拒诊", "推诿", "不规范操作", "违反操作规程",
]
PLACEHOLDER_MARKS = ["【待填写", "【待补充", "TODO", "XXX", "xxxx", "待补充", "占位"]


# ---------------------------------------------------------------- 解析

# 这些章节是交付附录，不计入正文字数
EXCLUDE_TITLES = ["变更清单", "复核", "说明", "附录", "改写记录", "自检"]


def split_sections(text: str):
    """返回 [{level, title, body, start, end}]，body 到下一个任意级别标题为止。"""
    lines = text.splitlines()
    heads = []
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            heads.append((idx, len(m.group(1)), m.group(2).strip()))
    sections = []
    for i, (idx, level, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(lines)
        sections.append({
            "level": level,
            "title": title,
            "body": "\n".join(lines[idx + 1:end]).strip(),
            "start": idx,
            "end": end,
        })
    return sections


def get_section(sections, aliases):
    """按别名优先级查找章节正文（别名越靠前优先级越高）。"""
    for a in aliases:
        for s in sections:
            if a in s["title"]:
                return s["body"]
    return ""


def has_section(sections, aliases) -> bool:
    """只判断章节标题是否存在（标题下直接跟子标题时 body 为空，不能当缺失）。"""
    for a in aliases:
        for s in sections:
            if a in s["title"]:
                return True
    return False


def _strip_qualifiers(term: str) -> str:
    term = re.sub(r"^\d+", "", term.strip())
    changed = True
    while changed and term:
        changed = False
        for q in QUALIFIERS:
            if term.startswith(q) and len(term) > len(q):
                term = term[len(q):]
                changed = True
                break
    return term


def _strip_excluded(text: str, sections) -> str:
    """去掉附录类章节（变更清单、复核提示等），只留病例正文。"""
    lines = text.splitlines()
    drop = set()
    for s in sections:
        if any(w in s["title"] for w in EXCLUDE_TITLES):
            end = len(lines)
            for t in sections:
                if t["start"] > s["start"] and t["level"] <= s["level"]:
                    end = t["start"]
                    break
            drop.update(range(s["start"], end))
    return "\n".join(line for i, line in enumerate(lines) if i not in drop)


def _char_count(text: str) -> int:
    body = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.M)
    body = re.sub(r"^\s*[-*|>]\s*", "", body, flags=re.M)
    body = re.sub(r"[#*`|>\s\-—–]", "", body)
    return len(body)


def _fmt_hours(h: float) -> str:
    if h < 1:
        return f"{h * 60:.0f} 分钟"
    if h < 48:
        return f"{h:.0f} 小时"
    return f"{h / 24:.0f} 天"


# ---------------------------------------------------------------- 检查

def lint(text: str, fmt: str | None = None, target: int | None = None):
    issues = []

    def add(level, code, message):
        issues.append({"level": level, "code": code, "message": message})

    sections = split_sections(text)

    # 1) 结构
    if not fmt:
        fmt = "soap"
        for name, preset in PRESETS.items():
            if all(get_section(sections, aliases) for _, aliases in preset):
                fmt = name
                break
    preset = PRESETS.get(fmt)
    if not preset:
        add("error", "structure", f"未知文体：{fmt}（可选 {', '.join(PRESETS)}）")
        preset = []
    missing = [label for label, aliases in preset if not has_section(sections, aliases)]
    if missing:
        add("error", "structure", f"缺少章节：{'、'.join(missing)}")

    # 2) 占位符残留
    for mark in PLACEHOLDER_MARKS:
        if mark in text:
            add("error", "placeholder", f"残留未填写内容：{mark}")
            break

    # 3) PII
    findings = scan(text)
    if findings:
        kinds = sorted({f["kind"] for f in findings})
        add("error", "pii", f"残留可识别信息 {len(findings)} 处（{'、'.join(kinds)}）")

    # 4) 主诉一致性
    chief = get_section(sections, ["主诉"])
    hpi = get_section(sections, ["现病史"])
    if chief and hpi:
        chief_durs = {(m.group(1), m.group(2)) for m in RE_DURATION.finditer(chief)}
        if not chief_durs:
            add("warn", "chief_complaint", "主诉中未识别到病程时长（应含「X 天/小时」）")
        for num, unit in sorted(chief_durs):
            if not re.search(rf"{re.escape(num)}\s*{unit}", hpi):
                add("warn", "chief_complaint",
                    f"主诉时长「{num} {unit}」未在现病史中出现，二者可能不一致")
        if re.search(r"(急性|慢性|阑尾炎|胆囊炎|肺炎|梗死|肿瘤|癌|综合征)", chief):
            add("warn", "chief_complaint", "主诉中疑似出现诊断名，主诉应只描述症状与时长")

    # 5) 时间线单调
    if hpi:
        durs = [(float(m.group(1)) * UNIT_HOURS[m.group(2)], m.group(0))
                for m in RE_DURATION_AGO.finditer(hpi)]
        for (prev_h, prev_s), (cur_h, cur_s) in zip(durs, durs[1:]):
            if cur_h > prev_h + 1e-9:
                add("warn", "timeline",
                    f"时间线疑似倒序：「{prev_s}」→「{cur_s}」（应随时间推进而递减）")
                break

    # 6) 诊断支撑
    diag = get_section(sections, ["初步诊断", "诊断", "评估"])
    support = " ".join([
        get_section(sections, ["体格检查", "查体", "专科检查"]),
        get_section(sections, ["辅助检查", "实验室检查", "检查结果", "影像"]),
        hpi,
    ])
    if diag and support:
        for raw in re.split(r"[；;、，,。\n]", diag):
            raw = re.sub(r"^\s*\d+[.、)）]\s*", "", raw).strip(" -　")
            if not raw or len(raw) < 2:
                continue
            core = _strip_qualifiers(raw)
            core = re.split(r"伴|并|合并", core)[0].strip()
            if not core or len(core) < 2:
                continue
            if core in support:
                continue
            hints = SUPPORT_HINTS.get(core, [])
            if any(h in support for h in hints):
                continue
            add("warn", "diagnosis_support",
                f"诊断「{raw}」在体征/检查中未找到支撑，请人工确认")

    # 7) 诊断依据是否空泛
    evidence = get_section(sections, ["诊断依据"])
    if evidence and _char_count(evidence) < 20:
        add("warn", "evidence", "诊断依据过于简略（不足 20 字），应逐条对应症状/体征/检查")

    # 8) 字数（只统计病例正文，附录不计）
    chars = _char_count(_strip_excluded(text, sections))
    if target:
        lo, hi = int(target * 0.8), int(target * 1.2)
        if not (lo <= chars <= hi):
            add("warn", "length", f"字数 {chars}，超出目标 {target} 的允许区间 {lo}–{hi}")

    # 9) 追责性表述
    for w in JUDGEMENT_WORDS:
        if w in text:
            add("warn", "judgement", f"含评价性/追责性表述：「{w}」，建议改为客观描述")

    # 10) 绝对日期
    dates = []
    for pat in (RE_DATE_CN, RE_DATE_SEP):
        dates += [m.group(0) for m in pat.finditer(text)]
    dates += [m.group(0) for m in RE_DATE_YM.finditer(text)]
    if dates:
        add("info", "absolute_date", f"含 {len(dates)} 处绝对日期（首处：{dates[0]}），建议时间平移")

    return {
        "format": fmt,
        "chars": chars,
        "target": target,
        "issues": issues,
        "summary": {
            "error": sum(1 for i in issues if i["level"] == "error"),
            "warn": sum(1 for i in issues if i["level"] == "warn"),
            "info": sum(1 for i in issues if i["level"] == "info"),
        },
    }


# ---------------------------------------------------------------- CLI

LEVEL_TAG = {"error": "[ERROR]", "warn": "[WARN ]", "info": "[INFO ]"}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lint_case.py",
        description="病例一致性校验（结构 / 时间线 / 诊断支撑 / PII / 字数）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python lint_case.py case.md --format soap --target 900",
    )
    ap.add_argument("file", help="待校验的病例文件（UTF-8）")
    ap.add_argument("--format", choices=sorted(PRESETS), help="文体；不指定则自动识别")
    ap.add_argument("--target", type=int, help="目标字数（允许 ±20%）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--strict", action="store_true", help="把 warn 也视为失败")
    args = ap.parse_args(argv)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"错误：无法读取 {args.file}（{e}）", file=sys.stderr)
        return 2

    result = lint(text, args.format, args.target)

    if args.json:
        print(json.dumps({"file": args.file, **result}, ensure_ascii=False, indent=2))
    else:
        s = result["summary"]
        target_note = ""
        if args.target:
            target_note = (f" · 目标 {args.target} "
                           f"（{int(args.target * 0.8)}–{int(args.target * 1.2)}）")
        print(f"case-rewriter lint · {args.file}")
        print(f"文体 {result['format']} · 字数 {result['chars']}{target_note}")
        print("-" * 56)
        if not result["issues"]:
            print("未发现问题。")
        for i in result["issues"]:
            print(f"{LEVEL_TAG[i['level']]} {i['code']:<18} {i['message']}")
        print("-" * 56)
        print(f"结果：{s['error']} error · {s['warn']} warn · {s['info']} info")

    if result["summary"]["error"]:
        return 1
    if args.strict and result["summary"]["warn"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
