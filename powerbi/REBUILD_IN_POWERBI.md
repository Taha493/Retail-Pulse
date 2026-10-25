# Rebuilding the report in Power BI Desktop

Everything Power BI needs is already in this repo: the data model, measures, theme and page layouts. Once you have Power BI Desktop (Windows, or a Windows VM on Linux, see below), the `.pbix` takes about **1–2 hours** to build.

## 0. Get a Windows machine (Linux users)

1. Install KVM: `sudo pacman -S qemu-full virt-manager dnsmasq` (CachyOS/Arch), then `sudo systemctl enable --now libvirtd`.
2. Download the free **Windows 11 Enterprise evaluation** ISO (90 days) from Microsoft's Evaluation Center.
3. Create a VM in virt-manager (4 vCPU, 8 GB RAM, 60 GB disk). Install Windows, then install **Power BI Desktop** from the Microsoft Store.
4. Share the repo folder with the VM (virtiofs or a shared folder), or copy `data/gold/` across.

## 1. Load the data (Get Data)

1. *Home → Transform data → Manage parameters → New*: `SourceFolder` = the path to the repo's `data\` folder.
2. *Get Data → Blank query → Advanced editor*: paste [`power_query/07_Gold_Import.pq`](power_query/07_Gold_Import.pq). Duplicate it for each table: `fact_sales`, `fact_fx_rates`, `dim_date`, `dim_customer`, `dim_product`, `dim_country`, `dim_currency`.
   *Optional, to show Power Query skills:* also add `02`–`06` from [`power_query/`](power_query/). They rebuild the cleaning from the raw Excel file and APIs.
3. Check the types: keys are whole numbers, `revenue_*` are fixed decimal, `is_*` are True/False.

## 2. Model view

1. Create the five relationships listed in [`data_model.md`](data_model.md). All are many-to-one with single direction.
2. Select `dim_date` → *Table tools → Mark as date table* → `date`.
3. Sort by column: `month_year` by `month_start`, `weekday_name` by `weekday_num`, `quarter` by `quarter_num`.
4. Hide the key columns and `fact_fx_rates` from report view.
5. *Modeling → New table*: `Cohort Offset = GENERATESERIES ( 0, 12, 1 )` (for the retention matrix).

## 3. Measures

1. *Home → Enter data* → create an empty table called `_Measures`.
2. Copy each measure from [`measures.dax`](measures.dax) into *New measure*. Set the display folder named in the file's comments.
3. Format strings: currency measures `£#,0` (or dynamic format string `[Currency Symbol] & "#,0"`), percentages `0.0%`.

## 4. Theme

*View → Themes → Browse for themes* → [`theme.json`](theme.json). The web replica uses the same file, so colours match exactly.

## 5. Pages

Build each page to match the screenshots in `docs/images/`. The table maps each web visual to its Power BI visual:

| Page | Web replica visual | Power BI visual | Fields / measures |
|---|---|---|---|
| Executive Overview | KPI cards with sparkline | **Card (new)** with reference label + sparkline | `Net Revenue`, `Net Revenue YoY %`, `KPI Delta Color` |
| | Revenue vs PY line | Line chart | `dim_date[month_start]`, `Net Revenue`, `Net Revenue PY` |
| | Map | Filled map (or Azure Map) | `dim_country[country_name]`, `Net Revenue` |
| | Category / top products bars | Clustered bar | `dim_product[category]` / Top N filter on `product_name` |
| Sales Performance | MTD/QTD/YTD tiles | Card | `Net Revenue MTD/QTD/YTD` |
| | Date hierarchy drill-down | Column chart with **drill mode on** | `dim_date` Year → Quarter → Month → Date |
| | MoM % | Column chart, conditional colour | `Net Revenue MoM %` |
| | Weekday × hour heatmap | Matrix with background colour scale | rows `weekday_name`, cols `invoice_hour` |
| | YoY waterfall | Waterfall | category = `category`, breakdown, `Net Revenue YoY` |
| | Category matrix | Matrix with data bars + conditional formatting | `category`, `sub_category`, `Net Revenue`, `Net Revenue YoY %` |
| Customer Analytics | RFM treemap | Treemap | `rfm_segment`, `Net Revenue` |
| | Cohort heatmap | Matrix | rows `cohort_month`, cols `Cohort Offset[Value]`, `Cohort Retention %` |
| | New vs returning | Stacked column | `New Customers`, `Returning Customers` |
| Product Analytics | Pareto curve | Line chart (x = `Revenue Rank`) | `Cumulative Revenue %` |
| | Decomposition | **Decomposition tree** | Analyse `Net Revenue` by category → sub-category → product |
| | Returns scatter | Scatter chart | `Total Revenue`, `Return Rate %`, details `product_name` |
| Geography | Country tooltip panel | **Report page tooltip** (page type = Tooltip) | country KPIs + monthly sparkline |
| | League table | Table with data bars | `country_name`, `Net Revenue`, `Product Share %` |
| Data Quality | Rule log | Table from `docs/data_quality_report.html` or the `dq_*` tables | — |

## 6. Interactions

* *Format → Edit interactions*: set the cohort matrix to **None** for the date slicer (the web replica does the same).
* *View → Sync slicers*: sync Date, Region, Country, Category, Segment and Currency across all pages.
* Add a *Clear all slicers* button (Insert → Buttons → Clear all slicers).

## 7. Publish

Save as `retail-insights.pbix` in `powerbi/`. Optionally publish to the Power BI Service with *Publish to web*, which needs a work account.
