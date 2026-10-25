"""Unit tests for the silver-layer cleaning rules, on small hand-made fixtures."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from retail_bi.transform import silver
from retail_bi.transform.rules import RuleLog, category_expr, line_type_expr


def lines(rows: list[dict]) -> pl.DataFrame:
    base = {
        "invoice": "500000",
        "stock_code": "85123A",
        "description": "WHITE HANGING HEART T-LIGHT HOLDER",
        "quantity": 6,
        "invoice_date": datetime(2010, 5, 3, 10, 0),
        "price": 2.55,
        "customer_id": 17850,
        "country": "United Kingdom",
        "_source_sheet": "Year 2009-2010",
    }
    return pl.DataFrame([{**base, **r} for r in rows], schema_overrides={"customer_id": pl.Int64})


def test_duplicates_split_cross_sheet_overlap_from_true_duplicates():
    df = lines(
        [
            {},  # original
            {"_source_sheet": "Year 2010-2011"},  # same row in the other sheet -> overlap
            {},  # same row, same sheet -> duplicate
            {"invoice": "500001"},  # different row
        ]
    )
    rl = RuleLog()
    out = silver.drop_duplicates(df, rl)
    assert out.height == 2
    overlap, dupes = rl.entries
    assert overlap["rows_affected"] == 1 and dupes["rows_affected"] == 1


@pytest.mark.parametrize(
    "code, expected",
    [
        ("85123A", "product"),
        ("POST", "postage"),
        ("DOT", "postage"),
        ("AMAZONFEE", "fee"),
        ("M", "adjustment"),
        ("ADJUST2", "adjustment"),
        ("GIFT_0001_20", "adjustment"),
        ("TEST001", "test"),
        ("DCGS0058", "product"),
        ("BANK CHARGES", "fee"),
    ],
)
def test_line_type(code, expected):
    out = pl.DataFrame({"c": [code]}).select(line_type_expr(pl.col("c")))
    assert out.item() == expected


def test_classify_cancellations_bad_debt_and_writeoffs():
    df = lines(
        [
            {"invoice": "C500002", "quantity": -2},  # return
            {"invoice": "A500003", "stock_code": "B", "price": -11062.06},  # bad debt
            {"quantity": -50, "price": 0.0, "customer_id": None},  # write-off
            {},
        ]
    )
    out = silver.classify(df, RuleLog())
    assert out["invoice_type"].to_list() == ["cancellation", "bad_debt", "sale", "sale"]
    assert out["line_type"].to_list() == ["product", "adjustment", "stock_writeoff", "product"]


def test_guests_get_minus_one_and_are_flagged():
    out = silver.handle_guests(lines([{"customer_id": None}, {}]), RuleLog())
    assert out["customer_id"].to_list() == [-1, 17850]
    assert out["is_guest"].to_list() == [True, False]


def test_canonical_name_prefers_most_frequent_upper_case_description():
    df = lines(
        [
            {"description": "WHITE HANGING HEART T-LIGHT HOLDER"},
            {"description": "WHITE HANGING HEART T-LIGHT HOLDER"},
            {"description": "CREAM HANGING HEART T-LIGHT HOLDER"},
            {"description": "damaged"},  # warehouse note, never a name
            {"description": None},
        ]
    ).with_columns(pl.lit("product").alias("line_type"))
    out = silver.canonical_names(df, RuleLog())
    assert out["product_name"].unique().to_list() == ["WHITE HANGING HEART T-LIGHT HOLDER"]


def test_outlier_order_and_its_cancellation_are_both_flagged():
    df = lines(
        [
            {"invoice": "581483", "stock_code": "23843", "quantity": 80995, "price": 2.08, "customer_id": 16446},
            {"invoice": "C581484", "stock_code": "23843", "quantity": -80995, "price": 2.08, "customer_id": 16446},
            {"invoice": "497946", "stock_code": "37410", "quantity": 19152, "price": 0.10},  # big but genuine
        ]
    )
    df = silver.classify(df, RuleLog())
    out = silver.flag_outlier_pairs(df, RuleLog())
    assert out["is_outlier_pair"].to_list() == [True, True, False]


def test_unknown_country_label_fails_loudly():
    df = lines([{"country": "Atlantis"}])
    with pytest.raises(ValueError, match="Atlantis"):
        silver.map_countries(df, RuleLog())


def test_country_overrides_resolve_to_iso3():
    df = lines([{"country": "EIRE"}, {"country": "RSA"}, {"country": "Channel Islands"}, {"country": "France"}])
    out = silver.map_countries(df, RuleLog())
    assert out["country_iso3"].to_list() == ["IRL", "ZAF", "CHI", "FRA"]


@pytest.mark.parametrize(
    "name, category",
    [
        ("REGENCY CAKESTAND 3 TIER", "Kitchen & Dining"),
        ("PAPER CHAIN KIT 50'S CHRISTMAS", "Seasonal"),
        ("JUMBO BAG RED RETROSPOT", "Bags & Purses"),
        ("WHITE HANGING HEART T-LIGHT HOLDER", "Candles & Lighting"),
        ("PARTY BUNTING", "Party Supplies"),
        ("ZZZZ UNKNOWN THING", "Other"),
    ],
)
def test_category_rules(name, category):
    cat, _ = category_expr(pl.col("d"))
    assert pl.DataFrame({"d": [name]}).select(cat).item() == category
