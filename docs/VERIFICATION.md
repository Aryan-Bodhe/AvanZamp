# Implementation verification — 2026-11-11

This records executed checks, not release acceptance. The operator UI remains a later phase.

| Check | Observed result |
| --- | --- |
| Baseline offline suite | 73 passed |
| Final `.venv/bin/python -m pytest -q` | **110 passed, 3 skipped** in 2.44 seconds |
| Twelve golden cases | Expected decisions, paths, and driving checks reproduced in `data/golden.json` order under explicit demo behavior |
| CLI `reset --demo` | Six demo-history entries prepared in an isolated temporary database |
| CLI clean reset + batch | All 12 expected outcomes printed, including 09 before 07 |
| Concurrent SQLite human approvals | One approval commits; the competing approval cannot reuse the old balance |
| Application review service | Revision preservation, source confirmation, stale revisions, idempotency, and role revocation tested with an in-memory persistence port |
| Import/syntax/configuration | Compatibility imports, compileall, YAML parsing, and container configuration assertions passed |
| Prototype archive | Private SQLite backup passes quick_check; run count agrees with the preserved original |
| Initial migration | Frozen schema file agrees with application schema; applying it requires unavailable dependencies/PostgreSQL |
| Evaluation runner default | Labels-only output: zero real cases, `measured=false`, `release_accepted=false` |

The three skipped modules require the installed pdfplumber/rapidfuzz algorithms, the SQLAlchemy/API stack, and local PostgreSQL integration respectively. No test fabricated real API provenance or reported real-model extraction accuracy. Synthetic PDF/fixture pairs were preserved.

Package installation was attempted and failed because the package index could not be reached/resolved. FastAPI, SQLAlchemy, Alembic, Authlib, psycopg, lint/type tools and the required parser/matcher could not be installed. PostgreSQL/Docker integration, clean lock installation, lint/type CI, migration application, real worker-kill/load tests, live OIDC/TLS, real-model evaluation, and PostgreSQL backup restoration are **unverified**. CI and opt-in commands are supplied for those checks; their presence is not a passing result.

See [PILOT.md](PILOT.md) for the contract amendment, deployment/restore instructions, and outstanding release gates.
