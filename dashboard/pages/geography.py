"""Page 5: Geography (map, report-page tooltip, league table, market sizing)."""

from __future__ import annotations

import dash
import plotly.graph_objects as go
import polars as pl
from dash import Input, Output, State, callback, dcc, html

import charts
import data_access as da
from components import data_table, kpi_slot, stat, visual
from theme import MODES, PALETTE, compact, empty, pct, style

dash.register_page(__name__, path="/geography", name="Geography", order=4)

MAP = {"type": "visual", "vid": "ge-map"}
da.XF_DIMS.update({"ge-map": "country_name", "ge-region": "region"})
da.EXPORTS.update(
    {
        "ge-map": lambda f: da.MODEL.countries(f.without("country_name")),
        "ge-table": lambda f: da.MODEL.countries(f),
        "ge-scatter": lambda f: da.MODEL.countries(f),
        "ge-region": lambda f: da.MODEL.by(f.without("region"), ["region"], ["Net Revenue", "Total Orders"]),
    }
)

layout = html.Div(
    [
        html.Div(
            [kpi_slot(k) for k in ("ge-countries", "ge-intl", "ge-aov-uk", "ge-aov-intl")], className="kpi-row span-12"
        ),
        visual(
            "ge-map",
            "Net revenue by country",
            span=8,
            height=360,
            hint="Hover a country for its report-page tooltip · click to cross-filter",
        ),
        visual(
            "ge-tooltip",
            "Country details",
            span=4,
            height=360,
            body=html.Div(id="ge-tooltip-body", className="tooltip-panel"),
        ),
        visual("ge-table", "Country league table", span=5, height=320, body=html.Div(id="ge-table-body")),
        visual(
            "ge-scatter",
            "Do richer markets buy more?",
            span=4,
            height=320,
            subtitle="Revenue per 1M inhabitants vs GDP per capita (log scales)",
        ),
        visual("ge-region", "Net revenue by region", span=3, height=320, hint="Click a bar to cross-filter"),
    ],
    className="grid",
)


@callback(
    Output("ge-countries", "children"),
    Output("ge-intl", "children"),
    Output("ge-aov-uk", "children"),
    Output("ge-aov-intl", "children"),
    Output(MAP, "figure"),
    Output("ge-table-body", "children"),
    Output({"type": "visual", "vid": "ge-scatter"}, "figure"),
    Output({"type": "visual", "vid": "ge-region"}, "figure"),
    da.CONTEXT_INPUTS,
)
def update(*args):
    f, xf, mode, sym = da.context(*args)
    m = MODES[mode]
    geo = da.MODEL.countries(f)
    geo_all = da.MODEL.countries(f.without("country_name"))
    mk = da.MODEL.by(f, ["market"], ["Net Revenue", "Avg Order Value"])
    mk_d = {r["market"]: r for r in mk.iter_rows(named=True)}
    total = sum(r["Net Revenue"] or 0 for r in mk_d.values())
    intl = (mk_d.get("International") or {}).get("Net Revenue") or 0

    tiles = [
        stat(
            "Countries with sales",
            f"{geo.filter(pl.col('Net Revenue') > 0).height}",
            f"of {len(da.options('country_name'))} in the data",
        ),
        stat("International share", pct(intl / total if total else None), compact(intl, sym) + " outside the UK"),
        stat("Avg order · UK", compact((mk_d.get("Domestic") or {}).get("Avg Order Value"), sym), "domestic orders"),
        stat(
            "Avg order · International",
            compact((mk_d.get("International") or {}).get("Avg Order Value"), sym),
            "export orders are bigger, wholesale-sized baskets",
        ),
    ]

    world = charts.choropleth(geo_all, "Net Revenue", mode, sym, selected=da.selected(xf, "country_name"))

    table = data_table(
        geo.with_columns((pl.col("Net Revenue") / pl.col("Net Revenue").sum()).alias("share")),
        [
            ("country_name", "Country", "text"),
            ("Net Revenue", "Net revenue", f"money:{sym}"),
            ("share", "Share", "pct"),
            ("Total Orders", "Orders", "int"),
            ("Active Customers", "Customers", "int"),
            ("Avg Order Value", "Avg order", f"money:{sym}"),
        ],
        bar="Net Revenue",
        max_rows=45,
        mode=mode,
    )

    sc = geo.filter(pl.col("Revenue per 1M Population") > 0, pl.col("gdp_per_capita").is_not_null())
    if sc.is_empty():
        scatter = empty(mode)
    else:
        names = sc["country_name"].to_list()
        domestic = [n == "United Kingdom" for n in names]
        scatter = go.Figure(
            go.Scatter(
                x=sc["gdp_per_capita"].to_list(),
                y=sc["Revenue per 1M Population"].to_list(),
                mode="markers+text",
                text=["United Kingdom" if d else "" for d in domestic],
                textposition="middle left",
                textfont=dict(size=10, color=m["muted"]),
                marker=dict(
                    size=[12 if d else 8 for d in domestic],
                    color=[PALETTE[1] if d else PALETTE[0] for d in domestic],
                    opacity=0.8,
                    line=dict(color=m["surface"], width=1),
                ),
                customdata=names,
                hovertemplate="<b>%{customdata}</b><br>GDP per capita: $%{x:,.0f}<br>Revenue per 1M people: "
                + sym
                + "%{y:,.0f}<extra></extra>",
            )
        )
        style(scatter, mode)
        xt = [5e3, 1e4, 2e4, 5e4, 1e5]
        yt = [10, 100, 1e3, 1e4, 1e5]
        scatter.update_xaxes(
            type="log",
            tickvals=xt,
            ticktext=[compact(t, "$", 0) for t in xt],
            showgrid=True,
            title="GDP per capita (2010)",
        )
        scatter.update_yaxes(type="log", tickvals=yt, ticktext=[compact(t, sym, 0) for t in yt])

    reg = da.MODEL.by(f.without("region"), ["region"], ["Net Revenue"])
    region_fig = charts.bar_h(
        reg.filter(pl.col("Net Revenue") > 0), "region", "Net Revenue", mode, sym, selected=da.selected(xf, "region")
    )
    return (*tiles, world, table, scatter, region_fig)


@callback(
    Output("ge-tooltip-body", "children"),
    Input(MAP, "hoverData"),
    State("sl-date", "start_date"),
    State("sl-date", "end_date"),
    State("sl-currency", "value"),
    *[State(sid, "value") for sid in da.SLICERS],
    State("xfilter", "data"),
    State("theme", "data"),
)
def tooltip(hover, *state):
    """Report-page tooltip: a mini report for the hovered country."""
    f, _, mode, sym = da.context(*state)
    # Default to the biggest market until the user hovers somewhere else
    country = hover["points"][0]["customdata"] if hover else "United Kingdom"
    fc = f.without("country_name")
    fc = type(fc).build(fc.start, fc.end, fc.currency, dict(fc.slicers), {"country_name": [country]})
    k = da.MODEL.evaluate(fc, ["Net Revenue", "Total Orders", "Active Customers", "Avg Order Value", "Return Rate %"])
    trend = da.MODEL.trend(fc, "month", ["Net Revenue"])
    top = da.MODEL.by(fc, ["category"], ["Net Revenue"], order='"Net Revenue" DESC', limit=1)
    fig = go.Figure(
        go.Scatter(
            x=trend["period"].to_list(),
            y=trend["Net Revenue"].to_list(),
            mode="lines",
            line=dict(color=PALETTE[0], width=2),
            fill="tozeroy",
            fillcolor="rgba(17,141,255,0.10)",
            hovertemplate="%{x|%b %Y}: " + sym + "%{y:,.0f}<extra></extra>",
        )
    )
    style(fig, mode, height=150)
    fig.update_yaxes(tickprefix=sym, tickformat="~s", rangemode="tozero")
    fig.update_xaxes(tickformat="%b %y")

    def cell(label, value):
        return html.Div([html.Div(label, className="tt-k"), html.Div(value, className="tt-v")])

    return [
        html.Div(country, className="tt-title"),
        html.Div("Hover a country on the map to switch" if not hover else "", className="tt-k"),
        html.Div(
            [
                cell("Net revenue", compact(k["Net Revenue"], sym)),
                cell("Orders", f"{k['Total Orders'] or 0:,}"),
                cell("Customers", f"{k['Active Customers'] or 0:,}"),
                cell("Avg order", compact(k["Avg Order Value"], sym)),
                cell("Return rate", pct(k["Return Rate %"])),
                cell("Top category", top["category"].item() if not top.is_empty() else "–"),
            ],
            className="tt-grid",
        ),
        html.Div("Monthly net revenue", className="tt-k", style={"marginTop": "10px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "150px"}),
    ]
