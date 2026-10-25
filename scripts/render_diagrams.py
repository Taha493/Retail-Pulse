"""Render the Mermaid diagrams (pipeline + data model) to PNG for the README.

Usage: uv run python scripts/render_diagrams.py
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"

PIPELINE = """
flowchart LR
    subgraph S[Sources]
        A1[UCI Online Retail II<br/>1.07M rows · xlsx]
        A2[Frankfurter API<br/>ECB FX rates]
        A3[World Bank API<br/>population · GDP]
        A4[ISO-3166 list<br/>codes · regions]
    end
    subgraph P[Python pipeline · make all]
        B[Bronze<br/>typed Parquet]
        C[Silver<br/>13 logged cleaning rules]
        D[Gold<br/>star schema]
        V{{Pandera<br/>8 data contracts}}
    end
    subgraph O[Outputs]
        E[(DuckDB<br/>warehouse + views)]
        F[Power BI input<br/>data/gold/*.parquet · csv]
        G[Power BI-style report<br/>Plotly Dash]
        H[DQ report<br/>HTML]
    end
    A1 & A2 & A3 & A4 --> B --> C --> D --> V
    V --> E & F & H
    E --> G
    F -. Get Data .-> PBI[Power BI Desktop<br/>measures.dax · theme.json]
"""


def er_from_markdown() -> str:
    md = (ROOT / "powerbi" / "data_model.md").read_text()
    return re.search(r"```mermaid\n(.*?)```", md, re.S).group(1)


def render(diagram: str, out: Path, width: int) -> None:
    html = f"""<!doctype html><html><body style="margin:0;background:#fff">
<div id="d" class="mermaid" style="display:inline-block;padding:16px">{diagram}</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad:true, theme:'base', themeVariables:{{
  primaryColor:'#E6F2FF', primaryBorderColor:'#118DFF', primaryTextColor:'#252423', lineColor:'#605E5C',
  fontFamily:'Segoe UI, Open Sans, sans-serif', fontSize:'15px', tertiaryColor:'#F3F2F1'}}, flowchart:{{useMaxWidth:false}}, er:{{useMaxWidth:false}}}});</script>
</body></html>"""
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=2)
        page.set_content(html)
        page.wait_for_selector("#d svg")
        page.wait_for_timeout(500)
        page.locator("#d").screenshot(path=str(out))
        b.close()
    print("saved", out.relative_to(ROOT))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    render(PIPELINE, OUT / "pipeline.png", 1500)
    render(er_from_markdown(), OUT / "data_model.png", 1600)
