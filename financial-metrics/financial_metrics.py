"""
财务指标计算器 (Financial Metrics Calculator)

支持:
  - 杜邦三因子分解: ROE = 销售净利率 × 总资产周转率 × 权益乘数
  - 杜邦五因子分解: ROE = 税务负担 × 利息负担 × EBIT 利润率 × 总资产周转率 × 权益乘数
  - Altman Z-Score (账面权益版) + Z'-Score (1983 修订·无市值)

用法:
  python financial_metrics.py <公司名或PDF目录> [--since YEAR] [--latest N] [--output FILE]

示例:
  python financial_metrics.py 盐湖股份
  python financial_metrics.py 盐湖股份 --since 2020
  python financial_metrics.py 盐湖股份 --latest 3
  python financial_metrics.py "D:\\workspace\\年报\\贵州茅台年报"

依赖: PyMuPDF (fitz), tabulate  (pip install pymupdf tabulate)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

# Windows GBK 终端兼容
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import fitz  # PyMuPDF

DEFAULT_REPORTS_ROOT = r"D:\workspace\年报"

# 金额正则: 千分位逗号或带小数
NUM = r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d{2,}"


# ===== Step 1: 定位公司年报 PDF =====
def find_pdfs(company_or_dir: str) -> tuple[str, list[tuple[int, str]]]:
    """返回 (company_name, [(year, pdf_path), ...])。"""
    # 如果是目录直接用
    if os.path.isdir(company_or_dir):
        pdf_dir = company_or_dir
        company_name = os.path.basename(pdf_dir.rstrip("\\/")).replace("年报", "")
    else:
        # 默认 D:\workspace\年报\<公司名>年报\
        pdf_dir = os.path.join(DEFAULT_REPORTS_ROOT, f"{company_or_dir}年报")
        company_name = company_or_dir

    if not os.path.isdir(pdf_dir):
        raise SystemExit(f"❌ 目录不存在: {pdf_dir}\n"
                         f"   先用 cninfo-annual-reports skill 下载，或传完整目录路径。")

    pdfs = []
    for name in os.listdir(pdf_dir):
        if not name.lower().endswith(".pdf"):
            continue
        m = re.search(r"(\d{4})\s*年", name)
        if not m:
            continue
        # 跳过摘要/英文版等
        if any(kw in name for kw in ["摘要", "英文版", "已取消", "更正"]):
            continue
        pdfs.append((int(m.group(1)), os.path.join(pdf_dir, name)))

    if not pdfs:
        raise SystemExit(f"❌ 目录中未找到年报 PDF: {pdf_dir}")

    pdfs.sort(key=lambda x: -x[0])  # 倒序: 最新年优先
    return company_name, pdfs


# ===== Step 2: PDF 解析 =====
def _flatten(text: str) -> str:
    """合并空白便于正则匹配。"""
    return re.sub(r"\s+", " ", text)


def _extract_value(text: str, label_pattern: str, count: int = 2) -> list[float]:
    """
    在 text 中找 label_pattern 后紧跟的 count 个金额数字。
    label_pattern 是已编译的正则字符串（可含 lookbehind）。
    label 后允许 0~80 字符的非数字干扰（如单位标注、换行、空格）。
    """
    flat = _flatten(text)
    pat = re.compile(
        label_pattern + r"[^\d-]{0,80}?" + (r"(" + NUM + r")" + r"[^\d-]{0,30}?") * count
    )
    m = pat.search(flat)
    if not m:
        return []
    return [float(v.replace(",", "")) for v in m.groups() if v]


def parse_pdf(pdf_path: str) -> dict[str, list[float]]:
    """
    解析年报 PDF，提取关键科目。
    返回 {科目名: [本期值, 上期值]}（部分科目可能只有本期）。

    实现策略:
      1. 先定位「合并利润表」和「合并资产负债表」的页范围
      2. 只在对应报表的页文本里搜索科目，避免正文中"利润总额"等词的干扰
      3. 归母口径标签缺失时，fallback 到 "净利润" / "所有者权益合计"
         （适用于无少数股东权益的单一主体公司，如芭田股份）
    """
    doc = fitz.open(pdf_path)

    # 找合并利润表和合并资产负债表的页范围
    income_pages = _find_section_pages(
        doc,
        start_marker="合并利润表",
        stop_markers=["母公司利润表", "合并现金流量表", "合并所有者权益变动表"],
    )
    balance_pages = _find_section_pages(
        doc,
        start_marker="合并资产负债表",
        stop_markers=["母公司资产负债表", "合并利润表"],
    )

    income_text = "\n".join(doc[i].get_text() for i in income_pages) if income_pages else ""
    balance_text = "\n".join(doc[i].get_text() for i in balance_pages) if balance_pages else ""
    doc.close()

    # 带 fallback 的取数: 依次尝试 patterns，第一个成功的胜出
    def extract_with_fallback(text: str, patterns: list[str], count: int = 2) -> list[float]:
        for pat in patterns:
            vals = _extract_value(text, pat, count)
            if vals:
                return vals
        return []

    # 利润表科目
    out: dict[str, list[float]] = {}
    out['revenue']           = extract_with_fallback(income_text, [r"营业收入"])
    out['interest_expense']  = extract_with_fallback(income_text, [r"利息费用"])
    out['profit_before_tax'] = extract_with_fallback(income_text, [r"利润总额"])
    out['income_tax']        = extract_with_fallback(income_text, [r"所得税费用"])
    # 优先 "归属于母公司股东的净利润"; 失败则 fallback "净利润（净亏损" (单一主体公司)
    out['net_profit_parent'] = extract_with_fallback(income_text, [
        r"归属于母公司股东的净利润",
        r"净利润（净亏损",
        r"净利润\(净亏损",
    ])
    # 资产负债表科目
    out['current_assets']      = extract_with_fallback(balance_text, [r"流动资产合计"])
    out['current_liabilities'] = extract_with_fallback(balance_text, [r"流动负债合计"])
    out['total_liabilities']   = extract_with_fallback(balance_text, [r"(?<![动])负债合计"])
    out['undistributed_profit'] = extract_with_fallback(balance_text, [r"未分配利润"])
    out['surplus_reserve']     = extract_with_fallback(balance_text, [r"盈余公积"])
    # 优先 "归属于母公司所有者权益合计"; 失败则 fallback "所有者权益合计" (单一主体)
    out['equity_parent'] = extract_with_fallback(balance_text, [
        r"归属于母公司所有者权益合计",
        r"(?<![司])所有者权益合计",
    ])
    # 总权益口径: 有少数股东时用 "所有者权益合计" 排除归母标签，无少数股东时与 equity_parent 相同
    out['total_equity'] = extract_with_fallback(balance_text, [
        r"(?<![司])所有者权益合计",
    ])
    out['total_assets']  = extract_with_fallback(balance_text, [r"资产总计"])
    out['share_capital'] = extract_with_fallback(balance_text, [r"股本"])
    return out


def _find_section_pages(doc, start_marker: str, stop_markers: list[str],
                       max_pages: int = 6) -> list[int]:
    """
    定位从 start_marker 开始、到任一 stop_marker 之前的页范围。
    - stop_marker 在某页出现时，该页**仍包含**（因为 stop 之前的内容属于当前 section）
    - 但不再向下扩展
    - max_pages 上限防止误吞过多页（默认 6，覆盖跨 5 页的大表）
    """
    start = None
    for i in range(doc.page_count):
        if start_marker in doc[i].get_text():
            start = i
            break
    if start is None:
        return []

    pages = [start]
    for i in range(start + 1, min(start + max_pages, doc.page_count)):
        t = doc[i].get_text()
        if any(m in t for m in stop_markers):
            # 当前页可能仍含当前 section 的尾部数据，仍包含
            pages.append(i)
            break
        pages.append(i)
    return pages


# ===== Step 3: 多年数据合并 (最新年报版本优先) =====
def build_yearly_dataset(pdfs: list[tuple[int, str]]) -> dict[int, dict[str, float]]:
    """
    每份年报 N 提供 (本期=year=N, 上期=year=N-1) 两份数据。
    合并规则: 每个年份的数据来自「包含该年份的最新年报」——
    即从最新年报开始倒序遍历，仅在该年份尚未有数据时填入。
    """
    data: dict[int, dict[str, float]] = {}

    for year, path in pdfs:  # 已是倒序
        parsed = parse_pdf(path)
        for key, vals in parsed.items():
            if len(vals) >= 2:
                # 上期数据填到 year-1（最新视角，优先）
                target_prev = data.setdefault(year - 1, {})
                if key not in target_prev:
                    target_prev[key] = vals[1]
            if len(vals) >= 1:
                # 本期数据填到 year
                target_cur = data.setdefault(year, {})
                if key not in target_cur:
                    target_cur[key] = vals[0]

    return data


# ===== Step 4: 指标计算 =====
def _avg(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    """算术平均。任一为空则用单一值近似。"""
    if curr is None and prev is None:
        return None
    if curr is None:
        return prev
    if prev is None:
        return curr
    return (curr + prev) / 2


def _pct(x: Optional[float], digits: int = 2) -> str:
    return "—" if x is None else f"{x*100:.{digits}f}%"


def _num(x: Optional[float], digits: int = 4) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def _get(d: dict, key: str) -> Optional[float]:
    v = d.get(key)
    return v if v not in (None, 0) and v != [] else None


def compute_metrics(year: int, cur: dict[str, float], prev: dict[str, float] | None) -> dict:
    """
    计算单年的杜邦三因子/五因子 + Z-Score。
    cur: 当年期末数据 (必须有)
    prev: 上年期末数据 (可为 None，缺则用期末近似平均)
    """
    prev = prev or {}

    revenue      = _get(cur, 'revenue')
    net_profit_p = _get(cur, 'net_profit_parent')
    interest     = _get(cur, 'interest_expense') or 0.0
    pbt          = _get(cur, 'profit_before_tax')
    income_tax   = _get(cur, 'income_tax') or 0.0
    ebit         = (pbt + interest) if (pbt is not None) else None

    total_assets_cur  = _get(cur, 'total_assets')
    total_assets_prev = _get(prev, 'total_assets')
    avg_total_assets  = _avg(total_assets_cur, total_assets_prev)

    equity_p_cur  = _get(cur, 'equity_parent')
    equity_p_prev = _get(prev, 'equity_parent')
    avg_equity_p  = _avg(equity_p_cur, equity_p_prev)

    total_equity_cur  = _get(cur, 'total_equity')
    total_equity_prev = _get(prev, 'total_equity')

    current_assets    = _get(cur, 'current_assets') or 0.0
    current_liab      = _get(cur, 'current_liabilities') or 0.0
    total_liab        = _get(cur, 'total_liabilities') or 0.0
    undistributed     = _get(cur, 'undistributed_profit') or 0.0
    surplus           = _get(cur, 'surplus_reserve') or 0.0
    working_capital   = current_assets - current_liab

    m: dict[str, Optional[float]] = {
        'year': year,
        'revenue': revenue,
        'net_profit_parent': net_profit_p,
        'total_assets': total_assets_cur,
        'equity_parent': equity_p_cur,
    }

    # ===== 杜邦三因子 =====
    if revenue and net_profit_p is not None:
        m['npm_3'] = net_profit_p / revenue           # 销售净利率
    if revenue and avg_total_assets:
        m['asset_turnover'] = revenue / avg_total_assets
    if avg_total_assets and avg_equity_p:
        m['equity_multiplier'] = avg_total_assets / avg_equity_p
    if all(m.get(k) for k in ['npm_3', 'asset_turnover', 'equity_multiplier']):
        m['roe_3'] = m['npm_3'] * m['asset_turnover'] * m['equity_multiplier']

    # ===== 杜邦五因子 =====
    if net_profit_p is not None and pbt is not None and pbt != 0:
        m['tax_burden'] = net_profit_p / pbt            # 税务负担
    if pbt is not None and ebit is not None and ebit != 0:
        m['interest_burden'] = pbt / ebit                # 利息负担
    if ebit is not None and revenue:
        m['ebit_margin'] = ebit / revenue                # EBIT 利润率
    if all(m.get(k) for k in ['tax_burden', 'interest_burden', 'ebit_margin',
                              'asset_turnover', 'equity_multiplier']):
        m['roe_5'] = (m['tax_burden'] * m['interest_burden'] * m['ebit_margin']
                      * m['asset_turnover'] * m['equity_multiplier'])

    # ===== Altman Z-Score (账面权益版) =====
    if total_assets_cur and total_assets_cur != 0:
        X1 = working_capital / total_assets_cur
        X2 = (undistributed + surplus) / total_assets_cur
        X3 = (ebit / total_assets_cur) if ebit is not None else None
        X4 = (total_equity_cur / total_liab) if (total_equity_cur and total_liab) else None
        X5 = (revenue / total_assets_cur) if revenue else None

        if all(v is not None for v in [X1, X2, X3, X4, X5]):
            m['z_score'] = 1.2 * X1 + 1.4 * X2 + 3.3 * X3 + 0.6 * X4 + 1.0 * X5
            m['z_prime'] = 0.717 * X1 + 0.847 * X2 + 3.107 * X3 + 0.420 * X4
            m['z_X1'], m['z_X2'], m['z_X3'], m['z_X4'], m['z_X5'] = X1, X2, X3, X4, X5

    return m


# ===== Step 5: 终端表格 =====
def print_terminal_table(company: str, years: list[int], metrics: dict[int, dict]) -> None:
    print(f"\n{'='*72}")
    print(f"  {company}  财务指标分析  ({len(years)} 年: {years[0]}–{years[-1]})")
    print(f"{'='*72}")

    def row(label, key, fmt, digits=4):
        cells = [fmt(metrics[y].get(key), digits) for y in years]
        print(f"  {label:<22} " + "  ".join(f"{c:>14}" for c in cells))

    def yi(v, digits=2):  # 亿元
        return "—" if v is None else f"{v/1e8:.{digits}f}"

    # 表头
    print(f"  {'指标':<22} " + "  ".join(f"{str(y):>14}" for y in years))
    print(f"  {'-'*22} " + "  ".join("-" * 14 for _ in years))

    print("\n  [原始数据 (亿元)]")
    row("营业收入",     'revenue',            yi, 2)
    row("归母净利润",   'net_profit_parent',  yi, 2)
    row("资产总计",     'total_assets',       yi, 2)
    row("归母权益",     'equity_parent',      yi, 2)

    print("\n  [杜邦三因子]")
    row("销售净利率",       'npm_3',             _pct, 2)
    row("总资产周转率",     'asset_turnover',    _num, 4)
    row("权益乘数",         'equity_multiplier', _num, 4)
    row("→ ROE (合成)",     'roe_3',             _pct, 2)

    print("\n  [杜邦五因子]")
    row("税务负担",         'tax_burden',        _pct, 2)
    row("利息负担",         'interest_burden',   _pct, 2)
    row("EBIT 利润率",      'ebit_margin',       _pct, 2)
    row("总资产周转率",     'asset_turnover',    _num, 4)
    row("权益乘数",         'equity_multiplier', _num, 4)
    row("→ ROE (合成)",     'roe_5',             _pct, 2)

    print("\n  [Altman Z-Score]")
    row("X1 营运资金/总资产",   'z_X1', _num, 4)
    row("X2 留存收益/总资产",   'z_X2', _num, 4)
    row("X3 EBIT/总资产",       'z_X3', _num, 4)
    row("X4 权益/负债",         'z_X4', _num, 4)
    row("X5 营收/总资产",       'z_X5', _num, 4)
    row("→ Z (账面版)",         'z_score', _num, 2)
    row("→ Z' (1983 修订)",     'z_prime', _num, 2)
    print()


# ===== Step 6: Markdown 报告 =====
def write_markdown(company: str, years: list[int], metrics: dict[int, dict],
                   out_path: str, trend_lines: list[str] | None = None) -> None:
    lines = [
        f"# {company} 财务指标分析",
        f"",
        f"**分析年份**: {years[0]}–{years[-1]} ({len(years)} 年)",
        f"**生成工具**: financial-metrics skill",
        f"",
        f"## 一、原始数据（单位：亿元）",
        f"",
        f"| 项目 | " + " | ".join(str(y) for y in years) + " |",
        f"|---|" + "|".join("---" for _ in years) + "|",
    ]

    def md_row(label, key, scale=1e8, digits=2, fmt="num"):
        cells = []
        for y in years:
            v = metrics[y].get(key)
            if v is None:
                cells.append("—")
            elif fmt == "pct":
                cells.append(f"{v*100:.{digits}f}%")
            else:
                cells.append(f"{v/scale:.{digits}f}" if scale != 1 else f"{v:.{digits}f}")
        return f"| {label} | " + " | ".join(cells) + " |"

    lines += [
        md_row("营业收入",   'revenue'),
        md_row("归母净利润", 'net_profit_parent'),
        md_row("资产总计",   'total_assets'),
        md_row("归母权益",   'equity_parent'),
        "",
        "## 二、杜邦三因子分解",
        "",
        "| 因子 | " + " | ".join(str(y) for y in years) + " |",
        "|---|" + "|".join("---" for _ in years) + "|",
        md_row("销售净利率",         'npm_3',             scale=1, fmt="pct"),
        md_row("总资产周转率",       'asset_turnover',    scale=1, digits=4),
        md_row("权益乘数",           'equity_multiplier', scale=1, digits=4),
        md_row("**ROE (合成)**",     'roe_3',             scale=1, fmt="pct"),
        "",
        "## 三、杜邦五因子分解",
        "",
        "ROE = 税务负担 × 利息负担 × EBIT 利润率 × 总资产周转率 × 权益乘数",
        "",
        "| 因子 | " + " | ".join(str(y) for y in years) + " |",
        "|---|" + "|".join("---" for _ in years) + "|",
        md_row("税务负担",         'tax_burden',        scale=1, fmt="pct"),
        md_row("利息负担",         'interest_burden',   scale=1, fmt="pct"),
        md_row("EBIT 利润率",      'ebit_margin',       scale=1, fmt="pct"),
        md_row("总资产周转率",     'asset_turnover',    scale=1, digits=4),
        md_row("权益乘数",         'equity_multiplier', scale=1, digits=4),
        md_row("**ROE (合成)**",   'roe_5',             scale=1, fmt="pct"),
        "",
        "## 四、Altman Z-Score",
        "",
        "Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5  (账面权益版)",
        "",
        "| 变量 | " + " | ".join(str(y) for y in years) + " |",
        "|---|" + "|".join("---" for _ in years) + "|",
        md_row("X1 营运资金/总资产", 'z_X1', scale=1, digits=4),
        md_row("X2 留存收益/总资产", 'z_X2', scale=1, digits=4),
        md_row("X3 EBIT/总资产",     'z_X3', scale=1, digits=4),
        md_row("X4 权益/负债",       'z_X4', scale=1, digits=4),
        md_row("X5 营收/总资产",     'z_X5', scale=1, digits=4),
        md_row("**Z (账面版)**",     'z_score', scale=1, digits=2),
        md_row("**Z' (1983 修订)**", 'z_prime', scale=1, digits=2),
        "",
        "**判读**:",
        "- Z > 2.99: 安全区; 1.81–2.99: 灰色区; < 1.81: 高风险",
        "- Z' > 2.9: 安全; 1.21–2.9: 灰色; < 1.21: 高风险",
        "- X4 用账面权益/总负债 (非市值)，低估了真实 X4",
        "",
    ]

    # 追加趋势分析章节
    if trend_lines:
        lines.append("## 五、趋势分析")
        lines.append("")
        lines.extend(trend_lines)
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ===== Step 7: 趋势分析 (自动生成文字) =====
def _z_zone(z):
    if z is None:
        return "数据缺失"
    if z > 2.99:
        return "安全区"
    if z > 1.81:
        return "灰色区"
    return "高风险"


def _zp_zone(z):
    if z is None:
        return "数据缺失"
    if z > 2.9:
        return "安全"
    if z > 1.21:
        return "灰色"
    return "高风险"


def _delta_str(v_first, v_last, is_pct=True):
    """生成 "+5.3pp" / "-0.123" 这种变化描述。"""
    d = v_last - v_first
    sign = "+" if d > 0 else ""
    if is_pct:
        return f"{sign}{d*100:.1f}pp"
    return f"{sign}{d:.4f}"


def generate_trend_analysis(years: list[int], metrics: dict[int, dict]) -> list[str]:
    """
    自动生成趋势分析文字。返回 list[str]（每行一段）。
    覆盖: 杜邦三因子主因识别 / 杜邦五因子拆解 / Z-score 区间 + X1-X5 关键观察。
    """
    lines: list[str] = []
    n = len(years)
    if n == 0:
        return lines

    first_y, last_y = years[0], years[-1]
    first = metrics[first_y]
    last = metrics[last_y]

    # ============ 杜邦三因子 ============
    lines.append("### 杜邦三因子趋势")
    lines.append("")

    if n < 2:
        # 单年: 仅描述当年
        npm = first.get('npm_3')
        at = first.get('asset_turnover')
        em = first.get('equity_multiplier')
        roe = first.get('roe_3')
        lines.append(f"- {first_y} 年 ROE = {_pct(roe)}，由销售净利率 {_pct(npm)} × "
                     f"总资产周转率 {_num(at)} × 权益乘数 {_num(em)} 构成")
        if npm is not None and at is not None and em is not None:
            if npm > 0.3:
                lines.append(f"- 销售净利率高达 {_pct(npm)}：高利润率驱动型（典型资源/垄断行业特征）")
            if em < 1.5:
                lines.append(f"- 权益乘数仅 {_num(em)}：低杠杆运营，财务稳健")
        return lines  # 单年直接返回

    # 多年趋势
    roe_first = first.get('roe_3')
    roe_last = last.get('roe_3')
    if roe_first is not None and roe_last is not None:
        delta = (roe_last - roe_first) * 100
        direction = "上升" if delta > 0 else ("下降" if delta < 0 else "持平")
        sign = "+" if delta > 0 else ""
        lines.append(f"- **ROE**: {first_y} {_pct(roe_first)} → {last_y} {_pct(roe_last)} "
                     f"({direction} {sign}{delta:.1f}pp)")

    # 三因子各自变化 + 找主导
    factor_deltas = []
    for label, key, is_pct in [("销售净利率", "npm_3", True),
                                ("总资产周转率", "asset_turnover", False),
                                ("权益乘数", "equity_multiplier", False)]:
        v1 = first.get(key)
        v2 = last.get(key)
        if v1 is None or v2 is None:
            continue
        lines.append(f"  - {label}: {_pct(v1) if is_pct else _num(v1)} → "
                     f"{_pct(v2) if is_pct else _num(v2)} ({_delta_str(v1, v2, is_pct)})")
        # 相对变化用于主因识别
        if v1 != 0:
            factor_deltas.append((label, (v2 - v1) / abs(v1)))

    if factor_deltas and roe_first is not None and roe_last is not None:
        factor_deltas.sort(key=lambda x: -abs(x[1]))
        dom_label, dom_rel = factor_deltas[0]
        roe_dir = "上升" if roe_last > roe_first else "下降"
        lines.append(f"- **主因**: {dom_label} 相对变化 {dom_rel*100:+.1f}%，是 ROE {roe_dir} 的最大驱动")

    # 描述中间波动 (3+ 年时)
    if n >= 3:
        roe_series = [(y, metrics[y].get('roe_3')) for y in years]
        valid = [(y, v) for y, v in roe_series if v is not None]
        if len(valid) >= 3:
            # 判断是否单调和波动
            diffs = [valid[i+1][1] - valid[i][1] for i in range(len(valid)-1)]
            all_down = all(d < 0 for d in diffs)
            all_up = all(d > 0 for d in diffs)
            if all_down:
                lines.append(f"- ROE 在 {years[0]}–{years[-1]} 期间**单边下行**")
            elif all_up:
                lines.append(f"- ROE 在 {years[0]}–{years[-1]} 期间**单边上行**")
            else:
                # 找最低点 / 最高点
                min_y, min_v = min(valid, key=lambda x: x[1])
                max_y, max_v = max(valid, key=lambda x: x[1])
                lines.append(f"- 期间有波动，ROE 最低 {_pct(min_v)} ({min_y})，最高 {_pct(max_v)} ({max_y})")

    # ============ 杜邦五因子 ============
    lines.append("")
    lines.append("### 杜邦五因子拆解 (销售净利率再分解)")
    lines.append("")

    # 税务负担
    tb1 = first.get('tax_burden')
    tb2 = last.get('tax_burden')
    if tb1 is not None and tb2 is not None:
        if tb2 > 1.0:
            lines.append(f"- **税务负担 {_pct(tb1)} → {_pct(tb2)}（突破 100%）**: "
                         f"{last_y} 年所得税费用为负（递延税资产返还/税收优惠），对 ROE 有非经营性推升")
        elif tb1 > 1.0:
            lines.append(f"- 税务负担从 {_pct(tb1)}（异常>100%）回归 {_pct(tb2)}: 上年税收返还效应消失")
        elif abs(tb2 - tb1) > 0.05:
            direction = "上升（实际税率下降）" if tb2 > tb1 else "下降（实际税率上升）"
            lines.append(f"- 税务负担 {_pct(tb1)} → {_pct(tb2)}: {direction}")
        else:
            lines.append(f"- 税务负担稳定 ({_pct(tb1)} → {_pct(tb2)})，实际税率无大变化")

    # EBIT 利润率
    em1 = first.get('ebit_margin')
    em2 = last.get('ebit_margin')
    if em1 is not None and em2 is not None:
        delta = (em2 - em1) * 100
        sign = "+" if delta > 0 else ""
        verdict = "经营性盈利改善" if delta > 0 else "经营性盈利恶化"
        lines.append(f"- **EBIT 利润率 {_pct(em1)} → {_pct(em2)} ({sign}{delta:.1f}pp)**: {verdict}，"
                     f"剔除了税务/融资影响后的真实经营利润率变化")

    # 利息负担
    ib1 = first.get('interest_burden')
    ib2 = last.get('interest_burden')
    if ib1 is not None and ib2 is not None:
        if abs(ib1 - ib2) < 0.03:
            lines.append(f"- 利息负担稳定 ({_pct(ib1)}–{_pct(ib2)})，EBIT 与利润总额接近，"
                         f"公司现金充裕、财务费用对利润几乎无侵蚀")
        else:
            lines.append(f"- 利息负担 {_pct(ib1)} → {_pct(ib2)}: 财务成本结构有变化")

    # ============ Z-Score ============
    lines.append("")
    lines.append("### Altman Z-Score 趋势")
    lines.append("")

    z1 = first.get('z_score')
    z2 = last.get('z_score')
    zp1 = first.get('z_prime')
    zp2 = last.get('z_prime')

    if z1 is not None and z2 is not None:
        delta_z = z2 - z1
        sign = "+" if delta_z > 0 else ""
        verdict = "财务健康度提升" if delta_z > 0 else "财务健康度恶化"
        lines.append(f"- **Z 值**: {first_y} {z1:.2f} ({_z_zone(z1)}) → "
                     f"{last_y} {z2:.2f} ({_z_zone(z2)})，{sign}{delta_z:.2f}，{verdict}")
        if z2 > 2.99:
            lines.append(f"  当前处于**安全区** (Z > 2.99)")
        elif z2 > 1.81:
            lines.append(f"  当前处于**灰色区** (1.81 < Z < 2.99)，需关注")
        else:
            lines.append(f"  ⚠️ 当前处于**高风险区** (Z < 1.81)，破产风险较高")

    if n >= 2 and zp1 is not None and zp2 is not None:
        lines.append(f"- Z' (修订版·更严格): {first_y} {zp1:.2f} ({_zp_zone(zp1)}) → "
                     f"{last_y} {zp2:.2f} ({_zp_zone(zp2)})")

    # X2 留存收益 (历史包袱)
    x2_1 = first.get('z_X2')
    x2_2 = last.get('z_X2')
    if x2_1 is not None and x2_2 is not None:
        if x2_1 < 0 and x2_2 < 0:
            lines.append(f"- **X2 留存收益/总资产长期为负 ({x2_1:.3f} → {x2_2:.3f})**: "
                         f"历史累计亏损未填平，是压低 Z 值的核心因素；"
                         f"按当前填平速度，未来几年 X2 转正将让 Z 值显著跃升")
        elif x2_1 < 0 and x2_2 >= 0:
            lines.append(f"- **X2 从 {x2_1:.3f} 转正到 {x2_2:.3f}**: 历史亏损已填平，未来 Z 值将明显改善")
        elif x2_2 > x2_1:
            lines.append(f"- X2 留存收益 {x2_1:.3f} → {x2_2:.3f}: 盈利持续积累")
        else:
            lines.append(f"- X2 留存收益 {x2_1:.3f} → {x2_2:.3f}: 出现回落（分红过多或亏损）")

    # X4 杠杆
    x4_1 = first.get('z_X4')
    x4_2 = last.get('z_X4')
    if x4_1 is not None and x4_2 is not None and x4_1 > 0:
        ratio = x4_2 / x4_1
        if ratio > 1.3:
            lines.append(f"- X4 权益/负债 {x4_1:.2f} → {x4_2:.2f}: **持续去杠杆**，财务稳健性大幅提升")
        elif ratio < 0.7:
            lines.append(f"- X4 权益/负债 {x4_1:.2f} → {x4_2:.2f}: 杠杆显著上升，负债扩张快于权益")

    # X5 资产周转
    x5_1 = first.get('z_X5')
    x5_2 = last.get('z_X5')
    if x5_1 is not None and x5_2 is not None and x5_1 > 0:
        ratio = x5_2 / x5_1
        if ratio < 0.8:
            lines.append(f"- **X5 营收/总资产 {x5_1:.3f} → {x5_2:.3f} 持续下滑**: "
                         f"营收增长乏力 + 资产持续扩张，是 Z 值最大的结构性隐忧")
        elif ratio > 1.2:
            lines.append(f"- X5 营收/总资产 {x5_1:.3f} → {x5_2:.3f}: 资产周转效率提升")

    return lines


# ===== 主入口 =====
def main():
    p = argparse.ArgumentParser(
        description="财务指标计算器 (杜邦三因子/五因子 + Altman Z-Score)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("company", help="公司名 (如 盐湖股份) 或 PDF 目录路径")
    p.add_argument("--since", type=int, default=0, help="仅分析此年份及以后 (如 --since 2020)")
    p.add_argument("--latest", type=int, default=0, help="仅分析最近 N 年 (如 --latest 3)")
    p.add_argument("--output", default="", help="MD 报告输出路径，默认 PDF 目录下 <公司>_财务分析.md")
    p.add_argument("--no-report", action="store_true", help="不生成 MD 报告")
    args = p.parse_args()

    # 1) 定位 PDF
    company, pdfs = find_pdfs(args.company)
    print(f"📂 找到 {len(pdfs)} 份年报 ({pdfs[-1][0]}–{pdfs[0][0]}): "
          + ", ".join(str(y) for y, _ in pdfs))

    # 2) 解析 + 合并
    print("⏳ 解析 PDF 中...")
    dataset = build_yearly_dataset(pdfs)
    all_years = sorted(dataset.keys(), reverse=True)

    # 3) 范围过滤
    years = all_years
    if args.since:
        years = [y for y in years if y >= args.since]
    if args.latest:
        years = years[:args.latest]
    if not years:
        raise SystemExit("❌ 过滤后没有可分析年份")
    years = sorted(years)  # 升序展示

    print(f"📊 计算指标: {years[0]}–{years[-1]} ({len(years)} 年)\n")

    # 4) 计算
    metrics: dict[int, dict] = {}
    for y in years:
        cur = dataset.get(y, {})
        prev = dataset.get(y - 1, {})
        metrics[y] = compute_metrics(y, cur, prev)

    # 5) 终端输出
    print_terminal_table(company, years, metrics)

    # 6) 趋势分析
    trend_lines = generate_trend_analysis(years, metrics)
    if trend_lines:
        print("  [趋势分析]")
        for line in trend_lines:
            # 去掉 markdown 标题层级，保留内容
            display = line.lstrip("#").strip() if line.startswith("#") else line
            if display:
                print(f"  {display}")
        print()

    # 7) MD 报告 (含趋势分析章节)
    if not args.no_report:
        if args.output:
            out_path = args.output
        else:
            # 默认放到 PDF 目录
            sample_pdf_dir = os.path.dirname(pdfs[0][1])
            out_path = os.path.join(sample_pdf_dir, f"{company}_财务分析.md")
        write_markdown(company, years, metrics, out_path, trend_lines)
        print(f"📄 MD 报告已保存: {out_path}")


if __name__ == "__main__":
    main()
