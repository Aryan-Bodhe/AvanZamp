"""Golden compatibility under required production dependencies, still explicit synthetic demo data."""
import json
from decimal import Decimal
import pytest
pytest.importorskip('pdfplumber', reason='Install required parser for dependency compatibility checks')
pytest.importorskip('rapidfuzz', reason='Install required matcher for dependency compatibility checks')
from invoicedesk.db import Db
from invoicedesk.seed import reset
from invoicedesk.policy import ROOT, Policy
from invoicedesk.pipeline import run_invoice
from invoicedesk.extract.llm import LlmClient


def test_installed_parser_and_matcher_preserve_ordered_golden_demo(tmp_path,monkeypatch):
    monkeypatch.setenv('INVOICEDESK_PARSER','pdfplumber')
    monkeypatch.setenv('INVOICEDESK_MATCHER','rapidfuzz')
    db = Db(tmp_path/'demo.db',mode='demo')
    try:
        reset(db)
        for expected in json.loads((ROOT/'data/golden.json').read_text()):
            final = list(run_invoice(ROOT/'data/invoices'/expected['file'],db=db,policy=Policy.load(),llm=LlmClient('cache')))[-1]
            assert final.payload['decision']['outcome'] == expected['expected_outcome'], expected['file']
        assert db.billed('PO-2001') == Decimal('20000')
    finally:
        db.close()
