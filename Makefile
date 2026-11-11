.DEFAULT_GOAL := run

VENV ?= .venv
PYTHON = $(VENV)/bin/python
BOOTSTRAP_PYTHON ?= python3
# No FILE means a fresh offline demo; an explicit FILE uses persistent processing.
FILE ?=
PROFILE ?= pilot
DB ?= $(INVOICEDESK_DB)
LLM_MODE ?=
PROVIDER ?= $(LLM_PROVIDER)
MODEL ?= $(LLM_MODEL)
OUTPUT ?=
REFRESH ?= false
LOG_LEVEL ?=
DEMO_DB ?= data/demo.sqlite3
DEMO_FILE ?= data/invoices/01_clean_exact.pdf
DEMO_PARSER ?= poppler
DEMO_MATCHER ?= development
VERIFY_DIR ?=
export VERIFY_DIR

# Pass configurable values through the environment, quoted by the shell.
export FILE PROFILE DB PROVIDER MODEL OUTPUT REFRESH
export DEMO_DB DEMO_FILE DEMO_PARSER DEMO_MATCHER
MAKE_LOG_LEVEL = $(LOG_LEVEL)
MAKE_LLM_MODE = $(LLM_MODE)
export MAKE_LOG_LEVEL MAKE_LLM_MODE
unexport LLM_MODE LOG_LEVEL

# Explicit Make overrides become CLI environment settings; otherwise .env supplies them.
CONFIG_ENV = if [ -n "$$DB" ]; then export INVOICEDESK_DB="$$DB"; fi; if [ -n "$$MAKE_LOG_LEVEL" ]; then export LOG_LEVEL="$$MAKE_LOG_LEVEL"; fi;

.PHONY: help venv setup check-env run process test golden batch reset demo demo-all clean

help:
	@printf '%s\n' \
	  'make setup     Create the virtual environment and install requirements' \
	  'make ui-install Install the local UI dependencies' \
	  'make ui        Launch the local UI at http://127.0.0.1:8000' \
	  'make ui-clean  Clear invoices and launch; preserve vendors and purchase orders' \
	  'make verify-invoices VERIFY_DIR=folder  Verify each invoice with a fresh, isolated ledger' \
	  'make           Run a fresh offline demo (same as make run)' \
	  'make run       Reset the dedicated demo DB and process the happy-path sample' \
	  'make run FILE=invoice.pdf  Process your own file using .env and persistent history' \
	  'make test      Run all offline tests' \
	  'make golden    Verify the 12 ordered golden cases in a temporary database' \
	  'make batch     Process golden fixtures against DB current history' \
	  'make reset     Replace DB history and reload vendor/PO masters' \
	  'make demo      Run a fresh offline demo; no API key needed' \
	  'make demo-all  Reset the demo DB and run all 12 samples in golden order' \
	  'make clean     Remove Python/test caches; preserve data and environment' \
	  '' \
	  'Examples:' \
	  '  make run FILE="path/to/invoice.pdf"' \
	  '  make run FILE=invoice.png LLM_MODE=live PROVIDER=openai MODEL=gpt-5-mini OUTPUT=outputs/run.json' \
	  '  make run FILE=invoice.pdf DB=/tmp/invoicedesk.sqlite3 LOG_LEVEL=DEBUG' \
	  '  make run FILE=invoice.png LLM_MODE=live REFRESH=true  # bypass extraction cache' \
	  '  make demo DEMO_FILE=data/invoices/11_scanned_implied_po.pdf' \
	  '' \
	  'Demo targets explicitly use cached synthetic fixtures and development adapters.' \
	  'Default demo parser: Poppler (pdftotext); override with DEMO_PARSER=pdfplumber.' \
	  'Demo targets reset DEMO_DB (default data/demo.sqlite3), ignoring .env database settings.' \
	  'Custom-file settings load from .env; Make options and shell exports override it.'

venv:
	@test -x "$(PYTHON)" || "$(BOOTSTRAP_PYTHON)" -m venv "$(VENV)"

setup: venv
	"$(PYTHON)" -m pip install -r requirements-dev.lock

check-env:
	@test -x "$(PYTHON)" || { printf '%s\n' 'Virtual environment missing. Run make setup first.' >&2; exit 1; }

run: check-env
	@if [ -n "$$FILE" ]; then $(MAKE) --no-print-directory process; else $(MAKE) --no-print-directory demo; fi

process: check-env
	@test -n "$$FILE" || { printf '%s\n' 'Specify FILE=path/to/invoice.pdf, or use make run for the demo.' >&2; exit 1; }
	@$(CONFIG_ENV) set --; if [ "$$REFRESH" = true ]; then set -- "$$@" --refresh-extraction; fi; if [ -n "$$OUTPUT" ]; then set -- "$$@" --output "$$OUTPUT"; fi; \
	  if [ -n "$$MAKE_LLM_MODE" ]; then set -- "$$@" --llm-mode "$$MAKE_LLM_MODE"; fi; \
	  if [ -n "$$PROVIDER" ]; then set -- "$$@" --provider "$$PROVIDER"; fi; \
	  if [ -n "$$MODEL" ]; then set -- "$$@" --model "$$MODEL"; fi; \
	  "$(PYTHON)" -m invoicedesk.cli --profile "$$PROFILE" run "$$FILE" \
	  "$$@"

test: check-env
	"$(PYTHON)" -m pytest -q

golden: check-env
	"$(PYTHON)" -m pytest -q tests/test_pipeline.py::test_golden_ordered

batch: check-env
	@$(CONFIG_ENV) "$(PYTHON)" -m invoicedesk.cli batch

reset: check-env
	@$(CONFIG_ENV) "$(PYTHON)" -m invoicedesk.cli reset

demo: check-env
	@set -e; $(CONFIG_ENV) \
	  export INVOICEDESK_PARSER="$$DEMO_PARSER" INVOICEDESK_MATCHER="$$DEMO_MATCHER"; \
	  if [ "$$DEMO_PARSER" = poppler ] && ! command -v pdftotext >/dev/null 2>&1; then \
	    printf '%s\n' 'Install Poppler (pdftotext), or use DEMO_PARSER=pdfplumber with the installed Python dependencies.' >&2; exit 1; fi; \
	  printf 'Offline demo: resetting %s; parser=%s matcher=%s; synthetic fixtures, no API calls.\n' "$$DEMO_DB" "$$DEMO_PARSER" "$$DEMO_MATCHER"; \
	  "$(PYTHON)" -m invoicedesk.cli --db "$$DEMO_DB" --profile demo reset --demo; \
	  "$(PYTHON)" -m invoicedesk.cli --db "$$DEMO_DB" --profile demo run "$$DEMO_FILE" --llm-mode cache

demo-all: check-env
	@set -e; $(CONFIG_ENV) \
	  export INVOICEDESK_PARSER="$$DEMO_PARSER" INVOICEDESK_MATCHER="$$DEMO_MATCHER"; \
	  if [ "$$DEMO_PARSER" = poppler ] && ! command -v pdftotext >/dev/null 2>&1; then \
	    printf '%s\n' 'Install Poppler (pdftotext), or use DEMO_PARSER=pdfplumber with the installed Python dependencies.' >&2; exit 1; fi; \
	  printf 'Offline demo: resetting %s and running all 12 synthetic samples.\n' "$$DEMO_DB"; \
	  "$(PYTHON)" -m invoicedesk.cli --db "$$DEMO_DB" --profile demo reset; \
	  "$(PYTHON)" -m invoicedesk.cli --db "$$DEMO_DB" --profile demo batch

clean:
	@find invoicedesk scripts tests migrations -type d -name __pycache__ -prune -exec rm -rf {} +
	@rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__

.PHONY: ui ui-install ui-clean
ui-install: check-env
	"$(PYTHON)" -m pip install -r requirements-ui.txt

ui: check-env
	@$(CONFIG_ENV) "$(PYTHON)" -m invoicedesk.interfaces.local_api

ui-clean: check-env
	@$(CONFIG_ENV) "$(PYTHON)" -m invoicedesk.interfaces.local_api --clean-invoices

.PHONY: verify-invoices
verify-invoices: check-env
	@test -n "$$VERIFY_DIR" || { printf '%s\n' 'Specify VERIFY_DIR=path/to/invoices.' >&2; exit 1; }
	@$(CONFIG_ENV) "$(PYTHON)" -m invoicedesk.interfaces.local_verify "$$VERIFY_DIR"
