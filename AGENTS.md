# Budget Dashboard agent entry point

For user setup, read `README.md`, then follow `docs/setup.md` in order. Claude Code also enters through `CLAUDE.md`. Ask only for preferences or authority that cannot be determined from the repository and the user's request.

- Keep the app local on macOS. Do not configure bank connections, hosting, recurring jobs, or paid services.
- Ask for categories, monthly starting amounts, source CSV format, and whether to open the synthetic demo or real budget. Explain that the app currently uses USD.
- Keep financial records, configuration, converter scripts and exports in ignored `data/` or `local/`. Never include real data in commits, screenshots, logs or chat replies. Read user exports only when the user has directed you to those files; prefer headers and synthetic rows for discussing formats.
- Configure `data/config.json` before the first real import. Do not edit the source to rename categories. Preserve the required subscription and fallback roles and map source categories deliberately.
- If data already exists, inspect its schema and configuration before changes. Never overwrite records or change the category set under existing data. A later taxonomy change requires a separately agreed migration with a backup, preserving transaction links and monthly totals.
- Empower exports import directly. For other formats, follow the conversion contract in `docs/setup.md`; create a reusable local converter and validate it with synthetic examples before processing real records. Never silently guess debit/credit signs or ambiguous dates.
- Run the standard-library tests. Follow the smoke test in `docs/setup.md` using a fresh demo directory. If Node/Playwright are available, run their checks too. Ask before installing missing software. Do not use an existing authenticated browser profile.
- Before calling setup complete, verify the local server, a working monthly view, and a persisted save against synthetic data. Report the launch command, data location and exactly which checks ran. Stop the temporary test server.

For code changes, preserve the existing Python/JavaScript architecture, validation, integer-cent accounting, atomic saves, backups, and localhost protections. Keep changes small and cover new calculations or branches with meaningful tests. Run `python3 -m unittest -v test_budget.py test_release.py` and `node test_app.js`; run `python3 test_browser.py` for UI changes when Playwright is available.
