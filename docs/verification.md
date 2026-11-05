# Verification record

Created 5 November 2026. The prototype is AI-assisted and uses synthetic records.

## Executed

- Python 3.12.14 on Windows: `python -m unittest discover -s tests -v`.
- **17 tests passed**, including the local HTTP read/write and Host/Origin checks.
- Node.js: `node --check static/app.js` passed.
- Seeded a temporary SQLite workspace and generated sample state, Jira CSV and Confluence Markdown exports. No real personal data were used.
- A separate read-only review found the workflow/KPI definitions consistent with the code. Auditor/reviewer checks compare labels only. `as_of` is an overdue cutoff, not historical reconstruction.

Detailed output is in `evidence/tests.txt`; environment, counts and sample indicators are in `evidence/validation-summary.json`. Sample exports are included for inspection.

## Executed browser checks

The interface was opened in the in-app browser on 5 November 2026 using a separate temporary SQLite workspace. The following were observed directly:

- Synthetic-data banner, readable forms, indicator cards and tables at a narrow browser width.
- Registering a fourth fictional risk updated the coverage denominator from three to four risks.
- Attempting to use the process owner as auditor produced the expected error.
- Selecting a different auditor saved the plan; the displayed risk scores were ordered 20, 16, 12, 6.
- Jira CSV and Confluence Markdown links downloaded their respective files.
- Reloading retained the newly saved risk and audit.
- The checked overview is saved in `docs/screenshot.jpg`.

The temporary browser-check database is excluded from the repository. Closure/reopening and HTTP boundary checks were exercised by the automated tests; they were not repeated through the browser.

## Optional browser walkthrough

The following walkthrough can be used for further practice; only the checks explicitly recorded above were executed in the browser.

1. Start `python app.py --demo` and open `http://127.0.0.1:9877`.
2. Check the synthetic-data banner, four indicator cards, tables, labels and mobile-width layout.
3. Register a fictional risk; plan an audit with a different owner/auditor label.
4. Try using the process owner as auditor and observe the error.
5. Record an observation with evidence and complete the audit; inspect coverage.
6. Add a corrective action and advance statuses. Try closing without evidence or with the action owner as reviewer; observe rejection. Close with a different reviewer and evidence; inspect the activity/indicators.
7. Download both exports and compare their records with the interface.
8. Stop the local server; reopen to verify persistence if desired.

## Explicitly not tested or claimed

No real internal audit, standard-clause compliance, tamper resistance, authentication, Jira import, Confluence rendering/integration, production hosting or organisational audit-effectiveness assessment.
