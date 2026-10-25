"""Enrichment: FX conversion, geography, customer RFM and product ABC features."""

from __future__ import annotations

from datetime import date

import polars as pl

from retail_bi.config import get_logger, paths, settings

log = get_logger(__name__)

RFM_SEGMENTS = [
    # (segment, condition on r/f scores). Order matters: first match wins.
    ("Champions", (pl.col("r_score") >= 4) & (pl.col("f_score") >= 4)),
    ("Loyal Customers", (pl.col("r_score") == 3) & (pl.col("f_score") >= 4)),
    ("Cannot Lose Them", (pl.col("r_score") <= 2) & (pl.col("f_score") == 5)),
    ("At Risk", (pl.col("r_score") <= 2) & (pl.col("f_score") >= 3)),
    ("Potential Loyalists", (pl.col("r_score") >= 4) & (pl.col("f_score") >= 2)),
    ("New Customers", (pl.col("r_score") == 5) & (pl.col("f_score") == 1)),
    ("Promising", (pl.col("r_score") == 4) & (pl.col("f_score") == 1)),
    ("Need Attention", (pl.col("r_score") == 3) & (pl.col("f_score") == 3)),
    ("About to Sleep", pl.col("r_score") == 3),
    ("Hibernating", pl.lit(True)),
]


def _period() -> tuple[date, date]:
    p = settings()["period"]
    return date.fromisoformat(p["start"]), date.fromisoformat(p["end"])


def fx_daily() -> pl.DataFrame:
    """One row per calendar day; weekend/holiday gaps carry the last ECB rate."""
    start, end = _period()
    rates = pl.read_parquet(paths().bronze / "fx_rates.parquet").pivot(
        on="currency", index="date", values="rate_from_gbp"
    )
    days = pl.DataFrame({"date": pl.date_range(start, end, "1d", eager=True)})
    df = (
        days.join(rates, on="date", how="left")
        .sort("date")
        .with_columns(pl.exclude("date").forward_fill().backward_fill())
        .with_columns(pl.lit(1.0).alias("GBP"))
    )
    df.write_parquet(paths().silver / "fx_daily.parquet")
    return df


def sales(fx: pl.DataFrame) -> pl.DataFrame:
    lines = pl.read_parquet(paths().silver / "retail_lines.parquet").filter(pl.col("is_analysis_line"))
    df = lines.join(fx.select("date", "EUR", "USD"), on="date", how="left").with_columns(
        (pl.col("revenue_gbp") * pl.col("EUR")).round(2).alias("revenue_eur"),
        (pl.col("revenue_gbp") * pl.col("USD")).round(2).alias("revenue_usd"),
        (pl.col("invoice_type") == "cancellation").alias("is_return"),
    )
    assert df["revenue_eur"].null_count() == 0, "FX join left gaps"
    return df


def countries(sales_df: pl.DataFrame) -> pl.DataFrame:
    rules = settings()["rules"]
    iso = pl.read_parquet(paths().bronze / "countries.parquet")
    wb = pl.read_parquet(paths().bronze / "worldbank.parquet").select("iso3", "population", "gdp_per_capita")
    pseudo = pl.DataFrame(
        [
            {"iso3": k, "pseudo_name": v["name"], "pseudo_region": v["region"], "pseudo_sub": v["sub_region"]}
            for k, v in rules["pseudo_countries"].items()
        ]
    )
    names = pl.DataFrame(
        {"country": list(rules["country_display_names"]), "display": list(rules["country_display_names"].values())}
    )
    df = (
        sales_df.group_by("country_iso3")
        .agg(pl.col("country").mode().first().alias("country"))
        .rename({"country_iso3": "iso3"})
        .join(iso, on="iso3", how="left")
        .join(pseudo, on="iso3", how="left")
        .join(names, on="country", how="left")
        .join(wb, on="iso3", how="left")
        .select(
            "iso3",
            "iso2",
            pl.coalesce("pseudo_name", "display", "country").alias("country_name"),
            pl.coalesce("region", "pseudo_region").alias("region"),
            pl.coalesce("sub_region", "pseudo_sub").alias("sub_region"),
            pl.col("population").cast(pl.Int64),
            pl.col("gdp_per_capita").round(0),
            (pl.col("iso3") == "GBR").alias("is_domestic"),
        )
        .with_columns(
            pl.when(pl.col("is_domestic"))
            .then(pl.lit("Domestic"))
            .when(pl.col("iso3") == "UNK")
            .then(pl.lit("Unknown"))
            .otherwise(pl.lit("International"))
            .alias("market")
        )
        .sort("country_name")
    )
    return df


def _ntile(col: str, n: int = 5, descending: bool = False) -> pl.Expr:
    rank = pl.col(col).rank(method="average", descending=descending)
    return ((rank / pl.len()) * n).ceil().clip(1, n).cast(pl.Int8)


def customers(sales_df: pl.DataFrame) -> pl.DataFrame:
    offset = settings()["rules"]["rfm_reference_offset_days"]
    known = sales_df.filter(~pl.col("is_guest"))
    ref_date = known["date"].max() + pl.duration(days=offset)
    ref = pl.select(ref_date).item()
    df = (
        known.group_by("customer_id")
        .agg(
            pl.col("date").filter(~pl.col("is_return")).min().alias("first_purchase_date"),
            pl.col("date").filter(~pl.col("is_return")).max().alias("last_purchase_date"),
            pl.col("invoice").filter(~pl.col("is_return")).n_unique().alias("orders"),
            pl.col("revenue_gbp").sum().round(2).alias("lifetime_revenue_gbp"),
            pl.col("country").mode().first().alias("home_country"),
        )
        # Customers who only ever returned items have no purchase date
        .filter(pl.col("first_purchase_date").is_not_null())
        .with_columns(
            (pl.lit(ref) - pl.col("last_purchase_date")).dt.total_days().alias("recency_days"),
            pl.col("first_purchase_date").dt.truncate("1mo").alias("cohort_month"),
        )
        .with_columns(
            _ntile("recency_days", descending=True).alias("r_score"),
            _ntile("orders").alias("f_score"),
            _ntile("lifetime_revenue_gbp").alias("m_score"),
        )
    )
    seg = pl.lit(None, dtype=pl.String)
    for name, cond in reversed(RFM_SEGMENTS):
        seg = pl.when(cond).then(pl.lit(name)).otherwise(seg)
    df = df.with_columns(
        seg.alias("rfm_segment"),
        pl.concat_str([pl.col("r_score"), pl.col("f_score"), pl.col("m_score")]).alias("rfm_score"),
    )
    log.info("enrich: %d customers, reference date %s", df.height, ref)
    return df


def products(sales_df: pl.DataFrame) -> pl.DataFrame:
    th = settings()["rules"]["abc_thresholds"]
    df = (
        sales_df.group_by("stock_code")
        .agg(
            pl.col("product_name").first(),
            pl.col("category").first(),
            pl.col("sub_category").first(),
            pl.col("price").filter(~pl.col("is_return")).median().round(2).alias("median_unit_price_gbp"),
            pl.col("date").min().alias("first_sold_date"),
            pl.col("revenue_gbp").sum().alias("_net"),
        )
        .sort("_net", descending=True)
        .with_columns((pl.col("_net").clip(0).cum_sum() / pl.col("_net").clip(0).sum()).alias("_cum"))
        .with_columns(
            pl.when(pl.col("_cum") <= th["A"])
            .then(pl.lit("A"))
            .when(pl.col("_cum") <= th["B"])
            .then(pl.lit("B"))
            .otherwise(pl.lit("C"))
            .alias("abc_class"),
            pl.when(pl.col("median_unit_price_gbp") < 1)
            .then(pl.lit("< £1"))
            .when(pl.col("median_unit_price_gbp") < 2.5)
            .then(pl.lit("£1 – £2.49"))
            .when(pl.col("median_unit_price_gbp") < 5)
            .then(pl.lit("£2.50 – £4.99"))
            .when(pl.col("median_unit_price_gbp") < 10)
            .then(pl.lit("£5 – £9.99"))
            .otherwise(pl.lit("£10+"))
            .alias("price_band"),
        )
        .drop("_net", "_cum")
    )
    counts = df["abc_class"].value_counts().sort("abc_class")
    log.info("enrich: ABC classes %s", dict(counts.iter_rows()))
    return df
