#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""case-rewriter :: spec_lint.py —— 大病历书写规范校验（零依赖）

对照 `references/specs/dabingli.md` 检查 R03–R23 中可机检的条目。

用法
----
    python spec_lint.py 大病历.md
    python spec_lint.py 大病历.md --json
    python spec_lint.py 大病历.md --strict      # warn 也算失败

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

# ---------------------------------------------------------------- 规范常量

# 章节顺序（R02/R03/R04）：位置必须递增
REQUIRED_ORDER = [
    ("主诉", ["主诉"]),
    ("现病史", ["现病史"]),
    ("既往史", ["既往史"]),
    ("系统回顾", ["系统回顾"]),
    ("个人史", ["个人史"]),
    ("婚姻史", ["婚姻史"]),
    ("月经生育史", ["月经生育史", "月经史"]),
    ("婚育史", ["婚育史"]),
    ("家族史", ["家族史"]),
    ("体格检查", ["体格检查"]),
    ("专科情况", ["专科情况"]),
    ("辅助检查", ["辅助检查"]),
    ("病例摘要", ["病例摘要", "病史摘要"]),
    ("入院诊断", ["入院诊断"]),
]

# 体格检查必写项（R05）
EXAM_ITEMS = [
    ("一般状况", r"一般状况"),
    ("皮肤、黏膜", r"皮肤[、，]?\s*黏膜"),
    ("淋巴结", r"淋巴结"),
    ("头颅", r"头颅"),
    ("眼", r"眼\s*[:：]"),
    ("耳", r"耳\s*[:：]"),
    ("鼻", r"鼻\s*[:：]"),
    ("口腔", r"口腔\s*[:：]"),
    ("颈部", r"颈部"),
    ("胸部", r"胸部"),
    ("肺", r"肺\s*[:：]|###\s*肺"),
    ("心脏", r"心脏"),
    ("桡动脉", r"桡动脉"),
    ("周围血管征", r"周围血管征"),
    ("腹部", r"腹部"),
    ("肛门直肠", r"肛门直肠"),
    ("外生殖器", r"外生殖器"),
    ("脊柱", r"脊柱"),
    ("四肢", r"四肢"),
    ("神经系统", r"神经系统"),
]

# R11 淋巴结必须写全
LYMPH_NODES = ["耳前", "耳后", "枕部", "颌下", "颈前", "颈后", "锁骨上", "腋窝", "滑车上", "腹股沟", "腘窝"]
LYMPH_SUBGROUPS = ["尖群", "中央群", "胸肌群", "肩胛下群", "外侧群", "上群", "下群"]

# R12 神经反射必须写全
REFLEXES = [
    "角膜反射", "腹壁反射", "提睾反射",
    "肱二头肌", "肱三头肌", "膝腱", "跟腱",
    "Babinski", "Oppenheim", "Gordon", "Chaddock", "Hoffmann",
    "颈强直", "Kernig", "Brudzinski",
]

# R04 系统回顾 8 个系统
SYSTEMS = [
    "呼吸系统", "循环系统", "消化系统", "泌尿生殖系统",
    "造血系统", "内分泌系统及代谢", "神经精神系统", "肌肉骨骼系统",
]

# R03 段间不留空行的项目（各自起段，但中间不能空行）
BLOCK_LABELS = ["既往史", "个人史", "婚姻史", "月经生育史", "婚育史", "家族史"]

HPI_KEYWORDS = ["神志", "精神", "睡眠", "食欲", "大便", "小便", "体重", "体力"]

DIAGNOSIS_WORDS = ["炎", "癌", "瘤", "梗死", "综合征", "病", "溃疡", "结石", "梗阻", "衰竭", "感染"]

RE_AUX = re.compile(r"（\s*\d{4}-\d{1,2}-\d{1,2}\s*[，,]\s*[^）]+?）\s*示\s*[:：]")
RE_TIME_ABBR = re.compile(r"(?<![A-Za-z])\d+\s*(?:d|h|w|mo|y)(?![A-Za-z])")
RE_SYS_NUM = re.compile(r"^\s*(?:[（(]?\d+[.、)）]|[①②③④⑤⑥⑦⑧⑨⑩])")
RE_NUM = re.compile(r"\d+(?:\.\d+)?")
RE_PLACEHOLDER = re.compile(r"【待填写")
QUOTE_CHARS = "\"“”「」『』"

# 规范里无法用文本表达、必须写成「抄写提示」的条目（缺失即提示补标注）
# 每项：编号 / 说明 / 必须同时出现在同一行提示里的关键词
TIP_RULES = [
    ("R01", "蓝黑笔书写", ["蓝黑笔"]),
    ("R02", "首行空两格", ["首行空两格"]),
    ("R06", "三线表居中绘制", ["三线表"]),
    ("R08", "过敏史有则红笔", ["过敏", "红笔"]),
    ("R09", "首页基本信息不可空项", ["空项"]),
    ("R13", "错字斜线划掉、同页不超 3 处", ["斜线"]),
    ("R16", "入院诊断靠右书写", ["靠右"]),
    ("R21", "专科情况有则写、没有则不写", ["有则写"]),
]


# ---------------------------------------------------------------- 工具

def find_label(text: str, aliases):
    """返回标签首次出现的位置；找不到返回 -1。"""
    best = -1
    for a in aliases:
        i = text.find(a)
        if i != -1 and (best == -1 or i < best):
            best = i
    return best


def slice_between(text: str, start_aliases, end_aliases):
    """截取两个章节之间的正文（按整行边界，避免把标题行切半）。"""
    s = find_label(text, start_aliases)
    if s == -1:
        return ""
    ls = text.rfind("\n", 0, s) + 1
    e = find_label(text[s + 1:], end_aliases)
    if e == -1:
        return text[ls:]
    e_abs = s + 1 + e
    le = text.rfind("\n", 0, e_abs) + 1
    return text[ls:le]


def _label_line_map(lines, labels):
    """找每个标签**出现在行首**的行号（忽略 # 与 ** 装饰），用于判断段间空行。"""
    found = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(">"):
            continue
        s = re.sub(r"^#+\s*", "", s).strip("*").strip()
        for lb in labels:
            if lb not in found and s.startswith(lb):
                found[lb] = i
                break
    return found


def _char_count(text: str) -> int:
    body = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.M)
    body = re.sub(r"^>.*$", "", body, flags=re.M)
    body = re.sub(r"[#*`|>\s\-—–]", "", body)
    return len(body)


# ---------------------------------------------------------------- 检查

def lint(text: str):
    issues = []

    def add(level, code, message):
        issues.append({"level": level, "code": code, "message": message})

    # 抄写提示用引用块书写，结构分析时先剔除，避免提示文字里的章节名干扰定位
    raw = text
    text = re.sub(r"^>.*$", "", text, flags=re.M)

    # R00 占位符残留
    if RE_PLACEHOLDER.search(text):
        add("error", "placeholder", "残留【待填写】占位符，未填写完整")

    # R02/R03/R04 章节齐全 + 顺序
    missing = [name for name, aliases in REQUIRED_ORDER if find_label(text, aliases) == -1]
    if missing:
        add("error", "structure", f"缺少章节：{'、'.join(missing)}")
    positions = [(name, find_label(text, aliases)) for name, aliases in REQUIRED_ORDER]
    positions = [(n, p) for n, p in positions if p != -1]
    for (n1, p1), (n2, p2) in zip(positions, positions[1:]):
        if p2 < p1:
            add("error", "order", f"章节顺序错误：「{n2}」出现在「{n1}」之前")
            break

    # R05 体格检查必写项
    exam = slice_between(text, ["体格检查"], ["专科情况", "辅助检查"])
    if exam:
        miss = [name for name, pat in EXAM_ITEMS if not re.search(pat, exam)]
        if miss:
            add("error", "exam_items", f"体格检查漏写 {len(miss)} 项：{'、'.join(miss)}")

    # R11 淋巴结
    if exam and "淋巴结" in exam:
        lymph = exam[exam.find("淋巴结"):]
        lymph = lymph[:600]
        miss = [n for n in LYMPH_NODES if n not in lymph]
        if miss:
            add("warn", "lymph_nodes", f"淋巴结漏写：{'、'.join(miss)}")
        miss_sub = [n for n in LYMPH_SUBGROUPS if n not in lymph]
        if miss_sub:
            add("info", "lymph_groups", f"腋窝/腹股沟淋巴结分组未写全：{'、'.join(miss_sub)}")

    # R12 神经反射
    if exam and "神经系统" in exam:
        neuro = exam[exam.find("神经系统"):]
        miss = [r for r in REFLEXES if r not in neuro]
        if miss:
            add("error", "reflexes", f"神经反射漏写：{'、'.join(miss)}")

    # R12 禁止"未引出"
    if "未引出" in text:
        add("error", "reflex_phrasing", "出现「未引出」，规范明确不可写「……未引出」")

    # R06 三线表
    if "肋间" not in text:
        add("error", "three_line_table", "未找到心脏叩诊三线表（应含「肋间」列）")
    else:
        if "左锁骨中线距胸骨中线" not in text:
            add("error", "three_line_note", "三线表下方缺少「注：左锁骨中线距胸骨中线……」")

    # R10 三线表数值：小数点后只可为 0 或 5
    for line in text.splitlines():
        if "|" not in line or "肋间" in line or "---" in line:
            continue
        for m in RE_NUM.finditer(line):
            num = m.group(0)
            if "." in num:
                dec = num.split(".")[1]
                if len(dec) != 1 or dec not in ("0", "5"):
                    add("error", "three_line_values",
                        f"三线表数值「{num}」不合规：小数点后只可为 0 或 5（如 2.0、3.5）")
                    break

    # R04 系统回顾：8 系统齐全、不标数字
    sys_text = slice_between(text, ["系统回顾"], ["个人史"])
    if sys_text:
        miss = [s for s in SYSTEMS if s not in sys_text]
        if miss:
            add("error", "systems", f"系统回顾缺系统：{'、'.join(miss)}")
        for line in sys_text.splitlines():
            if line.strip().startswith(">") or line.strip().startswith("#"):
                continue
            if RE_SYS_NUM.match(line):
                add("error", "systems_numbering",
                    f"系统回顾出现数字编号：「{line.strip()[:16]}」，规范要求各系统前不可标数字")
                break

    # R03 段间不留空行：相邻项目之间不得出现空行
    lines = raw.splitlines()
    lmap = _label_line_map(lines, BLOCK_LABELS + ["系统回顾"])
    for a, b in zip(BLOCK_LABELS, BLOCK_LABELS[1:]):
        if a not in lmap or b not in lmap:
            continue
        ia, ib = lmap[a], lmap[b]
        sys_i = lmap.get("系统回顾")
        if sys_i is not None and ia < sys_i < ib:
            continue  # 被系统回顾隔开，不适用 R03
        between = [l for l in lines[ia + 1:ib] if not l.strip().startswith(">")]
        if any(not l.strip() for l in between):
            add("warn", "block_spacing",
                f"「{a}」与「{b}」之间有空行，规范要求各自起段但段间不留空行")

    # R17 主诉
    chief = slice_between(text, ["主诉"], ["现病史"])
    if chief:
        body = re.sub(r"^#+\s*主诉\s*$", "", chief, flags=re.M)
        body = re.sub(r"[#\s]", "", body)
        n = _char_count(body)
        if n > 20:
            add("warn", "chief_length", f"主诉 {n} 字，超过 20 字上限")
        if not re.search(r"\d+(?:余)?\s*(分钟|小时|天|周|月|年|min|h)", body):
            add("warn", "chief_duration", "主诉未写持续时间")
        hit = [w for w in DIAGNOSIS_WORDS if w in body]
        if hit:
            add("warn", "chief_diagnosis", f"主诉疑似含诊断词（{'、'.join(hit)}），主诉只写症状与时间")

    # R18 现病史要素
    hpi = slice_between(text, ["现病史"], ["既往史"])
    if hpi:
        miss = [k for k in HPI_KEYWORDS if k not in hpi]
        if len(miss) >= 3:
            add("warn", "hpi_general", f"现病史一般情况缺项：{'、'.join(miss)}")
        if RE_TIME_ABBR.search(hpi):
            bad = RE_TIME_ABBR.search(hpi).group(0)
            add("error", "time_abbr", f"现病史出现时间英文缩写「{bad}」，必须用文字表述（如「1 天」）")

    # R08 过敏史
    if "过敏" not in text:
        add("error", "allergy", "未写过敏史（无过敏也须写「否认药物过敏史」「否认食物过敏史」）")

    # R14 辅助检查格式
    aux = slice_between(text, ["辅助检查"], ["病例摘要", "病史摘要"])
    if aux:
        lines = [l.strip() for l in aux.splitlines()
                 if l.strip() and not l.strip().startswith(("#", ">", "|", "-", "【"))]
        bad = [l for l in lines if not RE_AUX.search(l)]
        if bad:
            add("error", "aux_format",
                f"辅助检查 {len(bad)} 行不符合格式「检查名（YYYY-MM-DD，医院）示：结果」，"
                f"首行：{bad[0][:28]}")

    # R23 病例摘要
    summary = slice_between(text, ["病例摘要", "病史摘要"], ["入院诊断"])
    if summary:
        n = _char_count(summary)
        if n > 300:
            add("error", "summary_length", f"病例摘要 {n} 字，超过 300 字上限")
        if "主因" not in summary or "入院" not in summary:
            add("warn", "summary_format", "病例摘要未用「主因\"……\"入院」句式")
        if not re.search(r"(女|男)", summary):
            add("warn", "summary_format", "病例摘要未写性别")
        if not re.search(r"\d+\s*岁", summary):
            add("warn", "summary_format", "病例摘要未写年龄")

    # R15 入院诊断：编号 + 引号
    diag = slice_between(text, ["入院诊断"], ["见习医生", "带教老师"])
    if diag:
        rows = [l for l in diag.splitlines()
                if re.match(r"^\s*\d+\s*[.、．]", l.strip())]
        if not rows:
            add("error", "diagnosis_numbering", "入院诊断未按 1. 2. 编号")
        noquote = [r for r in rows if not any(q in r for q in QUOTE_CHARS)]
        if noquote:
            add("error", "diagnosis_quotes",
                f"入院诊断病名未加引号：{noquote[0].strip()[:24]}（规范要求病名、诊断名带引号）")

    # 抄写提示齐全性：无法用文本表达的规范必须以引用块提示标注出来
    tip_lines = [l for l in raw.splitlines() if l.strip().startswith(">")]
    missing_tips = [
        (code, desc) for code, desc, keys in TIP_RULES
        if not any(all(k in l for k in keys) for l in tip_lines)
    ]
    if missing_tips:
        detail = "；".join(f"{c} {d}" for c, d in missing_tips)
        add("info", "tips", f"缺少 {len(missing_tips)} 条抄写提示：{detail}")

    return {
        "issues": issues,
        "summary": {
            "error": sum(1 for i in issues if i["level"] == "error"),
            "warn": sum(1 for i in issues if i["level"] == "warn"),
            "info": sum(1 for i in issues if i["level"] == "info"),
        },
    }


LEVEL_TAG = {"error": "[ERROR]", "warn": "[WARN ]", "info": "[INFO ]"}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="spec_lint.py",
        description="大病历书写规范校验（对照 references/specs/dabingli.md）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python spec_lint.py examples/output-dabingli.md",
    )
    ap.add_argument("file", help="待校验的大病历文件（UTF-8）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--strict", action="store_true", help="把 warn 也视为失败")
    args = ap.parse_args(argv)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"错误：无法读取 {args.file}（{e}）", file=sys.stderr)
        return 2

    result = lint(text)

    if args.json:
        print(json.dumps({"file": args.file, **result}, ensure_ascii=False, indent=2))
    else:
        s = result["summary"]
        print(f"case-rewriter spec_lint · {args.file}")
        print("-" * 60)
        if not result["issues"]:
            print("规范校验通过，未发现问题。")
        for i in result["issues"]:
            print(f"{LEVEL_TAG[i['level']]} {i['code']:<20} {i['message']}")
        print("-" * 60)
        print(f"结果：{s['error']} error · {s['warn']} warn · {s['info']} info")

    if result["summary"]["error"]:
        return 1
    if args.strict and result["summary"]["warn"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
