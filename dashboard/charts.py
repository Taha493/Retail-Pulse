"""Chart builders that follow Power BI's default visual look (and the dataviz rules:
thin marks, one axis, recessive grid, colour by entity, hover on everything)."""

from __future__ import annotations

import math

import plotly.graph_objects as go
import polars as pl

from theme import ACCENT, MODES, NEUTRAL, PALETTE, compact, empty, pct, style


def bar_h(
    df: pl.DataFrame,
    label: str,
    value: str,
    mode: str,
    symbol: str = "",
    selected: str | None = None,
    height: int | None = None,
    fmt: str = "money",
) -> go.Figure:
    """Horizontal bar ranked largest at top. Clicking a bar cross-filters (customdata=label)."""
    if df.is_empty():
        return empty(mode)
    df = df.sort(value)
    m = MODES[mode]
    labels, values = df[label].to_list(), df[value].to_list()
    colors = [ACCENT if selected in (None, lab) else m["dim"] for lab in labels]
    text = [compact(v, symbol) if fmt == "money" else (pct(v) if fmt == "pct" else f"{v:,.0f}") for v in values]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=[_trim(s) for s in labels],
            orientation="h",
            marker=dict(color=colors, cornerradius=4),
            text=text,
            textposition="outside",
            cliponaxis=False,
            textfont=dict(color=m["muted"]),
            customdata=labels,
            hovertemplate="<b>%{customdata}</b><br>%{text}<extra></extra>",
        )
    )
    style(fig, mode, height)
    fig.update_xaxes(visible=False, range=[0, max(values) * 1.18 if values and max(values) > 0 else 1])
    fig.update_yaxes(showgrid=False, ticksuffix="  ", tickfont=dict(color=m["ink"]))
    fig.update_layout(bargap=0.3)
    return fig


def bar_v(
    x: list,
    y: list,
    mode: str,
    symbol: str = "",
    custom: list | None = None,
    colors: list[str] | None = None,
    hover_fmt: str = "money",
    height: int | None = None,
) -> go.Figure:
    text = [compact(v, symbol) if hover_fmt == "money" else pct(v, signed=True) for v in y]
    fig = go.Figure(
        go.Bar(
            x=x,
            y=y,
            marker=dict(color=colors or ACCENT, cornerradius=4),
            customdata=custom or x,
            text=text,
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
            textposition="none",
        )
    )
    style(fig, mode, height)
    fig.update_yaxes(
        tickprefix=symbol if hover_fmt == "money" else "", tickformat="~s" if hover_fmt == "money" else ".0%"
    )
    return fig


def line_vs_py(df: pl.DataFrame, x: str, cur: str, py: str, mode: str, symbol: str) -> go.Figure:
    """Current period vs same period last year: two series, legend + endpoint labels."""
    if df.is_empty():
        return empty(mode)
    m = MODES[mode]
    xs = df[x].to_list()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=df[py].to_list(),
            name="Same period last year",
            mode="lines",
            line=dict(color=m["faint"], width=2),
            hovertemplate=f"PY: {symbol}%{{y:,.0f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=df[cur].to_list(),
            name="Selected period",
            mode="lines+markers",
            line=dict(color=ACCENT, width=2),
            marker=dict(size=8, line=dict(color=m["surface"], width=2)),
            hovertemplate=f"<b>%{{x|%b %Y}}</b><br>Revenue: {symbol}%{{y:,.0f}}<extra></extra>",
        )
    )
    last = df.drop_nulls(cur).tail(1)
    if not last.is_empty():
        fig.add_annotation(
            x=last[x].item(),
            y=last[cur].item(),
            text=compact(last[cur].item(), symbol),
            showarrow=False,
            xanchor="left",
            xshift=8,
            font=dict(color=m["ink"], size=12),
        )
    style(fig, mode, legend=True)
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(tickprefix=symbol, tickformat="~s", rangemode="tozero")
    fig.update_xaxes(tickformat="%b %y")
    return fig


def choropleth(
    df: pl.DataFrame,
    value: str,
    mode: str,
    symbol: str,
    selected: str | None = None,
    height: int | None = None,
    scope_europe: bool = False,
) -> go.Figure:
    """Filled map. Colour uses a log scale because the UK is ~90% of revenue."""
    m = MODES[mode]
    df = df.filter(pl.col(value) > 0, pl.col("iso3").str.len_chars() == 3)
    if df.is_empty():
        return empty(mode)
    z = [math.log10(v) for v in df[value].to_list()]
    lo, hi = math.floor(min(z)), math.ceil(max(z))
    ticks = list(range(lo, hi + 1))
    names = df["country_name"].to_list()
    fig = go.Figure(
        go.Choropleth(
            locations=df["iso3"].to_list(),
            z=z,
            locationmode="ISO-3",
            customdata=names,
            text=[compact(v, symbol) for v in df[value].to_list()],
            colorscale=[[i / (len(m["seq"]) - 1), c] for i, c in enumerate(m["seq"])],
            zmin=lo,
            zmax=hi,
            marker_line_color=m["surface"],
            marker_line_width=0.6,
            colorbar=dict(
                tickvals=ticks,
                ticktext=[compact(10**t, symbol, 0) for t in ticks],
                thickness=8,
                len=0.6,
                outlinewidth=0,
                tickfont=dict(color=m["muted"], size=10),
                x=1.0,
            ),
            hovertemplate="<b>%{customdata}</b><br>%{text}<extra></extra>",
            selectedpoints=[names.index(selected)] if selected in names else None,
            unselected=dict(marker=dict(opacity=0.35)),
        )
    )
    style(fig, mode, height)
    fig.update_geos(
        showframe=False,
        showcoastlines=False,
        projection_type="natural earth",
        showland=True,
        landcolor=m["grid"],
        showcountries=True,
        countrycolor=m["surface"],
        bgcolor="rgba(0,0,0,0)",
        lataxis_range=[-50, 78] if not scope_europe else [34, 70],
        lonaxis_range=[-170, 180] if not scope_europe else [-25, 45],
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), dragmode=False)
    return fig


def heatmap(
    z: list[list],
    x: list,
    y: list,
    mode: str,
    hover: str,
    zfmt: str = "",
    height: int | None = None,
    text: list[list] | None = None,
) -> go.Figure:
    m = MODES[mode]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=x,
            y=y,
            colorscale=[[i / (len(m["seq"]) - 1), c] for i, c in enumerate(m["seq"])],
            xgap=2,
            ygap=2,
            hovertemplate=hover + "<extra></extra>",
            text=text,
            texttemplate="%{text}" if text else None,
            textfont=dict(size=10),
            colorbar=dict(thickness=8, outlinewidth=0, tickformat=zfmt, tickfont=dict(color=m["muted"], size=10)),
            hoverongaps=False,
        )
    )
    style(fig, mode, height)
    fig.update_xaxes(showgrid=False, side="top", type="category")
    fig.update_yaxes(showgrid=False, autorange="reversed", type="category")
    return fig


def categorical_colors(entities: list[str], universe: list[str]) -> list[str]:
    return [
        PALETTE[universe.index(e)] if e in universe and universe.index(e) < len(PALETTE) else NEUTRAL for e in entities
    ]


def _trim(s: str, n: int = 28) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
