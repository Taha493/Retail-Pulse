"""Project configuration and path helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class Paths:
    raw: Path
    bronze: Path
    silver: Path
    gold: Path
    warehouse: Path
    docs: Path

    def ensure(self) -> None:
        for p in (self.raw, self.bronze, self.silver, self.gold, self.docs):
            p.mkdir(parents=True, exist_ok=True)
        self.warehouse.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    with CONFIG_FILE.open() as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def paths() -> Paths:
    p = {k: ROOT / v for k, v in settings()["paths"].items()}
    out = Paths(**p)
    out.ensure()
    return out


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)
