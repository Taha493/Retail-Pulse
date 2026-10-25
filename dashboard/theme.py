"""Visual theme shared with Power BI: colours come from powerbi/theme.json."""

from __future__ import annotations

import json
from pathlib import Path

import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
PBI_THEME = json.loads((ROOT / "powerbi" / "theme.json").read_text())

PALETTE: list[str] = PBI_THEME["dataColors"]
ACCENT = PALETTE[0]
GOOD, BAD, NEUTRAL = PBI_THEME["good"], PBI_THEME["bad"], PBI_THEME["neutral"]
FONT = '"Segoe UI", "Selawik", "Open Sans", system-ui, sans-serif'

# Light/dark surfaces and ink. The dark set is its own selection, not an inversion.
MODES = {
    "light": {
        "surface": "#FFFFFF",
        "ink": "#252423",
        "muted": "#605E5C",
        "faint": "#8A8886",
        "grid": "#EDEBE9",
        "axis": "#C8C6C4",
        "dim": "#E1DFDD",
        "seq": ["#EAF3FF", "#BFD9FF", "#7FB6FF", "#3C93F5", "#0F6CD4", "#0B4FA0"],
        "div": [BAD, "#E9E7E5", "#118DFF"],
        "good": GOOD,
        "bad": BAD,
    },
    "dark": {
        "surface": "#252423",
        "ink": "#F3F2F1",
        "muted": "#C8C6C4",
        "faint": "#A19F9D",
        "grid": "#3B3A39",
        "axis": "#605E5C",
        "dim": "#484644",
        "seq": ["#1C2B3F", "#1D4878", "#1F66B0", "#2F86E6", "#6AAEFF", "#B5D6FF"],
        "div": ["#F1707B", "#4A4846", "#4FA8FF"],
        "good": "#6CCB5F",
        "bad": "#F1707B",
    },
}


def color_for(entity: str, universe: list[str]) -> str:
    """Colour follows the entity (stable index in the full list), never its rank."""
    try:
        i = universe.index(entity)
    except ValueError:
        return NEUTRAL
    return PALETTE[i] if i < len(PALETTE) else NEUTRAL


def style(fig: go.Figure, mode: str = "light", height: int | None = None, legend: bool = False) -> go.Figure:
    m = MODES[mode]
    fig.update_layout(
        font=dict(family=FONT, size=11, color=m["muted"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=12, t=8, b=8),
        hoverlabel=dict(bgcolor=m["surface"], bordercolor=m["axis"], font=dict(family=FONT, color=m["ink"], size=12)),
        showlegend=legend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.0,
            xanchor="left",
            x=0,
            font=dict(color=m["muted"]),
            bgcolor="rgba(0,0,0,0)",
        ),
        bargap=0.25,
        colorway=PALETTE,
        uirevision="keep",
    )
    axis = dict(
        gridcolor=m["grid"],
        linecolor=m["axis"],
        zerolinecolor=m["axis"],
        tickfont=dict(color=m["muted"]),
        title_font=dict(color=m["muted"]),
        automargin=True,
        showspikes=False,
    )
    fig.update_xaxes(**axis, showgrid=False)
    fig.update_yaxes(**axis, showgrid=True)
    if height:
        fig.update_layout(height=height)
    return fig


def empty(mode: str = "light", message: str = "No data for the current filters") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(color=MODES[mode]["faint"], size=13))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, mode)


# --- number formatting ----------------------------------------------------------


def compact(v: float | None, prefix: str = "", decimals: int = 1) -> str:
    if v is None:
        return "–"
    sign = "-" if v < 0 else ""
    a = abs(v)
    for div, suffix in ((1e9, "bn"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}{prefix}{a / div:.{decimals}f}{suffix}"
    return f"{sign}{prefix}{a:,.0f}" if a >= 100 else f"{sign}{prefix}{a:,.2f}"


def pct(v: float | None, decimals: int = 1, signed: bool = False) -> str:
    if v is None:
        return "–"
    return f"{v * 100:+.{decimals}f}%" if signed else f"{v * 100:.{decimals}f}%"
