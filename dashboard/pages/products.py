"""Page 4: Product Analytics (Pareto / ABC, decomposition, returns, price bands)."""

from __future__ import annotations

import math
from functools import lru_cache

import dash
import plotly.graph_objects as go
import polars as pl
from dash import Output, callback, html

import charts
import data_access as da
from components import data_table, kpi_slot, stat, visual
from theme import MODES, NEUTRAL, PALETTE, compact, empty, pct, style

dash.register_page(__name__, path="/products", name="Product Analytics", order=3)

PRICE_BANDS = ["< £1", "£1 – £2.49", "£2.50 – £4.99", "£5 – £9.99", "£10+"]

da.XF_DIMS.update({"pr-decomp": "category", "pr-price": "price_band"})
da.EXPORTS.update(
    {
        "pr-pareto": lambda f: da.MODEL.pareto(f),
        "pr-decomp": lambda f: da.MODEL.by(f.without("category"), ["category", "sub_category"], ["Net Revenue"]),
        "pr-returns": lambda f: da.MODEL.product_returns(f),
        "pr-price": lambda f: da.MODEL.by(f.without("price_band"), ["price_band"], ["Net Revenue", "Units Sold"]),
        "pr-table": lambda f: da.MODEL.pareto(f),
    }
)


@lru_cache(maxsize=1)
def category_universe() -> list[str]:
    """Stable category order (all-time revenue) so colour follows the category, not its rank."""
    from retail_bi.measures.measures import Filters

    return da.MODEL.by(Filters(), ["category"], ["Net Revenue"], order='"Net Revenue" DESC')["category"].to_list()


def cat_color(c: str) -> str:
    u = category_universe()
    i = u.index(c) if c in u else 99
    return PALETTE[i] if i < 7 else NEUTRAL  # slot 8+ folds into a neutral "other" tone


layout = html.Div(
    [
        html.Div(
            [kpi_slot(k) for k in ("pr-sold", "pr-a", "pr-price-avg", "pr-returns-kpi")], className="kpi-row span-12"
        ),
        visual(
            "pr-pareto",
            "Pareto: how concentrated is revenue?",
            span=5,
            height=310,
            subtitle="Cumulative share of net revenue by product rank (ABC analysis)",
        ),
        visual(
            "pr-decomp",
            "Decomposition: category → sub-category",
            span=7,
            height=310,
            subtitle="Top 7 categories coloured; the rest grouped in grey",
            hint="Click a box to cross-filter by its category",
        ),
        visual(
            "pr-returns",
            "Which products come back?",
            span=5,
            height=300,
            subtitle="Products with ≥ £2K sales · revenue (log) vs return rate",
        ),
        visual("pr-price", "Net revenue by price band", span=3, height=300, hint="Click a band to cross-filter"),
        visual("pr-table", "Product leaderboard", span=4, height=300, body=html.Div(id="pr-table-body")),
    ],
    className="grid",
)


@callback(
    Output("pr-sold", "children"),
    Output("pr-a", "children"),
    Output("pr-price-avg", "children"),
    Output("pr-returns-kpi", "children"),
    Output({"type": "visual", "vid": "pr-pareto"}, "figure"),
    Output({"type": "visual", "vid": "pr-decomp"}, "figure"),
    Output({"type": "visual", "vid": "pr-returns"}, "figure"),
    Output({"type": "visual", "vid": "pr-price"}, "figure"),
    Output("pr-table-body", "children"),
    da.CONTEXT_INPUTS,
)
def update(*args):
    f, xf, mode, sym = da.context(*args)
    m = MODES[mode]
    par = da.MODEL.pareto(f)
    k = da.MODEL.evaluate(f, ["Avg Unit Price", "Return Value", "Return Rate %"])

    n = par.height
    a_count = par.filter(pl.col("Cumulative Revenue %") <= 0.8).height + (1 if n else 0)
    tiles = [
        stat("Products sold", f"{n:,}", "distinct stock codes with sales"),
        stat("Products making 80% of revenue", f"{a_count:,}", f"{a_count / n:.0%} of the range" if n else None),
        stat("Avg unit price", f"{sym}{k['Avg Unit Price'] or 0:,.2f}", "revenue ÷ units sold"),
        stat("Return value", compact(k["Return Value"], sym), f"{pct(k['Return Rate %'])} of gross sales"),
    ]

    # --- Pareto curve with ABC bands ----------------------------------------------
    if par.is_empty():
        pareto = empty(mode)
    else:
        x = [(i + 1) / n for i in range(n)]
        y = par["Cumulative Revenue %"].to_list()
        pareto = go.Figure(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                line=dict(color=PALETTE[0], width=2),
                fill="tozeroy",
                fillcolor="rgba(17,141,255,0.08)",
                customdata=par["product_name"].to_list(),
                hovertemplate="Top %{x:.0%} of products<br>→ %{y:.0%} of revenue<br>#%{pointNumber}: %{customdata}"
                "<extra></extra>",
            )
        )
        for lo, hi, label in ((0, 0.8, "A"), (0.8, 0.95, "B"), (0.95, 1.0, "C")):
            pareto.add_hrect(y0=lo, y1=hi, fillcolor=m["grid"], opacity=0.5 if label == "B" else 0.0, line_width=0)
            pareto.add_annotation(
                x=1.0,
                y=(lo + hi) / 2,
                text=f"<b>{label}</b>",
                showarrow=False,
                xanchor="right",
                font=dict(color=m["muted"]),
            )
        pareto.add_shape(type="line", x0=0, x1=a_count / n, y0=0.8, y1=0.8, line=dict(color=m["faint"], width=1))
        pareto.add_shape(
            type="line", x0=a_count / n, x1=a_count / n, y0=0, y1=0.8, line=dict(color=m["faint"], width=1)
        )
        pareto.add_annotation(
            x=a_count / n,
            y=0.8,
            text=f"{a_count / n:.0%} of products → 80% of revenue",
            showarrow=False,
            xanchor="left",
            yanchor="top",
            xshift=6,
            yshift=-4,
            font=dict(color=m["ink"], size=12),
        )
        style(pareto, mode)
        pareto.update_xaxes(tickformat=".0%", title="Share of products (ranked)", range=[0, 1])
        pareto.update_yaxes(tickformat=".0%", range=[0, 1.02])
        pareto.update_layout(hovermode="x")

    # --- decomposition treemap -------------------------------------------------------
    dec = da.MODEL.by(f.without("category"), ["category", "sub_category"], ["Net Revenue"]).filter(
        pl.col("Net Revenue") > 0
    )
    if dec.is_empty():
        decomp = empty(mode)
    else:
        sel = da.selected(xf, "category")
        cats = dec.group_by("category").agg(pl.col("Net Revenue").sum()).sort("Net Revenue", descending=True)
        ids, labels, parents, values, colors, custom = [], [], [], [], [], []
        for c, v in cats.iter_rows():
            col = cat_color(c) if sel in (None, c) else m["dim"]
            ids.append(c), labels.append(c), parents.append(""), values.append(v), colors.append(col), custom.append(c)
        for c, s, v in dec.iter_rows():
            ids.append(f"{c}/{s}"), labels.append(s), parents.append(c), values.append(v)
            colors.append(cat_color(c) if sel in (None, c) else m["dim"]), custom.append(c)
        decomp = go.Figure(
            go.Treemap(
                ids=ids,
                labels=labels,
                parents=parents,
                values=values,
                customdata=custom,
                branchvalues="total",
                marker=dict(colors=colors, line=dict(color=m["surface"], width=2)),
                text=[compact(v, sym) for v in values],
                texttemplate="<b>%{label}</b><br>%{text}",
                hovertemplate="<b>%{label}</b><br>%{text} · %{percentRoot:.1%} of total<extra></extra>",
                textfont=dict(color="#FFFFFF", size=11),
                tiling=dict(pad=2),
                maxdepth=2,
                pathbar=dict(visible=False),
            )
        )
        style(decomp, mode)
        decomp.update_layout(margin=dict(l=0, r=0, t=0, b=0))

    # --- returns scatter ------------------------------------------------------------
    ret = da.MODEL.product_returns(f).filter(pl.col("Return Rate %") > 0)
    if ret.is_empty():
        scatter = empty(mode)
    else:
        worst = set(
            ret.filter(pl.col("Total Revenue") >= 5000)
            .sort("Return Rate %", descending=True)
            .head(3)["product_name"]
            .to_list()
        )
        scatter = go.Figure(
            go.Scatter(
                x=ret["Total Revenue"].to_list(),
                y=ret["Return Rate %"].to_list(),
                mode="markers",
                marker=dict(size=8, color=PALETTE[0], opacity=0.55, line=dict(color=m["surface"], width=1)),
                customdata=list(
                    zip(
                        ret["product_name"].to_list(),
                        [compact(v, sym) for v in ret["Return Value"].to_list()],
                        strict=True,
                    )
                ),
                hovertemplate="<b>%{customdata[0]}</b><br>Sales: " + sym + "%{x:,.0f}<br>Return rate: %{y:.1%}"
                "<br>Returned: %{customdata[1]}<extra></extra>",
            )
        )
        for r in ret.filter(pl.col("product_name").is_in(list(worst))).iter_rows(named=True):
            scatter.add_annotation(
                x=math.log10(r["Total Revenue"]),
                y=r["Return Rate %"],
                text=charts._trim(r["product_name"], 22),
                showarrow=False,
                xanchor="left",
                xshift=7,
                font=dict(size=10, color=m["muted"]),
            )
        style(scatter, mode)
        ticks = [t for t in (2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5) if t <= max(ret["Total Revenue"].to_list()) * 1.5]
        scatter.update_xaxes(type="log", tickvals=ticks, ticktext=[compact(t, sym, 0) for t in ticks], showgrid=True)
        scatter.update_yaxes(tickformat=".0%", rangemode="tozero")

    # --- price bands (ordered categories) ------------------------------------------
    pb = da.MODEL.by(f.without("price_band"), ["price_band"], ["Net Revenue"])
    if pb.is_empty():
        price = empty(mode)
    else:
        lookup = dict(pb.iter_rows())
        bands = [b for b in PRICE_BANDS if b in lookup]
        sel = da.selected(xf, "price_band")
        price = charts.bar_v(
            [b.replace(" – £", "–") for b in bands],
            [lookup[b] for b in bands],
            mode,
            sym,
            custom=bands,
            colors=[PALETTE[0] if sel in (None, b) else m["dim"] for b in bands],
        )
        price.update_traces(
            text=[compact(lookup[b], sym) for b in bands],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(color=m["muted"]),
        )
        price.update_xaxes(type="category", tickangle=0)
        price.update_yaxes(visible=False)

    returns = da.MODEL.product_returns(f, min_revenue=0).select("product_name", "Return Rate %")
    board = par.join(returns, on="product_name", how="left").with_columns(
        pl.when(pl.col("product_name").str.len_chars() > 26)
        .then(pl.col("product_name").str.slice(0, 25) + "…")
        .otherwise(pl.col("product_name"))
        .alias("product_name")
    )
    table = data_table(
        board,
        [
            ("Revenue Rank", "#", "int"),
            ("product_name", "Product", "text"),
            ("Net Revenue", "Net revenue", f"money:{sym}"),
            ("Return Rate %", "Returns", "pct"),
        ],
        bar="Net Revenue",
        max_rows=30,
        mode=mode,
    )
    return (*tiles, pareto, decomp, scatter, price, table)
