"""Data tests on the built model: integrity, reconciliation, and DAX-equivalent measures.

These run against the real outputs, so they need `make all` first.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from retail_bi.config import paths
from retail_bi.measures.measures import Filters, SemanticModel
from retail_bi.validate.schemas import GOLD

GOLD_DIR = paths().gold
pytestmark = pytest.mark.skipif(not (GOLD_DIR / "fact_sales.parquet").exists(), reason="run `make all` first")


@pytest.fixture(scope="module")
def fact() -> pl.DataFrame:
    return pl.read_parquet(GOLD_DIR / "fact_sales.parquet")


@pytest.fixture(scope="module")
def dims() -> dict[str, pl.DataFrame]:
    return {
        t: pl.read_parquet(GOLD_DIR / f"{t}.parquet")
        for t in ("dim_date", "dim_customer", "dim_product", "dim_country")
    }


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    return SemanticModel()


# --- star schema integrity -------------------------------------------------------


@pytest.mark.parametrize(
    "fk, dim",
    [
        ("date_key", "dim_date"),
        ("customer_key", "dim_customer"),
        ("product_key", "dim_product"),
        ("country_key", "dim_country"),
    ],
)
def test_every_foreign_key_resolves(fact, dims, fk, dim):
    pk = fk
    assert fact.join(dims[dim], left_on=fk, right_on=pk, how="anti").height == 0
    assert dims[dim][pk].is_unique().all()


def test_date_table_is_contiguous_and_covers_facts(fact, dims):
    d = dims["dim_date"]["date"]
    assert (d.diff().drop_nulls().dt.total_days() == 1).all()
    assert fact["date_key"].min() >= dims["dim_date"]["date_key"].min()
    assert fact["date_key"].max() <= dims["dim_date"]["date_key"].max()


def test_gold_reconciles_with_silver(fact):
    silver = pl.read_parquet(paths().silver / "retail_lines.parquet").filter(pl.col("is_analysis_line"))
    assert fact.height == silver.height
    assert fact["revenue_gbp"].sum() == pytest.approx(silver["revenue_gbp"].sum(), abs=0.01)


def test_contracts_reject_bad_rows(fact):
    bad = fact.head(5).with_columns(pl.lit(-1.0).alias("unit_price_gbp"))
    import pandera.polars as pa

    with pytest.raises(pa.errors.SchemaErrors):
        GOLD["fact_sales"].validate(bad, lazy=True)


# --- measures: the Python twin of measures.dax -----------------------------------------


def test_core_measures_match_hand_calculation(fact, model):
    f = Filters()
    got = model.evaluate(f)
    sales = fact.filter(~pl.col("is_return"))
    gross = sales["revenue_gbp"].sum()
    returns = -fact.filter(pl.col("is_return"))["revenue_gbp"].sum()
    orders = sales["invoice_no"].n_unique()
    assert got["Total Revenue"] == pytest.approx(gross, rel=1e-9)
    assert got["Return Value"] == pytest.approx(returns, rel=1e-9)
    assert got["Net Revenue"] == pytest.approx(gross - returns, rel=1e-9)
    assert got["Total Orders"] == orders
    assert got["Avg Order Value"] == pytest.approx(gross / orders, rel=1e-9)
    assert got["Return Rate %"] == pytest.approx(returns / gross, rel=1e-9)
    assert got["Active Customers"] == sales.filter(pl.col("customer_key") != -1)["customer_key"].n_unique()


def test_filter_context_and_currency(fact, dims, model):
    f = Filters.build("2011-01-01", "2011-06-30", "EUR", {"category": ["Seasonal"]})
    prods = dims["dim_product"].filter(pl.col("category") == "Seasonal")["product_key"]
    expected = fact.filter(
        pl.col("product_key").is_in(prods.implode()),
        pl.col("date_key").is_between(20110101, 20110630),
    )["revenue_eur"].sum()
    assert model.evaluate(f, ["Net Revenue"])["Net Revenue"] == pytest.approx(expected, rel=1e-9)


def test_sameperiodlastyear_shift(model):
    f = Filters.build("2011-01-01", "2011-03-31")
    py = f.shifted_years(-1)
    assert (py.start, py.end) == (date(2010, 1, 1), date(2010, 3, 31))
    cur, prev = model.with_prior_year(f, ["Net Revenue"])
    assert prev["Net Revenue"] == pytest.approx(model.evaluate(py, ["Net Revenue"])["Net Revenue"])
    assert cur["Net Revenue"] != prev["Net Revenue"]


def test_cross_filter_removal_for_own_visual():
    f = Filters.build(slicers={"region": ["Europe"]}, cross={"category": ["Seasonal"]})
    assert f.without("category").cross == ()
    assert f.without("category").slicers == f.slicers


def test_pareto_ends_at_100_percent(model):
    p = model.pareto(Filters())
    assert p["Cumulative Revenue %"].max() == pytest.approx(1.0)
    assert p["Revenue Rank"].to_list()[:3] == [1, 2, 3]


def test_unsafe_columns_are_rejected():
    with pytest.raises(ValueError):
        Filters.build(slicers={"1=1; DROP TABLE fact_sales; --": ["x"]}).where()
