# Development

`budget_server.py` contains CSV import, integer-cent calculations, configuration validation, persistence, and the local HTTP server. `app.js`, `budget.html`, and `style.css` provide the browser interface. There is no frontend build step.

The server binds only to `127.0.0.1`, checks the Host and write Origin, and requires a per-run token for API requests. A process lock prevents simultaneous writers to the same data directory; revision checks reject stale browser writes. Saves use a temporary file, flush/fsync and atomic replacement.

Allocations retain an expense's original transaction. Linked credits use largest-remainder distribution across those allocations, so cents are conserved even when proportional shares do not divide evenly. Schema validation prevents overallocated expenses and credits exceeding either a refund or the original charge.

## Checks

```sh
python3 -m unittest -v test_budget.py test_release.py
node test_app.js
```

The Python checks cover allocation/credit arithmetic, import overlap decisions, legacy export signs, recurring classification, saved-record validation, configuration, no-overwrite demo creation, concurrent writes and local server behavior. Node checks exercise the real frontend functions for month selection, coverage and save failures.

For optional browser testing, install Playwright in an isolated development environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python test_browser.py
.venv/bin/python capture_demo.py
```

Browser tests start a temporary local server with synthetic records and a fresh Chromium context. They cover imports, allocations, linked credits, filters, month visibility, keyboard navigation, save-error recovery, and desktop/mobile/dark layouts. `capture_demo.py` regenerates the README screenshots from the real app and checks the displayed example totals. Never substitute screenshots of real financial records.

The interface stays on its existing JavaScript/CSS stack. BoardUI's free components were evaluated; introducing React and Tailwind solely for appearance would add setup and build work without changing the budgeting behavior. No BoardUI source or runtime dependency is included.
