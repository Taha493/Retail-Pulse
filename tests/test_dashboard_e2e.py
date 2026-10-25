"""End-to-end checks of the report's Power BI behaviours in a real (headless) browser.

Starts the Dash app on a spare port. Skipped if Playwright's Chromium is missing.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    if not (ROOT / "warehouse" / "retail.duckdb").exists():
        pytest.skip("warehouse not built (run `make all`)")
    port = _free_port()
    env = {**os.environ, "PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "dashboard" / "app.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.5)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def page(base_url):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser binaries not installed
            pytest.skip(f"chromium unavailable: {e}")
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 500 else None)
        pg.errors = errors
        yield pg
        assert not errors, f"server errors: {errors}"
        browser.close()


def _ready(page, url):
    page.goto(url)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)


def _kpi(page, kid):
    return page.locator(f"#{kid} .kpi-value").inner_text()


def test_cross_filter_toggle(page, base_url):
    _ready(page, base_url)
    before = _kpi(page, "ov-kpi-revenue")
    bar = page.locator('[id*="ov-category"] .bars .point path').last  # largest category
    bar.click(force=True)
    page.wait_for_selector(".chip-accent")
    assert "Cross-filter" in page.locator(".chip-accent").inner_text()
    # KPI cards respond to the selection
    page.wait_for_function(f"document.querySelector('#ov-kpi-revenue .kpi-value').innerText !== '{before}'")
    page.locator('[id*="ov-category"] .bars .point path').last.click(force=True)
    page.wait_for_selector(".chip-accent", state="detached")
    page.wait_for_function(f"document.querySelector('#ov-kpi-revenue .kpi-value').innerText === '{before}'")


def test_currency_switch(page, base_url):
    _ready(page, base_url)
    page.get_by_text("EUR", exact=True).click()
    page.wait_for_function("document.querySelector('#ov-kpi-revenue .kpi-value').innerText.startsWith('€')")


def test_theme_toggle(page, base_url):
    _ready(page, base_url)
    page.click("#theme-toggle")
    page.wait_for_selector("#root.theme-dark")


def test_drill_down_and_up(page, base_url):
    _ready(page, base_url + "/sales")
    page.click("#preset-all")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    assert "years" in page.locator("#sa-drill-crumbs").inner_text()
    page.locator('[id*="sa-drill"] .bars .point path').last.click(force=True)
    page.wait_for_function("document.querySelector('#sa-drill-crumbs').innerText.includes('quarters')")
    page.click("#sa-drill-up")
    page.wait_for_function("document.querySelector('#sa-drill-crumbs').innerText.includes('years')")


def test_cascading_slicer(page, base_url):
    _ready(page, base_url)
    page.click("#sl-region")
    page.get_by_role("option", name="Oceania").click()
    page.keyboard.press("Escape")
    page.wait_for_load_state("networkidle")
    page.click("#sl-country")
    menu = page.get_by_role("listbox").filter(has_not_text="GBP")  # skip the currency radio group
    options = menu.get_by_role("option").all_inner_texts()
    assert options and all(o.strip() == "Australia" for o in options), options


def test_export_and_focus(page, base_url):
    _ready(page, base_url)
    page.hover('[id*="ov-category"]')
    with page.expect_download() as dl:
        page.click('[id*="\\"export\\""][id*="ov-category"]')
    assert dl.value.suggested_filename == "ov-category.csv"
    page.click('[id*="\\"focus\\""][id*="ov-trend"]')
    page.wait_for_selector("#focus-modal:not(.hidden)")
    page.click("#focus-close")
    page.wait_for_selector("#focus-modal.hidden", state="attached")


@pytest.mark.parametrize("path", ["/", "/sales", "/customers", "/products", "/geography", "/data-quality"])
def test_pages_render(page, base_url, path):
    _ready(page, base_url + path)
    assert page.locator(".js-plotly-plot").count() >= 1
