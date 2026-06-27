---
name: financial-metrics
description: Use when computing financial metrics from a Chinese A-share company's annual reports (PDFs in D:\workspace\年报\<公司名>年报\ or any specified dir) — user mentions 杜邦分析, 三因子, 五因子, Z-score, Altman, ROE decomposition, 财务指标, 算下 XX 公司的杜邦/Z值, or wants to compute profitability/leverage/efficiency ratios from 年报. Triggers on company name + financial-analysis intent.
---

# 财务指标计算 Skill

## Overview

从公司年报 PDF 批量计算三种指标：
- **杜邦三因子**: ROE = 销售净利率 × 总资产周转率 × 权益乘数
- **杜邦五因子**: ROE = 税务负担 × 利息负担 × EBIT 利润率 × 总资产周转率 × 权益乘数
- **Altman Z-Score** (账面权益版) + **Z'-Score** (1983 修订·4 因子·无市值)

底层是同目录下的 `financial_metrics.py`。

## When to Use

- 用户说"算下 XX 的杜邦分析"、"XX 的 Z-score"、"测下 XX 财务健康度"
- 已用 cninfo-annual-reports skill 下载某公司年报，想做指标分析
- 用户给公司名（年报已在 `D:\workspace\年报\<公司名>年报\`）或显式给 PDF 目录

## When NOT to Use

- 只想要单一指标（如纯 ROE）→ 直接从年报"主要会计数据"页读
- 港股/美股财报 → 中文标签解析失效
- 中报/季报 → PDF 结构与年报不同，可能需调整

## Quick Start

```bash
# 默认从 D:\workspace\年报\<公司名>年报\ 读全部年报
python C:/Users/Xulu/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份

# 仅分析最近 3 年
python C:/Users/Xulu/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份 --latest 3

# 仅分析 2020 年及以后
python C:/Users/Xulu/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份 --since 2020

# 自定义 PDF 目录
python C:/Users/Xulu/.claude/skills/financial-metrics/financial_metrics.py "D:\workspace\年报\贵州茅台年报"

# 不生成 MD 报告（仅终端）
python C:/Users/Xulu/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份 --no-report
```

完整参数：`python .../financial_metrics.py --help`

## Output

- **终端表格**: 原始数据(亿元) + 三因子 + 五因子 + Z-Score，按年份横向展示
- **趋势分析**: 自动生成三段文字
  - 杜邦三因子主因识别（哪个因子相对变化最大、是 ROE 升/降的驱动）
  - 杜邦五因子拆解（税务负担突破100% / EBIT利润率趋势 / 利息负担稳定性）
  - Z-Score 区间判读 + X2 留存收益/X4 杠杆/X5 周转等结构性观察
- **MD 报告**: 默认保存到 PDF 同级目录 `<公司>_财务分析.md`
  - 五节: 原始数据 / 三因子 / 五因子 / Z-Score / 趋势分析

## How It Works (4-Step Pipeline)

1. **定位 PDF**: `D:\workspace\年报\<公司名>年报\` 下按文件名 `\d{4}年` 提取年份，跳过摘要/英文版
2. **报表段定位**: `_find_section_pages(doc, "合并利润表", [...])` 找报表页范围（避免正文干扰）
3. **科目抽取**: `_extract_value()` 用正则在报表段文本里抓 `标签 + 数字 + 数字`（本期/上期）
   - **关键坑**：标签用 lookbehind 排除父级标签（`(?<![动])负债合计` 排除"流动/非流动负债合计"；`(?<![司])所有者权益合计` 排除"归属于母公司所有者权益合计"）
4. **多年合并**: 倒序遍历（最新年报优先），每份年报 N 提供 (本期=N, 上期=N-1) 两份数据。每个年份采用"包含该年份的最新年报版本"（自动处理追溯调整）
5. **指标计算**: `compute_metrics(year, cur, prev)`，用 `(期初+期末)/2` 作平均

## ⚠️ 数据完整性约束（重要）

**只有「有自己的年报」的年份才会被纳入分析。**

原因: 算年份 N 的 ROE/Z-Score 需要 N-1 末资产负债表数据做平均。
- 若 N 年报存在: N-1 末数据可从 N 年报"上期"列取（对照数据，完整可靠）
- 若 N 年报不存在: N 数据只来自 N+1 年报的"上期"对照列，而 N-1 末数据完全没有 → 平均退化为单点期末值，导致周转率/权益乘数/Z 值失真

例如：只有 2023/2024/2025 三份年报时：
- ✅ 分析 2023/2024/2025（每年都用自己年报的"本期"+ 上年对照）
- ❌ 不分析 2022（2022 数据只来自 2023 年报的"上期"列，但 2021 末数据缺失，无法算平均）

脚本运行时会打印排除信息：
```
ℹ️  排除 1 个无独立年报的年份（仅作为上期对照）: 2022
```

## Common Pitfalls（已处理）

| 坑 | 处理方式 |
|---|---|
| Windows GBK 终端不支持中文 | 脚本顶部 `sys.stdout.reconfigure(utf-8)`；调用时加 `PYTHONIOENCODING=utf-8` 更稳 |
| "利润总额"在内控章节先出现 | `_find_section_pages` 限定只在合并利润表段内搜索 |
| "负债合计"被"流动负债合计"截胡 | lookbehind `(?<![动])` 排除 |
| "所有者权益合计"被"归属于母公司所有者权益合计"截胡 | lookbehind `(?<![司])` 排除（注意是"司"字不是"者"字，因子串"公司所有者权益合计"中"司"在前） |
| 最早年份缺期初数据 | `_avg()` 退化为单一值（期末）近似 |
| 同一份数据多版本（追溯调整） | 倒序合并，最新年报优先 |

## Z-Score X4 口径

**默认**: X4 = 所有者权益合计（含少数股东）/ 负债合计 → 账面权益版
**未实现**: 原版 Altman 用市值（需股价）。如需市值版，传 `--price` 参数（待实现，目前未支持）。

## 输出与公司披露 ROE 的差异

- 脚本 ROE 用 `(期初+期末)/2` 算术平均
- 公司披露"加权平均 ROE"按月加权
- 同一控制下企业合并 / 增发等场景两者差异较大（如盐湖 2022 加权 89.47% vs 算术 62%）
- 平常年份差异 < 0.5pp

## Extension Points

- 加新指标 → 编辑 `compute_metrics()` 函数
- 加新科目 → 编辑 `parse_pdf()` 的 `income_fields` / `balance_fields` 字典（注意 lookbehind）
- 改默认目录 → 编辑 `DEFAULT_REPORTS_ROOT`
- 支持市值版 Z-Score → 加 `--price` 参数，从最近年报读股本，乘以股价
