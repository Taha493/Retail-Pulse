"""Capture every report page as a PNG (used for the README) and surface callback errors.

Usage: uv run python scripts/screenshots.py [--base http://127.0.0.1:8050] [--dark] [--mobile]
The dashboard must already be running.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = {
    "overview": "/",
    "sales": "/sales",
    "customers": "/customers",
    "products": "/products",
    "geography": "/geography",
    "data-quality": "/data-quality",
}
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8050")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        size = {"width": 390, "height": 844} if args.mobile else {"width": 1440, "height": 900}
        ctx = browser.new_context(viewport=size, device_scale_factor=2 if args.mobile else 1.5)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
        if args.dark:
            page.goto(args.base)
            page.evaluate("localStorage.setItem('theme', JSON.stringify('dark'))")
        for name, path in PAGES.items():
            if args.only and name not in args.only:
                continue
            page.goto(args.base + path)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            # Pin the bottom page tabs into the flow so full-page captures show them once
            page.add_style_tag(content=".page-tabs{position:static}#root{padding-bottom:0}")
            suffix = ("-dark" if args.dark else "") + ("-mobile" if args.mobile else "")
            out = OUT / f"{name}{suffix}.png"
            page.screenshot(path=str(out), full_page=True)
            print("saved", out.relative_to(OUT.parents[1]))
        browser.close()
    for e in dict.fromkeys(errors):
        print("ERROR", e)


if __name__ == "__main__":
    main()
