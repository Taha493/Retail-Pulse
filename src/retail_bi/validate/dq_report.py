"""Render docs/data_quality_report.html from the rule log and validation results."""

from __future__ import annotations

import html
from datetime import datetime

import plotly.graph_objects as go
import polars as pl

from retail_bi.config import get_logger, paths

log = get_logger(__name__)

ACCENT = "#118DFF"
FONT = "Segoe UI, Selawik, Open Sans, sans-serif"


def _fig_html(fig: go.Figure) -> str:
    fig.update_layout(
        font_family=FONT,
        margin=dict(l=10, r=10, t=40, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=380,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False})


def _table(df: pl.DataFrame, num_cols: tuple[str, ...] = ()) -> str:
    head = "".join(f"<th>{html.escape(c.replace('_', ' ').title())}</th>" for c in df.columns)
    body = []
    for row in df.iter_rows(named=True):
        cells = []
        for c, v in row.items():
            if c in num_cols and isinstance(v, (int, float)):
                cells.append(f'<td class="num">{v:,.0f}</td>')
            elif c == "status":
                cells.append(f'<td><span class="pill {str(v).lower()}">{v}</span></td>')
            else:
                cells.append(f"<td>{html.escape(str(v if v is not None else ''))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def run() -> None:
    p = paths()
    rules = pl.read_parquet(p.silver / "rule_log.parquet")
    checks = pl.read_parquet(p.silver / "validation_results.parquet")
    bronze = pl.read_parquet(p.bronze / "retail.parquet")
    lines = pl.read_parquet(p.silver / "retail_lines.parquet")

    raw_rows = bronze.height
    removed = rules.filter(pl.col("action") == "removed")["rows_affected"].sum()
    final = rules.filter(pl.col("action") == "final")["rows_affected"].item()

    # Funnel: raw -> deduplicated -> product lines -> analysis-ready
    dedup = raw_rows - removed
    products = lines.filter(pl.col("line_type") == "product").height
    funnel = go.Figure(
        go.Funnel(
            y=["Raw rows", "After de-duplication", "Product lines", "Analysis-ready"],
            x=[raw_rows, dedup, products, final],
            textinfo="value+percent initial",
            marker_color=[ACCENT, "#3CA0FF", "#6CB8FF", "#12239E"],
        )
    )
    funnel.update_layout(title="Row funnel")

    nulls = (
        bronze.select(
            [(pl.col(c).null_count() / pl.len() * 100).alias(c) for c in bronze.columns if not c.startswith("_")]
        )
        .unpivot(variable_name="column", value_name="null_pct")
        .sort("null_pct")
    )
    null_fig = go.Figure(
        go.Bar(
            x=nulls["null_pct"].to_list(),
            y=nulls["column"].to_list(),
            orientation="h",
            marker_color=ACCENT,
            text=[f"{v:.1f}%" for v in nulls["null_pct"]],
            textposition="outside",
        )
    )
    null_fig.update_layout(title="Null % per column (bronze)", xaxis_ticksuffix="%")

    line_types = lines.group_by("line_type").agg(pl.len().alias("rows")).sort("rows")
    lt_fig = go.Figure(
        go.Bar(
            x=line_types["rows"].to_list(), y=line_types["line_type"].to_list(), orientation="h", marker_color="#E66C37"
        )
    )
    lt_fig.update_layout(title="Line types after classification", xaxis_type="log")

    country_map = (
        lines.filter(pl.col("country") != pl.col("country_iso3"))
        .group_by("country", "country_iso3")
        .agg(pl.len().alias("rows"))
        .sort("rows", descending=True)
        .head(12)
    )

    kpis = [
        ("Raw rows", f"{raw_rows:,}"),
        ("Rows removed", f"{removed:,}"),
        ("Analysis-ready", f"{final:,}"),
        ("Contracts passed", f"{(checks['status'] == 'PASS').sum()}/{checks.height}"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{k}</div></div>' for k, v in kpis)

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Data Quality Report</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
:root {{ --bg:#F3F2F1; --card:#fff; --ink:#252423; --muted:#605E5C; --line:#E1DFDD; --accent:{ACCENT}; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-family:{FONT}; }}
header {{ background:#fff; border-bottom:1px solid var(--line); padding:18px 24px; }}
header h1 {{ margin:0; font-size:22px; font-weight:600; }} header p {{ margin:4px 0 0; color:var(--muted); font-size:13px; }}
main {{ max-width:1200px; margin:0 auto; padding:20px 16px 40px; display:grid; gap:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:4px; padding:16px; overflow-x:auto; }}
.card h2 {{ margin:0 0 12px; font-size:15px; font-weight:600; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; }}
.kpi {{ background:#fff; border:1px solid var(--line); border-radius:4px; padding:16px; }}
.kpi .v {{ font-size:28px; font-weight:600; }} .kpi .l {{ color:var(--muted); font-size:13px; }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:16px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th {{ text-align:left; color:var(--muted); font-weight:600; border-bottom:2px solid var(--line); padding:8px; white-space:nowrap; }}
td {{ border-bottom:1px solid var(--line); padding:8px; vertical-align:top; }} td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.pill {{ padding:2px 8px; border-radius:10px; font-size:12px; font-weight:600; }}
.pill.pass {{ background:#DFF6DD; color:#107C10; }} .pill.fail {{ background:#FDE7E9; color:#A4262C; }}
</style></head><body>
<header><h1>Data Quality Report: Online Retail II</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} · every cleaning rule, how many rows it touched, and the data contracts each layer must pass</p></header>
<main>
<div class="kpis">{kpi_html}</div>
<div class="card"><h2>Cleaning rules (in execution order)</h2>{_table(rules, ("rows_affected", "rows_after"))}</div>
<div class="grid2"><div class="card">{_fig_html(funnel)}</div><div class="card">{_fig_html(null_fig)}</div></div>
<div class="grid2"><div class="card">{_fig_html(lt_fig)}</div>
<div class="card"><h2>Country labels resolved to ISO-3166</h2>{_table(country_map, ("rows",))}</div></div>
<div class="card"><h2>Data contracts (Pandera)</h2>{_table(checks, ("rows", "checks", "failures"))}</div>
</main></body></html>"""
    out = p.docs / "data_quality_report.html"
    out.write_text(page)
    log.info("dq report: %s", out)
