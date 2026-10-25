"""Semantic layer: the Python twin of powerbi/measures.dax.

Each DAX measure has a SQL expression here with the same name. `Filters` plays
the role of Power BI's filter context (slicers + cross-filter selections), and
`SemanticModel` evaluates measures against the DuckDB warehouse.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import duckdb
import polars as pl

from retail_bi.config import paths

CURRENCIES = {"GBP": "£", "EUR": "€", "USD": "$"}

# Measure name -> SQL aggregate over mart_sales. `{rev}` becomes the revenue
# column of the selected currency (the DAX version uses SWITCH on a slicer).
MEASURES: dict[str, str] = {
    "Total Revenue": "SUM({rev}) FILTER (WHERE NOT is_return)",
    "Return Value": "COALESCE(-SUM({rev}) FILTER (WHERE is_return), 0)",
    "Net Revenue": "SUM({rev})",
    "Total Orders": "COUNT(DISTINCT invoice_no) FILTER (WHERE NOT is_return)",
    "Units Sold": "SUM(quantity) FILTER (WHERE NOT is_return)::BIGINT",
    "Active Customers": "COUNT(DISTINCT customer_key) FILTER (WHERE NOT is_return AND NOT is_guest)",
    "Avg Order Value": "SUM({rev}) FILTER (WHERE NOT is_return) "
    "/ NULLIF(COUNT(DISTINCT invoice_no) FILTER (WHERE NOT is_return), 0)",
    "Return Rate %": "COALESCE(-SUM({rev}) FILTER (WHERE is_return), 0) "
    "/ NULLIF(SUM({rev}) FILTER (WHERE NOT is_return), 0)",
    "Revenue per Customer": "SUM({rev}) FILTER (WHERE NOT is_return AND NOT is_guest) "
    "/ NULLIF(COUNT(DISTINCT customer_key) FILTER (WHERE NOT is_return AND NOT is_guest), 0)",
    "Avg Unit Price": "SUM({rev}) FILTER (WHERE NOT is_return) / NULLIF(SUM(quantity) FILTER (WHERE NOT is_return), 0)",
}

# Columns a slicer or cross-filter may target (whitelist -> safe to inline).
FILTERABLE = {
    "country_name",
    "region",
    "market",
    "category",
    "sub_category",
    "rfm_segment",
    "abc_class",
    "price_band",
    "product_name",
    "weekday_short",
    "month_start",
    "year",
}


@dataclass(frozen=True)
class Filters:
    """Filter context: slicer values + cross-filter selections."""

    start: date | None = None
    end: date | None = None
    currency: str = "GBP"
    slicers: tuple[tuple[str, tuple], ...] = ()
    cross: tuple[tuple[str, tuple], ...] = field(default=())

    @classmethod
    def build(
        cls, start=None, end=None, currency="GBP", slicers: dict | None = None, cross: dict | None = None
    ) -> Filters:
        def norm(d: dict | None) -> tuple:
            return tuple(sorted((k, tuple(v)) for k, v in (d or {}).items() if v))

        to_date = lambda v: date.fromisoformat(v[:10]) if isinstance(v, str) else v  # noqa: E731
        return cls(to_date(start), to_date(end), currency or "GBP", norm(slicers), norm(cross))

    @property
    def rev(self) -> str:
        return f"revenue_{self.currency.lower()}"

    def without(self, column: str) -> Filters:
        """Drop one column's filters (a visual never filters itself)."""
        return replace(
            self,
            slicers=tuple(s for s in self.slicers if s[0] != column),
            cross=tuple(c for c in self.cross if c[0] != column),
        )

    def shifted_years(self, years: int) -> Filters:
        """SAMEPERIODLASTYEAR for the date range."""

        def shift(d: date | None) -> date | None:
            if d is None:
                return None
            try:
                return d.replace(year=d.year + years)
            except ValueError:  # 29 Feb
                return d.replace(year=d.year + years, day=28)

        return replace(self, start=shift(self.start), end=shift(self.end))

    def where(self, extra: str | None = None) -> tuple[str, list]:
        clauses, params = ["TRUE"], []
        if self.start:
            clauses.append("date >= ?")
            params.append(self.start)
        if self.end:
            clauses.append("date <= ?")
            params.append(self.end)
        for col, values in self.slicers + self.cross:
            if col not in FILTERABLE:
                raise ValueError(f"Column {col!r} is not filterable")
            clauses.append(f"{col} IN ({', '.join('?' * len(values))})")
            params.extend(values)
        if extra:
            clauses.append(extra)
        return " AND ".join(clauses), params


class SemanticModel:
    """Evaluates measures under a filter context. Thread-safe (one cursor per thread)."""

    def __init__(self, db_path: Path | None = None):
        self._con = duckdb.connect(str(db_path or paths().warehouse), read_only=True)
        self._local = threading.local()

    def _cur(self) -> duckdb.DuckDBPyConnection:
        if not hasattr(self._local, "cur"):
            self._local.cur = self._con.cursor()
        return self._local.cur

    def sql(self, query: str, params: list | None = None) -> pl.DataFrame:
        return pl.from_arrow(self._cur().sql(query, params=params or None).to_arrow_table())

    @staticmethod
    def measure_sql(names: list[str], f: Filters) -> str:
        return ", ".join(f'{MEASURES[n].format(rev=f.rev)} AS "{n}"' for n in names)

    # --- core evaluation ------------------------------------------------------

    def evaluate(self, f: Filters, names: list[str] | None = None) -> dict[str, float | None]:
        names = names or list(MEASURES)
        where, params = f.where()
        row = self.sql(f"SELECT {self.measure_sql(names, f)} FROM mart_sales WHERE {where}", params)
        return row.row(0, named=True)

    def by(
        self,
        f: Filters,
        group: list[str],
        names: list[str],
        order: str | None = None,
        limit: int | None = None,
        extra_where: str | None = None,
    ) -> pl.DataFrame:
        where, params = f.where(extra_where)
        cols = ", ".join(group)
        q = f"SELECT {cols}, {self.measure_sql(names, f)} FROM mart_sales WHERE {where} GROUP BY {cols}"
        q += f" ORDER BY {order or cols}"
        if limit:
            q += f" LIMIT {int(limit)}"
        return self.sql(q, params)

    # --- time intelligence ----------------------------------------------------

    def with_prior_year(self, f: Filters, names: list[str]) -> tuple[dict, dict]:
        """Current and SAMEPERIODLASTYEAR values for KPI cards."""
        return self.evaluate(f, names), self.evaluate(f.shifted_years(-1), names)

    def monthly_with_py(self, f: Filters, name: str = "Net Revenue") -> pl.DataFrame:
        cur = self.by(f, ["month_start"], [name])
        py = (
            self.by(f.shifted_years(-1), ["month_start"], [name])
            .with_columns(pl.col("month_start").dt.offset_by("1y"))
            .rename({name: f"{name} PY"})
        )
        return cur.join(py, on="month_start", how="left").with_columns(
            ((pl.col(name) - pl.col(f"{name} PY")) / pl.col(f"{name} PY")).alias("YoY %"),
            pl.col(name).pct_change().alias("MoM %"),
            pl.col(name).rolling_mean(3, min_samples=1).alias("Rolling 3M Avg"),
        )

    def trend(self, f: Filters, grain: str, names: list[str]) -> pl.DataFrame:
        """Measures on the date hierarchy (Year -> Quarter -> Month -> Day)."""
        if grain not in {"year", "quarter", "month", "day"}:
            raise ValueError(grain)
        where, params = f.where()
        return self.sql(
            f"""SELECT date_trunc('{grain}', date)::DATE AS period, {self.measure_sql(names, f)}
                FROM mart_sales WHERE {where} GROUP BY 1 ORDER BY 1""",
            params,
        )

    def weekday_hour(self, f: Filters, name: str = "Net Revenue") -> pl.DataFrame:
        return self.by(f, ["weekday_num", "weekday_short", "invoice_hour"], [name])

    def period_to_date(self, f: Filters) -> dict[str, float]:
        """MTD / QTD / YTD net revenue as of the end of the selected range."""
        end = f.end or self.sql("SELECT MAX(date) d FROM mart_sales").item()
        starts = {
            "MTD": end.replace(day=1),
            "QTD": date(end.year, 3 * ((end.month - 1) // 3) + 1, 1),
            "YTD": date(end.year, 1, 1),
        }
        out = {}
        for k, s in starts.items():
            out[k] = self.evaluate(replace(f, start=s, end=end), ["Net Revenue"])["Net Revenue"] or 0.0
        return out

    # --- customer analytics ---------------------------------------------------

    def new_vs_returning(self, f: Filters) -> pl.DataFrame:
        """Active customers per month split by first-purchase month."""
        where, params = f.where("NOT is_return AND NOT is_guest")
        return self.sql(
            f"""
            SELECT month_start,
                   COUNT(DISTINCT customer_key) FILTER (WHERE cohort_month = month_start) AS "New Customers",
                   COUNT(DISTINCT customer_key) FILTER (WHERE cohort_month < month_start) AS "Returning Customers"
            FROM mart_sales WHERE {where} GROUP BY month_start ORDER BY month_start
            """,
            params,
        )

    def cohort_retention(self, f: Filters, max_months: int = 12) -> pl.DataFrame:
        where, params = f.where("NOT is_return AND NOT is_guest")
        return self.sql(
            f"""
            WITH a AS (
                SELECT DISTINCT customer_key, cohort_month, month_start FROM mart_sales WHERE {where}
            ), s AS (
                SELECT cohort_month, date_diff('month', cohort_month, month_start) AS m, COUNT(*) AS n
                FROM a GROUP BY ALL
            ), size AS (
                SELECT cohort_month, COUNT(DISTINCT customer_key) AS cohort_size
                FROM mart_sales WHERE NOT is_guest AND NOT is_return AND cohort_month = month_start
                GROUP BY ALL
            )
            SELECT s.cohort_month, s.m AS months_since_first, s.n AS active, size.cohort_size,
                   s.n / size.cohort_size AS retention
            FROM s JOIN size USING (cohort_month)
            WHERE s.m BETWEEN 0 AND {int(max_months)}
            ORDER BY cohort_month, months_since_first
            """,
            params,
        )

    def repeat_purchase_rate(self, f: Filters) -> float | None:
        where, params = f.where("NOT is_return AND NOT is_guest")
        return self.sql(
            f"""SELECT AVG((n > 1)::INT) AS r FROM (
                    SELECT customer_key, COUNT(DISTINCT invoice_no) n FROM mart_sales WHERE {where} GROUP BY 1)""",
            params,
        ).item()

    def segment_summary(self, f: Filters) -> pl.DataFrame:
        return self.by(
            f,
            ["rfm_segment"],
            ["Net Revenue", "Active Customers", "Revenue per Customer"],
            order='"Net Revenue" DESC',
            extra_where="NOT is_guest",
        )

    def customer_value_distribution(self, f: Filters) -> pl.DataFrame:
        where, params = f.where("NOT is_guest")
        return self.sql(
            f"""SELECT customer_label, rfm_segment, SUM({f.rev}) AS value,
                       COUNT(DISTINCT invoice_no) FILTER (WHERE NOT is_return) AS orders
                FROM mart_sales WHERE {where} GROUP BY ALL HAVING SUM({f.rev}) > 0""",
            params,
        )

    # --- product analytics ----------------------------------------------------

    def pareto(self, f: Filters) -> pl.DataFrame:
        """RANKX + cumulative share of net revenue per product (ABC curve)."""
        df = self.by(f, ["product_name", "abc_class"], ["Net Revenue"], order='"Net Revenue" DESC')
        total = df["Net Revenue"].clip(0).sum()
        return df.with_columns(
            pl.int_range(1, pl.len() + 1).alias("Revenue Rank"),
            (pl.col("Net Revenue").clip(0).cum_sum() / total).alias("Cumulative Revenue %"),
            (pl.col("Net Revenue") / total).alias("Product Share %"),
        )

    def product_returns(self, f: Filters, min_revenue: float = 2000) -> pl.DataFrame:
        return self.by(
            f,
            ["product_name", "category"],
            ["Total Revenue", "Return Value", "Return Rate %", "Units Sold"],
            order='"Total Revenue" DESC',
        ).filter(pl.col("Total Revenue") >= min_revenue)

    # --- geography ------------------------------------------------------------

    def countries(self, f: Filters) -> pl.DataFrame:
        where, params = f.where()
        return self.sql(
            f"""SELECT m.country_name, m.iso3, m.region, m.market, d.population, d.gdp_per_capita,
                       {self.measure_sql(["Net Revenue", "Total Orders", "Active Customers", "Avg Order Value"], f)},
                       SUM(m.{f.rev}) / NULLIF(d.population, 0) * 1e6 AS "Revenue per 1M Population"
                FROM mart_sales m JOIN dim_country d USING (country_key)
                WHERE {where}
                GROUP BY m.country_name, m.iso3, m.region, m.market, d.population, d.gdp_per_capita
                ORDER BY "Net Revenue" DESC""",
            params,
        )

    # --- metadata -------------------------------------------------------------

    def date_bounds(self) -> tuple[date, date]:
        row = self.sql("SELECT MIN(date) AS a, MAX(date) AS b FROM mart_sales").row(0)
        return row[0], row[1]

    def distinct(self, column: str) -> list[str]:
        if column not in FILTERABLE:
            raise ValueError(column)
        return self.sql(f"SELECT DISTINCT {column} AS v FROM mart_sales WHERE v IS NOT NULL ORDER BY 1")["v"].to_list()

    def last_refresh(self) -> str:
        return self.sql("SELECT MAX(invoice_datetime) AS t FROM mart_sales").item().strftime("%d %b %Y")


def default_ytd(model: SemanticModel) -> tuple[date, date]:
    """Default report period: calendar YTD of the latest year in the data."""
    _, last = model.date_bounds()
    return date(last.year, 1, 1), last


def previous_day(d: date) -> date:
    return d - timedelta(days=1)
