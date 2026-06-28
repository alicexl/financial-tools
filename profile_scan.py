"""
扫描所有公司年报 PDF，提取用于"格式族"分类的特征。
输出: 每家公司的 PDF 格式特征 → profile_scan_report.md / .json

特征清单（每份 PDF 提取）:
  - 单位标注原始文本（前 30 个匹配 "单位" 的行）
  - 报表段标记原文（合并利润表 / 合并及公司利润表 / 母公司利润表 / 无标记）
  - 利润表首页前 500 字符（用于观察项目排列）
  - 资产负债表首页前 500 字符
  - 营业收入标签原文（营业总收入 / 营业收入 / 一、营业收入 / 一、营业总收入）
  - 归母净利润标签原文（多种变体）
  - 归母权益标签原文（多种变体）
  - 单位识别（_detect_unit_scale 的结果）
  - 当前 parse_pdf 的关键字段提取结果（用于标记 OK / FAIL）
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "C:/Users/Xulu/.claude/skills/financial-metrics")
import financial_metrics as fm  # noqa: E402
import fitz  # noqa: E402

BASE = "D:/workspace/年报"


def scan_one_pdf(pdf_path: str) -> dict:
    """扫描单份 PDF，提取格式特征。"""
    doc = fitz.open(pdf_path)
    out = {"page_count": doc.page_count}

    # 1. 单位标度（_detect_unit_scale 的结果）
    try:
        out["unit_scale"] = fm._detect_unit_scale(doc)
    except Exception as e:
        out["unit_scale"] = f"ERR: {e}"

    # 2. 抓所有"单位"标注行（用于人工看变体）
    unit_lines = []
    for i in range(min(doc.page_count, 200)):
        t = doc[i].get_text()
        for m in re.finditer(r"[^\n]*单位[^\n]*", t):
            line = m.group().strip()
            if line and len(line) < 80 and line not in unit_lines:
                unit_lines.append(line)
            if len(unit_lines) >= 10:
                break
        if len(unit_lines) >= 10:
            break
    out["unit_lines_sample"] = unit_lines[:5]

    # 3. 抓"人民币" 单独成行的标注
    rmb_lines = []
    for i in range(min(doc.page_count, 200)):
        t = doc[i].get_text()
        for m in re.finditer(r"^\s*人民币[^\n]{0,20}$", t, re.MULTILINE):
            line = m.group().strip()
            if line and line not in rmb_lines:
                rmb_lines.append(line)
            if len(rmb_lines) >= 5:
                break
        if len(rmb_lines) >= 5:
            break
    out["rmb_lines_sample"] = rmb_lines[:3]

    # 4. 报表段标记出现情况
    markers_to_check = [
        "合并资产负债表", "合并及公司资产负债表", "合并利润表", "合并及公司利润表",
        "母公司资产负债表", "母公司利润表",
    ]
    marker_pages = {m: [] for m in markers_to_check}
    for i in range(doc.page_count):
        t = doc[i].get_text()
        for m in markers_to_check:
            if m in t:
                marker_pages[m].append(i)
    out["marker_first_page"] = {m: (v[0] if v else None) for m, v in marker_pages.items()}

    # 5. 找利润表起始页（用于看 营业收入 标签原文）
    income_pages = fm._find_section_pages(
        doc,
        start_marker=["合并利润表", "合并及公司利润表"],
        stop_markers=["母公司利润表", "合并现金流量表", "合并所有者权益变动表",
                      "合并及公司现金流量表", "合并及公司所有者权益变动表"],
        content_hints=["营业收入", "营业总收入", "营业总成本",
                       "利润总额", "所得税费用", "净利润"],
        strong_hints=["营业总收入"],
    )
    out["income_pages"] = income_pages[:3]
    if income_pages:
        text = doc[income_pages[0]].get_text()
        # 找 营业收入 / 营业总收入 行
        for kw in ["一、营业总收入", "一、营业收入", "营业总收入", "营业收入"]:
            m = re.search(rf"[^\n]*{re.escape(kw)}[^\n]*", text)
            if m:
                out["revenue_label_line"] = m.group().strip()[:80]
                break
        else:
            out["revenue_label_line"] = None
        # 找 归属于母公司 标签
        for kw in ['归属于母公司股东的净利润', '归属于母公司所有者的净利润',
                   '归属于母公司普通股股东', '净利润']:
            m = re.search(rf"[^\n]*{re.escape(kw)}[^\n]*", text)
            if m:
                out["npp_label_line"] = m.group().strip()[:100]
                break
        else:
            out["npp_label_line"] = None

    # 6. 找资产负债表起始页
    balance_pages = fm._find_section_pages(
        doc,
        start_marker=["合并资产负债表", "合并及公司资产负债表"],
        stop_markers=["母公司资产负债表", "合并利润表", "合并及公司利润表"],
        content_hints=["流动资产合计", "流动负债合计", "资产总计",
                       "负债合计", "所有者权益合计"],
        strong_hints=["归属于母公司", "少数股东权益"],
    )
    out["balance_pages"] = balance_pages[:3]
    if balance_pages:
        text = "\n".join(doc[i].get_text() for i in balance_pages)
        for kw in ['归属于母公司所有者权益合计',
                   '归属于母公司所有者权益（或股东权益）合计',
                   '归属于母公司股东权益合计',
                   '归属于母公司普通股股东权益合计',
                   '所有者权益（或股东权益）合计',
                   '所有者权益合计']:
            m = re.search(rf"[^\n]*{re.escape(kw)}[^\n]*", text)
            if m:
                out["equity_label_line"] = m.group().strip()[:100]
                break
        else:
            out["equity_label_line"] = None

    doc.close()

    # 7. 当前 parse_pdf 的关键字段提取结果
    try:
        parsed = fm.parse_pdf(pdf_path)
        out["parsed_revenue"] = parsed.get("revenue", [])
        out["parsed_npp"] = parsed.get("net_profit_parent", [])
        out["parsed_ta"] = parsed.get("total_assets", [])
        out["parsed_eq"] = parsed.get("equity_parent", [])
    except Exception as e:
        out["parse_err"] = f"{type(e).__name__}: {e}"

    return out


def classify_status(features: dict) -> str:
    """根据 parse 结果打标签: OK / SUSPICIOUS / FAIL"""
    rev = features.get("parsed_revenue", [])
    npp = features.get("parsed_npp", [])
    ta = features.get("parsed_ta", [])
    eq = features.get("parsed_eq", [])
    if "parse_err" in features:
        return "ERR"
    if not rev or not npp or not ta or not eq:
        return "MISSING_FIELD"
    rev_yi = rev[0] / 1e8
    ta_yi = ta[0] / 1e8
    if not (1e8 <= rev[0] <= 1e13):
        return f"SUSPICIOUS_rev({rev_yi:.2f}亿)"
    if not (1e8 <= ta[0] <= 1e13):
        return f"SUSPICIOUS_ta({ta_yi:.2f}亿)"
    return "OK"


def main():
    companies = sorted(d for d in os.listdir(BASE)
                       if os.path.isdir(os.path.join(BASE, d)))
    all_features = {}
    summary = []
    for c_dir in companies:
        company_name = c_dir.replace("年报", "")
        d = os.path.join(BASE, c_dir)
        pdfs = sorted(f for f in os.listdir(d) if f.endswith(".pdf") and "年报" in f)
        if not pdfs:
            continue
        # 只取最新一份
        latest_pdf = pdfs[-1]
        pdf_path = os.path.join(d, latest_pdf)
        try:
            features = scan_one_pdf(pdf_path)
        except Exception as e:
            features = {"err": f"{type(e).__name__}: {e}"}
        features["pdf_file"] = latest_pdf
        features["status"] = classify_status(features) if "err" not in features else "SCAN_ERR"
        all_features[company_name] = features
        summary.append((company_name, features["status"], latest_pdf))
        print(f"  {company_name}: {features['status']}  ({latest_pdf})", flush=True)

    # 写 JSON 全量
    out_json = "D:/workspace/financial-tools/profile_scan.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_features, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Full features → {out_json}")

    # 写 MD 摘要
    out_md = "D:/workspace/financial-tools/profile_scan_report.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# PDF 格式扫描报告\n\n")
        f.write(f"扫描公司数: {len(summary)}\n\n")
        # 按状态分组
        by_status = {}
        for name, status, pdf in summary:
            by_status.setdefault(status, []).append((name, pdf))
        for status in sorted(by_status.keys()):
            f.write(f"## {status} ({len(by_status[status])} 家)\n\n")
            for name, pdf in sorted(by_status[status]):
                feat = all_features[name]
                f.write(f"### {name}\n")
                f.write(f"- PDF: `{pdf}`\n")
                f.write(f"- unit_scale: {feat.get('unit_scale')}\n")
                if feat.get("unit_lines_sample"):
                    f.write(f"- 单位标注样本: `{feat['unit_lines_sample'][:2]}`\n")
                if feat.get("rmb_lines_sample"):
                    f.write(f"- 人民币单行: `{feat['rmb_lines_sample'][:2]}`\n")
                fm_dict = feat.get("marker_first_page", {})
                f.write(f"- marker 首现页: 合并利润表={fm_dict.get('合并利润表')} "
                        f"合并及公司利润表={fm_dict.get('合并及公司利润表')}\n")
                if feat.get("income_pages"):
                    f.write(f"- income_pages: {feat['income_pages']}\n")
                if feat.get("revenue_label_line"):
                    f.write(f"- revenue 标签: `{feat['revenue_label_line']}`\n")
                if feat.get("npp_label_line"):
                    f.write(f"- npp 标签: `{feat['npp_label_line']}`\n")
                if feat.get("balance_pages"):
                    f.write(f"- balance_pages: {feat['balance_pages']}\n")
                if feat.get("equity_label_line"):
                    f.write(f"- equity 标签: `{feat['equity_label_line']}`\n")
                parsed_rev = feat.get("parsed_revenue", [])
                if parsed_rev:
                    f.write(f"- 解析 rev: {[round(v/1e8, 2) for v in parsed_rev]} 亿\n")
                parsed_npp = feat.get("parsed_npp", [])
                if parsed_npp:
                    f.write(f"- 解析 npp: {[round(v/1e8, 2) for v in parsed_npp]} 亿\n")
                parsed_ta = feat.get("parsed_ta", [])
                if parsed_ta:
                    f.write(f"- 解析 ta: {[round(v/1e8, 2) for v in parsed_ta]} 亿\n")
                parsed_eq = feat.get("parsed_eq", [])
                if parsed_eq:
                    f.write(f"- 解析 eq: {[round(v/1e8, 2) for v in parsed_eq]} 亿\n")
                f.write("\n")
    print(f"✅ Markdown report → {out_md}")

    # 控制台 summary
    print("\n=== SUMMARY ===")
    for status in sorted(by_status.keys()):
        print(f"  {status}: {len(by_status[status])}")


if __name__ == "__main__":
    main()
