# financial-tools

Two [Claude Code](https://www.anthropic.com/claude-code) skills for working with Chinese A-share annual reports (PDF) — downloading from cninfo and computing financial metrics (DuPont analysis + Altman Z-Score).

Designed for personal use; sensible defaults but easily configurable.

## Skills

| Skill | Purpose |
|---|---|
| [`cninfo-annual-reports`](./cninfo-annual-reports/) | Batch download annual / semi-annual / quarterly reports from [cninfo.com.cn](http://www.cninfo.com.cn/) by company name or ticker |
| [`financial-metrics`](./financial-metrics/) | Compute DuPont 3-factor / 5-factor decomposition + Altman Z-Score from local annual report PDFs |

Both skills work together: the downloader produces PDFs in the layout the metrics calculator expects.

---

## Installation

### Prerequisites

- [Claude Code](https://www.anthropic.com/claude-code) CLI installed
- Python 3.9+
- Dependencies:
  ```bash
  pip install requests pymupdf
  ```

### Steps

1. **Clone this repo** anywhere you like:
   ```bash
   git clone https://github.com/alicexl/financial-tools.git
   cd financial-tools
   ```

2. **Symlink (or copy) each skill into Claude Code's skills directory**:

   **Windows (Git Bash / PowerShell as admin)**:
   ```bash
   # Symlinks let you `git pull` to update skills in place
   mklink /D "C:\Users\<YourUser>\.claude\skills\cninfo-annual-reports" "D:\path\to\financial-tools\cninfo-annual-reports"
   mklink /D "C:\Users\<YourUser>\.claude\skills\financial-metrics"      "D:\path\to\financial-tools\financial-metrics"
   ```

   **Linux / macOS**:
   ```bash
   ln -s "$(pwd)/cninfo-annual-reports" ~/.claude/skills/cninfo-annual-reports
   ln -s "$(pwd)/financial-metrics"     ~/.claude/skills/financial-metrics
   ```

   **Or simply copy** (no symlink, must re-copy to update):
   ```bash
   cp -r cninfo-annual-reports ~/.claude/skills/
   cp -r financial-metrics     ~/.claude/skills/
   ```

3. **Verify** in Claude Code:
   ```
   /skills
   ```
   Both `cninfo-annual-reports` and `financial-metrics` should appear.

4. **(Optional) Configure default paths**:
   - `cninfo-annual-reports/fetch_reports.py`: edit `DEFAULT_OUTPUT_ROOT` (default: `<cwd>/年报/`)
   - `financial-metrics/financial_metrics.py`: edit `DEFAULT_REPORTS_ROOT` (same default)

   Both default to `<current working directory when the script runs>/年报/`.
   In Claude Code, cwd is the directory Claude was launched from. Change if you want a fixed location.

---

## Usage in Claude Code

Once installed, just **talk naturally** — Claude Code auto-triggers the right skill based on your intent.

### Skill 1: Download annual reports

**Triggers** — say any of:
- "帮我下载 贵州茅台 的全部年报"
- "下载 000792 的定期报告"
- "把 盐湖股份 最近 5 年财报拉下来"

**What Claude will run**:
```bash
python ~/.claude/skills/cninfo-annual-reports/fetch_reports.py 贵州茅台
python ~/.claude/skills/cninfo-annual-reports/fetch_reports.py 000792 全部 --since 2020
python ~/.claude/skills/cninfo-annual-reports/fetch_reports.py 盐湖股份 年报 --list-only
```

**Key features**:
- Company name → ticker → orgId auto-resolution (orgId cannot be self-constructed)
- Incremental download (skips already-downloaded years, supports multiple filename formats)
- Filters out summaries / English versions / cancelled announcements
- Categories: 年报 / 半年报 / 一季报 / 三季报 / 全部

**Output**: `<cwd>/年报/<公司名>年报/<公司>_<年份>年年报.pdf`

---

### Skill 2: Compute financial metrics

**Triggers**:
- "算下 盐湖股份 的杜邦分析"
- "芭田股份 的 Z-score 是多少"
- "测下 贵州茅台 的财务健康度"

**What Claude will run**:
```bash
python ~/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份
python ~/.claude/skills/financial-metrics/financial_metrics.py 芭田股份 --latest 3
python ~/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份 --since 2020 --no-report
```

**Output**:
- **Terminal table**: revenue / net profit / total assets / equity + 3-factor / 5-factor / Z-Score, year columns
- **Auto-generated trend analysis**:
  - 3-factor: which factor drives ROE change the most (relative %)
  - 5-factor: tax burden anomalies (突破 100% means tax refund), EBIT margin trend, interest burden stability
  - Z-Score: zone classification + X2 historical losses / X4 leverage / X5 asset turnover observations
- **Markdown report**: `<公司>_财务分析.md` saved next to PDFs

**Default data directory**: `<cwd>/年报/<公司名>年报/` (matches the downloader's output; cwd = Claude Code launch dir)

---

## How They Work Together

```bash
# 1. Download
python ~/.claude/skills/cninfo-annual-reports/fetch_reports.py 盐湖股份

# 2. Analyze (reads what step 1 just downloaded)
python ~/.claude/skills/financial-metrics/financial_metrics.py 盐湖股份
```

Or in Claude Code conversation:

> You: "下载盐湖股份最近 3 年年报，然后做杜邦分析"
>
> Claude: *auto-runs skill 1, then skill 2*

---

## Skill documentation

Each skill folder has its own `SKILL.md` with detailed architecture, common pitfalls, and extension points:

- [`cninfo-annual-reports/SKILL.md`](./cninfo-annual-reports/SKILL.md)
- [`financial-metrics/SKILL.md`](./financial-metrics/SKILL.md)

## Tech notes

- **PDF parsing**: PyMuPDF (`fitz`); section-scoped regex with lookbehind to disambiguate labels like "负债合计" vs "流动负债合计"
- **Cross-year merge**: newest annual report wins for any given year (handles retrospective adjustments)
- **Single-entity fallback**: companies without minority interest (e.g., 芭田股份) fall back to "净利润" / "所有者权益合计"
- **No external API keys needed**: cninfo's endpoints are open; only standard `requests` for HTTP

## Limitations

- A-share only (cninfo covers Shenzhen + Shanghai exchanges)
- Annual reports only (not interim/quarterly — different PDF structure)
- Z-Score uses **book equity** for X4, not market cap (to avoid requiring stock price input)
- Trend analysis is rule-based; for nuanced qualitative analysis, ask Claude directly

## License

[MIT](./LICENSE)
