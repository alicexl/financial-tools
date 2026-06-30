"""
批量排雷分析: 对所有本地公司年报跑 generate_risk_warnings，汇总红/黄信号。
输出: 终端 summary + batch_risk_report.md
"""
import os
import re
import sys

sys.path.insert(0, "C:/Users/Xulu/.claude/skills/financial-metrics")
import financial_metrics as fm  # noqa: E402

BASE = "D:/workspace/年报"


def run_one(company_dir: str):
    d = company_dir
    pdfs = []
    for name in os.listdir(d):
        if not name.lower().endswith(".pdf"):
            continue
        m = re.search(r"(\d{4})\s*年", name)
        if not m:
            continue
        if any(kw in name for kw in ["摘要", "英文版", "已取消", "更正"]):
            continue
        pdfs.append((int(m.group(1)), os.path.join(d, name)))
    if not pdfs:
        return {"status": "NO_PDF"}
    pdfs.sort(key=lambda x: -x[0])  # 倒序
    pdfs = pdfs[:3]  # 最近 3 年
    pairs = [(y, p) for y, p in sorted(pdfs)]
    try:
        data = fm.build_yearly_dataset(pairs)
        if not data:
            return {"status": "EMPTY"}
        years = sorted(y for y in data.keys() if y in {p[0] for p in pairs})
        if not years:
            return {"status": "NO_YEAR"}
        metrics = {}
        for y in years:
            cur = data.get(y, {})
            prev = data.get(y - 1, {})
            metrics[y] = fm.compute_metrics(y, cur, prev)
        risk_lines = fm.generate_risk_warnings(years, metrics)
        last = metrics[years[-1]]
        return {
            "status": "OK",
            "years": years,
            "z_score": last.get("z_score"),
            "risk_lines": risk_lines,
            "red_count": sum(1 for L in risk_lines if L.strip().startswith("- 🚨")),
            "yellow_count": sum(1 for L in risk_lines if L.strip().startswith("- ⚠️")),
            "has_red": any("高度警示" in L for L in risk_lines),
            "has_yellow": any("关注信号" in L for L in risk_lines),
        }
    except Exception as e:
        return {"status": "ERR", "err": f"{type(e).__name__}: {e}"}


def main():
    companies = sorted(os.listdir(BASE))
    results = []
    for c in companies:
        d = os.path.join(BASE, c)
        if not os.path.isdir(d):
            continue
        name = c.replace("年报", "")
        r = run_one(d)
        results.append((name, r))
        if r["status"] == "OK":
            z = r["z_score"]
            zs = f"{z:.2f}" if z is not None else "?"
            print(f"  {name}: Z={zs} 🚨{r['red_count']} ⚠️{r['yellow_count']}", flush=True)
        else:
            print(f"  {name}: {r['status']} {r.get('err', '')}", flush=True)

    # 分类
    red_companies = [(n, r) for n, r in results
                     if r["status"] == "OK" and r["has_red"]]
    yellow_companies = [(n, r) for n, r in results
                        if r["status"] == "OK" and not r["has_red"] and r["has_yellow"]]
    clean_companies = [(n, r) for n, r in results
                       if r["status"] == "OK" and not r["has_red"] and not r["has_yellow"]]
    errs = [(n, r) for n, r in results if r["status"] not in ("OK",)]

    # 写 MD
    out_md = "D:/workspace/financial-tools/batch_risk_report.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 本地 60 家公司排雷分析汇总\n\n")
        f.write(f"扫描公司数: {len(results)} | "
                f"🚨 红线: {len(red_companies)} | "
                f"⚠️ 黄线: {len(yellow_companies)} | "
                f"✅ 健康: {len(clean_companies)} | "
                f"错误: {len(errs)}\n\n")

        # 综合排名表
        f.write("## 综合排名（按 Z 值升序）\n\n")
        f.write("| 公司 | Z 值 | 🚨 | ⚠️ | 等级 |\n")
        f.write("|---|---|---|---|---|\n")
        ranked = []
        for n, r in results:
            if r["status"] != "OK":
                continue
            z = r["z_score"]
            level = "🚨红" if r["has_red"] else ("⚠️黄" if r["has_yellow"] else "✅绿")
            ranked.append((n, z if z is not None else 99, r["red_count"], r["yellow_count"], level))
        ranked.sort(key=lambda x: x[1])
        for n, z, rc, yc, lv in ranked:
            zs = f"{z:.2f}" if z < 90 else "—"
            f.write(f"| {n} | {zs} | {rc} | {yc} | {lv} |\n")
        f.write("\n")

        # 详情：红线公司
        if red_companies:
            f.write("## 🚨 高度警示公司（含红线信号）\n\n")
            for n, r in sorted(red_companies, key=lambda x: x[1]["red_count"], reverse=True):
                z = r["z_score"]
                zs = f"{z:.2f}" if z is not None else "?"
                yrs = f"{r['years'][0]}–{r['years'][-1]}"
                f.write(f"### {n}（Z={zs}，{yrs}，🚨{r['red_count']} ⚠️{r['yellow_count']}）\n\n")
                for line in r["risk_lines"]:
                    if line.strip():
                        f.write(f"{line}\n")
                f.write("\n")

        # 详情：仅黄线
        if yellow_companies:
            f.write("## ⚠️ 关注公司（仅黄线信号）\n\n")
            for n, r in sorted(yellow_companies, key=lambda x: x[1]["yellow_count"], reverse=True):
                z = r["z_score"]
                zs = f"{z:.2f}" if z is not None else "?"
                yrs = f"{r['years'][0]}–{r['years'][-1]}"
                f.write(f"### {n}（Z={zs}，{yrs}，⚠️{r['yellow_count']}）\n\n")
                for line in r["risk_lines"]:
                    if line.strip():
                        f.write(f"{line}\n")
                f.write("\n")

        # 健康
        if clean_companies:
            f.write("## ✅ 健康公司（无任何信号）\n\n")
            for n, r in sorted(clean_companies):
                z = r["z_score"]
                zs = f"{z:.2f}" if z is not None else "?"
                f.write(f"- **{n}** (Z={zs})\n")
            f.write("\n")

    print(f"\n✅ MD 报告: {out_md}")
    print(f"\n=== 汇总 ===")
    print(f"  🚨 高度警示: {len(red_companies)}")
    print(f"  ⚠️ 仅黄线:   {len(yellow_companies)}")
    print(f"  ✅ 健康:     {len(clean_companies)}")
    print(f"  ❌ 错误:     {len(errs)}")


if __name__ == "__main__":
    main()
