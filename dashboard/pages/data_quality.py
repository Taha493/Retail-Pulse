"""Page 6: Data Quality: the pipeline's audit trail, inside the report."""

from __future__ import annotations

import dash
import plotly.graph_objects as go
import polars as pl
from dash import Input, Output, callback, html

import data_access as da
from components import data_table, kpi_slot, stat, visual
from theme import MODES, PALETTE, style

dash.register_page(__name__, path="/data-quality", name="Data Quality", order=5)

da.EXPORTS.update(
    {
        "dq-funnel": lambda f: da.dq_tables()[0],
        "dq-rules": lambda f: da.dq_tables()[0],
        "dq-contracts": lambda f: da.dq_tables()[1],
    }
)

layout = html.Div(
    [
        html.Div([kpi_slot(k) for k in ("dq-raw", "dq-removed", "dq-final", "dq-pass")], className="kpi-row span-12"),
        visual(
            "dq-funnel",
            "From raw rows to analysis-ready rows",
            span=5,
            height=300,
            subtitle="Duplicates are removed; everything else is flagged and kept",
        ),
        visual(
            "dq-flags",
            "Rows flagged per rule",
            span=7,
            height=300,
            subtitle="Flags exclude rows from analysis without deleting them",
        ),
        visual("dq-rules", "Cleaning rules in execution order", span=7, height=360, body=html.Div(id="dq-rules-body")),
        visual("dq-contracts", "Data contracts (Pandera)", span=5, height=360, body=html.Div(id="dq-contracts-body")),
    ],
    className="grid",
)


@callback(
    Output("dq-raw", "children"),
    Output("dq-removed", "children"),
    Output("dq-final", "children"),
    Output("dq-pass", "children"),
    Output({"type": "visual", "vid": "dq-funnel"}, "figure"),
    Output({"type": "visual", "vid": "dq-flags"}, "figure"),
    Output("dq-rules-body", "children"),
    Output("dq-contracts-body", "children"),
    Input("theme", "data"),
)
def update(mode):
    mode = mode or "light"
    m = MODES[mode]
    rules, contracts = da.dq_tables()
    raw = rules.filter(pl.col("action") == "source")["rows_affected"].item()
    removed = rules.filter(pl.col("action") == "removed")["rows_affected"].sum()
    final = rules.filter(pl.col("action") == "final")["rows_affected"].item()
    passed = (contracts["status"] == "PASS").sum()
    tiles = [
        stat("Raw rows", f"{raw:,}", "2 Excel sheets appended"),
        stat("Rows removed", f"{removed:,}", f"{removed / raw:.1%} (duplicates only)"),
        stat("Analysis-ready rows", f"{final:,}", f"{final / raw:.1%} of raw rows"),
        stat("Contracts passed", f"{passed}/{contracts.height}", f"{contracts['checks'].sum():,} checks across layers"),
    ]

    stages = ["Raw rows", "After de-duplication", "Analysis-ready"]
    values = [raw, raw - removed, final]
    funnel = go.Figure(
        go.Funnel(
            y=stages,
            x=values,
            texttemplate="%{value:,}<br>%{percentInitial:.1%}",
            marker=dict(color=[PALETTE[0]] * 3),
            textfont=dict(color="#FFFFFF"),
            connector=dict(fillcolor=m["grid"]),
            hovertemplate="%{y}: %{x:,} rows<extra></extra>",
        )
    )
    style(funnel, mode)

    flags = rules.filter(pl.col("action") == "flagged").sort("rows_affected")
    flag_fig = go.Figure(
        go.Bar(
            x=flags["rows_affected"].to_list(),
            y=flags["rule"].to_list(),
            orientation="h",
            marker=dict(color=PALETTE[0], cornerradius=4),
            text=[f"{v:,}" for v in flags["rows_affected"].to_list()],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(color=m["muted"]),
            customdata=flags["description"].to_list(),
            hovertemplate="<b>%{y}</b><br>%{x:,} rows<br>%{customdata}<extra></extra>",
        )
    )
    style(flag_fig, mode)
    flag_fig.update_xaxes(visible=False, range=[0, max(flags["rows_affected"].to_list()) * 1.15])
    flag_fig.update_yaxes(tickfont=dict(color=m["ink"]), ticksuffix="  ")

    rule_table = data_table(
        rules.with_columns(pl.col("step").cast(pl.Int64)),
        [
            ("step", "#", "int"),
            ("rule", "Rule", "text"),
            ("action", "Action", "text"),
            ("rows_affected", "Rows", "int"),
            ("description", "What it does", "text"),
        ],
        bar="rows_affected",
        max_rows=40,
        mode=mode,
    )
    contract_rows = [
        html.Tr(
            [
                html.Td(r["table"]),
                html.Td(f"{r['rows']:,}", className="num"),
                html.Td(r["checks"], className="num"),
                html.Td(html.Span(r["status"], className=f"pill {r['status'].lower()}")),
            ]
        )
        for r in contracts.iter_rows(named=True)
    ]
    contract_table = html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Layer.table"),
                            html.Th("Rows", className="num"),
                            html.Th("Checks", className="num"),
                            html.Th("Status"),
                        ]
                    )
                ),
                html.Tbody(contract_rows),
            ],
            className="matrix",
        ),
        className="matrix-wrap",
    )
    return (*tiles, funnel, flag_fig, rule_table, contract_table)
