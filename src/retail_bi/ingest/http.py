"""HTTP helpers with retries, checksums and a lineage manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from retail_bi.config import get_logger, paths, settings

log = get_logger(__name__)


def _client() -> httpx.Client:
    timeout = settings()["http"]["timeout_seconds"]
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "retail-bi-portfolio/1.0"},
    )


def _retrying(fn):
    attempts = settings()["http"]["retries"]
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=2, max=30),
        reraise=True,
    )(fn)


@_retrying
def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    with _client() as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.json()


@_retrying
def download(url: str, dest: Path) -> Path:
    """Stream a file to disk (atomic rename once complete)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _client() as c, c.stream("GET", url) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --- lineage manifest -------------------------------------------------------


def _manifest_path() -> Path:
    return paths().raw / "_manifest.json"


def load_manifest() -> dict[str, Any]:
    p = _manifest_path()
    return json.loads(p.read_text()) if p.exists() else {}


def record(name: str, url: str, file: Path, rows: int | None = None) -> None:
    manifest = load_manifest()
    manifest[name] = {
        "source_url": url,
        "file": file.name,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "bytes": file.stat().st_size,
        "sha256": sha256(file),
        "rows": rows,
    }
    _manifest_path().write_text(json.dumps(manifest, indent=2))


def is_fresh(name: str, file: Path) -> bool:
    """True if the file exists and matches the checksum we recorded."""
    entry = load_manifest().get(name)
    return bool(entry) and file.exists() and sha256(file) == entry["sha256"]
