import json
from decimal import Decimal
from pathlib import Path
import pytest
from invoicedesk.db import Db
from invoicedesk.seed import reset, batch
from invoicedesk.policy import ROOT, Policy
from invoicedesk.pipeline import run_invoice
from invoicedesk.extract.llm import LlmClient
from invoicedesk.extract.reconcile import reconcile
from invoicedesk.extract.grounding import ground
from invoicedesk.models import ExtractedInvoice, LineItem, Quality

@pytest.fixture
def db(tmp_path):
    db=Db(tmp_path/'test.sqlite3', mode='demo'); reset(db)
    yield db
    db.close()

def run(db,filename,mode='cache'):
    return list(run_invoice(ROOT/'data/invoices'/filename,db=db,policy=Policy.load(),llm=LlmClient(mode)))

def test_golden_ordered(db):
    for expected in json.loads((ROOT/'data/golden.json').read_text()):
        events=run(db,expected['file']); decision=events[-1].payload['decision']
        assert decision['outcome']==expected['expected_outcome'],expected['file']
        assert set(expected['expected_driving_checks'])<=set(decision['driving_checks'])
        extraction=next(e for e in events if e.stage=='extract' and e.state=='completed')
        assert extraction.detail==expected['expected_path']
        assert [e.seq for e in events]==list(range(1,len(events)+1))
        assert db.rows('SELECT * FROM events WHERE run_id=?',(events[-1].run_id,))
    assert db.billed('PO-2001')==Decimal('20000')
    assert db.billed('PO-1004')==Decimal('7620')

def test_missing_vs_unavailable(db):
    event=run(db,'10_missing_invoice_number.pdf')[-1]
    assert event.payload['decision']['outcome']=='HOLD_MISSING_INFO'
    event=run(db,'11_scanned_implied_po.pdf','off')[-1]
    assert event.payload['decision']['outcome']=='NEEDS_REVIEW'
    assert 'completeness' not in event.payload['decision']['driving_checks']

def test_review_ledger_and_audit(db):
    events=run(db,'11_scanned_implied_po.pdf'); rid=events[-1].run_id
    assert db.billed('PO-4001')==0
    db.review(rid,True,'Verified against scan')
    assert db.billed('PO-4001')==Decimal('3000')
    assert len(db.rows('SELECT * FROM review_audit'))==1
    with pytest.raises(ValueError):db.review(rid,True,'Repeated click')
    assert db.billed('PO-4001')==Decimal('3000')

def test_cannot_approve_missing_fields(db):
    rid=run(db,'10_missing_invoice_number.pdf')[-1].run_id
    with pytest.raises(ValueError):db.review(rid,True,'')
    assert db.billed('PO-3001')==0

def test_demo_state(db):
    batch(db,demo=True)
    assert len(db.runs())==6
    assert db.billed('PO-2001')==Decimal('20000')
    for prefix in ['01','08','09','10','11','12']:
        assert not any(r['filename'].startswith(prefix) for r in db.runs())
    assert run(db,'01_clean_exact.pdf')[-1].payload['decision']['outcome']=='AUTO_APPROVE'
    assert run(db,'08_split_po_3of3_overbill.pdf')[-1].payload['decision']['outcome']=='REJECT'
    assert run(db,'09_near_duplicate.pdf')[-1].payload['decision']['driving_checks']==['duplicate_near']

def test_reconciliation_catches_altered_item():
    inv=ExtractedInvoice(subtotal='100',tax_amount='8',total='108',line_items=[LineItem(description='Changed',amount='99')])
    assert not all(f['passed'] for f in reconcile(inv,Decimal('.02')))

def test_grounding_checks_value_not_only_snippet():
    inv=ExtractedInvoice(invoice_number='FAKE-123',evidence={'invoice_number':'Invoice No: REAL-99'})
    ground(inv,'Invoice No: REAL-99')
    assert inv.field_quality['invoice_number']==Quality.UNVERIFIED

def test_empty_po_balance(db):
    run(db,'01_clean_exact.pdf')
    final=run(db,'12_exact_duplicate.pdf')[-1]
    assert final.payload['decision']['outcome']=='REJECT'
    assert db.billed('PO-1001')==Decimal('4800')

def test_corrupt_pdf_persists_review(db,tmp_path):
    path=tmp_path/'broken.pdf';path.write_bytes(b'%PDF-1.4\nnot a real document')
    final=list(run_invoice(path,db=db,policy=Policy.load(),llm=LlmClient('off')))[-1]
    assert final.payload['decision']['outcome']=='NEEDS_REVIEW'
    assert len(db.runs())==1

def test_fresh_pdf_not_in_golden(db,tmp_path):
    from scripts.pdf_fallback import write_pdf
    path=tmp_path/'fresh.pdf'
    write_pdf(path,[
        'Vendor: Northwind Office Supplies Ltd','Invoice No: FRESH-552',
        'Invoice date: 2026-11-07','PO Number: PO-1001','Currency: USD',
        'Re: Office furniture - Q4 order','Item: Desk | 1 | 1200.00 | 1200.00',
        'Subtotal: 1200.00','Tax: 96.00','Total Due: 1296.00'])
    events=list(run_invoice(path,db=db,policy=Policy.load(),llm=LlmClient('off')))
    assert events[-1].payload['decision']['outcome']=='AUTO_APPROVE'
    assert db.billed('PO-1001')==Decimal('1200')

def test_scan_has_no_text_layer():
    from invoicedesk.extract.text import read_text
    assert not read_text(ROOT/'data/invoices/11_scanned_implied_po.pdf').strip()

def test_cancelled_run_rolls_back(db):
    stream=run_invoice(ROOT/'data/invoices/01_clean_exact.pdf',db=db,policy=Policy.load(),llm=LlmClient('off'))
    for event in stream:
        if event.stage=='amounts':break
    stream.close()
    assert not db.conn.in_transaction
    assert db.runs()==[]
