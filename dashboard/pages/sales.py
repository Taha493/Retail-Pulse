"""Page 2: Sales Performance (time intelligence + drill-down)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import dash
import plotly.graph_objects as go
import polars as pl
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

import charts
import data_access as da
from components import data_table, kpi_slot, stat, visual
from theme import MODES, compact, empty, pct, style

dash.register_page(__name__, path="/sales", name="Sales Performance", order=1)

GRAINS = ["year", "quarter", "month", "day"]
GRAIN_LABEL = {"year": "Year", "quarter": "Quarter", "month": "Month", "day": "Day"}
DRILL = {"type": "visual", "vid": "sa-drill"}

da.EXPORTS.update(
    {
        "sa-drill": lambda f: da.MODEL.trend(f, "month", ["Net Revenue", "Total Orders"]),
        "sa-mom": lambda f: da.MODEL.monthly_with_py(f),
        "sa-heatmap": lambda f: da.MODEL.weekday_hour(f),
        "sa-waterfall": lambda f: _category_yoy(f),
        "sa-matrix": lambda f: _subcategory_matrix(f),
    }
)


def _period_end(start: date, grain: str) -> date:
    months = {"year": 12, "quarter": 3, "month": 1}.get(grain)
    if months is None:
        return start
    y, m = divmod(start.month - 1 + months, 12)
    return date(start.year + y, m + 1, 1) - timedelta(days=1)


def _label(d: date, grain: str) -> str:
    return {
        "year": f"{d.year}",
        "quarter": f"Q{(d.month - 1) // 3 + 1} {d.year}",
        "month": d.strftime("%b %Y"),
        "day": d.strftime("%d %b"),
    }[grain]


def _category_yoy(f) -> pl.DataFrame:
    cur = da.MODEL.by(f, ["category"], ["Net Revenue"])
    py = da.MODEL.by(f.shifted_years(-1), ["category"], ["Net Revenue"]).rename({"Net Revenue": "Net Revenue PY"})
    return (
        cur.join(py, on="category", how="full", coalesce=True)
        .fill_null(0)
        .with_columns((pl.col("Net Revenue") - pl.col("Net Revenue PY")).alias("YoY Change"))
        .sort("YoY Change", descending=True)
    )


def _subcategory_matrix(f) -> pl.DataFrame:
    names = ["Net Revenue", "Total Orders", "Avg Order Value", "Units Sold"]
    cur = da.MODEL.by(f, ["category", "sub_category"], names)
    py = da.MODEL.by(f.shifted_years(-1), ["category", "sub_category"], ["Net Revenue"]).rename(
        {"Net Revenue": "Net Revenue PY"}
    )
    return (
        cur.join(py, on=["category", "sub_category"], how="left")
        .with_columns(((pl.col("Net Revenue") - pl.col("Net Revenue PY")) / pl.col("Net Revenue PY")).alias("YoY %"))
        .sort("Net Revenue", descending=True)
    )


layout = html.Div(
    [
        dcc.Store(id="sa-drill-path", data=[]),
        html.Div([kpi_slot(k) for k in ("sa-mtd", "sa-qtd", "sa-ytd", "sa-units")], className="kpi-row span-12"),
        visual(
            "sa-drill",
            "Net revenue by date hierarchy",
            span=7,
            height=290,
            body=html.Div(
                [
                    html.Div(
                        [
                            html.Button("⬆ Drill up", id="sa-drill-up", className="drill-btn"),
                            html.Button("Reset", id="sa-drill-reset", className="drill-btn"),
                            html.Span(id="sa-drill-crumbs", className="crumbs"),
                        ],
                        className="drill-bar",
                    ),
                    dcc.Graph(id=DRILL, config={"displayModeBar": False}, style={"height": "262px"}),
                ]
            ),
            hint="Click a column to drill down: Year → Quarter → Month → Day",
        ),
        visual(
            "sa-mom",
            "Month-over-month growth",
            span=5,
            height=290,
            subtitle="Change in net revenue vs the previous month · Dec 2011 has only 9 days of data",
        ),
        visual(
            "sa-heatmap",
            "When do customers buy? Net revenue by weekday and hour",
            span=6,
            height=300,
            subtitle="Blank row = no trading: the shop traded on only one Saturday (5 Dec 2009)",
        ),
        visual(
            "sa-waterfall",
            "What drove the change vs last year?",
            span=6,
            height=300,
            subtitle="Same period last year → selected period, by category · axis zoomed to show the changes",
        ),
        visual(
            "sa-matrix",
            "Category matrix",
            span=12,
            height=320,
            body=html.Div(id="sa-matrix-body"),
            subtitle="YoY % shaded by direction; data bars show net revenue",
        ),
    ],
    className="grid",
)


@callback(
    Output("sa-drill-path", "data"),
    Input(DRILL, "clickData"),
    Input("sa-drill-up", "n_clicks"),
    Input("sa-drill-reset", "n_clicks"),
    State("sa-drill-path", "data"),
    prevent_initial_call=True,
)
def drill(click, _up, _reset, path):
    path = path or []
    if ctx.triggered_id == "sa-drill-reset":
        return []
    if ctx.triggered_id == "sa-drill-up":
        return path[:-1] if path else no_update
    if not click:
        return no_update
    grain, period = click["points"][0]["customdata"].split("|")
    if grain == "day":
        return no_update
    return [*path, {"grain": grain, "period": period}]


@callback(
    Output("sa-mtd", "children"),
    Output("sa-qtd", "children"),
    Output("sa-ytd", "children"),
    Output("sa-units", "children"),
    Output(DRILL, "figure"),
    Output("sa-drill-crumbs", "children"),
    Output("sa-drill-up", "disabled"),
    Output({"type": "visual", "vid": "sa-mom"}, "figure"),
    Output({"type": "visual", "vid": "sa-heatmap"}, "figure"),
    Output({"type": "visual", "vid": "sa-waterfall"}, "figure"),
    Output("sa-matrix-body", "children"),
    *da.CONTEXT_INPUTS,
    Input("sa-drill-path", "data"),
)
def update(*args):
    *ctx_args, path = args
    f, xf, mode, sym = da.context(*ctx_args)
    m = MODES[mode]
    path = path or []
    end = f.end or da.LAST_DATE

    ptd = da.MODEL.period_to_date(f)
    ptd_py = da.MODEL.period_to_date(f.shifted_years(-1))
    tiles = []
    for k, label in (("MTD", "Month to date"), ("QTD", "Quarter to date"), ("YTD", "Year to date")):
        delta = (ptd[k] - ptd_py[k]) / ptd_py[k] if ptd_py[k] else None
        tiles.append(
            stat(
                f"{label} · {k}",
                compact(ptd[k], sym, 2 if ptd[k] >= 1e6 else 1),
                f"{pct(delta, signed=True)} vs PY · as of {end:%d %b %Y}" if delta is not None else None,
            )
        )
    units = da.MODEL.evaluate(f, ["Units Sold", "Avg Unit Price"])
    tiles.append(
        stat("Units sold", compact(units["Units Sold"]), f"avg {sym}{units['Avg Unit Price'] or 0:,.2f} per unit")
    )

    # --- drill-down column chart -----------------------------------------------------
    grain = GRAINS[GRAINS.index(path[-1]["grain"]) + 1] if path else "year"
    fd = f
    if path:
        s = date.fromisoformat(path[-1]["period"][:10])
        e = _period_end(s, path[-1]["grain"])
        fd = replace(f, start=max(s, f.start) if f.start else s, end=min(e, f.end) if f.end else e)
    t = da.MODEL.trend(fd, grain, ["Net Revenue"])
    # A level with a single column says nothing: step down automatically
    while t.height == 1 and grain != "day":
        grain = GRAINS[GRAINS.index(grain) + 1]
        t = da.MODEL.trend(fd, grain, ["Net Revenue"])
    if t.is_empty():
        drill_fig = empty(mode)
    else:
        periods = t["period"].to_list()
        drill_fig = charts.bar_v(
            [_label(p, grain) for p in periods],
            t["Net Revenue"].to_list(),
            mode,
            sym,
            custom=[f"{grain}|{p.isoformat()}" for p in periods],
        )
        if grain != "day":
            drill_fig.update_traces(
                text=[compact(v, sym) for v in t["Net Revenue"].to_list()],
                textposition="outside",
                cliponaxis=False,
                textfont=dict(color=m["muted"]),
            )
        drill_fig.update_xaxes(type="category")
    crumbs = (
        [html.B("All dates")]
        if not path
        else [
            "All dates",
            *[x for p in path for x in (" › ", _label(date.fromisoformat(p["period"][:10]), p["grain"]))],
        ]
    )
    crumbs.append(f"  ·  showing {GRAIN_LABEL[grain].lower()}s")

    # --- MoM % (its own chart: no dual axis) -------------------------------------
    mom = da.MODEL.monthly_with_py(f).drop_nulls("MoM %")
    if mom.is_empty():
        mom_fig = empty(mode, "Select at least two months")
    else:
        vals = mom["MoM %"].to_list()
        mom_fig = charts.bar_v(
            [d.strftime("%b %y") for d in mom["month_start"].to_list()],
            vals,
            mode,
            colors=[m["div"][2] if v >= 0 else m["div"][0] for v in vals],
            hover_fmt="pct",
        )
        mom_fig.update_xaxes(type="category")
        mom_fig.update_yaxes(zeroline=True, zerolinewidth=1)

    # --- weekday x hour heatmap ---------------------------------------------------
    wh = da.MODEL.weekday_hour(f)
    if wh.is_empty():
        heat = empty(mode)
    else:
        hours = list(range(int(wh["invoice_hour"].min()), int(wh["invoice_hour"].max()) + 1))
        days = wh.select("weekday_num", "weekday_short").unique().sort("weekday_num")["weekday_short"].to_list()
        grid = {(r["weekday_short"], r["invoice_hour"]): r["Net Revenue"] for r in wh.iter_rows(named=True)}
        z = [[grid.get((d, h)) for h in hours] for d in days]
        heat = charts.heatmap(
            z,
            [f"{h:02d}:00" for h in hours],
            days,
            mode,
            hover=f"%{{y}} %{{x}}<br>Net revenue: {sym}%{{z:,.0f}}",
            zfmt="~s",
        )

    # --- waterfall ---------------------------------------------------------------
    yoy = _category_yoy(f)
    if yoy.is_empty():
        wf = empty(mode)
    else:
        py_total, cy_total = yoy["Net Revenue PY"].sum(), yoy["Net Revenue"].sum()
        cats = yoy["category"].to_list()
        changes = yoy["YoY Change"].to_list()
        wf = go.Figure(
            go.Waterfall(
                x=["Last year", *cats, "This year"],
                y=[py_total, *changes, cy_total],
                measure=["absolute", *["relative"] * len(cats), "total"],
                increasing=dict(marker=dict(color=m["div"][2])),
                decreasing=dict(marker=dict(color=m["div"][0])),
                totals=dict(marker=dict(color=m["faint"])),
                connector=dict(line=dict(color=m["axis"], width=1)),
                text=[compact(py_total, sym), *[compact(c, sym) for c in changes], compact(cy_total, sym)],
                textposition="none",
                hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
            )
        )
        style(wf, mode)
        wf.update_yaxes(tickprefix=sym, tickformat="~s")
        wf.update_xaxes(tickangle=-35)
        lo = min(py_total, cy_total) * 0.85
        wf.update_yaxes(range=[lo, max(py_total, cy_total) * 1.05])

    # --- matrix ------------------------------------------------------------------
    mx = _subcategory_matrix(f)
    matrix = data_table(
        mx,
        [
            ("category", "Category", "text"),
            ("sub_category", "Sub-category", "text"),
            ("Net Revenue", "Net revenue", f"money:{sym}"),
            ("Net Revenue PY", "Last year", f"money:{sym}"),
            ("YoY %", "YoY %", "pct_signed"),
            ("Total Orders", "Orders", "int"),
            ("Avg Order Value", "Avg order", f"money:{sym}"),
            ("Units Sold", "Units", "int"),
        ],
        bar="Net Revenue",
        color_scale="YoY %",
        max_rows=40,
        mode=mode,
    )
    return (*tiles, drill_fig, crumbs, not path, mom_fig, heat, wf, matrix)
