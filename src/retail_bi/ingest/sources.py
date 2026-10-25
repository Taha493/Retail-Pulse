"""Ingestion: pull every source into data/raw/ (the Power BI "Get Data" step).

Each function is idempotent: if the file is present and its checksum matches
the manifest, the download is skipped.
"""

from __future__ import annotations

import json
import zipfile

from retail_bi.config import get_logger, paths, settings
from retail_bi.ingest.http import download, get_json, is_fresh, record

log = get_logger(__name__)


def download_retail(force: bool = False) -> None:
    cfg = settings()["sources"]["retail"]
    raw = paths().raw
    target = raw / cfg["file"]
    if not force and is_fresh("retail", target):
        log.info("retail: up to date, skipping")
        return
    zip_path = raw / "online_retail_ii.zip"
    log.info("retail: downloading %s", cfg["url"])
    download(cfg["url"], zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".xlsx"))
        with zf.open(member) as src, target.open("wb") as dst:
            dst.write(src.read())
    zip_path.unlink()
    record("retail", cfg["url"], target)
    log.info("retail: saved %s (%.1f MB)", target.name, target.stat().st_size / 1e6)


def fetch_fx(force: bool = False) -> None:
    cfg = settings()["sources"]["fx"]
    period = settings()["period"]
    target = paths().raw / cfg["file"]
    if not force and is_fresh("fx", target):
        log.info("fx: up to date, skipping")
        return
    url = cfg["url"].format(start=period["start"], end=period["end"])
    data = get_json(url, params={"base": cfg["base"], "symbols": ",".join(cfg["symbols"])})
    target.write_text(json.dumps(data))
    record("fx", url, target, rows=len(data["rates"]))
    log.info("fx: %d trading days", len(data["rates"]))


def fetch_worldbank(force: bool = False) -> None:
    cfg = settings()["sources"]["worldbank"]
    target = paths().raw / cfg["file"]
    if not force and is_fresh("worldbank", target):
        log.info("worldbank: up to date, skipping")
        return
    out: dict[str, list] = {}
    for name, indicator in cfg["indicators"].items():
        url = cfg["url"].format(indicator=indicator)
        rows: list = []
        page, pages = 1, 1
        while page <= pages:
            meta, data = get_json(
                url,
                params={"date": cfg["year"], "format": "json", "per_page": 400, "page": page},
            )
            pages = meta["pages"]
            rows.extend(data or [])
            page += 1
        out[name] = rows
        log.info("worldbank: %s -> %d rows", name, len(rows))
    target.write_text(json.dumps(out))
    record("worldbank", cfg["url"], target, rows=sum(len(v) for v in out.values()))


def fetch_countries(force: bool = False) -> None:
    cfg = settings()["sources"]["countries"]
    target = paths().raw / cfg["file"]
    if not force and is_fresh("countries", target):
        log.info("countries: up to date, skipping")
        return
    download(cfg["url"], target)
    rows = sum(1 for _ in target.open()) - 1
    record("countries", cfg["url"], target, rows=rows)
    log.info("countries: %d rows", rows)


def run(force: bool = False) -> None:
    fetch_countries(force)
    fetch_fx(force)
    fetch_worldbank(force)
    download_retail(force)
