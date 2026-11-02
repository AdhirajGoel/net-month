# net-month development

`budget_server.py` contains CSV import, integer-cent calculations, configuration validation, persistence, and the local HTTP server. `app.js`, `budget.html`, and `style.css` provide the browser interface. There is no frontend build step.

The server binds only to `127.0.0.1`, checks the Host and write Origin, and requires a per-run token for API requests. A process lock prevents simultaneous writers to the same data directory; revision checks reject stale browser writes. Saves use a temporary file, flush/fsync and atomic replacement.

Allocations retain an expense's original transaction. Linked credits use largest-remainder distribution across those allocations, so cents are conserved even when proportional shares do not divide evenly. Schema validation prevents overallocated expenses and credits exceeding either a refund or the original charge. CSV amounts are checked against the supported decimal-dollar format before removing currency and thousands separators. Invalid formatting is reported with its source row.

Each snapshot groups allocations by transaction and credit links by both endpoints once, then reuses those lists. This avoids rescanning the complete history for every transaction while preserving the existing ordering, totals and API response.

## Snapshot performance

A paired check on macOS with Python 3.11 used synthetic histories with 100 expenses per month and one allocation per expense. The complete snapshot output matched the previous implementation at every size.

| Transactions | Previous calculation | Grouped calculation |
| --- | --- | --- |
| 1,200 | 0.039 s | 0.010 s |
| 6,000 | 0.751 s | 0.053 s |
| 12,000 | 3.068 s | 0.102 s |

These are single-run measurements of `snapshot()` on one host. CSV reads, network transfer and browser rendering are additional work. The improvement makes long histories cheaper to recalculate after a save without changing the CSV format or adding a database.

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
