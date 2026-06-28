"""Batch regression test: run financial_metrics on all companies in D:/workspace/年报/."""
import os
import re
import sys

sys.path.insert(0, "C:/Users/Xulu/.claude/skills/financial-metrics")
import financial_metrics as fm  # noqa: E402

BASE = "D:/workspace/年报"


def run_one(company_dir: str) -> dict:
    d = company_dir
    pdfs = sorted(f for f in os.listdir(d)
                  if f.lower().endswith(".pdf") and re.search(r"\d{4}年", f)
                  and not any(kw in f for kw in ["摘要", "英文版", "已取消", "更正"]))
    if not pdfs:
        return {"status": "NO_PDF"}
    # 最近 3 份年报
    pdfs = pdfs[-3:]
    pairs = []
    for f in pdfs:
        m = re.search(r"(\d{4})年", f)
        if m:
            pairs.append((int(m.group(1)), os.path.join(d, f)))
    if not pairs:
        return {"status": "NO_YEAR"}
    try:
        data = fm.build_yearly_dataset(pairs)
        if not data:
            return {"status": "EMPTY"}
        years = sorted(data.keys())
        last = years[-1]
        d_last = data[last]
        rev = d_last.get("revenue") or 0
        npp = d_last.get("net_profit_parent") or 0
        ta = d_last.get("total_assets") or 0
        eq = d_last.get("equity_parent") or 0
        # 简单合理性: 营收应在 1亿 - 10万亿之间；净利润可负（真实亏损）
        flags = []
        if not (1e8 <= rev <= 1e13):
            flags.append(f"rev_suspicious({rev/1e8:.2f}亿)")
        if not (-1e12 <= npp <= 1e12):
            flags.append(f"npp_suspicious({npp/1e8:.2f}亿)")
        if not (1e8 <= ta <= 1e13):
            flags.append(f"ta_suspicious({ta/1e8:.2f}亿)")
        if not (1e8 <= eq <= 1e13):
            flags.append(f"eq_suspicious({eq/1e8:.2f}亿)")
        return {
            "status": "OK" if not flags else "SUSPICIOUS",
            "years": len(years),
            "last": last,
            "rev": rev / 1e8,
            "npp": npp / 1e8,
            "ta": ta / 1e8,
            "eq": eq / 1e8,
            "flags": flags,
        }
    except Exception as e:
        return {"status": "ERR", "err": f"{type(e).__name__}: {e}"}


def main():
    companies = sorted(os.listdir(BASE))
    ok, suspicious, bad = [], [], []
    for c in companies:
        d = os.path.join(BASE, c)
        if not os.path.isdir(d):
            continue
        company_name = c.replace("年报", "")
        r = run_one(d)
        if r["status"] == "OK":
            ok.append((company_name, r))
        elif r["status"] == "SUSPICIOUS":
            suspicious.append((company_name, r))
        else:
            bad.append((company_name, r))

    print(f"\n=== {len(ok)} OK ===")
    for n, r in ok:
        print(f"  {n} ({r['years']}y last={r['last']}): "
              f"rev={r['rev']:.2f}亿 npp={r['npp']:.2f}亿 "
              f"ta={r['ta']:.2f}亿 eq={r['eq']:.2f}亿")

    print(f"\n=== {len(suspicious)} SUSPICIOUS ===")
    for n, r in suspicious:
        print(f"  {n} ({r['last']}): {r['flags']} | "
              f"rev={r['rev']:.4f}亿 npp={r['npp']:.4f}亿 "
              f"ta={r['ta']:.4f}亿 eq={r['eq']:.4f}亿")

    print(f"\n=== {len(bad)} BAD ===")
    for n, r in bad:
        print(f"  {n}: {r}")


if __name__ == "__main__":
    main()
