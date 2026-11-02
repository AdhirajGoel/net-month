# net-month setup

Use this procedure with Codex or Claude Code on macOS. The goal is a working local dashboard with the user's own categories and a repeatable import workflow.

## 1. Inspect and ask

Confirm macOS and Python 3.9 or newer with `python3 --version`. Inspect whether `data/` already contains records. Read this repository's configuration example rather than guessing its schema.

Ask for the user's:

- Category names, monthly starting amounts in USD, and groups such as Needs/Wants. The agent may suggest a compact starting set, but the amounts must come from the user.
- Category for detected subscriptions and a fallback category for previously detected subscriptions that need review.
- CSV source: current Empower, older Empower, or another bank/export format.
- Preference to start with the synthetic demo or a new empty budget.

No API keys, bank passwords, or paid services are required. If Python is missing, ask before installing it. Node and Playwright are development tools, not app requirements.

## 2. Configure an empty budget

Create `data/` and copy `config.example.json` to `data/config.json` only if that file does not already exist. Keep local files out of Git.

The configuration contains:

| Key | Meaning |
| --- | --- |
| `categories` | Category names and nonnegative monthly amounts in dollars, with at most two decimal places. Zero is a valid starting plan. |
| `category_map` | Source CSV category names mapped to configured categories. Source matching ignores case and surrounding spaces. Unmapped categories go to Review. |
| `subscription_category` | Configured category used by monthly subscription detection. |
| `fallback_category` | Configured category used when an earlier automatic subscription has linked credits but no longer qualifies. It remains flagged for review. |
| `groups` | Display groups containing every configured category exactly once. |

Use the user's answers to populate this file before importing. Each new month inherits the preceding saved month's budget; edit existing monthly amounts in the dashboard. Changing starting amounts in the configuration does not rewrite saved budgets.

If records already exist, retain their category names and matching configuration. Do not add, remove, or rename categories against existing records as part of setup. The app rejects mismatched category sets rather than silently losing data. Back up both the CSV and configuration before any separately requested migration.

## 3. Prepare imports

Current Empower CSVs use `Date,Account,Description,Category,Amount`. Dates are `YYYY-MM-DD`; charges are negative and credits are positive. Amounts use a decimal point and at most two decimal places. Optional dollar signs and correctly grouped thousands separators are accepted (`-$12.34`, `$-12.34`, `-1,234.56`); malformed or locale-ambiguous amounts such as `-12,34` are rejected before normalization. Older Empower files with `Date,Original Date,Account Name,Name,Amount,Category` are also supported; their positive charges are inverted during preview. Optional institution/account identifiers distinguish otherwise similar older accounts locally.

For another institution, create a small reusable converter under ignored `local/`, with its output under `data/`. It should:

1. Read a supplied file and write a separate import-ready CSV, preserving the original. Require a new output filename; never overwrite an existing export.
2. Produce the five current-format columns above. Preserve distinct account identity and descriptions. Use ISO dates and decimal dollars, with negative charges and positive credits.
3. Resolve date conventions and signs with the user when ambiguous. Handle separate debit/credit columns explicitly. Reject missing descriptions/accounts, invalid dates, nonfinite amounts, fractions of a cent, zero amounts, and malformed rows. Do not drop or combine transactions silently.
4. Preserve row counts and reconcile debit totals, credit totals and signed totals with the source. Use Python's `decimal.Decimal`, not binary floating-point arithmetic, for money.
5. Test synthetic charges, refunds, transfers and duplicate-looking purchases. Validate the result with `budget_server.parse_export`, then show the user the dashboard preview before confirming the real import.

Use `examples/empower.csv` and `examples/empower-legacy.csv` as synthetic format references. Never add real financial records to those files. Give the user one repeatable conversion command for next month. Keep conversion and importing explicit; no scheduled collection is needed.

## 4. Verify in isolation

Run from the repository root:

```sh
python3 -m unittest -v test_budget.py test_release.py
python3 demo.py
python3 budget_server.py --data-dir demo-data
```

If `demo-data/` already exists, reuse it only if the user wants to preserve that demo, or create a fresh named directory with `python3 demo.py --data-dir local/demo-check` and launch it with `python3 budget_server.py --data-dir local/demo-check`. Never delete a directory to make a test pass.

In the demo, select October 2026. Verify net allocated spending of **$2,568.00**, annual insurance net of **$80.00**, and Groceries+Food net of **$360.00**. In Transactions, the $1,200 insurance charge retains its August date and has twelve monthly allocations. The $80 November dinner repayment links to the October $120 dinner.

Save a synthetic manual expense, reload the page, and verify the entry persists. Stop the demo server. If available, `node test_app.js` and `python3 test_browser.py` automate additional interface checks in fresh synthetic directories. Those checks do not use the user's real records.

## 5. Launch and hand off

Start the real budget with `python3 budget_server.py` or double-click `Open net-month.command`. Both use `data/`; the server selects a free localhost port and opens the browser. Keep Terminal open while using the app. A second launch reopens the already running dashboard for the same directory.

Tell the user where their records and configuration live, how to launch and stop the app, and how to repeat any conversion. Explain that setup is complete only after the checks actually run. A tool's sandbox may require permission for local HTTP or browser execution; report a blocked check precisely instead of claiming it passed.
