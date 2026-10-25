"""Page 1: Executive Overview."""

from __future__ import annotations

import dash
from dash import Output, callback, html

import charts
import data_access as da
from components import kpi_card, kpi_slot, visual
from theme import compact, pct

dash.register_page(__name__, path="/", name="Executive Overview", order=0)

KPIS = [
    ("ov-kpi-revenue", "Net Revenue", "money", False),
    ("ov-kpi-orders", "Total Orders", "int", False),
    ("ov-kpi-aov", "Avg Order Value", "money", False),
    ("ov-kpi-customers", "Active Customers", "int", False),
    ("ov-kpi-return", "Return Rate %", "pct", True),
]
KPI_MEASURE = {
    "ov-kpi-revenue": "Net Revenue",
    "ov-kpi-orders": "Total Orders",
    "ov-kpi-aov": "Avg Order Value",
    "ov-kpi-customers": "Active Customers",
    "ov-kpi-return": "Return Rate %",
}

da.XF_DIMS.update({"ov-map": "country_name", "ov-category": "category", "ov-products": "product_name"})
da.EXPORTS.update(
    {
        "ov-trend": lambda f: da.MODEL.monthly_with_py(f),
        "ov-map": lambda f: da.MODEL.countries(f.without("country_name")),
        "ov-category": lambda f: da.MODEL.by(f.without("category"), ["category"], ["Net Revenue"]),
        "ov-products": lambda f: da.MODEL.by(
            f.without("product_name"), ["product_name"], ["Net Revenue"], order='"Net Revenue" DESC', limit=10
        ),
    }
)

layout = html.Div(
    [
        html.Div([kpi_slot(kid) for kid, *_ in KPIS], className="kpi-row span-12"),
        visual(
            "ov-trend",
            "Net revenue by month vs same period last year",
            span=8,
            height=290,
            subtitle="Data ends 9 Dec 2011, so December covers 9 days in both years",
        ),
        visual("ov-map", "Net revenue by country", span=4, height=290, hint="Click a country to cross-filter"),
        visual("ov-category", "Net revenue by category", span=6, height=330, hint="Click a bar to cross-filter"),
        visual("ov-products", "Top 10 products by net revenue", span=6, height=330),
    ],
    className="grid",
)


def _fmt(v, kind, symbol):
    if kind == "money":
        return compact(v, symbol, 2 if v and abs(v) >= 1e6 else 1)
    if kind == "pct":
        return pct(v)
    return compact(v)


@callback(
    *[Output(kid, "children") for kid, *_ in KPIS],
    Output({"type": "visual", "vid": "ov-trend"}, "figure"),
    Output({"type": "visual", "vid": "ov-map"}, "figure"),
    Output({"type": "visual", "vid": "ov-category"}, "figure"),
    Output({"type": "visual", "vid": "ov-products"}, "figure"),
    da.CONTEXT_INPUTS,
)
def update(*args):
    f, xf, mode, sym = da.context(*args)
    names = list(KPI_MEASURE.values())
    cur, py = da.MODEL.with_prior_year(f, names)
    monthly = da.MODEL.trend(f, "month", names)

    cards = []
    for kid, label, kind, invert in KPIS:
        name = KPI_MEASURE[kid]
        c, p = cur[name], py[name]
        delta = (c - p) / abs(p) if c is not None and p else None
        if kind == "pct" and c is not None and p is not None:
            delta = c - p  # change in percentage points
        cards.append(
            kpi_card(
                label,
                _fmt(c, kind, sym),
                delta,
                "vs PY",
                spark=[v or 0 for v in monthly[name].to_list()],
                mode=mode,
                invert=invert,
                points=kind == "pct",
            )
        )

    trend = charts.line_vs_py(da.MODEL.monthly_with_py(f), "month_start", "Net Revenue", "Net Revenue PY", mode, sym)

    sel_country = da.selected(xf, "country_name")
    geo = da.MODEL.countries(f.without("country_name"))
    world = charts.choropleth(geo, "Net Revenue", mode, sym, selected=sel_country)

    cat = da.MODEL.by(f.without("category"), ["category"], ["Net Revenue"])
    cat_fig = charts.bar_h(cat, "category", "Net Revenue", mode, sym, selected=da.selected(xf, "category"))

    prod = da.MODEL.by(
        f.without("product_name"), ["product_name"], ["Net Revenue"], order='"Net Revenue" DESC', limit=10
    )
    prod_fig = charts.bar_h(prod, "product_name", "Net Revenue", mode, sym, selected=da.selected(xf, "product_name"))

    return (*cards, trend, world, cat_fig, prod_fig)
