.PHONY: all ingest bronze silver gold validate warehouse report dashboard test test-e2e lint format screenshots diagrams clean

UV := uv run

all:            ## Full pipeline: internet -> Power BI-ready star schema + warehouse + DQ report
	$(UV) retail-bi all

ingest bronze silver gold validate warehouse report:
	$(UV) retail-bi $@

dashboard:      ## Power BI-style report on http://127.0.0.1:8050
	$(UV) python dashboard/app.py

test:           ## Unit + data tests (fast)
	$(UV) pytest -m "not e2e"

test-e2e:       ## Browser tests of slicers, cross-filtering, drill-down, export, focus mode
	$(UV) pytest -m e2e

lint:
	$(UV) ruff check src dashboard tests scripts

format:
	$(UV) ruff format src dashboard tests scripts

screenshots:    ## Needs `make dashboard` running in another terminal
	$(UV) python scripts/screenshots.py
	$(UV) python scripts/screenshots.py --dark --only overview
	$(UV) python scripts/screenshots.py --mobile --only overview

diagrams:
	$(UV) python scripts/render_diagrams.py

clean:          ## Remove generated data (keeps raw downloads)
	rm -rf data/bronze/* data/silver/* data/gold/* warehouse/*.duckdb
