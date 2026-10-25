"""Pandera data contracts for each layer. Run after every build."""

from __future__ import annotations

from datetime import datetime

import pandera.polars as pa
import polars as pl

from retail_bi.config import get_logger, paths, settings

log = get_logger(__name__)

_p = settings()["period"]
START = datetime.fromisoformat(_p["start"])
END = datetime.fromisoformat(_p["end"]).replace(hour=23, minute=59)
DATE_KEY_MIN = int(START.strftime("%Y%m%d"))
DATE_KEY_MAX = int(END.strftime("%Y%m%d"))


def _frame_check(expr: pl.Expr, name: str) -> pa.Check:
    return pa.Check(lambda data: data.lazyframe.select(expr), name=name)


BRONZE_RETAIL = pa.DataFrameSchema(
    {
        "invoice": pa.Column(pl.String, pa.Check.str_matches(r"^[CA]?\d{6}$")),
        "stock_code": pa.Column(pl.String),
        "description": pa.Column(pl.String, nullable=True),
        "quantity": pa.Column(pl.Int64),
        "invoice_date": pa.Column(pl.Datetime("us"), pa.Check.in_range(START, END)),
        "price": pa.Column(pl.Float64),
        "customer_id": pa.Column(pl.Int64, nullable=True),
        "country": pa.Column(pl.String),
    },
    name="bronze.retail",
)

SILVER_LINES = pa.DataFrameSchema(
    {
        "invoice_type": pa.Column(pl.String, pa.Check.isin(["sale", "cancellation", "bad_debt"])),
        "line_type": pa.Column(
            pl.String, pa.Check.isin(["product", "postage", "fee", "adjustment", "test", "stock_writeoff"])
        ),
        "customer_id": pa.Column(pl.Int64),
        "country_iso3": pa.Column(pl.String, pa.Check.str_length(3, 3)),
        "product_name": pa.Column(pl.String),
        "category": pa.Column(pl.String),
        "date_key": pa.Column(pl.Int32, pa.Check.in_range(DATE_KEY_MIN, DATE_KEY_MAX)),
        "is_analysis_line": pa.Column(pl.Boolean),
    },
    checks=[
        _frame_check(
            ~pl.col("is_analysis_line") | ((pl.col("price") > 0) & (pl.col("line_type") == "product")),
            "analysis_lines_are_priced_products",
        ),
    ],
    name="silver.retail_lines",
)

GOLD = {
    "fact_sales": pa.DataFrameSchema(
        {
            "sales_key": pa.Column(pl.Int32, unique=True),
            "invoice_no": pa.Column(pl.String, pa.Check.str_matches(r"^C?\d{6}$")),
            "date_key": pa.Column(pl.Int32, pa.Check.in_range(DATE_KEY_MIN, DATE_KEY_MAX)),
            "customer_key": pa.Column(pl.Int32),
            "product_key": pa.Column(pl.Int32),
            "country_key": pa.Column(pl.Int32),
            "quantity": pa.Column(pl.Int64, pa.Check.ne(0)),
            "unit_price_gbp": pa.Column(pl.Float64, pa.Check.gt(0)),
            "revenue_gbp": pa.Column(pl.Float64),
            "revenue_eur": pa.Column(pl.Float64),
            "revenue_usd": pa.Column(pl.Float64),
            "is_return": pa.Column(pl.Boolean),
        },
        checks=[
            _frame_check(
                (pl.col("revenue_gbp") - pl.col("quantity") * pl.col("unit_price_gbp")).abs() < 0.011,
                "revenue_equals_qty_x_price",
            ),
            _frame_check(pl.col("is_return") == (pl.col("quantity") < 0), "returns_have_negative_qty"),
            _frame_check(pl.col("is_return") == pl.col("invoice_no").str.starts_with("C"), "returns_are_c_invoices"),
        ],
        name="gold.fact_sales",
    ),
    "dim_date": pa.DataFrameSchema(
        {
            "date_key": pa.Column(pl.Int32, unique=True),
            "date": pa.Column(pl.Date, unique=True),
            "month_num": pa.Column(pl.Int8, pa.Check.in_range(1, 12)),
            "weekday_num": pa.Column(pl.Int8, pa.Check.in_range(1, 7)),
        },
        checks=[_frame_check(pl.col("date").diff().dt.total_days().fill_null(1) == 1, "date_table_is_contiguous")],
        name="gold.dim_date",
    ),
    "dim_customer": pa.DataFrameSchema(
        {
            "customer_key": pa.Column(pl.Int32, unique=True),
            "customer_id": pa.Column(pl.Int64, unique=True),
            "rfm_segment": pa.Column(pl.String),
            "r_score": pa.Column(pl.Int8, pa.Check.in_range(1, 5), nullable=True),
        },
        name="gold.dim_customer",
    ),
    "dim_product": pa.DataFrameSchema(
        {
            "product_key": pa.Column(pl.Int32, unique=True),
            "stock_code": pa.Column(pl.String, unique=True),
            "product_name": pa.Column(pl.String),
            "category": pa.Column(pl.String),
            "abc_class": pa.Column(pl.String, pa.Check.isin(["A", "B", "C"])),
        },
        name="gold.dim_product",
    ),
    "dim_country": pa.DataFrameSchema(
        {
            "country_key": pa.Column(pl.Int32, unique=True),
            "iso3": pa.Column(pl.String, unique=True),
            "country_name": pa.Column(pl.String, unique=True),
            "region": pa.Column(pl.String),
        },
        name="gold.dim_country",
    ),
    "fact_fx_rates": pa.DataFrameSchema(
        {
            "date_key": pa.Column(pl.Int32),
            "currency_code": pa.Column(pl.String, pa.Check.isin(["GBP", "EUR", "USD"])),
            "rate_from_gbp": pa.Column(pl.Float64, pa.Check.gt(0)),
        },
        unique=["date_key", "currency_code"],
        name="gold.fact_fx_rates",
    ),
}


def _validate(schema: pa.DataFrameSchema, df: pl.DataFrame) -> dict:
    checks = sum(len(c.checks) + 2 for c in schema.columns.values()) + len(schema.checks)
    try:
        schema.validate(df, lazy=True)
        failures, detail = 0, ""
    except pa.errors.SchemaErrors as e:
        fc = e.failure_cases
        failures = fc.height
        detail = "; ".join(
            f"{r['column'] or 'frame'}:{r['check']} ({r['n']})"
            for r in fc.group_by("column", "check").agg(pl.len().alias("n")).iter_rows(named=True)
        )
    return {
        "table": schema.name,
        "rows": df.height,
        "checks": checks,
        "failures": failures,
        "status": "PASS" if failures == 0 else "FAIL",
        "detail": detail,
    }


def run(strict: bool = True) -> pl.DataFrame:
    p = paths()
    results = [
        _validate(BRONZE_RETAIL, pl.read_parquet(p.bronze / "retail.parquet")),
        _validate(SILVER_LINES, pl.read_parquet(p.silver / "retail_lines.parquet")),
    ]
    results += [_validate(schema, pl.read_parquet(p.gold / f"{t}.parquet")) for t, schema in GOLD.items()]
    out = pl.DataFrame(results)
    out.write_parquet(p.silver / "validation_results.parquet")
    for r in results:
        log.info("validate: %-22s %-4s %s", r["table"], r["status"], r["detail"])
    if strict and (out["status"] == "FAIL").any():
        raise SystemExit("Data validation failed - see log above")
    return out
