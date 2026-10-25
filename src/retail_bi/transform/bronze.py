"""Bronze layer: raw files -> typed Parquet. No business logic.

Power Query equivalent: Source -> Promote Headers -> Changed Type -> Append.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import fastexcel
import polars as pl

from retail_bi.config import get_logger, paths, settings

log = get_logger(__name__)

RETAIL_COLUMNS = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price",
    "Customer ID": "customer_id",
    "Country": "country",
}

# Force types: inference reads Invoice as Int64 from the first rows and would
# drop the "C"/"A" prefixes that mark cancellations and bad-debt adjustments.
RETAIL_OVERRIDES = {
    "Invoice": pl.String,
    "StockCode": pl.String,
    "Description": pl.String,
    "Customer ID": pl.Float64,
    "Country": pl.String,
}


def retail() -> pl.DataFrame:
    src = paths().raw / settings()["sources"]["retail"]["file"]
    ingested_at = datetime.now(UTC).replace(tzinfo=None)
    sheets = fastexcel.read_excel(src).sheet_names
    frames = []
    for sheet in sheets:
        df = pl.read_excel(src, sheet_name=sheet, engine="calamine", schema_overrides=RETAIL_OVERRIDES)
        frames.append(df.with_columns(pl.lit(sheet).alias("_source_sheet")))
        log.info("bronze retail: sheet %r -> %d rows", sheet, df.height)
    df = (
        pl.concat(frames, how="vertical")
        .rename(RETAIL_COLUMNS)
        .with_columns(
            pl.col("quantity").cast(pl.Int64),
            pl.col("price").cast(pl.Float64),
            pl.col("customer_id").cast(pl.Int64),
            pl.col("invoice_date").cast(pl.Datetime("us")),
            pl.lit(ingested_at).alias("_ingested_at"),
        )
    )
    df.write_parquet(paths().bronze / "retail.parquet")
    log.info("bronze retail: %d rows total", df.height)
    return df


def fx() -> pl.DataFrame:
    cfg = settings()["sources"]["fx"]
    data = json.loads((paths().raw / cfg["file"]).read_text())
    rows = [
        {"date": d, "currency": cur, "rate_from_gbp": rate}
        for d, rates in data["rates"].items()
        for cur, rate in rates.items()
    ]
    df = pl.DataFrame(rows).with_columns(pl.col("date").str.to_date())
    df.write_parquet(paths().bronze / "fx_rates.parquet")
    log.info("bronze fx: %d rows", df.height)
    return df


def worldbank() -> pl.DataFrame:
    cfg = settings()["sources"]["worldbank"]
    data = json.loads((paths().raw / cfg["file"]).read_text())
    rows = [
        {
            "iso3": r["countryiso3code"],
            "wb_name": r["country"]["value"],
            "indicator": name,
            "value": r["value"],
        }
        for name, records in data.items()
        for r in records
        if r["countryiso3code"]
    ]
    df = pl.DataFrame(rows, schema_overrides={"value": pl.Float64}).pivot(
        on="indicator", index=["iso3", "wb_name"], values="value"
    )
    df.write_parquet(paths().bronze / "worldbank.parquet")
    log.info("bronze worldbank: %d countries", df.height)
    return df


def countries() -> pl.DataFrame:
    cfg = settings()["sources"]["countries"]
    df = pl.read_csv(paths().raw / cfg["file"], infer_schema=False).select(
        pl.col("name").alias("iso_name"),
        pl.col("alpha-2").alias("iso2"),
        pl.col("alpha-3").alias("iso3"),
        pl.col("region"),
        pl.col("sub-region").alias("sub_region"),
    )
    df.write_parquet(paths().bronze / "countries.parquet")
    log.info("bronze countries: %d rows", df.height)
    return df


def run() -> None:
    countries()
    worldbank()
    fx()
    retail()
