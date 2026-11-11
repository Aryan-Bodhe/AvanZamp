# InvoiceDesk

Run the local operator UI with `make ui-install` then `make ui`, and open **http://127.0.0.1:8000**. It uses the actual configured LLM provider and an isolated copy of your existing database under `private/ui/`. See [local UI setup and verification](docs/LOCAL_UI.md).

Use `make ui-clean` to start with empty invoice history while keeping vendors and purchase orders. Stop the existing UI server first; the command backs up the local database before clearing invoice records and postings.

Run independent invoice-layout checks with `make verify-invoices VERIFY_DIR="/path/to/invoices"`. Each file gets its own disposable invoice history and ledger, using your current vendors/POs and the real configured LLM provider.

InvoiceDesk reads vendor invoices, runs deterministic procurement checks, and records an explained recommendation. Only an authorized human approval commits PO balance in the pilot. The LLM extracts printed facts; it never decides, approves, sends messages, or executes payments.

This repository contains the original reproducible demo and a new single-company backend/API implementation. **It is not an accepted production pilot.** A local operator UI is now available; browser acceptance, real-document release evaluation, and operational acceptance remain outstanding. See [pilot architecture and acceptance](docs/PILOT.md) for architecture and remaining gates, and [executed verification](docs/VERIFICATION.md) for observed results.

## Install and verify

Python 3.12 is the deployment target. Tests use synthetic providers and block external network access.

With the existing virtual environment, start the terminal demo with one command:

```sh
make run
```

Plain `make` does the same. Each run prepares a fresh demo database and processes the happy-path invoice, so repeat runs work without manual resets or API keys. Run `make help` for all commands. For a new environment, install dependencies first:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

The exact dependency pins are a candidate lock; a clean install could not be verified in the implementation environment because package-index network/DNS access was unavailable. CI checks installation, dependencies, tests, lint, types, and migrations.

The offline demo retains the 12 golden outcomes and their original order from `data/golden.json`. Its synthetic extraction fixtures remain paired with their PDFs. Demo recommendations consume balance under the **explicit demo profile**; this is deliberately different from human posting in the pilot.

```sh
make demo-all                              # Reset and run all 12 samples in order
make run FILE=path/to/invoice.pdf           # Process your own file; keep its history
make run FILE=invoice.png LLM_MODE=live     # Use configured provider credentials
make test
```

`make run` without `FILE`, `make demo`, and `make demo-all` reset only `DEMO_DB` (default `data/demo.sqlite3`), regardless of the database configured in `.env`. To inspect another demo edge case, use `make demo DEMO_FILE=data/invoices/11_scanned_implied_po.pdf`. Custom-file processing uses `.env`, accepts `DB=...`, `PROVIDER=...`, `MODEL=...`, and `OUTPUT=...`, and never resets history automatically.

The Make demo targets explicitly select Poppler (`pdftotext`) and the development matcher for this offline environment. With the required Python dependencies installed, override them using `DEMO_PARSER=pdfplumber DEMO_MATCHER=rapidfuzz`. Production rejects development adapters and requires pdfplumber and rapidfuzz. There are no silent substitutions.

For a manual CLI rehearsal, `python -m invoicedesk.cli reset --demo` still prepares the six-entry demo history. CLI `batch` processes the current history; use a clean demo database first, or use `make demo-all` to handle both steps. Never use demo state for a pilot company. The old local CLI/report imports remain compatibility adapters. Without a demo profile, the local SQLite preview never posts recommendations and is not the deployment backend.

`scripts/generate_test_data.py` generates the golden PDFs and their paired synthetic extraction fixtures. `scripts/generate_example_invoice.py` generates the image/PDF examples in `data/examples/` (requires DejaVu Sans fonts). These examples and their generators remain test inputs, not evidence of real-document extraction accuracy.

## Backend and API

The modular monolith has four boundaries:

- `domain/`: contracts, exact money, policy, semantic validation, reconciliation, checks, recommendations, approval invariants.
- `application/`: processing and revision-aware job/review services.
- `infrastructure/`: PostgreSQL/SQLAlchemy, private storage, provider adapters, parsing, telemetry.
- `interfaces/`: FastAPI/OIDC, worker, CLI, and operational commands.

Deploy using [Docker Compose](compose.yaml), [configuration template](.env.pilot.example), and the [operator runbook](docs/PILOT.md). API and worker use the same image; PostgreSQL leases durable jobs, and Caddy terminates HTTPS. No deployment or live model calls are performed by tests.

Endpoints under `/v1` cover submissions, job status, replayable SSE, paginated history, detailed reports, protected document downloads, corrections, approval/rejection, explicit retries, and procurement administration. `/docs` and `/openapi.json` describe the API. Uploads use a streamed binary request body with `X-Filename`. Mutations require an idempotency key and session CSRF token; reviews and administration also require revisions.

The trusted local CLI uses those same services:

```sh
.venv/bin/python -m invoicedesk.cli pilot --actor OIDC_SUBJECT submit invoice.pdf --key submission-1
.venv/bin/python -m invoicedesk.cli pilot --actor OIDC_SUBJECT report JOB_ID
.venv/bin/python -m invoicedesk.cli pilot --actor OIDC_SUBJECT approve JOB_ID --revision 1 --key approval-1 --reason 'Compared with source' --confirmed-source
```

Supply `DATABASE_URL`, `DOCUMENT_ROOT`, and the OIDC subject allowlist through the trusted deployment environment. CLI access to database credentials is privileged operator access; browser users authenticate through OIDC.

## Product limits

One company and approval currency, two-way invoice/PO matching, human-authorized ledger posting. No FX, goods receipts, email ingestion, payment execution, or extra BOM/advance approval engines. Scans retain unverified evidence. Typed values, arithmetic, source grounding, vendor identity, and approval remain separate results.

The original [candidate plan](PROJECT_PLAN.md) preserves the brief and demo contracts. The [pilot contract amendment](docs/PILOT.md#contract-amendment) and current runbook describe the backend; the pilot rules above take precedence over the historical plan.
