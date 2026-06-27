"""
巨潮资讯网 (cninfo.com.cn) 定期报告下载器

用法:
  python fetch_reports.py <公司名或代码> [报告类型] [--output DIR] [--list-only] [--since YEAR]

示例:
  python fetch_reports.py 盐湖股份                       # 全部年报
  python fetch_reports.py 盐湖股份 全部                  # 全部定期报告(年/半年/一季/三季)
  python fetch_reports.py 盐湖股份 半年报                 # 仅半年报
  python fetch_reports.py 000792 年报 --since 2020       # 仅 2020 年及以后
  python fetch_reports.py 贵州茅台 年报 --list-only       # 只列出不下载
  python fetch_reports.py 盐湖股份 年报 --output "D:\\custom\\dir"

依赖: requests  (pip install requests)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime


def normalize_company_name(name: str) -> str:
    """
    规范化公司名用于目录/文件名：
    - 全角拉丁字母/数字 → 半角 (NFKC)
      京东方Ａ → 京东方A
      ＣＳＣ → CSC
    避免下游 skill (financial-metrics) 因大小/全半角差异匹配目录失败。
    中文标点（：、（）等）保留不变。
    """
    if not name:
        return name
    return unicodedata.normalize("NFKC", name)
from typing import Iterable

# Windows GBK 终端兼容: 强制 stdout 用 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

# ===== 接口配置 =====
SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
ANNOUNCE_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "http://static.cninfo.com.cn/"
DEFAULT_OUTPUT_ROOT = os.path.join(os.getcwd(), "年报")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 报告类型 → cninfo category
CATEGORY_MAP = {
    "年报":   "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
}
ALL_TYPES = ["年报", "半年报", "一季报", "三季报"]

# 公告标题中需要排除的干扰词
EXCLUDE_KEYWORDS = ["摘要", "英文版", "已取消", "更正", "补充", "修订", "更新后", "第二次", "第一次"]


def guess_column(stock_code: str) -> str:
    """根据代码前缀推断交易所 column 值。6 字头 = 上交所，其余 = 深交所。"""
    return "sse" if stock_code.startswith("6") else "szse"


# ===== Step 1: 公司名 → 股票代码 + orgId =====
def search_company(keyword: str) -> list[dict]:
    """返回匹配的公司列表，含 code/orgId/zwjc/category。"""
    resp = requests.post(
        SEARCH_URL,
        data={"keyWord": keyword, "maxNum": 10},
        headers={"User-Agent": UA},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def resolve_company(keyword: str) -> dict:
    """
    将关键词解析为唯一 A 股公司。
    若有多条 A 股匹配，打印候选让用户选择；若无匹配，抛错。
    """
    results = search_company(keyword)
    if not results:
        raise SystemExit(f"❌ 未找到匹配公司: {keyword}")

    a_stocks = [r for r in results if r.get("category") == "A股"]
    if not a_stocks:
        # 退而求其次：取全部结果的第一条
        print(f"⚠️  未找到 A 股匹配，使用第一条结果: {results[0].get('zwjc')} ({results[0].get('code')})")
        return results[0]
    if len(a_stocks) == 1:
        return a_stocks[0]

    # 多条匹配 — 让用户/调用方选
    print(f"找到 {len(a_stocks)} 个 A 股匹配:")
    for i, s in enumerate(a_stocks):
        print(f"  [{i}] {s['zwjc']} ({s['code']})")
    try:
        choice = input("选择序号 (回车默认 0): ").strip()
        idx = int(choice) if choice else 0
    except (ValueError, KeyboardInterrupt):
        idx = 0
    return a_stocks[idx]


# ===== Step 2: 公告查询 =====
def query_announcements(stock_code: str, org_id: str, category: str,
                        start_date: str = "", end_date: str = "",
                        page_size: int = 50) -> list[dict]:
    """查询某 category 的全部公告，自动翻页。"""
    column = guess_column(stock_code)
    se_date = f"{start_date}~{end_date}" if (start_date or end_date) else ""
    all_anns: list[dict] = []
    page_num = 1

    while True:
        resp = requests.post(
            ANNOUNCE_URL,
            data={
                "pageNum": page_num,
                "pageSize": page_size,
                "column": column,
                "tabName": "fulltext",
                "stock": f"{stock_code},{org_id}",
                "category": category,
                "seDate": se_date,
                "isHLtitle": "true",
            },
            headers={"User-Agent": UA},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        anns = data.get("announcements") or []
        if not anns:
            break
        all_anns.extend(anns)
        if len(all_anns) >= data.get("totalAnnouncement", 0):
            break
        page_num += 1
        time.sleep(0.5)

    return all_anns


def filter_reports(announcements: Iterable[dict], report_type: str) -> list[dict]:
    """
    从原始公告列表筛选出正式报告。
    - 必须含 "年度报告" / "半年度报告" / "季度报告" 等关键字
    - 排除摘要、英文版、已取消、更正等
    - 标题必须形如 "XXXX年年度报告"
    """
    type_keyword = {
        "年报": "年度报告",
        "半年报": "半年度报告",
        "一季报": "第一季度报告",
        "三季报": "第三季度报告",
    }[report_type]

    out = []
    for ann in announcements:
        title = ann.get("announcementTitle", "")
        if type_keyword not in title:
            continue
        if any(kw in title for kw in EXCLUDE_KEYWORDS):
            continue
        # 形式检查: 必须含 "XXXX年"
        if not re.search(r"\d{4}年", title):
            continue
        out.append(ann)
    return out


# ===== Step 3: PDF 下载 =====
def download_pdf(adjunct_url: str, save_path: str) -> int:
    url = PDF_BASE + adjunct_url
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=120, stream=True)
    resp.raise_for_status()
    total = 0
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                total += len(chunk)
    return total


# ===== 文件名规范化 =====
def build_filename(company: str, report_type: str, ann: dict) -> str:
    """生成 {公司}_{年份}年{报告类型}.pdf"""
    title = ann.get("announcementTitle", "")
    year_match = re.search(r"(\d{4})年", title)
    year = year_match.group(1) if year_match else "unknown"
    return f"{company}_{year}年{report_type}.pdf"


# ===== 本地已下载扫描（用于增量下载） =====
# 兼容多种文件名格式，提取 (年份, 报告类型)
FILE_PATTERN = re.compile(
    r"(?P<year>\d{4})\s*年\s*(?P<type>年报|半年报|一季报|三季报|第一季度报告|第三季度报告|半年度报告|年度报告)",
)


def scan_existing(save_dir: str) -> dict[tuple[int, str], str]:
    """
    扫描目录下已下载的 PDF，返回 {(year, report_type): filepath}。
    兼容历史文件名（如 "盐湖股份_2023年年度报告.pdf"、"盐湖股份_2023年年度报告.PDF"、
    "盐湖股份2023年年度报告.pdf" 等格式）。
    """
    type_alias = {
        "年度报告": "年报",
        "半年度报告": "半年报",
        "第一季度报告": "一季报",
        "第三季度报告": "三季报",
    }
    existing: dict[tuple[int, str], str] = {}
    if not os.path.isdir(save_dir):
        return existing

    for name in os.listdir(save_dir):
        if not name.lower().endswith(".pdf"):
            continue
        m = FILE_PATTERN.search(name)
        if not m:
            continue
        year = int(m.group("year"))
        rtype = m.group("type")
        rtype = type_alias.get(rtype, rtype)
        key = (year, rtype)
        # 同一年份类型有多份时，保留第一份（不覆盖）
        if key not in existing:
            existing[key] = os.path.join(save_dir, name)
    return existing


# ===== 主入口 =====
def main():
    p = argparse.ArgumentParser(
        description="巨潮资讯网定期报告下载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("company", help="公司名或股票代码 (如 盐湖股份 / 000792)")
    p.add_argument("report_type", nargs="?", default="年报",
                   choices=["年报", "半年报", "一季报", "三季报", "全部"],
                   help="报告类型，默认 '年报'；'全部' 下载全部四类")
    p.add_argument("--output", default="",
                   help=f"输出目录，默认 {DEFAULT_OUTPUT_ROOT}\\<公司名>年报\\")
    p.add_argument("--since", type=int, default=0,
                   help="仅下载此年份及以后的报告 (如 --since 2020)")
    p.add_argument("--list-only", action="store_true",
                   help="只列出报告不下载")
    p.add_argument("--start-date", default="", help="起始日期 YYYY-MM-DD")
    p.add_argument("--end-date", default="", help="结束日期 YYYY-MM-DD")
    args = p.parse_args()

    # 1) 解析公司
    print(f"=== 搜索公司: {args.company} ===")
    company_info = resolve_company(args.company)
    stock_code = company_info["code"]
    org_id = company_info["orgId"]
    company_name = normalize_company_name(company_info["zwjc"])
    print(f"✅ {company_name} ({stock_code}), orgId={org_id}")

    # 2) 决定要下载哪些类型
    types = ALL_TYPES if args.report_type == "全部" else [args.report_type]

    # 3) 输出目录
    if args.output:
        save_root = args.output
    else:
        save_root = os.path.join(DEFAULT_OUTPUT_ROOT, f"{company_name}年报")
    os.makedirs(save_root, exist_ok=True)
    print(f"📂 保存到: {save_root}")

    # 4) 收集所有要下载的报告
    all_tasks = []  # [(report_type, ann), ...]
    for rt in types:
        category = CATEGORY_MAP[rt]
        print(f"\n=== 查询 {rt} (category={category}) ===")
        anns = query_announcements(
            stock_code, org_id, category,
            start_date=args.start_date, end_date=args.end_date,
        )
        reports = filter_reports(anns, rt)
        # 去重 (cninfo 偶尔返回重复记录，按 adjunctUrl 去重)
        seen = set()
        deduped = []
        for r in reports:
            key = r.get("adjunctUrl") or r.get("announcementId")
            if key and key not in seen:
                seen.add(key)
                deduped.append(r)
        reports = deduped
        # 按时间倒序
        reports.sort(key=lambda a: a.get("announcementTime", 0), reverse=True)
        # 按年份过滤
        if args.since:
            reports = [r for r in reports
                       if _year_of(r) is None or _year_of(r) >= args.since]
        print(f"  共 {len(anns)} 条原始 → 筛选后 {len(reports)} 份")
        for r in reports:
            all_tasks.append((rt, r))

    if not all_tasks:
        print("\n⚠️  没有匹配的报告")
        return

    # 4.5) 扫描本地已下载，做增量过滤
    existing = scan_existing(save_root)
    if existing:
        print(f"\n=== 本地已下载 ({len(existing)} 份) ===")
        # 按年份倒序展示
        for (yr, rt) in sorted(existing.keys(), reverse=True):
            print(f"  ✓ {yr} 年 {rt}")
        # 过滤掉本地已存在的
        before = len(all_tasks)
        all_tasks = [(rt, ann) for (rt, ann) in all_tasks
                     if (int(m.group(1)) if (m := re.search(r"(\d{4})年", ann.get("announcementTitle", ""))) else None,
                         rt) not in existing]
        print(f"\n=== 增量过滤: 远程 {before} 份 - 本地已下载 {before - len(all_tasks)} 份 = 待下载 {len(all_tasks)} 份 ===")

    if not all_tasks:
        print("\n✅ 本地已是最新，无需下载")
        return

    # 5) 打印清单
    print(f"\n=== 待{'下载' if not args.list_only else '列出'}清单 ({len(all_tasks)} 份) ===")
    for rt, ann in all_tasks:
        ts = ann.get("announcementTime", 0) / 1000
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
        size_kb = ann.get("adjunctSize", 0)
        print(f"  [{date_str}] [{rt}] {ann['announcementTitle']}  ({size_kb} KB)")

    if args.list_only:
        print("\n--list-only 模式，不下载")
        return

    # 6) 下载
    print(f"\n=== 开始下载 ===")
    ok, failed = 0, 0
    for rt, ann in all_tasks:
        filename = build_filename(company_name, rt, ann)
        save_path = os.path.join(save_root, filename)

        # 双保险：增量过滤后理论上不会重复，但仍检查文件
        if os.path.exists(save_path):
            print(f"  ⏭️  跳过(已存在): {filename}")
            continue

        adj_url = ann.get("adjunctUrl", "")
        if not adj_url:
            print(f"  ❌ 无下载链接: {filename}")
            failed += 1
            continue

        try:
            print(f"  ⬇️  {filename} ...", end=" ", flush=True)
            n = download_pdf(adj_url, save_path)
            print(f"✅ {n/1024/1024:.1f} MB")
            ok += 1
        except Exception as e:
            print(f"❌ {e}")
            failed += 1
            if os.path.exists(save_path):
                os.remove(save_path)
        time.sleep(1)  # 礼貌延迟

    print(f"\n=== 完成: 本次下载 {ok} | 失败 {failed} ===")
    print(f"📂 目录: {save_root}")


def _year_of(ann: dict) -> int | None:
    m = re.search(r"(\d{4})年", ann.get("announcementTitle", ""))
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    main()
