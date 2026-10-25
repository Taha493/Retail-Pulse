"""Load the gold star schema into DuckDB and build the SQL views."""

from __future__ import annotations

from pathlib import Path

import duckdb

from retail_bi.config import get_logger, paths

log = get_logger(__name__)

SQL_DIR = Path(__file__).parent / "sql"
DQ_TABLES = {"dq_rule_log": "rule_log.parquet", "dq_validation": "validation_results.parquet"}
TABLES = ["dim_date", "dim_customer", "dim_product", "dim_country", "dim_currency", "fact_sales", "fact_fx_rates"]


def run() -> None:
    db = paths().warehouse
    tmp = db.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        for t in TABLES:
            src = (paths().gold / f"{t}.parquet").as_posix()
            con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{src}')")
        con.execute("ALTER TABLE dim_date ADD PRIMARY KEY (date_key)")
        # Data-quality metadata, shown on the dashboard's Data Quality page
        for table, file in DQ_TABLES.items():
            src = paths().silver / file
            if src.exists():
                con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{src.as_posix()}')")
        for sql_file in sorted(SQL_DIR.glob("*.sql")):
            con.execute(sql_file.read_text())
            log.info("warehouse: applied %s", sql_file.name)
        n = con.execute("SELECT COUNT(*) FROM mart_sales").fetchone()[0]
    # Swap in the new file so a running dashboard never sees a half-built DB
    tmp.replace(db)
    log.info("warehouse: %s ready (%s mart rows)", db.name, f"{n:,}")
