---
name: cninfo-annual-reports
description: Use when downloading annual reports, semi-annual reports, or quarterly reports from cninfo (巨潮资讯网) for a Chinese A-share listed company — user mentions 下载年报/半年报/季报/财报, 巨潮, cninfo, wants all historical annual reports of 某公司, or asks to batch fetch 定期报告 for 000792/600519/any A-share ticker. Triggers on company name OR stock code.
---

# 巨潮资讯网年报下载 Skill

## Overview

根据**公司名**或**股票代码**从巨潮资讯网（cninfo.com.cn）批量下载历年年报/半年报/季报。

底层是同目录下的 `fetch_reports.py`，已封装好三个 cninfo 接口（搜索/公告/PDF）的所有细节。

## When to Use

- 用户说"帮我下载 XX 的全部年报"
- 用户给一个 A 股公司名（中文）或代码（000xxx / 002xxx / 300xxx / 600xxx / 688xxx）想取财报
- 用户已有某公司年报 PDF，要补历史年份
- 需要列出某公司所有定期报告（不下载）

## When NOT to Use

- 港股/美股/新三板 — cninfo 只覆盖 A 股
- 招股说明书/募集说明书/临时公告 — 当前只支持四类定期报告；若需扩展，加 category 到 `fetch_reports.py:CATEGORY_MAP`
- 已知 adjunctUrl 直接下单一篇 — 直接 `curl http://static.cninfo.com.cn/<adjunctUrl>`

## Quick Start

```bash
# 默认下载全部年报到 <cwd>/年报/<公司名>年报/
# (cwd = Claude Code 启动目录，由 os.getcwd() 决定)
python C:/Users/Xulu/.claude/skills/cninfo-annual-reports/fetch_reports.py 盐湖股份

# 全部定期报告（年报+半年报+一季+三季）
python C:/Users/Xulu/.claude/skills/cninfo-annual-reports/fetch_reports.py 盐湖股份 全部

# 只下载 2020 年及以后
python C:/Users/Xulu/.claude/skills/cninfo-annual-reports/fetch_reports.py 盐湖股份 年报 --since 2020

# 只列出，不下载（dry run）— 也会显示本地已下载增量统计
python C:/Users/Xulu/.claude/skills/cninfo-annual-reports/fetch_reports.py 贵州茅台 --list-only
```

完整参数：`python .../fetch_reports.py --help`

## Incremental Download (增量下载)

**默认行为**：每次运行前先扫描本地目录，识别已下载的 `(年份, 报告类型)` 组合，只下载缺失部分。

- 兼容多种文件名格式：`盐湖股份_2023年年度报告.pdf`、`盐湖股份_2023年年度报告.PDF`、`盐湖股份2023年年报.pdf` 都能识别
- 兼容报告类型别名：年度报告=年报、半年度报告=半年报、第一季度报告=一季报、第三季度报告=三季报
- 输出会显示「本地已下载 N 份」+「远程 N - 本地 M = 待下载 K 份」
- 完全没增量时直接打印 `✅ 本地已是最新，无需下载`

## How It Works (4-Step Pipeline)

1. **公司名 → 股票代码 + orgId**
   - `POST http://www.cninfo.com.cn/new/information/topSearch/query`
   - **orgId 不能自己拼**，必须从搜索接口取（深市 `gssz0000792`，沪市 `gssh0600519`，科创板/创业板有不规则 orgId）
2. **代码 + category → 公告列表**
   - `POST http://www.cninfo.com.cn/new/hisAnnouncement/query`
   - category 字典：年报=`category_ndbg_szsh`，半年报=`category_bndbg_szsh`，一季报=`category_yjdbg_szsh`，三季报=`category_sjdbg_szsh`
   - 自动翻页 + 按 `adjunctUrl` 去重（cninfo 偶尔返回重复记录）
3. **本地扫描（增量）**
   - `scan_existing(save_dir)` 用正则识别文件名里的 `(年份, 类型)`
   - 已存在的从待下载列表中剔除
4. **PDF 下载**
   - `GET http://static.cninfo.com.cn/<adjunctUrl>`
   - 按 `{公司}_{年份}年{类型}.pdf` 命名

## Common Pitfalls（已处理，但需要知道）

| 坑 | 处理方式 |
|---|---|
| Windows GBK 终端不支持 emoji/中文 | 脚本顶部 `sys.stdout.reconfigure(encoding="utf-8")`；调用时也加 `PYTHONIOENCODING=utf-8` 更稳 |
| cninfo 返回重复公告条目 | 按 `adjunctUrl` 去重 |
| 标题里混了「摘要」「英文版」「已取消」 | `EXCLUDE_KEYWORDS` 过滤 |
| 公司有多条 A 股匹配（如吸收合并遗留） | 脚本进入交互选择；非交互调用会默认取第 0 条 |
| 沪 vs 深 column 必须正确 | `guess_column()` 按代码前缀判断（6 字头=sse，其余=szse） |
| 大文件 PDF（如盐湖 2025 = 25MB） | 下载 timeout=120s，stream 模式 |

## 反爬说明

cninfo 极宽松：无 UA / Referer / Cookie 要求。脚本仍带 UA + 1 秒间隔，避免被风控。如批量抓多家公司，建议公司间隔 2-3 秒。

## Implementation Reference

- 主脚本：`fetch_reports.py`（同目录）
- 接口调研原始记录（URL/参数/JSON 样例）：见 `fetch_reports.py` 注释 + 本 SKILL.md "How It Works" 段
- 修改/扩展：
  - 加新报告类型 → 编辑 `CATEGORY_MAP`
  - 改默认输出目录 → 编辑 `DEFAULT_OUTPUT_ROOT`
  - 改文件名规则 → 编辑 `build_filename()`
