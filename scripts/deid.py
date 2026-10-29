#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""case-rewriter :: deid.py —— 病例文本脱敏与时间平移（零依赖）

用法
----
    python deid.py case.md                      # 只出报告，不改文件
    python deid.py case.md -o case.deid.md      # 写出脱敏结果
    python deid.py case.md -o out.md --shift-days 21
    python deid.py case.md --check              # 有残留 PII 则退出码 1（可挂 CI）
    python deid.py case.md -o out.md --map map.json --names 张三,李四

退出码
------
    0  完成（--check 模式下表示未发现可识别信息）
    1  --check 模式下发现可识别信息
    2  文件或参数错误
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

# ---------------------------------------------------------------- 识别规则

RE_IDCARD = re.compile(
    r"(?<!\d)([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])(?!\d)"
)
RE_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
RE_TEL = re.compile(r"(?<!\d)(0\d{2,3}[-\s]?\d{7,8})(?!\d)")
RE_RECORD = re.compile(
    r"((?:住院号|门诊号|病历号|病案号|就诊号|检查号|检验号|登记号|影像号|病理号|床号)\s*[:：]?\s*)"
    r"([A-Za-z0-9\-]{2,})"
)
# 排除常见动词，避免把"就诊于……"整段吞进机构名
RE_HOSPITAL = re.compile(
    r"[^，。；、\s于在到至来往入转收送由诊治疗住门急]{2,12}(?:医院|卫生院|保健院|医疗中心)"
)
RE_NAME_LABEL = re.compile(r"(姓名\s*[:：]\s*)([\u4e00-\u9fa5]{2,4})")
RE_PATIENT_NAME = re.compile(r"患者\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})(?=[，,。；;、（(\s])")
RE_XMOU = re.compile(
    r"([\u4e00-\u9fa5]某)(?![医院市地县科项种日时年月份级类位名人校镇乡村区])"
)

# 泛指表述，不算可识别信息
GENERIC_HOSPITAL = {
    "医院", "某医院", "三级医院", "二级医院", "一级医院", "三甲医院", "三乙医院",
    "二甲医院", "二乙医院", "综合医院", "专科医院", "社区医院", "中心医院",
    "上级医院", "下级医院", "当地医院", "基层医院", "定点医院", "转诊医院",
    "外院", "本院", "我院", "卫生院", "保健院", "医疗中心",
}

RE_DATE_CN = re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
RE_DATE_SEP = re.compile(r"(?<!\d)((?:19|20)\d{2})([-/.])(\d{1,2})\2(\d{1,2})(?!\d)")
RE_DATE_YM = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月(?!\s*\d+\s*日)")

# 常见姓氏白名单 —— 用它把"患者腹痛，伴恶心"这类误判挡掉
SURNAMES = set(
    "王李张刘陈杨黄赵周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶"
    "程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾"
    "毛郝龚邵万钱严覃武戴莫孔向汤常温康施文牛樊葛邢安齐易乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关"
    "兰焦俞左柳甘祝包宁尚符舒阮柯纪梅童凌毕单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳管柴蒙鲍华喻"
    "祁蒲房滕屈饶解牟艾尤阳时穆农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷晏席卫米柏宗瞿"
    "桂全佟应臧闵苟邬边卞姬师和仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖巩明佘池查麻苑迟邝封边候"
)

NAME_STOPWORDS = {
    "男性", "女性", "本人", "家属", "患儿", "既往", "入院", "主诉", "自诉", "表示", "否认",
    "患者", "诊断", "治疗", "现病", "病史", "反复", "突然", "自觉", "出现", "急诊", "门诊",
    "病程", "神志", "精神", "体温", "血压", "心率", "呼吸", "性别", "年龄", "职业", "民族",
    "婚姻", "住址", "联系", "平素", "体健", "无明", "明显", "无诱", "诱因", "否认", "双侧",
}


def _plausible_name(nm: str) -> bool:
    if not (2 <= len(nm) <= 4):
        return False
    if nm in NAME_STOPWORDS or nm.endswith("某"):
        return False
    return nm[0] in SURNAMES


def _alpha_index(i: int) -> str:
    return chr(ord("A") + i) if i < 26 else f"Z{i}"


NAME_PATTERNS = [(RE_NAME_LABEL, 2), (RE_PATIENT_NAME, 1)]


def find_names(text: str, extra=()):
    """返回文本中疑似人名的列表（按首次出现顺序去重）。"""
    found = []
    for pat, gi in NAME_PATTERNS:
        for m in pat.finditer(text):
            nm = m.group(gi)
            if _plausible_name(nm):
                found.append(nm)
    for nm in extra:
        if nm and nm in text:
            found.append(nm)
    seen, ordered = set(), []
    for nm in found:
        if nm not in seen:
            seen.add(nm)
            ordered.append(nm)
    return ordered


# ---------------------------------------------------------------- 扫描 / 变换

SCAN_RULES = [
    ("身份证号", RE_IDCARD),
    ("手机号", RE_PHONE),
    ("固定电话", RE_TEL),
    ("病历编号", RE_RECORD),
    ("医疗机构", RE_HOSPITAL),
]


def scan(text: str, extra_names=()):
    """只扫描不修改，返回 findings 列表（供 lint_case.py 复用）。"""
    findings = []
    for kind, pat in SCAN_RULES:
        for m in pat.finditer(text):
            raw = m.group(0).strip()
            if kind == "医疗机构" and not _is_specific_hospital(raw):
                continue
            findings.append({"kind": kind, "text": raw, "pos": m.start()})
    for nm in find_names(text, extra_names):
        for m in re.finditer(re.escape(nm), text):
            findings.append({"kind": "姓名", "text": nm, "pos": m.start()})
    for m in RE_XMOU.finditer(text):
        if m.group(1)[0] in SURNAMES:
            findings.append({"kind": "姓名(某)", "text": m.group(1), "pos": m.start()})
    findings.sort(key=lambda f: f["pos"])
    return findings


META_PREFIXES = ["原文", "原", "具体", "上述", "该", "本", "此", "其他", "其余"]
VERB_PREFIXES = ["保留", "具备", "转入", "转至", "建议", "联系", "就近", "前往", "送至", "收入"]


def _is_specific_hospital(raw: str) -> bool:
    """区分"江城市第一人民医院"与"某三级医院""原文医院名"这类泛指表述。"""
    if raw in GENERIC_HOSPITAL or raw.startswith("某"):
        return False
    core = raw
    changed = True
    while changed:
        changed = False
        for p in META_PREFIXES:
            if core.startswith(p) and len(core) > len(p):
                core = core[len(p):]
                changed = True
                break
    for p in VERB_PREFIXES:
        if core.startswith(p) and len(core) > len(p):
            core = core[len(p):]
            break
    return core not in GENERIC_HOSPITAL


def _mask_hospital(m):
    raw = m.group(0)
    if not _is_specific_hospital(raw):
        return raw
    if re.search(r"三甲|三级甲等|三级", raw):
        return "某三级医院"
    if re.search(r"二甲|二级甲等|二级", raw):
        return "某二级医院"
    if re.search(r"一甲|一级", raw):
        return "某一级医院"
    return "某医院"


def _shift_cn(m, days, bad):
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        nd = dt.date(y, mo, d) + dt.timedelta(days=days)
    except ValueError:
        bad.append(m.group(0))
        return m.group(0)
    return f"{nd.year}年{nd.month}月{nd.day}日"


def _shift_sep(m, days, bad):
    y, sep, mo, d = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
    try:
        nd = dt.date(y, mo, d) + dt.timedelta(days=days)
    except ValueError:
        bad.append(m.group(0))
        return m.group(0)
    return f"{nd.year}{sep}{nd.month}{sep}{nd.day}"


def transform(text: str, shift_days: int = 0, extra_names=()):
    """执行脱敏，返回 (新文本, 报告字典, 映射字典)。"""
    report = {
        "姓名": 0, "身份证号": 0, "手机号": 0, "固定电话": 0,
        "病历编号": 0, "医疗机构": 0, "日期平移": 0, "无效日期": 0,
    }
    mapping = {"names": {}, "shift_days": shift_days}
    out = text

    # 1) 姓名 → 患者A / 患者B ...（长名优先，避免子串重复替换）
    names = find_names(out, extra_names)
    for nm in sorted(names, key=len, reverse=True):
        ph = "患者" + _alpha_index(names.index(nm))
        cnt = out.count(nm)
        if cnt:
            out = out.replace(nm, ph)
            report["姓名"] += cnt
            mapping["names"][nm] = ph

    # 2) 证件与联系方式
    out, n = RE_IDCARD.subn("[身份证号]", out)
    report["身份证号"] += n
    out, n = RE_PHONE.subn("[手机号]", out)
    report["手机号"] += n
    out, n = RE_TEL.subn("[固定电话]", out)
    report["固定电话"] += n

    # 3) 病历类编号（保留字段名，抹掉号码）
    def _rec(m):
        return m.group(1) + "[编号]"

    out, n = RE_RECORD.subn(_rec, out)
    report["病历编号"] += n

    # 4) 医疗机构
    hosp_n = sum(1 for m in RE_HOSPITAL.finditer(out) if _is_specific_hospital(m.group(0)))
    if hosp_n:
        out = RE_HOSPITAL.sub(_mask_hospital, out)
        report["医疗机构"] += hosp_n

    # 5) 日期平移
    bad = []
    if shift_days:
        out, n1 = RE_DATE_CN.subn(lambda m: _shift_cn(m, shift_days, bad), out)
        out, n2 = RE_DATE_SEP.subn(lambda m: _shift_sep(m, shift_days, bad), out)
        report["日期平移"] += n1 + n2
    else:
        report["日期平移"] = 0
    report["无效日期"] = len(bad)

    # 6) "张某" → "某"（仅限姓氏开头，避免误伤"于某医院"）
    xmou_n = sum(1 for m in RE_XMOU.finditer(out) if m.group(1)[0] in SURNAMES)
    if xmou_n:
        out = RE_XMOU.sub(
            lambda m: "某" if m.group(1)[0] in SURNAMES else m.group(0), out
        )
        report["姓名"] += xmou_n

    return out, report, mapping


# ---------------------------------------------------------------- CLI

def _print_report(path: str, report: dict, findings=None):
    print(f"case-rewriter deid · {path}")
    print("-" * 52)
    if findings is not None:
        if not findings:
            print("未发现可识别的个人信息。")
        else:
            for f in findings:
                preview = f["text"] if len(f["text"]) <= 24 else f["text"][:24] + "…"
                print(f"  [{f['kind']}] {preview}")
            print(f"  共 {len(findings)} 处")
        return
    total = sum(report.values())
    if total == 0:
        print("未发现可识别的个人信息，未做修改。")
    else:
        for k, v in report.items():
            if v:
                print(f"  {k:<8} {v} 处")
        print(f"  合计     {total} 处")
    print("-" * 52)
    if report.get("医疗机构"):
        print("提示：机构名已统一替换，请确认正文诊疗能力与新机构等级匹配。")
    if report.get("无效日期"):
        print("提示：存在无法解析的日期（如 2 月 30 日），已原样保留，请人工核对。")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="deid.py",
        description="病例文本脱敏与时间平移（零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python deid.py case.md -o out.md --shift-days 21",
    )
    ap.add_argument("file", help="输入病例文件（UTF-8）")
    ap.add_argument("-o", "--out", help="输出文件；不指定则只出报告")
    ap.add_argument("--shift-days", type=int, default=0, help="日期整体平移天数（保持相对间隔）")
    ap.add_argument("--names", default="", help="额外指定人名，逗号分隔，如 张三,李四")
    ap.add_argument("--map", dest="map_path", help="输出姓名映射表（含原始信息，勿提交）")
    ap.add_argument("--check", action="store_true", help="仅检查，发现可识别信息则退出码 1")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args(argv)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"错误：无法读取 {args.file}（{e}）", file=sys.stderr)
        return 2

    extra = [x.strip() for x in args.names.split(",") if x.strip()]

    if args.check:
        findings = scan(text, extra)
        if args.json:
            print(json.dumps({"file": args.file, "findings": findings}, ensure_ascii=False, indent=2))
        else:
            _print_report(args.file, {}, findings)
        return 1 if findings else 0

    new_text, report, mapping = transform(text, args.shift_days, extra)

    if args.map_path:
        try:
            with open(args.map_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"警告：映射表写入失败（{e}）", file=sys.stderr)

    if args.json:
        print(json.dumps({"file": args.file, "report": report, "out": args.out},
                         ensure_ascii=False, indent=2))
    else:
        _print_report(args.file, report)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(new_text)
            print(f"已写出：{args.out}")
        except OSError as e:
            print(f"错误：无法写入 {args.out}（{e}）", file=sys.stderr)
            return 2
    elif not args.json:
        print("（未指定 -o，未落盘。加 -o 输出文件名即可写出。）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
