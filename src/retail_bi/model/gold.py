"""Gold layer: the star schema that Power BI imports.

fact_sales (invoice line) -> dim_date, dim_customer, dim_product, dim_country
fact_fx_rates (day x currency) -> dim_date, dim_currency
All relationships are one-to-many on integer surrogate keys.
"""

from __future__ import annotations

from datetime import date

import holidays
import polars as pl

from retail_bi.config import get_logger, paths, settings
from retail_bi.transform import enrich

log = get_logger(__name__)


def dim_date() -> pl.DataFrame:
    p = settings()["period"]
    fy_start = settings()["rules"]["fiscal_year_start_month"]
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    uk = holidays.country_holidays("GB", subdiv="ENG", years=range(start.year, end.year + 1))
    hol = pl.DataFrame({"date": list(uk.keys()), "holiday_name": list(uk.values())})
    d = pl.col("date")
    fy = pl.when(d.dt.month() >= fy_start).then(d.dt.year()).otherwise(d.dt.year() - 1)
    return (
        pl.DataFrame({"date": pl.date_range(start, end, "1d", eager=True)})
        .join(hol, on="date", how="left")
        .with_columns(
            d.dt.strftime("%Y%m%d").cast(pl.Int32).alias("date_key"),
            d.dt.year().cast(pl.Int16).alias("year"),
            d.dt.quarter().cast(pl.Int8).alias("quarter_num"),
            pl.format("Q{}", d.dt.quarter()).alias("quarter"),
            d.dt.month().cast(pl.Int8).alias("month_num"),
            d.dt.strftime("%B").alias("month_name"),
            d.dt.strftime("%b").alias("month_short"),
            d.dt.strftime("%Y-%m").alias("year_month"),
            d.dt.strftime("%b %Y").alias("month_year"),
            d.dt.truncate("1mo").alias("month_start"),
            d.dt.day().cast(pl.Int8).alias("day_of_month"),
            d.dt.week().cast(pl.Int8).alias("week_iso"),
            d.dt.weekday().cast(pl.Int8).alias("weekday_num"),
            d.dt.strftime("%A").alias("weekday_name"),
            d.dt.strftime("%a").alias("weekday_short"),
            (d.dt.weekday() >= 6).alias("is_weekend"),
            pl.col("holiday_name").is_not_null().alias("is_uk_holiday"),
            pl.format("FY{}/{}", fy, (fy + 1) % 100).alias("fiscal_year"),
        )
        .select(
            "date_key",
            "date",
            "year",
            "quarter_num",
            "quarter",
            "month_num",
            "month_name",
            "month_short",
            "year_month",
            "month_year",
            "month_start",
            "day_of_month",
            "week_iso",
            "weekday_num",
            "weekday_name",
            "weekday_short",
            "is_weekend",
            "is_uk_holiday",
            "holiday_name",
            "fiscal_year",
        )
    )


def dim_customer(cust: pl.DataFrame) -> pl.DataFrame:
    df = cust.sort("customer_id").with_columns(
        pl.int_range(1, pl.len() + 1, dtype=pl.Int32).alias("customer_key"),
        pl.format("C{}", pl.col("customer_id")).alias("customer_label"),
    )
    guest = pl.DataFrame(
        {"customer_key": [-1], "customer_id": [-1], "customer_label": ["Guest"], "rfm_segment": ["Guest"]},
        schema_overrides={"customer_key": pl.Int32},
    )
    df = pl.concat([df, guest], how="diagonal_relaxed")
    return df.select(
        "customer_key",
        "customer_id",
        "customer_label",
        "home_country",
        "first_purchase_date",
        "last_purchase_date",
        "cohort_month",
        "orders",
        "lifetime_revenue_gbp",
        "recency_days",
        "r_score",
        "f_score",
        "m_score",
        "rfm_score",
        "rfm_segment",
    )


def dim_product(prod: pl.DataFrame) -> pl.DataFrame:
    return (
        prod.sort("stock_code")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int32).alias("product_key"))
        .select(
            "product_key",
            "stock_code",
            "product_name",
            "category",
            "sub_category",
            "abc_class",
            "price_band",
            "median_unit_price_gbp",
            "first_sold_date",
        )
    )


def dim_country(ctry: pl.DataFrame) -> pl.DataFrame:
    return ctry.with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int32).alias("country_key")).select(
        "country_key",
        "country_name",
        "iso2",
        "iso3",
        "region",
        "sub_region",
        "market",
        "is_domestic",
        "population",
        "gdp_per_capita",
    )


def dim_currency() -> pl.DataFrame:
    return pl.DataFrame(
        {"currency_code": ["GBP", "EUR", "USD"], "currency_symbol": ["£", "€", "$"], "sort_order": [1, 2, 3]}
    )


def fact_sales(sales: pl.DataFrame, dc: pl.DataFrame, dp: pl.DataFrame, dco: pl.DataFrame) -> pl.DataFrame:
    df = (
        sales.join(dc.select("customer_id", "customer_key"), on="customer_id", how="left")
        .join(dp.select("stock_code", "product_key"), on="stock_code", how="left")
        .join(dco.select(pl.col("iso3").alias("country_iso3"), "country_key"), on="country_iso3", how="left")
        # Returns-only customers are not in dim_customer -> treat as Guest
        .with_columns(pl.col("customer_key").fill_null(-1))
        .sort("invoice_date", "invoice", "stock_code")
        .with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.Int32).alias("sales_key"))
    )
    return df.select(
        "sales_key",
        pl.col("invoice").alias("invoice_no"),
        "date_key",
        pl.col("invoice_date").alias("invoice_datetime"),
        "invoice_hour",
        "customer_key",
        "product_key",
        "country_key",
        "quantity",
        pl.col("price").alias("unit_price_gbp"),
        "revenue_gbp",
        "revenue_eur",
        "revenue_usd",
        "is_return",
        "is_unmatched_return",
    )


def fact_fx_rates(fx: pl.DataFrame) -> pl.DataFrame:
    return (
        fx.unpivot(index="date", on=["GBP", "EUR", "USD"], variable_name="currency_code", value_name="rate_from_gbp")
        .with_columns(pl.col("date").dt.strftime("%Y%m%d").cast(pl.Int32).alias("date_key"))
        .select("date_key", "currency_code", "rate_from_gbp")
        .sort("date_key", "currency_code")
    )


def _check_integrity(tables: dict[str, pl.DataFrame]) -> None:
    f = tables["fact_sales"]
    for fk, dim, pk in [
        ("date_key", "dim_date", "date_key"),
        ("customer_key", "dim_customer", "customer_key"),
        ("product_key", "dim_product", "product_key"),
        ("country_key", "dim_country", "country_key"),
    ]:
        orphans = f.join(tables[dim], left_on=fk, right_on=pk, how="anti").height
        if orphans or f[fk].null_count():
            raise ValueError(f"fact_sales.{fk}: {orphans} orphan rows vs {dim}")
        if tables[dim][pk].n_unique() != tables[dim].height:
            raise ValueError(f"{dim}.{pk} is not unique")


def run() -> dict[str, pl.DataFrame]:
    fx = enrich.fx_daily()
    sales = enrich.sales(fx)
    dc = dim_customer(enrich.customers(sales))
    dp = dim_product(enrich.products(sales))
    dco = dim_country(enrich.countries(sales))
    tables = {
        "dim_date": dim_date(),
        "dim_customer": dc,
        "dim_product": dp,
        "dim_country": dco,
        "dim_currency": dim_currency(),
        "fact_sales": fact_sales(sales, dc, dp, dco),
        "fact_fx_rates": fact_fx_rates(fx),
    }
    _check_integrity(tables)
    gold = paths().gold
    for name, df in tables.items():
        df.write_parquet(gold / f"{name}.parquet")
        df.write_csv(gold / f"{name}.csv")
        log.info("gold: %-14s %9s rows", name, f"{df.height:,}")
    return tables
