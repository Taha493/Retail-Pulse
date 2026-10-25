"""Reusable report building blocks (Power BI visual equivalents)."""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
from dash import dcc, html

from theme import MODES, compact, pct, style

GRAPH_CONFIG = {"displayModeBar": False, "responsive": True}
TITLES: dict[str, str] = {}  # visual id -> title (used by focus mode)


def visual(
    vid: str,
    title: str,
    span: int = 6,
    height: int = 300,
    subtitle: str | None = None,
    body=None,
    hint: str | None = None,
) -> html.Div:
    """A Power BI-style visual container: title, header actions, then the chart."""
    TITLES[vid] = title
    actions = html.Div(
        [
            html.Button("⤓", id={"type": "export", "vid": vid}, className="vh-btn", title="Export data (CSV)"),
            html.Button("⤢", id={"type": "focus", "vid": vid}, className="vh-btn", title="Focus mode"),
        ],
        className="visual-header-actions",
    )
    content = (
        body
        if body is not None
        else dcc.Loading(
            dcc.Graph(id={"type": "visual", "vid": vid}, config=GRAPH_CONFIG, style={"height": f"{height}px"}),
            type="dot",
            color="#118DFF",
            delay_show=300,
        )
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(title, className="visual-title"),
                            html.Div(subtitle, className="visual-subtitle", id=f"{vid}-subtitle")
                            if subtitle is not None
                            else None,
                        ],
                    ),
                    actions,
                ],
                className="visual-header",
            ),
            content,
            html.Div(hint, className="visual-hint") if hint else None,
        ],
        className=f"visual span-{span}",
    )


def kpi_slot(kid: str) -> html.Div:
    return html.Div(id=kid, className="visual kpi")


def kpi_card(
    label: str,
    value: str,
    delta: float | None = None,
    delta_label: str = "vs PY",
    spark: list[float] | None = None,
    mode: str = "light",
    invert: bool = False,
    note: str | None = None,
    points: bool = False,
) -> list:
    """Card visual: headline value, delta vs prior year (icon + sign + colour), sparkline."""
    children = [html.Div(label, className="kpi-label"), html.Div(value, className="kpi-value")]
    if delta is not None:
        up = delta >= 0
        good = up != invert
        children.append(
            html.Div(
                [
                    html.Span("▲" if up else "▼", className="kpi-arrow"),
                    f" {delta * 100:+.1f} pts " if points else f" {pct(delta, signed=True)} ",
                    html.Span(delta_label, className="kpi-delta-label"),
                ],
                className="kpi-delta " + ("good" if good else "bad"),
            )
        )
    if note:
        children.append(html.Div(note, className="kpi-note"))
    if spark:
        fig = go.Figure(
            go.Scatter(
                y=spark,
                mode="lines",
                line=dict(color="#118DFF", width=2),
                fill="tozeroy",
                fillcolor="rgba(17,141,255,0.10)",
                hoverinfo="skip",
            )
        )
        style(fig, mode)
        fig.update_layout(margin=dict(l=0, r=0, t=4, b=0), height=38)
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False, rangemode="tozero")
        children.append(dcc.Graph(figure=fig, config={"staticPlot": True}, className="kpi-spark"))
    return children


def data_table(
    df: pl.DataFrame,
    columns: list[tuple[str, str, str]],
    bar: str | None = None,
    color_scale: str | None = None,
    max_rows: int = 15,
    mode: str = "light",
) -> html.Div:
    """Matrix/table visual with conditional formatting.

    columns: (field, header, format) where format is one of
    text | int | money:<symbol> | pct | pct_signed
    bar: field rendered with an in-cell data bar
    color_scale: field rendered with a diverging background (YoY-style)
    """
    m = MODES[mode]
    df = df.head(max_rows)
    bar_max = max((abs(v) for v in df[bar].to_list() if v is not None), default=1) if bar else 1

    def fmt(v, kind: str) -> str:
        if v is None:
            return "–"
        if kind == "int":
            return f"{v:,.0f}"
        if kind.startswith("money"):
            return compact(v, kind.split(":")[1] if ":" in kind else "")
        if kind == "pct":
            return pct(v)
        if kind == "pct_signed":
            return pct(v, signed=True)
        return str(v)

    head = html.Thead(html.Tr([html.Th(h, className="num" if k != "text" else None) for _, h, k in columns]))
    rows = []
    for r in df.iter_rows(named=True):
        cells = []
        for field, _, kind in columns:
            v = r.get(field)
            text = fmt(v, kind)
            cls = "num" if kind != "text" else None
            if field == bar and v is not None:
                w = max(0.0, min(100.0, abs(v) / bar_max * 100))
                cells.append(
                    html.Td(
                        html.Div(
                            [html.Div(className="databar", style={"width": f"{w:.1f}%"}), html.Span(text)],
                            className="databar-cell",
                        ),
                        className="num",
                    )
                )
            elif field == color_scale and v is not None:
                tone = m["good"] if v >= 0 else m["bad"]
                alpha = min(0.35, abs(v) * 1.2 + 0.06)
                cells.append(html.Td(text, className="num", style={"background": _rgba(tone, alpha)}))
            else:
                cells.append(html.Td(text, className=cls))
        rows.append(html.Tr(cells))
    return html.Div(html.Table([head, html.Tbody(rows)], className="matrix"), className="matrix-wrap")


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha:.2f})"


def stat(label: str, value: str, note: str | None = None) -> list:
    return [
        html.Div(label, className="kpi-label"),
        html.Div(value, className="kpi-value"),
        html.Div(note, className="kpi-delta-label") if note else None,
    ]
