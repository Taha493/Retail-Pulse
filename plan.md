# Power BI Portfolio Project — Built on Linux (CachyOS)

> **Goal:** Build a full BI project, from getting the data to the finished dashboard: **ingest → clean → model → measure → visualize**. It should show the same skills a Power BI developer is hired for (Power Query style transforms, a star schema, DAX measures, report design), even though Power BI Desktop doesn't run on Linux.

> **Status (2026-10-25): built.** `make all` rebuilds the pipeline, `make dashboard` serves the report, and all 48 tests pass.
> Still to do (needs your accounts or a Windows machine): deploy the live demo (`Dockerfile` is ready, but its build hasn't been tested), record the walkthrough GIF, push to GitHub, and build the real `.pbix` (see `powerbi/REBUILD_IN_POWERBI.md`).
> Deviation from the plan below: the Python code lives in the package `src/retail_bi/` (ingest/transform/model/validate/measures) instead of top-level `src/ingest/` etc.

---

## 0. The core problem & how we solve it

| Power BI step | What Power BI uses | What we use on CachyOS | Portfolio artifact |
|---|---|---|---|
| Get Data | Power Query connectors | Python ingestion scripts (HTTP/API) | `src/ingest/` |
| Transform | Power Query (M) | Python (Polars) + DuckDB SQL | `src/transform/` + equivalent `.pq` M scripts |
| Data Model | Model view (star schema, relationships) | DuckDB warehouse + Parquet/CSV star schema | `data/gold/` + ER diagram |
| Measures | DAX | DAX written in `.dax` files **plus** Python/SQL equivalents | `powerbi/measures.dax` |
| Report | Report canvas, visuals, slicers, cross-filtering | **Plotly Dash** app styled to look and behave like a Power BI report | `dashboard/` |
| Theme | Theme JSON | A real Power BI `theme.json` that the Dash app also reads | `powerbi/theme.json` |
| Publish | Power BI Service | Free hosting (Hugging Face Spaces / Render) + screenshots/GIF | Live link in README |

**Key idea:** the `data/gold/` output is the actual Power BI input. Anyone who opens Power BI Desktop can do *Get Data → Folder/Parquet*, apply `theme.json`, paste the measures from `measures.dax`, and rebuild the same report. The Dash app shows what that report looks like.

### Optional: getting real Power BI later (recommended before you apply for jobs)
- **Windows VM on KVM** (`virt-manager` + QEMU, which works well on CachyOS) with the free **Windows 11 Enterprise 90-day evaluation ISO** → install Power BI Desktop → build the real `.pbix` from `data/gold/` in about 1–2 hours, since all the logic is already written.
- Wine/Bottles: **does not work** reliably for Power BI Desktop, so don't spend time on it.
- Power BI Service (web) needs a work/school account, so it's probably not available.

---

## 1. Dataset choice

### Primary: **Online Retail II** (UCI Machine Learning Repository)
- URL: `https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip` (verified reachable)
- ~**1.07 million** invoice lines, UK-based online gift retailer, Dec 2009 → Dec 2011, about 40 countries.
- **Why this one:** it's real, messy transactional data (cancellations, negative quantities, missing customer IDs, duplicates, non-product stock codes, inconsistent descriptions), so the cleaning stage has a lot to show. It's also a sales dataset, which is the most common Power BI job scenario. And it's far less overused than "Superstore".

### Enrichment sources (shows multi-source ingestion from APIs)
| Source | Endpoint | Used for |
|---|---|---|
| **Frankfurter** (ECB FX rates, no key) | `https://api.frankfurter.dev/v1/2009-12-01..2011-12-31?base=GBP&symbols=EUR,USD` | Currency switcher (GBP/EUR/USD), like a Power BI *field parameter* |
| **World Bank API** (no key) | `https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD?date=2010&format=json` (+ `SP.POP.TOTL`) | Country population/GDP → revenue per capita, market sizing |
| **ISO-3166 country list** (GitHub CSV) | `https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.csv` | ISO codes, region and sub-region for map and geo hierarchy |
| **`holidays` Python package** | (offline lib) | UK bank holidays 2009–2011 for `dim_date` (the gov.uk API only covers recent years) |

> Note: `restcountries.com` timed out during planning, so it isn't used.

### Alternatives (if you want a different domain later)
- **NYC TLC Taxi trips** (Parquet, tens of millions of rows): good for showing performance and large-volume handling.
- **Olist Brazilian E-commerce** (Kaggle, needs an account): multi-table relational, reviews, delivery times.

---

## 2. Tech stack

| Layer | Tool | Why |
|---|---|---|
| Env/packaging | `uv` (already installed) + Python 3.12/3.13 | Fast, reproducible (`pyproject.toml` + `uv.lock`) |
| Ingestion | `httpx`, `tenacity` (retries) | Simple, robust API calls |
| Transform | **Polars** (+ `openpyxl`/`fastexcel` to read the source xlsx) | Fast; its chained style reads like Power Query steps |
| Warehouse / SQL | **DuckDB** (Python package, no server needed) | Local "SQL Server", star-schema builds, SQL views |
| Validation | **Pandera** (Polars backend) | Data quality tests, like a documented "data profiling" step |
| Dashboard | **Plotly Dash** + `dash-bootstrap-components` / `dash-mantine-components` | Multi-page, slicers, real cross-filtering through callbacks |
| Orchestration | `Makefile` (or `just`) | One command: `make all` |
| Tests/quality | `pytest`, `ruff` | Professional polish |
| Hosting | Hugging Face Spaces (Docker) or Render free tier | Live demo link for recruiters |

> Python 3.14 is installed system-wide. Pin **3.12 or 3.13** with `uv python pin 3.12`, because some data libraries lag behind new Python releases.

---

## 3. Project structure

```
PowerBI/
├── plan.md
├── README.md                    # Portfolio-facing write-up (screenshots, GIF, live link)
├── pyproject.toml / uv.lock
├── Makefile                     # make ingest | transform | model | validate | dashboard | all
├── config/
│   └── settings.yaml            # URLs, date ranges, paths, business rules
├── data/
│   ├── raw/                     # Untouched downloads (gitignored, except a manifest)
│   ├── bronze/                  # Raw → Parquet, typed, no business logic
│   ├── silver/                  # Cleaned, conformed, deduplicated
│   └── gold/                    # ★ Star schema = Power BI input (Parquet + CSV)
├── warehouse/
│   └── retail.duckdb            # DuckDB database with gold tables + views
├── src/
│   ├── ingest/                  # download_retail.py, fetch_fx.py, fetch_worldbank.py, fetch_countries.py
│   ├── transform/               # bronze.py, silver.py (cleaning rules), enrich.py
│   ├── model/                   # build_dims.py, build_facts.py, sql/*.sql
│   ├── validate/                # schemas.py (Pandera), data_quality_report.py
│   └── measures/                # measures.py: Python equivalents of each DAX measure
├── powerbi/
│   ├── theme.json               # Valid Power BI theme file
│   ├── measures.dax             # All DAX measures, documented
│   ├── power_query/*.pq         # M scripts mirroring the Python transforms
│   ├── data_model.md            # Relationships, cardinality, filter direction
│   └── REBUILD_IN_POWERBI.md    # Step-by-step guide to recreate the .pbix
├── dashboard/
│   ├── app.py                   # Dash entrypoint
│   ├── assets/powerbi.css       # Power BI look: canvas, cards, page tabs, fonts
│   ├── components/              # kpi_card.py, slicer.py, visual_container.py, tooltip.py
│   ├── pages/                   # overview.py, sales.py, customers.py, products.py, geography.py
│   └── data_access.py           # Reads gold tables from DuckDB (the "semantic model")
├── docs/
│   ├── images/                  # Screenshots, ER diagram, pipeline diagram, demo GIF
│   └── data_quality_report.html
└── tests/
```

---

## 4. Pipeline: phase by phase

### Phase 1 — Setup (≈ 0.5 day)
- [x] `uv init`, `uv python pin 3.12`, add deps: `polars duckdb httpx tenacity pandera[polars] fastexcel openpyxl holidays dash dash-bootstrap-components plotly pyyaml pytest ruff`
- [x] `git init`, `.gitignore` (`data/raw`, `data/bronze`, `warehouse/*.duckdb`, `.venv`)
- [x] `config/settings.yaml` with all URLs and business rules (no hard-coded constants in the code)
- [x] `Makefile` skeleton

### Phase 2 — Data gathering / ingestion (≈ 0.5 day) → `data/raw/`
- [x] `download_retail.py`: download the zip and extract `online_retail_II.xlsx` (2 sheets: `Year 2009-2010`, `Year 2010-2011`)
- [x] `fetch_fx.py`: daily GBP→EUR/USD rates for the whole date range → `fx_rates.json`
- [x] `fetch_worldbank.py`: population + GDP per capita (2010, 2011), paginated → `worldbank.json`
- [x] `fetch_countries.py`: ISO-3166 CSV → `countries.csv`
- [x] Write `data/raw/_manifest.json`: source URL, download timestamp, file size, SHA-256, row count (data lineage, which reviewers like)
- [x] Make every script **idempotent**: skip the download if the file exists and the checksum matches; retry with backoff

### Phase 3 — Bronze layer (≈ 0.5 day) → `data/bronze/*.parquet`
Mirrors the Power Query steps *Promote Headers → Changed Type*.
- [x] Read both Excel sheets and **append** them (Power Query: *Append Queries*)
- [x] Standardise column names to snake_case: `invoice, stock_code, description, quantity, invoice_date, price, customer_id, country`
- [x] Explicit dtypes (`invoice` as string, because of the "C" prefix; `customer_id` as nullable int; `invoice_date` as datetime)
- [x] Add `_source_sheet`, `_ingested_at` lineage columns
- [x] Convert the Excel file to Parquet once, since Excel reads are slow and every later step reads Parquet

### Phase 4 — Data cleaning: silver layer (≈ 1.5 days) → `data/silver/`
This is the main showcase step, so **log every rule and how many rows it affected** (this feeds the data quality report).

| # | Issue in Online Retail II | Rule |
|---|---|---|
| 1 | Exact duplicate rows (~34k) | Drop, count logged |
| 2 | Whitespace / casing in `description`, `stock_code` | Trim, upper-case codes, collapse double spaces |
| 3 | Cancellations: `invoice` starts with `C` and negative quantity | Keep, but flag `is_cancellation = true` → separate returns analysis instead of deleting |
| 4 | Non-product stock codes (`POST`, `DOT`, `M`, `D`, `C2`, `BANK CHARGES`, `AMAZONFEE`, `PADS`, `TEST*`, `ADJUST*`, `S`, `B`, `gift_*`) | Flag `line_type` = `product` / `postage` / `fee` / `adjustment` / `test`; dashboards default to `product` |
| 5 | `price <= 0` (free samples, bad-debt adjustments) | Exclude from revenue and flag; keep a count in the DQ report |
| 6 | Missing `customer_id` (~20–25%) | Keep for revenue totals; label as `Guest` (key `-1`), exclude from customer/RFM/cohort analytics |
| 7 | Same `stock_code` with several descriptions | Keep the most frequent description as the canonical `product_name` |
| 8 | Extreme outliers (e.g. the 80,995-unit order and its immediate cancellation) | Detect with IQR/z-score per product; match order/cancel pairs and neutralise them; document it |
| 9 | Country names not matching ISO (`EIRE`, `RSA`, `USA`, `Channel Islands`, `European Community`, `Unspecified`, `West Indies`) | Mapping table → ISO-3166 alpha-2/3; `Unspecified` → `Unknown` |
| 10 | Unmatched returns (return with no original sale inside the window) | Flag for the DQ report |

- [x] Derived columns: `line_revenue_gbp = quantity * price`, `invoice_date_key` (yyyymmdd), `invoice_hour`
- [x] **Product categorisation** (the dataset has no categories): keyword rules on description (e.g. `BAG`, `CANDLE`, `MUG|CUP`, `CHRISTMAS`, `LIGHT|LAMP`, `CARD`, `HEART`…) → `category`, `sub_category`; target >85% coverage, the rest goes to `Other`. This is real business logic, which reviewers like to see.
- [x] **Pandera schemas** after each layer: column types, non-null keys, value ranges, uniqueness
- [x] Generate `docs/data_quality_report.html`: rows in/out per rule, null % per column, before/after charts

### Phase 5 — Processing & enrichment (≈ 0.5 day)
- [x] Join FX rates by date (forward-fill weekends/holidays, as you would in Power Query) → `line_revenue_eur`, `line_revenue_usd`
- [x] Join World Bank and ISO data to countries → `region`, `sub_region`, `population`, `gdp_per_capita`
- [x] Customer-level features: first purchase date, cohort month, recency/frequency/monetary, **RFM scores (1–5) → segments** (Champions, Loyal, At Risk, Hibernating, New…)
- [x] Product-level: ABC classification (Pareto: A = top 80% revenue)

### Phase 6 — Data modelling: gold star schema (≈ 1 day) → `data/gold/` + DuckDB
This is exactly what Power BI imports.

```
                 dim_date
                    │ 1
                    │
dim_customer 1──* fact_sales *──1 dim_product
                    │ *
                    │ 1
               dim_country ──(snowflake-free: region columns flattened in)
                    
fact_fx_rates (date_key, currency, rate)  ── used by currency switcher measure
```

| Table | Grain | Key columns |
|---|---|---|
| `fact_sales` | One invoice line | `sales_key, invoice_no, date_key, customer_key, product_key, country_key, quantity, unit_price_gbp, revenue_gbp, revenue_eur, revenue_usd, is_cancellation, line_type` |
| `dim_date` | One day, 2009-12-01 → 2011-12-31 (continuous; Power BI date tables need this) | `date_key, date, year, quarter, month_num, month_name, month_year, week_iso, weekday_name, is_weekend, is_uk_holiday, fiscal_year` |
| `dim_customer` | One customer (+ `-1` Guest) | `customer_key, customer_id, country, first_purchase_date, cohort_month, rfm_segment, r/f/m scores, lifetime_revenue` |
| `dim_product` | One stock code | `product_key, stock_code, product_name, category, sub_category, abc_class, avg_unit_price` |
| `dim_country` | One country | `country_key, country_name, iso2, iso3, region, sub_region, population, gdp_per_capita` |
| `fact_fx_rates` | Day × currency | `date_key, currency, rate_from_gbp` |

- [x] Surrogate integer keys, every relationship one-to-many, single filter direction (Power BI best practice)
- [x] Export each table as **Parquet and CSV** to `data/gold/`
- [x] Load into `warehouse/retail.duckdb` + create SQL views (`vw_monthly_sales`, `vw_cohort_retention`, …)
- [x] `powerbi/data_model.md` + ER diagram image (Mermaid → PNG in `docs/images/`)

### Phase 7 — Semantic layer: DAX measures + Python equivalents (≈ 1 day)
Write each measure **twice**: real DAX in `powerbi/measures.dax` (the Power BI deliverable) and a matching function in `src/measures/measures.py` that the dashboard uses. Add a test that checks a few known values so the two stay in sync.

Measures to implement (grouped like display folders):
- **Core:** `Total Revenue`, `Total Orders` (DISTINCTCOUNT invoice), `Units Sold`, `Avg Order Value`, `Active Customers`, `Revenue per Customer`
- **Returns:** `Return Value`, `Return Rate %`, `Net Revenue`
- **Time intelligence:** `Revenue PY`, `Revenue YoY %`, `Revenue MTD/QTD/YTD`, `Revenue MoM %`, `Rolling 3M Revenue`
- **Customer:** `New Customers`, `Returning Customers`, `Repeat Purchase Rate`, `Cohort Retention %`, `Customer Lifetime Value`
- **Product:** `Revenue Rank` (RANKX), `Cumulative Revenue %` (Pareto), `Product Share %`
- **Geo:** `Revenue per 1M Population`
- **Dynamic:** `Selected Currency Revenue` (SWITCH over a currency slicer, like a field parameter), dynamic chart titles

Example of the documentation style in `measures.dax`:
```DAX
-- Revenue YoY % : growth vs same period last year (needs marked date table)
Revenue YoY % =
VAR _cy = [Total Revenue]
VAR _py = CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( _cy - _py, _py )
```

- [x] Also write `powerbi/power_query/*.pq`: M versions of the key cleaning steps (append sheets, flag cancellations, country mapping). This shows Power Query skill directly.

### Phase 8 — Dashboard: Power BI replica in Dash (≈ 3 days)

#### 8a. Power BI look & feel (`assets/powerbi.css` + components)
- [x] 16:9 **report canvas** (1280×720 logical) centred on a light grey background, white visual containers with subtle borders and padding, as in Power BI
- [x] **Page tabs at the bottom** (like Power BI's page navigator) + a top header bar with report title and last refresh time
- [x] Font: Segoe UI fallback stack (`"Segoe UI", "Selawik", "Open Sans", sans-serif`); Selawik is Microsoft's open-source Segoe UI metric clone
- [x] Colours read from `powerbi/theme.json`, so one file defines the theme for both Power BI and Dash
- [x] Reusable components: `KpiCard` (value + delta vs PY with ▲/▼ colour + sparkline), `Slicer` (dropdown / date-range / tile buttons), `VisualContainer` (title, "…" menu with *Export data → CSV* and *Focus mode*)
- [x] Plotly template matching Power BI defaults: no gridline clutter, light axis lines, data labels where useful, Power BI-style tooltips

#### 8b. Power BI behaviours to recreate
- [x] **Slicers** that sync across pages (Date range, Country/Region, Category, Customer Segment, Currency)
- [x] **Cross-filtering**: clicking a bar or map country filters the other visuals on the page (Dash `clickData` → shared filter store)
- [x] **Drill-down** on the date hierarchy (Year → Quarter → Month → Day) with drill up/down buttons
- [x] **Report-page tooltip** on hover over a country (mini-chart)
- [x] "Clear all slicers" button and an active-filters summary chip bar
- [x] Conditional formatting in tables (data bars, colour scales), like Power BI matrix visuals

#### 8c. Report pages
1. **Executive Overview**: KPI cards (Revenue, Orders, AOV, Customers, Return Rate, each with YoY), revenue trend line with PY comparison, revenue by region (filled map), top 10 products bar, revenue by category donut *(built as a bar chart: 13 categories is too many for a donut)*
2. **Sales Performance**: monthly revenue + MoM combo chart (column + line) *(built as two charts: drill-down columns and a separate MoM chart, because a dual axis misleads)*, weekday × hour **heatmap** (best time to sell), MTD/QTD/YTD cards, waterfall of YoY change by category
3. **Customer Analytics**: RFM segment treemap, **cohort retention matrix** (heatmap table), new vs returning stacked area, CLV distribution, top customers matrix
4. **Product Analytics**: **Pareto chart** (ABC analysis), category → sub-category → product decomposition (sunburst/treemap as a decomposition-tree stand-in), return-rate scatter (revenue vs return %), price band analysis
5. **Geography**: choropleth world map, country ranking table with data bars, revenue per capita vs GDP scatter, UK vs International split
6. **Data Quality** (bonus page): pipeline funnel (raw rows → clean rows by rule), null %, freshness, which shows data-engineering awareness

#### 8d. Performance
- [x] Pre-aggregate in DuckDB (month × country × category, etc.) so callbacks stay under 200 ms on ~1M rows. *Built as a materialised wide `mart_sales` table instead; a full KPI evaluation takes about 50 ms.*
- [ ] Cache with `flask-caching` / `functools.lru_cache` keyed on the filter state. *Skipped: queries were already fast enough.*

### Phase 9 — Testing & quality (≈ 0.5 day)
- [x] `pytest`: cleaning rules (unit tests with small fixtures), gold referential integrity (every FK exists in its dim), measure correctness against hand-calculated values
- [x] `ruff` lint/format; type hints
- [x] `make all` runs end to end from an empty `data/` folder (reproducibility check)

### Phase 10 — Portfolio packaging (≈ 1 day)
- [x] **README.md** (what recruiters read): business problem → architecture diagram → data model → key insights (3–5 bullet findings with numbers) → screenshots per page → demo GIF → "How to rebuild in Power BI" → how to run locally
- [x] `powerbi/REBUILD_IN_POWERBI.md`: Get Data → Parquet folder, mark `dim_date` as the date table, create relationships, paste measures, import `theme.json`, build the pages to match the screenshots
- [ ] Deploy the Dash app (Hugging Face Spaces, Docker SDK, free) and put the live link at the top of the README
- [ ] Record a 60–90 s walkthrough GIF/video (OBS or `peek` on Linux)
- [ ] Push to GitHub with a clean commit history and topics: `power-bi`, `dax`, `data-modeling`, `etl`, `dashboard`
- [ ] (Later) Build the real `.pbix` in a Windows VM and add it to the repo, replacing "replica" with "Power BI + web replica"

---

## 5. Timeline (about 10–12 working days part-time)

| Days | Phases |
|---|---|
| 1 | Setup, ingestion, bronze |
| 2–3 | Cleaning (silver), data quality report |
| 4 | Enrichment, RFM, ABC |
| 5 | Star schema, DuckDB, data model docs |
| 6 | DAX + Python measures, Power Query scripts |
| 7–9 | Dashboard (look & feel → pages → interactivity) |
| 10 | Tests, performance |
| 11–12 | README, deploy, GIF, polish |

---

## 6. Definition of done
- [x] `make all` rebuilds everything from the internet sources with zero manual steps
- [x] `data/gold/` holds a clean star schema that loads straight into Power BI
- [x] `measures.dax` holds 25+ documented measures, including time intelligence and RANKX
- [x] The Dash replica has 5–6 pages with synced slicers, cross-filtering, drill-down and KPI cards with YoY
- [x] The data quality report documents every cleaning rule with row counts
- [ ] Live demo link + README with insights and screenshots
- [x] All tests pass

---

## 7. Possible extensions (stand-out extras)
- **Incremental refresh simulation**: partition the fact table by month and add only new partitions
- **Row-level security demo**: a "Region Manager" login that limits the data (mirrors Power BI RLS roles and `USERPRINCIPALNAME()`)
- **Forecasting**: 3-month revenue forecast (statsmodels/Prophet) shown with a confidence band, like Power BI's analytics pane
- **dbt-duckdb** for the SQL layer (adds analytics-engineering keywords to your CV)
- **GitHub Actions** CI running tests + `ruff` on each push *(done: `.github/workflows/ci.yml`)*
