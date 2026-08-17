# ds-usage-export (DeepSeek Usage Export Tool) v1.0.6

> [中文版 README](README.md) · English

Solves two pain points of the DeepSeek Open Platform usage dashboard
(https://platform.deepseek.com/usage):

1. **Hourly usage is only visible when selecting a single date** — this tool fetches
   hourly buckets day by day for **any date range** and merges them into a continuous
   hourly series;
2. **The dashboard caps date ranges at 30 days** — this tool automatically chunks any
   range into ≤30-day windows, fetches and merges them, so you can export arbitrary
   historical periods (month by month, full year).

After signing in on platform.deepseek.com (internal login), paste the session
userToken once, then query, preview and export **CSV / Excel / newspaper-style HTML
chart report / official raw data** with one command.

---

## Features

| Feature | Description |
|---|---|
| Reuse login state | Token from browser `localStorage['userToken']` (one-line console command provided), saved to `~/.dsusage/config.json`, shared by CLI & Web |
| One-click export | `dsu go --start X --end Y`: all formats + official raw data + auto-open the HTML report |
| Newspaper-style HTML report | Self-contained `report.html`: masthead + front-page stats (full numbers) + inline-SVG charts (daily cost / token composition / hourly trend / model share / API key ranking) + tables; charts have ****wheel/button zoom** (animated), **hover tooltips** (**click to pin**), and **animations** |
| Hourly detail | `hourly` granularity: per-day 24h windows force hourly buckets from the platform, merged across days |
| Granularity modes | `auto` (single day = hourly, multi-day = server granularity), `hourly`, `daily` |
| Long ranges | Any range auto-chunked at ≤30 days, de-duplicated and merged |
| Official raw data | Calls the platform `usage/export` API, keeps `amount-*.csv` / `cost-*.csv` originals |
| Multi-dimensional summaries | Hourly detail / daily detail / daily summary / model summary / API key summary / cost detail (multi-currency) |
| Export formats | Excel (multi-sheet), CSV (utf-8-sig), HTML chart report, meta.json |
| API key filter | Filter by trackingId |
| CLI + Web | `dsu` subcommands and a local newspaper-style Web UI (http://127.0.0.1:8321) |
| Multi-language | Chinese (default) & English for CLI, HTML report and Web UI; auto-detect or `--lang zh|en` |
| Resilience | Retry with backoff on 429/5xx; clear token-error messages; `dsu diagnose` to inspect platform payloads |

## Screenshots

**Newspaper-style HTML report** (wheel/button zoom, hover & click-to-pin tooltips)

![Chinese report](examples/screenshots/report_zh.png)

![English report](examples/screenshots/report_en.png)

**Local Web UI** (newspaper style, zh/en toggle)

![Web UI](examples/screenshots/webui.png)
## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
# or full install (registers the dsu command)
pip install -e .
```

Dependencies: Python ≥ 3.9, `requests`, `openpyxl` (Excel), `flask` (Web UI).

### 2. Get the userToken

1. Sign in to **platform.deepseek.com** with Chrome/Edge and open the usage page `/usage`;
2. Press `F12` → Console, paste and run (the token is copied to your clipboard):

```js
copy(JSON.parse(localStorage.getItem('userToken')).value)
```

3. Save it:

```bash
dsu login          # interactive paste (hidden input)
# or pass it directly:
dsu login --token <paste-the-token>
```

> ⚠️ The token is equivalent to your account password. Keep it private; the tool only
> stores and uses it locally.

### 3. Verify & Query

```bash
dsu check                  # verify token & show balance
dsu keys                   # list API keys (trackingId / name)

# ⭐ One-click export: Excel + CSV + HTML report + official raw data, auto-opens the report
dsu go --start 2026-06-01 --end 2026-06-30

# Single-day hourly usage (hourly by default, HTML report included)
dsu day --date 2026-07-01

# Date range (auto: single day = hourly, multi-day = server granularity)
dsu range --start 2026-06-01 --end 2026-06-30

# Force hourly (per-day fetch; time grows linearly with day count)
dsu range --start 2026-06-01 --end 2026-06-30 --granularity hourly

# Full year (auto-chunked, with official raw CSV and HTML report)
dsu go --start 2026-01-01 --end 2026-12-31 --granularity daily

# Filter API key / timezone / output dir / format / HTML only
dsu range --start 2026-06-01 --end 2026-06-30 --api-key <trackingId> \
          --tz +08:00 --format html --out ./my_exports

# Force English interface
dsu --lang en go --start 2026-06-01 --end 2026-06-30
```

### 4. Web UI (newspaper style)

```bash
dsu serve                 # default http://127.0.0.1:8321
dsu serve --port 9000 --host 127.0.0.1
```

On the page: paste/verify token → pick range & granularity → fetch preview →
one-click export (incl. HTML chart report) → download files / view history.
Use the **EN** button in the masthead to switch the interface language.

### 5. Windows double-click launch

Two batch files in the project root:

- **`启动Web界面.bat`** — opens the Web UI in the browser (http://127.0.0.1:8321)
- **`一键导出.bat`** — asks for start/end dates (Enter = last 30 days), runs `dsu go`
  and auto-opens the report

## Export Outputs

Each export creates a timestamped subdirectory under `./exports/`:

```
dsu_2026-06-01_2026-06-30_UTC+0800_20260701_120000/
├── report.html           # ⭐ newspaper-style HTML chart report (double-click to open)
├── usage.xlsx            # Excel: info / daily summary / model summary / API key summary / cost …
├── hourly_detail.csv     # hourly detail (when hourly)
├── daily_detail.csv      # daily × model × key detail
├── daily_summary.csv     # daily summary
├── model_summary.csv     # model summary (with cost %)
├── api_key_summary.csv   # API key summary (with cost %)
├── cost_detail.csv       # cost detail (multi-currency)
├── raw_amount-*.csv      # official raw amount export (with --include-raw / go)
├── raw_cost-*.csv        # official raw cost export
└── meta.json             # export metadata (range/tz/granularity/totals/time)
```

## Multi-language

- Languages: **Chinese (default)** and **English**.
- CLI: `dsu --lang en ...`; otherwise auto-detected from `DSU_LANG` env,
  `~/.dsusage/config.json` `lang` field, then system locale.
- HTML report: follows the CLI/Web language at generation time.
- Web UI: masthead **EN / 中文** toggle (remembered in localStorage).
- Note: exported Excel/CSV column headers stay Chinese (data-level artifacts);
  the HTML report and Web preview translate them.

## Project Layout

```
ds-usage-export/
├── dsu.py                # entry (python dsu.py …)
├── pyproject.toml
├── requirements.txt
├── 启动Web界面.bat / 一键导出.bat   # Windows launchers
├── dsusage/
│   ├── api.py            # platform client: by_api_key amount/cost, usage/export zip, summary, keys
│   ├── i18n.py           # zh/en translations
│   ├── parsing.py        # official CSV parsing
│   ├── aggregate.py      # table building (hourly/daily/model/key/cost)
│   ├── exporters.py      # xlsx / csv / raw / meta writers
│   ├── report.py         # newspaper-style HTML report (inline SVG + tooltips + animations)
│   ├── service.py        # orchestration: chunked fetch, raw merge, export
│   ├── cli.py            # command line
│   ├── webapp.py         # Flask web UI
│   └── web/static/index.html
├── examples/report_demo.html   # sample report from synthetic data
├── tests/                # unit tests (synthetic data, no real account needed)
└── docs/
    ├── api-notes.md      # platform internal API research notes
    └── 获取Token.md       # how to obtain the userToken
```

## Development & Tests

```bash
python -m unittest discover -s tests -v
```

Tests use synthetic data and do not require a real account.

## How It Works

The platform usage page calls `/api/v0/usage/by_api_key/amount|cost?start=&end=&tz=`
and gets `bucket=3600` (hourly) for single-day ranges, `bucket=86400` (daily) for
longer ranges; the 30-day cap exists only in the frontend. This tool therefore
requests day by day for hourly buckets and chunks long ranges at 30 days.
See `docs/api-notes.md` for details.

## Version History

- **v1.0.6** (current): wheel zoom (mouse-anchored, animated) + zoom buttons + drag panning; README screenshots.\n- **v1.0.5**: wheel horizontal scroll for dense charts, click-to-pin tooltips, internal DEVELOPMENT.md (local only).\n- **v1.0.4**: multi-language (zh/en), fixed favicon/404 error spam in the web console.
- **v1.0.3**: full-number display, chart hover tooltips, newspaper animations; tag 1.0.3.
- **v1.0.2**: one-click `dsu go`, newspaper-style HTML report, newspaper web UI,
  `api_key` object-structure fix. See [CHANGELOG.md](CHANGELOG.md).
- **v1.0.1**: initial release: login reuse, hourly/daily/multi-dimensional queries,
  CSV/Excel/official raw export, >30-day auto-chunking, API key filter, CLI + Web.

## Disclaimer

This tool wraps the internal Web APIs already exposed by platform.deepseek.com for
personal usage archiving and analysis. Please comply with DeepSeek's terms of
service, keep request rates reasonable, and do not resell or misuse.
