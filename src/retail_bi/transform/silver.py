"""Silver layer: cleaned, conformed invoice lines.

Every rule is logged with the number of rows it touched; the log feeds the
data quality report and the dashboard's Data Quality page. Rows are flagged
rather than deleted wherever possible, so nothing disappears silently.
"""

from __future__ import annotations

import polars as pl

from retail_bi.config import get_logger, paths, settings
from retail_bi.transform.rules import RuleLog, category_expr, clean_text, line_type_expr

log = get_logger(__name__)

KEY_COLS = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country"]


def drop_duplicates(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    df = df.with_columns(
        pl.int_range(pl.len()).over(KEY_COLS).alias("_dup_n"),
        pl.col("_source_sheet").first().over(KEY_COLS).alias("_first_sheet"),
    )
    removed = df.filter(pl.col("_dup_n") > 0)
    cross = removed.filter(pl.col("_source_sheet") != pl.col("_first_sheet")).height
    df = df.filter(pl.col("_dup_n") == 0).drop("_dup_n", "_first_sheet")
    rl.add(
        "Cross-sheet overlap",
        "Both Excel sheets contain 1-9 Dec 2010; the second copy is removed",
        cross,
        df.height + (removed.height - cross),
        "removed",
    )
    rl.add(
        "Exact duplicate lines",
        "Identical rows within the same sheet (double-scanned lines)",
        removed.height - cross,
        df.height,
        "removed",
    )
    return df


def standardise_text(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    out = df.with_columns(
        clean_text("description").alias("description"),
        clean_text("stock_code").str.to_uppercase().alias("stock_code"),
        clean_text("country").alias("country"),
    )
    changed = (
        (out["description"] != df["description"]).fill_null(False)
        | (out["stock_code"] != df["stock_code"])
        | (out["country"] != df["country"])
    ).sum()
    rl.add("Text standardisation", "Trim/collapse whitespace, upper-case stock codes", changed, out.height, "fixed")
    return out


def classify(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    df = df.with_columns(
        pl.when(pl.col("invoice").str.starts_with("C"))
        .then(pl.lit("cancellation"))
        .when(pl.col("invoice").str.starts_with("A"))
        .then(pl.lit("bad_debt"))
        .otherwise(pl.lit("sale"))
        .alias("invoice_type"),
        line_type_expr(pl.col("stock_code")).alias("line_type"),
    )
    # Negative quantity on a normal invoice with zero price = warehouse write-off
    writeoff = (pl.col("invoice_type") == "sale") & (pl.col("quantity") < 0) & (pl.col("price") == 0)
    df = df.with_columns(
        pl.when(pl.col("invoice_type") == "bad_debt")
        .then(pl.lit("adjustment"))
        .when(writeoff & (pl.col("line_type") == "product"))
        .then(pl.lit("stock_writeoff"))
        .otherwise(pl.col("line_type"))
        .alias("line_type")
    )
    n_cancel = df.filter(pl.col("invoice_type") == "cancellation").height
    rl.add(
        "Cancellations flagged",
        "Invoice starts with 'C' -> kept as returns, not deleted",
        n_cancel,
        df.height,
        "flagged",
    )
    n_nonprod = df.filter(~pl.col("line_type").is_in(["product", "stock_writeoff"])).height
    rl.add(
        "Non-product lines", "Postage, fees, manual adjustments, bad debt, test codes", n_nonprod, df.height, "flagged"
    )
    n_wo = df.filter(pl.col("line_type") == "stock_writeoff").height
    rl.add(
        "Stock write-offs", "Negative qty, zero price, normal invoice (damaged/lost stock)", n_wo, df.height, "flagged"
    )
    return df


def flag_prices(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    df = df.with_columns((pl.col("price") <= 0).alias("is_zero_price"))
    n = df.filter(pl.col("is_zero_price") & (pl.col("line_type") == "product")).height
    rl.add("Zero / negative price", "Product lines with price <= 0 (free samples, errors)", n, df.height, "flagged")
    return df


def handle_guests(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    df = df.with_columns(
        pl.col("customer_id").is_null().alias("is_guest"),
        pl.col("customer_id").fill_null(-1),
    )
    n = df["is_guest"].sum()
    rl.add(
        "Missing customer ID",
        "Labelled Guest (-1); kept for revenue, excluded from customer analytics",
        n,
        df.height,
        "flagged",
    )
    return df


def canonical_names(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    # Lower-case descriptions are warehouse notes ("damaged", "?"), never names.
    is_name = pl.col("description").is_not_null() & ~pl.col("description").str.contains("[a-z]")
    names = (
        df.filter(is_name & (pl.col("line_type") == "product"))
        .group_by("stock_code", "description")
        .agg(pl.len().alias("n"), pl.col("invoice_date").max().alias("last_seen"))
        .sort(["stock_code", "n", "last_seen"], descending=[False, True, True])
        .group_by("stock_code", maintain_order=True)
        .agg(pl.col("description").first().alias("product_name"), pl.len().alias("n_variants"))
    )
    df = df.join(names, on="stock_code", how="left").with_columns(
        pl.col("product_name").fill_null(pl.col("description")).fill_null(pl.col("stock_code"))
    )
    changed = df.filter(
        (pl.col("line_type") == "product") & (pl.col("product_name") != pl.col("description")).fill_null(True)
    ).height
    multi = names.filter(pl.col("n_variants") > 1).height
    rl.add(
        "Canonical product names",
        f"{multi:,} stock codes had several descriptions; most frequent one kept",
        changed,
        df.height,
        "fixed",
    )
    return df.drop("n_variants")


def flag_outlier_pairs(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    """Huge orders that were cancelled straight away (e.g. 80,995 paper birdies)."""
    threshold = settings()["rules"]["outlier_quantity_threshold"]
    big = df.filter((pl.col("invoice_type") == "sale") & (pl.col("quantity") >= threshold))
    cancels = df.filter(pl.col("invoice_type") == "cancellation").select(
        "customer_id", "stock_code", (-pl.col("quantity")).alias("quantity"), pl.col("invoice").alias("cancel_invoice")
    )
    pairs = big.join(cancels, on=["customer_id", "stock_code", "quantity"], how="inner")
    flagged = set(pairs["invoice"]) | set(pairs["cancel_invoice"])
    stock = set(pairs["stock_code"])
    df = df.with_columns(
        (pl.col("invoice").is_in(list(flagged)) & pl.col("stock_code").is_in(list(stock))).alias("is_outlier_pair")
    )
    n = df["is_outlier_pair"].sum()
    rl.add(
        "Outlier order/cancel pairs",
        f"Orders >= {threshold:,} units cancelled in full; both lines neutralised",
        n,
        df.height,
        "flagged",
    )
    return df


def map_countries(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    rules = settings()["rules"]
    iso = pl.read_parquet(paths().bronze / "countries.parquet").select("iso_name", "iso3")
    overrides = pl.DataFrame(
        {"country": list(rules["country_overrides"]), "iso3_override": list(rules["country_overrides"].values())}
    )
    lookup = (
        df.select("country")
        .unique()
        .join(overrides, on="country", how="left")
        .join(iso, left_on="country", right_on="iso_name", how="left")
        .with_columns(pl.coalesce("iso3_override", "iso3").alias("country_iso3"))
        .select("country", "country_iso3")
    )
    unmatched = lookup.filter(pl.col("country_iso3").is_null())["country"].to_list()
    if unmatched:
        raise ValueError(f"Countries without an ISO mapping, add them to settings.yaml: {unmatched}")
    df = df.join(lookup, on="country", how="left")
    n = df.filter(pl.col("country").is_in(overrides["country"].to_list())).height
    rl.add(
        "Country standardisation",
        "Labels resolved to ISO-3166 via override table (United Kingdom, EIRE, RSA...)",
        n,
        df.height,
        "fixed",
    )
    return df


def flag_unmatched_returns(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    """Returns whose customer never bought that product inside the data window."""
    bought = (
        df.filter((pl.col("invoice_type") == "sale") & ~pl.col("is_guest"))
        .select("customer_id", "stock_code")
        .unique()
        .with_columns(pl.lit(True).alias("_bought"))
    )
    df = (
        df.join(bought, on=["customer_id", "stock_code"], how="left")
        .with_columns(
            ((pl.col("invoice_type") == "cancellation") & ~pl.col("is_guest") & pl.col("_bought").is_null()).alias(
                "is_unmatched_return"
            )
        )
        .drop("_bought")
    )
    n = df["is_unmatched_return"].sum()
    rl.add(
        "Unmatched returns",
        "Return with no original purchase in the window (bought before Dec 2009)",
        n,
        df.height,
        "flagged",
    )
    return df


def derive(df: pl.DataFrame, rl: RuleLog) -> pl.DataFrame:
    category, sub_category = category_expr(pl.col("product_name"))
    df = df.with_columns(
        (pl.col("quantity") * pl.col("price")).round(2).alias("revenue_gbp"),
        pl.col("invoice_date").dt.date().alias("date"),
        pl.col("invoice_date").dt.strftime("%Y%m%d").cast(pl.Int32).alias("date_key"),
        pl.col("invoice_date").dt.hour().cast(pl.Int8).alias("invoice_hour"),
        category.alias("category"),
        sub_category.alias("sub_category"),
    ).with_columns(
        (
            (pl.col("line_type") == "product")
            & ~pl.col("is_zero_price")
            & ~pl.col("is_outlier_pair")
            & pl.col("invoice_type").is_in(["sale", "cancellation"])
        ).alias("is_analysis_line")
    )
    products = df.filter(pl.col("line_type") == "product").select("stock_code", "category").unique()
    other = products.filter(pl.col("category") == "Other").height
    rl.add(
        "Product categorisation",
        f"Keyword rules gave {1 - other / products.height:.1%} of products a category",
        products.height - other,
        df.height,
        "derived",
    )
    final = df["is_analysis_line"].sum()
    rl.add("Analysis-ready lines", "Product sales + returns with valid price, outliers removed", final, final, "final")
    return df


def run() -> pl.DataFrame:
    rl = RuleLog()
    df = pl.read_parquet(paths().bronze / "retail.parquet")
    rl.add("Raw rows", "Both Excel sheets appended", df.height, df.height, "source")
    for step in (
        drop_duplicates,
        standardise_text,
        classify,
        flag_prices,
        handle_guests,
        canonical_names,
        flag_outlier_pairs,
        map_countries,
        flag_unmatched_returns,
        derive,
    ):
        seen = len(rl.entries)
        df = step(df, rl)
        for e in rl.entries[seen:]:
            log.info("silver: %-28s %9s rows %s", e["rule"], f"{e['rows_affected']:,}", e["action"])
    df.write_parquet(paths().silver / "retail_lines.parquet")
    rl.to_frame().write_parquet(paths().silver / "rule_log.parquet")
    return df
