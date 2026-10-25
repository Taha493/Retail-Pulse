"""Reusable business rules (kept separate so they can be unit-tested)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache

import polars as pl
import yaml

from retail_bi.config import ROOT, settings


@dataclass
class RuleLog:
    """Collects one entry per cleaning rule: what it did and to how many rows."""

    entries: list[dict] = field(default_factory=list)

    def add(self, rule: str, description: str, affected: int, rows_after: int, action: str) -> None:
        self.entries.append(
            {
                "step": len(self.entries) + 1,
                "rule": rule,
                "description": description,
                "action": action,
                "rows_affected": int(affected),
                "rows_after": int(rows_after),
            }
        )

    def to_frame(self) -> pl.DataFrame:
        return pl.DataFrame([asdict(self)["entries"]][0])


def line_type_expr(code: pl.Expr) -> pl.Expr:
    """Classify a stock code as product / postage / fee / adjustment / test."""
    rules = settings()["rules"]
    expr = pl.lit("product")
    # Prefixes are weaker than exact codes, so they are applied first and
    # exact codes override them.
    for line_type, prefixes in rules["non_product_prefixes"].items():
        for prefix in prefixes:
            expr = pl.when(code.str.starts_with(prefix)).then(pl.lit(line_type)).otherwise(expr)
    for line_type, codes in rules["non_product_codes"].items():
        expr = pl.when(code.is_in(codes)).then(pl.lit(line_type)).otherwise(expr)
    return expr


@lru_cache(maxsize=1)
def category_rules() -> tuple[list[tuple[str, str, str]], tuple[str, str]]:
    with (ROOT / "config" / "categories.yaml").open() as f:
        cfg = yaml.safe_load(f)
    return [tuple(r) for r in cfg["rules"]], tuple(cfg["fallback"])


def category_expr(description: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """Return (category, sub_category) expressions. First matching rule wins."""
    rules, (fb_cat, fb_sub) = category_rules()
    text = description.str.to_uppercase()
    cat: pl.Expr = pl.lit(fb_cat)
    sub: pl.Expr = pl.lit(fb_sub)
    for c, s, pattern in reversed(rules):
        hit = text.str.contains(pattern)
        cat = pl.when(hit).then(pl.lit(c)).otherwise(cat)
        sub = pl.when(hit).then(pl.lit(s)).otherwise(sub)
    return cat, sub


def clean_text(col: str) -> pl.Expr:
    return pl.col(col).str.strip_chars().str.replace_all(r"\s+", " ")
