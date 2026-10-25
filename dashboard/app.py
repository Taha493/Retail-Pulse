"""Retail Insights: a Power BI-style report built with Plotly Dash.

Run:  uv run python dashboard/app.py   ->  http://127.0.0.1:8050
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import dash  # noqa: E402
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update  # noqa: E402

import data_access as da  # noqa: E402
from components import TITLES  # noqa: E402

app = Dash(
    __name__,
    use_pages=True,
    pages_folder=str(Path(__file__).parent / "pages"),
    title="Retail Insights · Power BI-style report",
    suppress_callback_exceptions=True,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap",
    ],
)
server = app.server


def slicer(label: str, component) -> html.Div:
    return html.Div([html.Div(label, className="slicer-label"), component], className="slicer")


def dropdown(sid: str, column: str, placeholder: str = "All") -> dcc.Dropdown:
    return dcc.Dropdown(
        id=sid,
        options=da.options(column),
        multi=True,
        placeholder=placeholder,
        className="slicer-dd",
        persistence=True,
        persistence_type="session",
    )


header = html.Header(
    [
        html.Div(
            [
                html.Div(className="logo", children=[html.Span(), html.Span(), html.Span()]),
                html.Div(
                    [
                        html.Div("Retail Insights", className="report-title"),
                        html.Div(
                            f"Online Retail II · data through {da.MODEL.last_refresh()}",
                            className="report-subtitle",
                        ),
                    ]
                ),
            ],
            className="brand",
        ),
        html.Div(
            [
                dcc.RadioItems(
                    id="sl-currency",
                    options=[{"label": c, "value": c} for c in ("GBP", "EUR", "USD")],
                    value="GBP",
                    inline=True,
                    className="segmented",
                    persistence=True,
                ),
                html.Button("◐", id="theme-toggle", className="icon-btn", title="Toggle light / dark"),
            ],
            className="header-actions",
        ),
    ],
    className="app-header",
)

slicer_bar = html.Div(
    [
        slicer(
            "Date",
            html.Div(
                [
                    dcc.DatePickerRange(
                        id="sl-date",
                        min_date_allowed=da.FIRST_DATE,
                        max_date_allowed=da.LAST_DATE,
                        start_date=da.YTD_START,
                        end_date=da.YTD_END,
                        display_format="DD MMM YYYY",
                        first_day_of_week=1,
                        className="slicer-date",
                        persistence=True,
                        persistence_type="session",
                    ),
                    html.Div(
                        [
                            html.Button("2011 YTD", id="preset-ytd", className="chip-btn"),
                            html.Button("2010", id="preset-2010", className="chip-btn"),
                            html.Button("All", id="preset-all", className="chip-btn"),
                        ],
                        className="presets",
                    ),
                ],
                className="date-wrap",
            ),
        ),
        slicer("Region", dropdown("sl-region", "region")),
        slicer("Country", dropdown("sl-country", "country_name")),
        slicer("Category", dropdown("sl-category", "category")),
        slicer("Customer segment", dropdown("sl-segment", "rfm_segment")),
    ],
    className="slicer-bar",
)

filter_strip = html.Div(
    [
        html.Div(id="active-filters", className="active-filters"),
        html.Button("Clear all filters", id="btn-clear", className="link-btn"),
    ],
    className="filter-strip",
)


def page_tabs() -> html.Nav:
    return html.Nav(
        [
            dcc.Link(p["name"], href=p["relative_path"], className="page-tab", id=f"tab-{p['module'].split('.')[-1]}")
            for p in dash.page_registry.values()
        ],
        className="page-tabs",
        id="page-tabs",
    )


focus_modal = html.Div(
    html.Div(
        [
            html.Div(
                [
                    html.Div(id="focus-title", className="visual-title"),
                    html.Button("← Back to report", id="focus-close", className="link-btn"),
                ],
                className="focus-header",
            ),
            dcc.Graph(id="focus-graph", config={"displayModeBar": False}, style={"height": "70vh"}),
        ],
        className="focus-panel",
    ),
    id="focus-modal",
    className="focus-modal hidden",
)

app.layout = html.Div(
    [
        dcc.Location(id="url"),
        dcc.Store(id="xfilter", data=None),
        dcc.Store(id="theme", data="light", storage_type="local"),
        dcc.Download(id="download"),
        header,
        html.Main(
            [slicer_bar, filter_strip, html.Div(dash.page_container, className="canvas")],
            className="report",
        ),
        page_tabs(),
        focus_modal,
    ],
    id="root",
    className="theme-light",
)


# --- theme ----------------------------------------------------------------------


@app.callback(
    Output("theme", "data"), Input("theme-toggle", "n_clicks"), State("theme", "data"), prevent_initial_call=True
)
def toggle_theme(_, mode):
    return "dark" if mode == "light" else "light"


@app.callback(Output("root", "className"), Input("theme", "data"))
def apply_theme(mode):
    return f"theme-{mode or 'light'}"


# --- page tabs: highlight the active page -----------------------------------------


@app.callback(
    [Output(f"tab-{p['module'].split('.')[-1]}", "className") for p in dash.page_registry.values()],
    Input("url", "pathname"),
)
def active_tab(path):
    return [
        "page-tab active" if (path or "/") == p["relative_path"] else "page-tab" for p in dash.page_registry.values()
    ]


# --- slicers --------------------------------------------------------------------


@app.callback(
    Output("sl-date", "start_date"),
    Output("sl-date", "end_date"),
    *[Output(sid, "value") for sid in da.SLICERS],
    Output("sl-currency", "value"),
    Input("preset-ytd", "n_clicks"),
    Input("preset-2010", "n_clicks"),
    Input("preset-all", "n_clicks"),
    Input("btn-clear", "n_clicks"),
    prevent_initial_call=True,
)
def presets(*_):
    keep = [no_update] * len(da.SLICERS)
    match ctx.triggered_id:
        case "preset-ytd":
            return da.YTD_START, da.YTD_END, *keep, no_update
        case "preset-2010":
            return "2010-01-01", "2010-12-31", *keep, no_update
        case "preset-all":
            return da.FIRST_DATE, da.LAST_DATE, *keep, no_update
        case _:  # clear all
            return da.YTD_START, da.YTD_END, *([None] * len(da.SLICERS)), "GBP"


@app.callback(Output("sl-country", "options"), Input("sl-region", "value"))
def cascade_countries(regions):
    """Cascading slicer: the country list follows the region selection."""
    if not regions:
        return da.options("country_name")
    by_region = da.countries_by_region()
    return sorted(c for r in regions for c in by_region.get(r, []))


# --- cross-filtering ------------------------------------------------------------


@app.callback(
    Output("xfilter", "data"),
    Input({"type": "visual", "vid": ALL}, "clickData"),
    Input("url", "pathname"),
    Input("btn-clear", "n_clicks"),
    State("xfilter", "data"),
    prevent_initial_call=True,
)
def cross_filter(clicks, _path, _clear, current):
    """Click a data point to filter every other visual; click it again to clear."""
    trig = ctx.triggered_id
    if trig in ("url", "btn-clear"):
        return None
    if not isinstance(trig, dict):
        return no_update
    dim = da.XF_DIMS.get(trig["vid"])
    value = ctx.triggered[0]["value"]
    if not dim or not value:
        return no_update
    point = value["points"][0]
    raw = point.get("customdata")
    label = raw[0] if isinstance(raw, list) else raw
    if label is None:
        return no_update
    if current and current["dim"] == dim and current["value"] == label:
        return None
    return {"dim": dim, "value": label, "vid": trig["vid"]}


@app.callback(Output("active-filters", "children"), da.CONTEXT_INPUTS)
def show_filters(start, end, currency, *rest):
    *slicer_values, xf, _ = rest
    chips = [
        html.Span(
            f"{start[:10] if isinstance(start, str) else start} → {end[:10] if isinstance(end, str) else end}",
            className="chip",
        )
    ]
    labels = ["Region", "Country", "Category", "Segment"]
    for label, values in zip(labels, slicer_values, strict=True):
        if values:
            text = ", ".join(values[:3]) + (f" +{len(values) - 3}" if len(values) > 3 else "")
            chips.append(html.Span([html.B(f"{label}: "), text], className="chip"))
    if xf:
        chips.append(html.Span([html.B("Cross-filter: "), f"{xf['value']}"], className="chip chip-accent"))
    if currency and currency != "GBP":
        chips.append(html.Span([html.B("Currency: "), currency], className="chip"))
    return chips


# --- visual header actions: export + focus mode -------------------------------------


@app.callback(
    Output("download", "data"),
    Input({"type": "export", "vid": ALL}, "n_clicks"),
    State("sl-date", "start_date"),
    State("sl-date", "end_date"),
    State("sl-currency", "value"),
    *[State(sid, "value") for sid in da.SLICERS],
    State("xfilter", "data"),
    State("theme", "data"),
    prevent_initial_call=True,
)
def export(clicks, *state):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        return no_update
    vid = ctx.triggered_id["vid"]
    fn = da.EXPORTS.get(vid)
    if fn is None:
        return no_update
    f, *_ = da.context(*state)
    return dcc.send_string(fn(f).write_csv(), f"{vid}.csv")


@app.callback(
    Output("focus-modal", "className"),
    Output("focus-graph", "figure"),
    Output("focus-title", "children"),
    Input({"type": "focus", "vid": ALL}, "n_clicks"),
    Input("focus-close", "n_clicks"),
    State({"type": "visual", "vid": ALL}, "figure"),
    prevent_initial_call=True,
)
def focus(clicks, _close, figures):
    if ctx.triggered_id == "focus-close" or not ctx.triggered[0]["value"]:
        return "focus-modal hidden", no_update, no_update
    vid = ctx.triggered_id["vid"]
    for spec, fig in zip(ctx.states_list[0], figures, strict=True):
        if spec["id"]["vid"] == vid and fig:
            fig = dict(fig)
            fig["layout"] = {**fig.get("layout", {}), "height": None, "autosize": True}
            return "focus-modal", fig, TITLES.get(vid, vid)
    return "focus-modal hidden", no_update, no_update


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 8050)),
        debug=os.environ.get("DEBUG", "0") == "1",
    )
