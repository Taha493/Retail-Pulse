"""Single access point to the semantic model, plus the shared filter-context inputs."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import polars as pl
from dash import Input

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_bi.measures.measures import CURRENCIES, Filters, SemanticModel, default_ytd  # noqa: E402

MODEL = SemanticModel()
FIRST_DATE, LAST_DATE = MODEL.date_bounds()
YTD_START, YTD_END = default_ytd(MODEL)

# Slicer id -> mart column
SLICERS = {"sl-region": "region", "sl-country": "country_name", "sl-category": "category", "sl-segment": "rfm_segment"}

# Every report visual listens to the same filter context: this is what keeps
# slicers "synced" across pages, like Power BI's Sync Slicers pane.
CONTEXT_INPUTS = [
    Input("sl-date", "start_date"),
    Input("sl-date", "end_date"),
    Input("sl-currency", "value"),
    *[Input(sid, "value") for sid in SLICERS],
    Input("xfilter", "data"),
    Input("theme", "data"),
]

# Visual id -> column it cross-filters on when a data point is clicked
XF_DIMS: dict[str, str] = {}
# Visual id -> function(Filters) -> DataFrame, used by "Export data"
EXPORTS: dict[str, Callable[[Filters], pl.DataFrame]] = {}


def context(start, end, currency, *rest) -> tuple[Filters, dict | None, str, str]:
    """Turn raw callback inputs into (filter context, cross-filter, theme, currency symbol)."""
    *slicer_values, xf, theme = rest
    slicers = {col: v for col, v in zip(SLICERS.values(), slicer_values, strict=True) if v}
    cross = {xf["dim"]: [xf["value"]]} if xf else None
    f = Filters.build(start, end, currency, slicers, cross)
    return f, xf, theme or "light", CURRENCIES.get(currency or "GBP", "£")


def selected(xf: dict | None, dim: str) -> str | None:
    return xf["value"] if xf and xf.get("dim") == dim else None


@lru_cache(maxsize=1)
def options(column: str) -> list[str]:
    return MODEL.distinct(column)


@lru_cache(maxsize=1)
def countries_by_region() -> dict[str, list[str]]:
    df = MODEL.sql("SELECT DISTINCT region, country_name FROM mart_sales ORDER BY 2")
    return {r: g["country_name"].to_list() for (r,), g in df.group_by("region")}


@lru_cache(maxsize=1)
def dq_tables() -> tuple[pl.DataFrame, pl.DataFrame]:
    return MODEL.sql("SELECT * FROM dq_rule_log ORDER BY step"), MODEL.sql("SELECT * FROM dq_validation")
