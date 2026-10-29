# case-rewriter · 病例改写器

> 给一份原始病例 + 一份《病历书写要求》，产出一份**符合该规范**的新病例——附变更清单与规范校验报告。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#)

一个给 AI Agent 用的 Skill（兼容 Claude Skills / 通用 Agent 技能目录格式）。核心不是"换个说法"，而是**把规范文件编译成检查项**，再用脚本把"改写后不合规"这件事拦住。

---

## 为什么需要它

医学院的《病历书写要求》是硬约束：格式一处错就要**整页重写**。而人工把一份病例改成合规大病历，最容易踩的坑是——

- 淋巴结只写"全身浅表淋巴结未触及肿大"，规范要 11 组
- 神经反射漏了 Hoffmann 征
- 三线表数值写成 `2.3`，规范要求小数点后只能是 0 或 5
- 辅助检查写成"血常规示 WBC 升高"，规范要求"检查名（日期，医院）示：结果"
- 主诉写了 24 个字，上限 20
- 入院诊断没加引号、没靠右

这些**全部可以机检**。`spec_lint.py` 就是干这个的——11 类违规实测全部拦住。

---

## 效果对照

输入（`examples/input-case.md`，虚构病例）：

```markdown
## 主诉
转移性右下腹痛 1 天，发热 6 小时。

## 体格检查
T 38.6℃，P 102 次/分……右下腹麦氏点压痛（+）、反跳痛（+）、
肌紧张（+）……Murphy 征阴性……
```

输出（`examples/output-dabingli.md`，按《大病历书写要求》重建）：

```markdown
### 淋巴结
耳前、耳后、枕部、颌下、颈前、颈后、锁骨上、腋窝（尖群、中央群、胸肌群、
肩胛下群、外侧群）、滑车上、腹股沟（上群、下群）、腘窝淋巴结均未触及肿大。

### 心脏
叩诊：心脏相对浊音界如下（三线表居中绘制）

| 右（cm） | 肋间 | 左（cm） |
|---|---|---|
| 2.0 | Ⅱ | 2.5 |
| 2.0 | Ⅲ | 3.5 |
| 3.0 | Ⅳ | 5.0 |
| — | Ⅴ | 7.0 |

注：左锁骨中线距胸骨中线为 8.0 cm。

## 辅助检查
血常规（2024-04-02，某三级医院）示：白细胞 13.4×10⁹/L，中性粒细胞百分比 85.1%……

## 入院诊断
1．"急性化脓性阑尾炎"
2．"局限性腹膜炎"
```

规范校验结果：

```
case-rewriter spec_lint · examples/output-dabingli.md
------------------------------------------------------------
规范校验通过，未发现问题。
------------------------------------------------------------
结果：0 error · 0 warn · 0 info
```

---

## 内置规范

已把《大病历书写要求》（人卫第八版《诊断学》格式）拆成 23 条可执行规则：`references/specs/dabingli.md`

| 分区 | 内容 |
|---|---|
| R01–R07 | 格式要求：蓝黑笔、首行空两格、连续书写、系统回顾不标数字、三线表 |
| R08–R16 | 内容要求：过敏史、首页无空项、三线表数值、淋巴结、神经反射、辅助检查格式、引号、诊断靠右 |
| R17–R23 | 各章节必写要素：主诉、现病史、既往史、个人史、月经生育史、家族史、病例摘要 |
| 考核表 | 病历书写 30 + 体格检查及操作 30 + 问诊 20 + 初步诊断 10 + 处方医嘱 10 |

规范里有 4 处表述歧义，已列在第七节"待确认"表。其中 3 处已按使用者确认锁定：

| 编号 | 歧义 | 确认结果 |
|---|---|---|
| Q1 | "既往史、个人史、婚育史、家族史不另起一行" | **各自起段、段间不留空行** |
| Q2 | 系统回顾与"连续书写"如何共存 | 系统回顾单独成段，其后五项连续 |
| Q3 | 考核表有"处方医嘱 10 分"、模板无对应章节 | **不需要，不补章节**，全文止于"见习医生／带教老师" |

换成别的学校/科室的规范：把新规范按同样格式写进 `references/specs/`，改 `spec_lint.py` 顶部的常量即可。

---

## 抄写提示：写不进文字的要求怎么处理

规范里有一类要求**没法用文字表达**，但违反了直接判不合格：

| 编号 | 要求 | 文字里表达不出来，只能靠提示 |
|---|---|---|
| R01 | 蓝黑笔书写 | 文档看不出来 |
| R02 | 首行空两格、该另起一行的必须另起 | markdown 段落样式 ≠ 手写缩进 |
| R06 | 三线表居中绘制 | 表格居中靠排版，文字说不了 |
| R08 | 过敏史有则红笔 | 颜色不在文本里 |
| R09 | 首页不可出现空项 | 表格填没填满要人看 |
| R13 | 错字斜线划掉、同页不超 3 处 | 修改痕迹在纸上 |
| R16 | 入院诊断靠右 | 对齐方式不在文本里 |
| R21 | 专科情况有则写、没有则不写 | 取舍规则，不是内容 |

处理方式是两层：

1. **集中层**：文档开头一块「抄写须知」，8 条逐条列清做法
2. **内联层**：在对应位置放 `> **抄写提示（Rxx）**：…` 引用块（三线表前、淋巴结前、辅助检查前、摘要前、专科情况前、入院诊断前）

用引用块而不是正文，是因为渲染出来能看见、但一眼能分辨不是病历内容；抄写时不会误抄。

`spec_lint.py` 的 `tips` 检查会核对这 8 条是否都在**提示行内**出现过——不是正文里随便提一句就算。

---

## 安装

```bash
git clone https://github.com/<you>/case-rewriter.git

# 通用 Agent（含 WorkBuddy / Claude Skills 兼容目录）
cp -r case-rewriter ~/.workbuddy-ai/skills/case-rewriter
# 或
cp -r case-rewriter ~/.claude/skills/case-rewriter
```

Windows：

```powershell
Copy-Item -Recurse case-rewriter "$env:USERPROFILE\.workbuddy-ai\skills\case-rewriter"
```

装好后对 Agent 说：**"按这份要求把病例改成大病历"**（附上规范 PDF 和病例），即可触发。

> 不需要 Agent 也能用——脚本是独立的命令行工具，见下方。

---

## 用法

### 交互式（推荐）

```
你：（附上《大病历书写要求》PDF + 一份病例）
    按这个要求把病例改成大病历。

Agent：（读规范 → 抽 R01–R23 → 拆病例 → 列变量映射表 →
       按模板逐项重建 → 跑 spec_lint → 修到 0 error → 交付四件套）
```

Agent 会遵守 `SKILL.md` 的工作流：规范歧义不自己拍板，改写前先列变量映射表，交付必附变更清单与复核提示。

### 命令行

```bash
# 1) 规范符合性校验（核心）
python scripts/spec_lint.py examples/output-dabingli.md

# 2) 通用一致性校验（时间线 / 诊断支撑 / PII）
python scripts/lint_case.py examples/output-case.md --format soap --target 1100

# 3) 脱敏 + 时间平移
python scripts/deid.py examples/input-case.md -o out.md --shift-days 21

# 4) 按配置生成骨架
python scripts/scaffold.py --format soap --config examples/rewrite.yaml -o my-case.md
```

零依赖，Python 3.9+ 标准库即可运行。

---

## 脚本

| 脚本 | 作用 | 关键参数 |
|---|---|---|
| `scripts/spec_lint.py` | **规范符合性校验**（对照 `references/specs/`） | `--json`、`--strict` |
| `scripts/lint_case.py` | 通用一致性校验 | `--format`、`--target`、`--json` |
| `scripts/deid.py` | 脱敏 + 日期平移 | `-o`、`--shift-days`、`--check`、`--map`、`--names` |
| `scripts/scaffold.py` | 按配置生成骨架 | `--format`、`--config`、`-o`、`--force` |

### spec_lint 检查项

| 代号 | 规则 | 内容 | 级别 |
|---|---|---|---|
| `structure` | R02/R03 | 14 个章节齐全 | error |
| `order` | R02 | 章节顺序递增 | error |
| `block_spacing` | R03 | 既往史至家族史段间不留空行 | warn |
| `exam_items` | R05 | 体格检查 20 个必写部位 | error |
| `lymph_nodes` | R11 | 淋巴结 11 组 | warn |
| `reflexes` | R12 | 神经反射 15 项 | error |
| `reflex_phrasing` | R12 | 不得写"……未引出" | error |
| `three_line_table` / `three_line_note` | R06 | 三线表 + 表下注 | error |
| `three_line_values` | R10 | 小数点后只可 0 或 5 | error |
| `systems` / `systems_numbering` | R04 | 8 个系统齐全、不标数字 | error |
| `chief_length` / `chief_duration` / `chief_diagnosis` | R17 | 主诉 ≤20 字、含时长、不写诊断 | warn |
| `hpi_general` | R18 | 现病史一般情况七要素 | warn |
| `time_abbr` | R18 | 不得用 1d/5h 缩写 | error |
| `allergy` | R08 | 必须有过敏史表述 | error |
| `aux_format` | R14 | "检查名（日期，医院）示：结果" | error |
| `summary_length` / `summary_format` | R23 | 摘要 ≤300 字、"主因…入院" | error / warn |
| `diagnosis_numbering` / `diagnosis_quotes` | R15/R16 | 编号、病名加引号 | error |
| `placeholder` | — | 无 `【待填写】` 残留 | error |
| `tips` | R01/R02/R06/R08/R09/R13/R16/R21 | 8 条「抄写提示」齐全 | info |

退出码：`0` 通过（可含警告）、`1` 有 error、`2` 文件或参数错误。

### 负向测试（实测）

| 故意制造的违规 | 是否被拦 |
|---|---|
| 淋巴结漏写"滑车上" | ✅ `lymph_nodes` |
| 神经反射漏写 Hoffmann | ✅ `reflexes` |
| 三线表数值写 `2.3` | ✅ `three_line_values` |
| 三线表缺"注：左锁骨中线……" | ✅ `three_line_note` |
| 系统回顾加数字编号 | ✅ `systems_numbering` |
| 主诉 24 字 | ✅ `chief_length` |
| 辅助检查缺医院和日期 | ✅ `aux_format` |
| 写"病理反射未引出" | ✅ `reflex_phrasing` |
| 现病史用 `1d 前` | ✅ `time_abbr` |
| 入院诊断病名无引号 | ✅ `diagnosis_quotes` |
| 漏"一般状况" | ✅ `exam_items` |
| 婚姻史与月经生育史之间留空行 | ✅ `block_spacing` |
| 删掉"过敏史用红笔"提示 | ✅ `tips` |

---

## 改写矩阵（摘要）

规范决定**格式**，这张表决定**内容能改到什么程度**。

| | 能改 | 不能改 |
|---|---|---|
| **人口学** | 年龄 ±15 岁、性别（无特异性时）、职业、民族 | 跨好发年龄分层；涉及妊娠/妇科时翻性别 |
| **时间轴** | 整体平移、改粒度 | 改相对顺序、跨急性/慢性界限 |
| **数值** | 参考区间内 ±20% 扰动 | 跨越临床决策阈值 |
| **机构** | 换地区、换等级 | 换等级后不同步调整检查可及性 |
| **诊断** | 允许（需重建全部证据链） | 保留原诊断却改掉支撑证据 |
| **阴性体征** | 措辞 | 删除有鉴别意义的那几条 |

完整矩阵与踩坑案例：[`references/rewrite-matrix.md`](references/rewrite-matrix.md)

---

## 目录结构

```
case-rewriter/
├── SKILL.md                      # Agent 主入口：六步工作流 + 规范解析 + 改写矩阵
├── README.md
├── LICENSE                       # MIT
├── CHANGELOG.md
├── references/
│   ├── specs/
│   │   └── dabingli.md           # 大病历书写规范：R01–R23 + 考核表 + 待确认项
│   ├── rewrite-matrix.md         # 改写矩阵完整版 + 失败案例库
│   ├── ethics.md                 # 使用边界与合规要求
│   └── templates/
│       ├── dabingli.md           # 大病历骨架（含三线表、系统回顾）
│       ├── soap.md
│       ├── admission.md
│       └── exam-question.md
├── scripts/
│   ├── spec_lint.py              # 规范符合性校验（核心）
│   ├── lint_case.py              # 通用一致性校验
│   ├── deid.py                   # 脱敏 + 时间平移
│   ├── scaffold.py               # 骨架生成
│   └── _miniyaml.py              # 内置极简 YAML 解析
└── examples/
    ├── input-case.md             # 原始病例（虚构，含 PII 便于演示脱敏）
    ├── output-dabingli.md        # 规范大病历（0 error）
    ├── output-case.md            # SOAP 版
    └── rewrite.yaml              # 改写配置
```

---

## 使用边界

**可以**：教学病例、考核练习、病例报告脱敏、OSCE/SP 脚本、结构化归档。

**不可以**：伪造临床研究数据、篡改真实病历、把改写结果当真实病例投稿或举证、用于骗保。

所有输出都是**改写生成物**，须经带教老师/执业医师审核后方可使用；不构成诊疗依据。详见 [`references/ethics.md`](references/ethics.md)。

示例病例中的人物、机构、编号均为虚构。

---

## 贡献

欢迎 PR。新增规范请同时提供：

1. `references/specs/<规范名>.md`——规则编号 + 待确认项
2. `references/templates/<文体>.md`——骨架
3. `spec_lint.py` 里对应的检查项
4. `examples/` 下一份通过校验的样例

没有样例的规范等于没测过，不会被合并。

Bug 优先报 `spec_lint.py` 的误报/漏报，附触发它的片段（请先脱敏）。

---

## License

[MIT](LICENSE)
