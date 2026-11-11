# InvoiceDesk repository guidance

Read PROJECT_PLAN.md before changing the workflow. The candidate guide PDF is the source brief.

- Python package lives in invoicedesk/; invoicedesk/cli.py is the current entry point.
- Preserve Section 5 contracts. Flag any necessary contract change explicitly.
- Decisions and communications are deterministic. The LLM only extracts printed facts.
- Money uses Decimal in Python and decimal text in SQLite; never SUM money in SQLite.
- Terminal progress renders StageEvents; keep decision rules in the backend checks.
- Tests must run offline. Never replace synthetic extraction fixtures with claims of API provenance.
- Run `.venv/bin/python -m pytest -q` after changing behavior.
- Golden order is defined in data/golden.json, not lexical filename order.
- Demo preparation: `python -m invoicedesk.cli reset --demo`.
- Do not put API keys, runtime databases, or customer uploads in version control.
- Keep generated golden PDFs and their hash-keyed extraction fixtures together.
