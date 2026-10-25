"""Pipeline entry point.

uv run retail-bi all          # ingest -> bronze -> silver -> gold -> validate -> warehouse -> report
uv run retail-bi silver       # run a single stage
uv run retail-bi ingest --force
"""

from __future__ import annotations

import argparse
import time

from retail_bi.config import get_logger

log = get_logger("pipeline")


def _ingest(force: bool) -> None:
    from retail_bi.ingest import sources

    sources.run(force)


def _bronze(_: bool) -> None:
    from retail_bi.transform import bronze

    bronze.run()


def _silver(_: bool) -> None:
    from retail_bi.transform import silver

    silver.run()


def _gold(_: bool) -> None:
    from retail_bi.model import gold

    gold.run()


def _validate(_: bool) -> None:
    from retail_bi.validate import schemas

    schemas.run(strict=True)


def _warehouse(_: bool) -> None:
    from retail_bi.model import warehouse

    warehouse.run()


def _report(_: bool) -> None:
    from retail_bi.validate import dq_report

    dq_report.run()


STAGES = {
    "ingest": _ingest,
    "bronze": _bronze,
    "silver": _silver,
    "gold": _gold,
    "validate": _validate,
    "warehouse": _warehouse,
    "report": _report,
}


def main() -> None:
    ap = argparse.ArgumentParser(prog="retail-bi", description="Online Retail II -> Power BI-ready star schema")
    ap.add_argument("stage", choices=[*STAGES, "all"])
    ap.add_argument("--force", action="store_true", help="re-download sources even if unchanged")
    args = ap.parse_args()
    stages = list(STAGES) if args.stage == "all" else [args.stage]
    for name in stages:
        t = time.perf_counter()
        log.info("▶ %s", name)
        STAGES[name](args.force)
        log.info("✔ %s (%.1fs)", name, time.perf_counter() - t)


if __name__ == "__main__":
    main()
