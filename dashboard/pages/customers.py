"""Page 3: Customer Analytics (RFM, cohorts, new vs returning)."""

from __future__ import annotations

import math
from dataclasses import replace

import dash
import plotly.graph_objects as go
import polars as pl
from dash import Output, callback, html

import charts
import data_access as da
from components import data_table, kpi_card, kpi_slot, visual
from theme import MODES, PALETTE, compact, empty, pct, style

dash.register_page(__name__, path="/customers", name="Customer Analytics", order=2)

da.XF_DIMS.update({"cu-segments": "rfm_segment"})
da.EXPORTS.update(
    {
        "cu-segments": lambda f: da.MODEL.segment_summary(f.without("rfm_segment")),
        "cu-cohort": lambda f: da.MODEL.cohort_retention(replace(f, start=None, end=None)),
        "cu-newret": lambda f: da.MODEL.new_vs_returning(f),
        "cu-dist": lambda f: da.MODEL.customer_value_distribution(f),
        "cu-top": lambda f: da.MODEL.customer_value_distribution(f).sort("value", descending=True).head(100),
    }
)

layout = html.Div(
    [
        html.Div([kpi_slot(k) for k in ("cu-active", "cu-new", "cu-repeat", "cu-rpc")], className="kpi-row span-12"),
        visual(
            "cu-segments",
            "RFM segments by net revenue",
            span=6,
            height=320,
            subtitle="Box size = revenue · shade = revenue per customer",
            hint="Click a segment to cross-filter",
        ),
        visual(
            "cu-cohort",
            "Cohort retention: share of each first-purchase month still buying",
            span=6,
            height=320,
            subtitle="Ignores the date slicer (like Power BI's 'Edit interactions → None')",
        ),
        visual("cu-newret", "New vs returning customers per month", span=5, height=280),
        visual(
            "cu-dist",
            "How much is a customer worth?",
            span=3,
            height=280,
            subtitle="Customers by net revenue in the period (log scale)",
        ),
        visual("cu-top", "Top customers", span=4, height=280, body=html.Div(id="cu-top-body")),
    ],
    className="grid",
)


@callback(
    Output("cu-active", "children"),
    Output("cu-new", "children"),
    Output("cu-repeat", "children"),
    Output("cu-rpc", "children"),
    Output({"type": "visual", "vid": "cu-segments"}, "figure"),
    Output({"type": "visual", "vid": "cu-cohort"}, "figure"),
    Output({"type": "visual", "vid": "cu-newret"}, "figure"),
    Output({"type": "visual", "vid": "cu-dist"}, "figure"),
    Output("cu-top-body", "children"),
    da.CONTEXT_INPUTS,
)
def update(*args):
    f, xf, mode, sym = da.context(*args)
    m = MODES[mode]
    names = ["Active Customers", "Revenue per Customer"]
    cur, py = da.MODEL.with_prior_year(f, names)
    nr = da.MODEL.new_vs_returning(f)
    nr_py = da.MODEL.new_vs_returning(f.shifted_years(-1))
    new_c, new_py = nr["New Customers"].sum(), nr_py["New Customers"].sum()
    rep, rep_py = da.MODEL.repeat_purchase_rate(f), da.MODEL.repeat_purchase_rate(f.shifted_years(-1))

    def d(a, b):
        return (a - b) / b if a is not None and b else None

    cards = [
        kpi_card(
            "Active customers",
            compact(cur["Active Customers"]),
            d(cur["Active Customers"], py["Active Customers"]),
            mode=mode,
            spark=[v for v in (nr["New Customers"] + nr["Returning Customers"]).to_list()],
        ),
        kpi_card(
            "New customers",
            compact(new_c),
            d(new_c, new_py),
            mode=mode,
            spark=nr["New Customers"].to_list(),
            note="2010 is inflated: the data has no history before Dec 2009",
        ),
        kpi_card(
            "Repeat purchase rate",
            pct(rep),
            (rep - rep_py) if rep is not None and rep_py else None,
            mode=mode,
            points=True,
            note="customers with 2+ orders",
        ),
        kpi_card(
            "Revenue per customer",
            compact(cur["Revenue per Customer"], sym),
            d(cur["Revenue per Customer"], py["Revenue per Customer"]),
            mode=mode,
        ),
    ]

    # --- RFM treemap -------------------------------------------------------------
    seg = da.MODEL.segment_summary(f.without("rfm_segment")).filter(pl.col("Net Revenue") > 0)
    if seg.is_empty():
        tree = empty(mode)
    else:
        sel = da.selected(xf, "rfm_segment")
        labels = seg["rfm_segment"].to_list()
        rpc = seg["Revenue per Customer"].to_list()
        # Shade = revenue per customer on the sequential ramp (log-binned)
        ramp = m["seq"][1:]
        lo, hi = math.log10(max(min(rpc), 1)), math.log10(max(max(rpc), 1))
        step = [min(len(ramp) - 1, int((math.log10(max(v, 1)) - lo) / ((hi - lo) or 1) * len(ramp))) for v in rpc]
        colors = [ramp[i] if sel in (None, lab) else m["dim"] for i, lab in zip(step, labels, strict=True)]
        text_colors = [
            "#FFFFFF" if i >= 2 and sel in (None, lab) else m["ink"] for i, lab in zip(step, labels, strict=True)
        ]
        tree = go.Figure(
            go.Treemap(
                labels=labels,
                parents=[""] * len(labels),
                values=seg["Net Revenue"].to_list(),
                customdata=labels,
                marker=dict(colors=colors, line=dict(color=m["surface"], width=2)),
                text=[
                    f"{compact(v, sym)} · {int(c):,} customers<br>{compact(r, sym)} per customer"
                    for v, c, r in zip(
                        seg["Net Revenue"].to_list(), seg["Active Customers"].to_list(), rpc, strict=True
                    )
                ],
                texttemplate="<b>%{label}</b><br>%{text}",
                textfont=dict(size=12, color=text_colors),
                hovertemplate="<b>%{label}</b><br>%{text}<extra></extra>",
                tiling=dict(pad=0),
                branchvalues="total",
            )
        )
        style(tree, mode)
        tree.update_layout(margin=dict(l=0, r=0, t=0, b=0), uniformtext=dict(minsize=10, mode="hide"))

    # --- cohort heatmap ----------------------------------------------------------
    coh = da.MODEL.cohort_retention(replace(f, start=None, end=None), max_months=12)
    coh = (
        coh.filter(coh["cohort_month"] <= coh["cohort_month"].min().replace(year=coh["cohort_month"].min().year + 1))
        if not coh.is_empty()
        else coh
    )
    if coh.is_empty():
        cohort_fig = empty(mode)
    else:
        cohorts = sorted(set(coh["cohort_month"].to_list()))
        months = list(range(1, 13))  # M0 is 100% by definition
        lookup = {(r["cohort_month"], r["months_since_first"]): r["retention"] for r in coh.iter_rows(named=True)}
        sizes = {r["cohort_month"]: r["cohort_size"] for r in coh.iter_rows(named=True)}
        z = [[lookup.get((c, mm)) for mm in months] for c in cohorts]
        text = [[(f"{v * 100:.0f}" if v is not None else "") for v in row] for row in z]
        ylab = [f"{c:%b %y} ({sizes[c]:,})" for c in cohorts]
        cohort_fig = charts.heatmap(
            z,
            [f"M{mm}" for mm in months],
            ylab,
            mode,
            hover="Cohort %{y}<br>%{x}: %{z:.0%} still active",
            zfmt=".0%",
            text=text,
        )
        cohort_fig.update_traces(colorbar=dict(title=None))

    # --- new vs returning ----------------------------------------------------------
    if nr.is_empty():
        nr_fig = empty(mode)
    else:
        x = nr["month_start"].to_list()
        nr_fig = go.Figure(
            [
                go.Bar(
                    x=x,
                    y=nr["Returning Customers"].to_list(),
                    name="Returning",
                    marker=dict(color=PALETTE[0]),
                    hovertemplate="%{x|%b %Y}<br>Returning: %{y:,}<extra></extra>",
                ),
                go.Bar(
                    x=x,
                    y=nr["New Customers"].to_list(),
                    name="New",
                    marker=dict(color=PALETTE[1]),
                    hovertemplate="%{x|%b %Y}<br>New: %{y:,}<extra></extra>",
                ),
            ]
        )
        style(nr_fig, mode, legend=True)
        nr_fig.update_layout(barmode="stack", bargap=0.3)
        nr_fig.update_xaxes(tickformat="%b %y")

    # --- value distribution (histogram on log bins) -------------------------------
    dist = da.MODEL.customer_value_distribution(f)
    if dist.is_empty():
        dist_fig = empty(mode)
    else:
        vals = [math.log10(v) for v in dist["value"].to_list() if v >= 1]
        dist_fig = go.Figure(
            go.Histogram(
                x=vals,
                nbinsx=30,
                marker=dict(color=PALETTE[0], line=dict(color=m["surface"], width=1)),
                hovertemplate="%{y:,} customers<extra></extra>",
            )
        )
        style(dist_fig, mode)
        ticks = list(range(0, math.ceil(max(vals)) + 1))
        dist_fig.update_xaxes(
            tickvals=ticks,
            ticktext=[compact(10**t, sym, 0) for t in ticks],
            range=[0, max(vals) + 0.1],
            tickangle=0,
            zeroline=False,
        )
        dist_fig.update_layout(bargap=0.05)

    top = da.MODEL.customer_value_distribution(f).sort("value", descending=True)
    table = data_table(
        top,
        [
            ("customer_label", "Customer", "text"),
            ("rfm_segment", "Segment", "text"),
            ("orders", "Orders", "int"),
            ("value", "Net revenue", f"money:{sym}"),
        ],
        bar="value",
        max_rows=25,
        mode=mode,
    )
    return (*cards, tree, cohort_fig, nr_fig, dist_fig, table)
