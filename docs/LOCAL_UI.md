# Local InvoiceDesk UI

Run `make ui-install` once in the existing environment, then `make ui`. Open
<http://127.0.0.1:8000>. This serves buildless HTML/CSS/JavaScript through the
separate FastAPI entry point `invoicedesk.interfaces.local_api`. It binds only to
loopback, runs one worker, and uses one local operator. The PostgreSQL/OIDC API,
CLI, explicit golden demo profile, and their entry points remain separate.

## Start with an empty invoice history

Stop the running local UI server, then run:

```sh
make ui-clean
```

Equivalent: `.venv/bin/python -m invoicedesk.interfaces.local_api --clean-invoices`.
This clears only local invoice runs, queued jobs, events, extraction/recheck
artifacts, review history, invoice idempotency keys and invoice ledger postings,
then launches the UI at the usual address. Removing the postings restores PO
available balances. Vendors, POs, their states/revisions, their activity and
procurement source PDFs remain intact. The original source database is unchanged.

A SQLite backup is saved in ignored `private/ui-backups/` before clearing. Existing
upload files and genuine provider recordings remain on disk, so valid extraction
cache entries can still be reused. Normal `make ui` preserves the workspace.
The clean command refuses to run while a UI server owns the workspace lock.
This is an explicitly requested local testing reset, separate from the production
API's immutable invoice/ledger/audit history; no browser deletion endpoint is added.

## Live extraction

The local UI always selects live extraction. It accepts only the real `openai`
and `anthropic` adapters, configured by `.env` or exported environment variables:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-5-mini
OPENAI_API_KEY=your-local-key
```

Keep credentials in the ignored `.env` file. OpenAI uses the existing HTTPS
adapter; Anthropic also requires the project's Anthropic dependency. Conservative
PDF parsing remains the first pipeline tier; unfamiliar layouts and images go to
the actual configured model. Live extraction can reuse compatible, genuine API
recordings. Retries bypass the extraction cache. The UI offers no synthetic
provider, fixture mode, or synthetic sample-processing option. Existing offline
regression fixtures remain explicitly synthetic and are never read by the UI.

The local UI selects installed `pdfplumber`, or explicitly selects installed
Poppler (`pdftotext`) when pdfplumber is unavailable, and logs the selected reader.
An explicit `INVOICEDESK_PARSER` setting takes precedence. This local selection does
not change PostgreSQL production dependency requirements. Scanned inputs still use
the configured live provider and retain unverified source evidence. No currency
conversion or guessed missing values are introduced by the frontend.

## Isolated workspace and history

On first launch, SQLite's backup API copies the database configured by
`INVOICEDESK_DB` into ignored `private/ui/workspace.sqlite3`. The CLI default,
`data/local-preview.sqlite3`, is used when that setting is absent. If no source
exists, only procurement masters are seeded. Further launches reuse this workspace;
there is no automatic reset or UI reset endpoint. Source files found under local
`data`, `outputs`, or `archives` are copied only when their SHA-256 matches the
historical run. Missing historical sources, section reports, or raw responses are
shown as unavailable. Historical run IDs and recorded recommendations are retained.

UI uploads, live recordings, run artifacts, command responses and action history
remain under `private/ui/`. New tables have an `ui_` prefix; original Section 5
models and function contracts are preserved. Extraction event payloads gain
requested/resolved model metadata and independently verified source evidence.
The company identity follows the source sample documents: Acme Operations Inc,
410 Market Street, Suite 600, San Francisco, CA 94111; ap@acme.example.

## Procurement reference data

For this case study, assume approved vendors and authorized POs already exist in a
procurement system or spreadsheet. The candidate brief places that system on the
other side of the invoice matching workflow and asks for a PO dataset. Procurement
approval, vendor onboarding, and automatic PO PDF intake are outside the current
invoice-processing scope. New vendor/PO dialogs maintain the reference records
needed to test that workflow; uploading a PO through invoice intake does not create
an authorized PO.

Create or select an approved vendor, then enter the canonical PO number, vendor,
issue date, description, net amount, currency, tax rate and open/closed state.
Canonical PO identifiers must match the invoice reference after normalization.
The authorized net amount excludes tax and includes any approved non-tax charges
such as shipping. When charges have different tax treatment, retain that breakdown
with the source; the single tax-rate field cannot describe every tax component.
Printed invoice net/tax amounts remain preferable to an inferred net amount.

For an operator-authorized manual load, use the same revision/idempotency-aware
workspace service as the dialog. Preserve the supplied PO PDF and a manual-entry
manifest under ignored `private/ui/procurement-sources/`, and record source hashes,
operator assumptions and the mapping to the approved vendor in Activity. Never
label manual entry as LLM or API extraction. Keep supplier legal names consistent
and print an explicit currency code on source documents when possible.

Current matching checks supplier identity, PO reference or inferred PO, procurement
state, amounts, duplicates and approved balance. PO records currently store summary
amounts; they do not support SKU-level or quantity-by-quantity matching against PO
lines. Automatic PDF intake would be a separate draft-extraction and operator
confirmation workflow, with no automatic supplier approval or PO authorization.

## Processing and review

Upload returns HTTP 202 after content validation and durable queuing. A single
background worker owns its own SQLite connection; every yielded StageEvent is
committed in a short transaction. No LLM request runs inside a database
transaction. Browser polling every two seconds updates invoice lists and details;
leaving the page does not cancel processing. A workspace lock prevents a second
server from running another worker against the same database.

Queued jobs resume after restart. Interrupted running attempts become Errored and
require an explicit retry. Each retry creates a linked attempt, preserves its
predecessor, and supersedes review of that predecessor. Unposted predecessors in
the same explicit retry chain are excluded from duplicate comparison; independently
uploaded duplicates and posted invoices still participate. There is no automatic
retry after an ambiguous provider failure.

`AUTO_APPROVE` means **Approval recommended** and stays **Needs review** until an
operator approves. Rejection recommendations also remain Needs review until acted
on. Extraction/intake failures are Errored; partial pipeline reports survive.
Review actions are available only for completed, pending pilot records that carry
the required backend context. Historical records without that context can be
inspected and explicitly reprocessed, but cannot be approved directly.

Approval uses a short `BEGIN IMMEDIATE` transaction to check the revision, current
vendors, PO state, duplicate invoices, arithmetic, source confirmation and remaining
balance, then atomically writes one net ledger entry and audit record. Exceptions
require reasons; source uncertainty requires source confirmation. Failed arithmetic
or missing facts cannot be overridden. Rejection requires a reason and posts no
money. Requests use idempotency keys, and records require their current revision.
All money remains Decimal in Python and decimal text in SQLite.

PO receipt activity counts matched processing attempts, including pending/rejected
attempts. Only authorized net ledger postings consume balance. Full approval,
remaining net amount and overage are calculated in the backend. Procurement
open/closed remains separate. Referenced vendors/POs cannot be deleted; block or
close them. Unused record deletion requires typed-ID confirmation. Runs, ledger
postings and audit history have no deletion API.

## HTTP surface

All routes use `/api/v1`:

- `GET /config`; invoice list/detail, `POST /invoices/upload`, invoice
  `/events`, `/document`, `/report`, and `POST /approve`, `/reject`, `/retry`, `/recheck`.
- Vendors and purchase orders: list/detail, create (`POST`), update (`PUT`),
  delete (`DELETE`); vendors also have `POST /block` and `/unblock`.
- `GET /activity`, `GET /developer/runs`, and per-run developer details.

Mutation requests require `Idempotency-Key`. Review and record-edit commands carry
`revision`; deletion also carries `confirmation`. Structured errors distinguish
validation (422), missing records (404), and conflicts/blocked approvals (409).
List endpoints accept `page`, `page_size`, and applicable search/filter parameters.
Developer views expose only stored artifacts for the selected run; no global logs,
credentials, or environment dump are exposed. This is a local operator tool;
it does not introduce hosted deployment or OIDC configuration.

## Verification

Run `.venv/bin/python -m pytest -q` and `node --check
invoicedesk/interfaces/web/app.js`. New local persistence/review tests use explicit
domain facts without extraction providers. HTTP tests exercise the real ASGI app
with the worker stopped and no TCP sockets. Existing golden tests keep their
original offline fixtures and ordering.

The initial UI offline suite passed: **136 passed, 3 skipped**. JavaScript syntax and
Python compilation checks also passed. The original database contains no `ui_`
tables; the copied workspace retains all 17 historical runs.

The implementation session verified import of 17 existing runs, including Rostral
BOM previews and available section reports, without changing the source database
hash. A request to the actual configured OpenAI `gpt-5-mini` adapter failed at the
network boundary; it retained a partial report and 21 stage events, recorded
`ambiguous_timeout`, and did not automatically retry. A separate check reused a genuine existing Rostral API recording with zero
provider calls, retained resolved model `gpt-5-mini-2025-08-07`, and produced no
document-type validation error. Successful new live extraction must still be
checked in an environment that permits provider access.

The session installed compatible API dependencies from the local pip cache after
package-index DNS failed. The sandbox rejected loopback server binding and Chrome's
startup socket call, so browser upload, detail navigation, review dialogs and visual
acceptance remain unverified. Run these on the local host:

1. Start `make ui`, inspect the imported Rostral record, source and unavailable cells.
2. Upload a real PDF/image; navigate and refresh while extraction is in progress.
3. Approve a valid invoice after checking the source and confirm that only approved
   net balance changes. Repeat the approval request and confirm one posting.
4. Block its vendor or close its PO before another pending approval and verify refusal.
5. Exercise create/edit/cancel dialogs, search, pagination, revision conflicts and
   typed-ID deletion; inspect Activity and Developer diagnostics.
6. Restart during processing and confirm an interrupted attempt requires explicit
   retry while queued jobs resume. Never substitute synthetic model output for this
   live acceptance check.


## Currency, evidence and saved-extraction rechecks

Explicit US dollar spellings (USD, US$, U.S.$, US dollars and related forms) normalize
to USD while the original printed values remain in extraction/evidence. CAD, AUD,
NZD, SGD, HKD, EUR, GBP, INR and other supported explicit spellings retain their own
currency. A bare `$` resolves from explicit document evidence, or the currency of
an explicitly referenced PO when there is no conflicting document anchor. An
unresolved symbol stays unresolved; no FX conversion occurs. Currency mismatches
now have their own check and action rather than a misleading overbilling message.

Dates such as 20/11/2026 and 11/20/2026 have one valid interpretation. Dates such as
03/04/2026 need an explicit printed date-order declaration; conflicting declarations
remain unverified. Evidence verification tolerates currency-to-number whitespace
such as `$0` versus `$ 0`, while still checking exact numbers and matching the
source page. Structured parties and tables can be grounded through independently
verified cell references without requiring a fabricated aggregate snippet.

`Recheck saved extraction` applies current validators to the recorded facts and
original source, with **zero provider calls**. It appends a validation artifact and
increments the UI revision; it does not rewrite the original extraction, decision,
StageEvents, or provider provenance. Approval performs source validation before its
short transaction, then reruns current procurement checks within that transaction.
The displayed approved report comes from its stored approval recheck; the original
run remains available in Developer. Rechecking does not post a ledger entry.

The Section 5 model fields and pipeline signature remain unchanged. The additive
check IDs `currency_consistency` and `currency_resolution` separate currency handling
from `amount_vs_balance`; contexts record rule version `pilot-rules-2`. Source
validation is versioned as `source-validation-2`. The extraction prompt is version
`printed-facts-8`, so incompatible prompt recordings are not reused for new model
requests. Its workflow, examples, uncertainty behavior and evidence requirements
follow [OpenAI structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

The first Apple case was revalidated using its genuine stored OpenAI response:
32/32 source references grounded, all 11 checks passed, and USD 3,196 net authorized
at the user's request. Repeating the approval command produced one ledger entry;
PO-1241 retained USD 50.00 net. Original run artifacts were preserved. The private
verification record is `private/ui/verification/apple-first-approval.json`.

A new live request under prompt version 8 was attempted but this execution sandbox
could not connect to OpenAI. This does not replace the original successful API
recording or imply new-prompt model acceptance. Browser verification remains blocked
by sandbox socket restrictions. Restart the existing UI server after Python changes
and refresh the page to load the new static assets.

Current regression verification after these fixes: **172 passed, 3 skipped**;
JavaScript syntax and Python compilation checks passed. New tests use domain facts
and source documents without adding synthetic extraction providers.

## Column-header parsing and optional dates

A column layout such as `INVOICE NUMBER | DATE OF ISSUE | DUE DATE` must not turn
neighboring headings into an invoice number. The conservative parser rejects
heading-only values and table column headings masquerading as descriptions; the
shared merge then retains independently verified extracted facts. Genuine conflicts
between different printed identifiers still require review. Scalar snippets in the
original evidence dictionary are independently verified even if the model omitted
a duplicate entry in its field-evidence array.

Due date is optional scheduling metadata, separate from invoice date. A due-date
parse/verification issue is shown by an informational `optional_fields` check and
does not block an otherwise verified invoice. Free-form reference-text warnings are
also informational when an explicit PO reference is present and PO checks can
validate it independently. Vendor identity, invoice number/date, currency, monetary
facts, arithmetic, duplicates, PO ownership/state and balance remain enforced.

Saved-extraction rechecks can rebuild the parser/model merge from genuine stored
API facts and the hash-verified source, without calling a provider or rewriting the
original run. The current UI and duplicate checks use the validated artifact's
invoice identity; this prevents an old parser mistake from weakening duplicate
protection after approval. Contexts use `pilot-rules-3`, and revalidation metadata
uses `source-validation-3`. Existing Section 5 model fields and signatures remain
unchanged; `optional_fields` is an additive informational check.

The Apple column-layout case was replayed through the full pipeline using its
existing genuine API recording: correct INV-004, valid 26 November 2026 due date,
no invented reference text, no extraction warnings, 32/32 references grounded and
all 11 checks passed. Its live workspace report was rechecked at a new revision;
final Approved status still requires the explicit approval action.

## Verify a folder of independent invoice layouts

```sh
make verify-invoices VERIFY_DIR="/path/to/invoices"
```

The command calls the actual configured LLM when extraction requires it, using a
new workspace/cache per document. It copies current vendor/PO reference data and
starts each case with empty invoice history and zero approved balance. A successful
case is approved through the normal backend action in its disposable ledger. It
never posts those approvals to the main workspace. Reports, source documents,
provider recordings and per-case SQLite databases remain under ignored
`private/layout-verification/`.

Optional private labels can assert exact expected fields, row count and row order:

```sh
.venv/bin/python -m invoicedesk.interfaces.local_verify /path/to/invoices \
  --labels private/my-labels.json
```

Labels are keyed by filename and contain the source `sha256`, a `fields` mapping,
and a `line_items` array. Monetary labels use decimal text. Currency labels refer
to the backend's normalized code. Labels with a different source hash are rejected;
wrong identifiers, amounts, missing rows or additional rows fail verification.
This is a focused local regression tool, not a held-out production release gate.

When the UI worker has already made genuine model calls, `--from-batch` can replay
its private batch manifest and exact compatible API recordings. Replay verifies
provider/model/prompt/schema identity before processing; it does not fabricate API
provenance or make a fallback request for incompatible recordings. Live-origin
usage and timings are reported separately from the zero-call replay. Provider
failures remain errors, and retries remain explicit.

Source verification now accepts row-scoped references such as `line_items.0` by
checking the exact snippet on its claimed page, then independently verifying each
non-null cell against that snippet. A wrong amount or quantity remains unverified;
no missing values are calculated. Empty evidence for a known null is ignored
because no factual value was claimed. These changes use rule version `pilot-rules-4`
and source validator `source-validation-4`; Section 5 model fields and pipeline
signatures are unchanged.

The Apple folder contains four alternative layouts of two invoice identities.
They are expected to pass independently. A cumulative payables batch must still
flag repeated invoice numbers and prevent repeatedly consuming the same PO's
balance. Do not disable those rules to make repeated full-PO variants approve.

The observed four-file Apple layout run used four fresh OpenAI extractions through
the running local UI worker, followed by replay of genuine API recordings under
current code. All 44 human-labeled fields and all 16 item rows matched; each case
had zero unverified source references and reached Approved in its disposable
workspace with one USD 3,196 net posting. The main ledger was unchanged. The private
report is `private/layout-verification/apple-20261111-fresh-all/SUMMARY.md`.
Final offline regression verification: **187 passed, 3 skipped**.
