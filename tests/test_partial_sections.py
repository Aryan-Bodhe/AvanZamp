"""Sections and cells survive unrelated failures; approval remains a separate decision."""
import json
from decimal import Decimal
import pytest
from invoicedesk.extract.validation import parse_response
from invoicedesk.extract.sections import section_report
from invoicedesk.extract.reconcile import reconcile
from invoicedesk.extract.llm import LlmClient
from invoicedesk.extract.providers import ProviderResponse
from invoicedesk.pipeline import run_invoice
from invoicedesk.db import Db
from invoicedesk.seed import reset
from invoicedesk.policy import ROOT, Policy


def facts():
    return {'document_type':'invoice','vendor_name':'Northwind Office Supplies Ltd',
            'sender':{'name':'Northwind Office Supplies Ltd','address':'22 Commerce Avenue'},
            'recipient':{'name':'Acme Operations Inc','email':'ap@example.com'},
            'invoice_number':'PARTIAL-1','invoice_date':'2026-11-09','currency':'USD',
            'po_reference':'PO-1001','subtotal':'100.00','tax_amount':'8.00','total':'108.00',
            'line_items':[{'description':'Desk','quantity':'1','unit_price':'100.00','amount':'100.00'}],
            'evidence':{'total':'Total: 108.00'}}


def report(raw):
    parsed=parse_response(raw)
    checks=reconcile(parsed.invoice,Decimal('.02'))
    sections=section_report(parsed.invoice,parsed.issues,parsed.provided_fields,checks,parsed.provided_paths)
    return parsed,{section['section']:section for section in sections}


def test_bad_date_does_not_discard_parties_table_or_totals():
    raw=facts();raw['invoice_date']='not-a-date'
    parsed,sections=report(raw)
    assert parsed.invoice.invoice_date is None
    assert parsed.invoice.sender.name=='Northwind Office Supplies Ltd'
    assert parsed.invoice.recipient.name=='Acme Operations Inc'
    assert parsed.invoice.total==108
    assert sections['metadata']['status']=='PARTIAL'
    assert sections['metadata']['fields']['invoice_date']['status']=='INVALID'
    assert sections['line_items']['status']=='PARSED'
    assert sections['totals']['arithmetic_status']=='PASS'


def test_one_bad_cell_preserves_row_positions_and_other_cells():
    raw=facts()
    raw['line_items']=[{'description':'First','quantity':'2','unit_price':'bad','amount':'50.00'},
                       {'description':'Second','quantity':'1','unit_price':'50.00','amount':'50.00'}]
    parsed,sections=report(raw)
    assert len(parsed.invoice.line_items)==2
    assert parsed.invoice.line_items[0].unit_price is None
    assert parsed.invoice.line_items[0].amount==50
    assert parsed.invoice.line_items[1].unit_price==50
    rows=sections['line_items']['row_validation']
    assert rows[0]['status']=='PARTIAL' and rows[1]['status']=='PARSED'
    assert rows[0]['fields']['unit_price']['status']=='INVALID'
    assert sections['line_items']['arithmetic_status']=='PARTIAL'
    assert sections['totals']['status']=='PARSED'


def test_invalid_recipient_does_not_erase_sender_or_total():
    raw=facts();raw['recipient']['address']=['bad-address']
    parsed,sections=report(raw)
    assert parsed.invoice.recipient.name=='Acme Operations Inc'
    assert parsed.invoice.recipient.address is None
    assert parsed.invoice.sender.name=='Northwind Office Supplies Ltd'
    assert sections['recipient']['status']=='PARTIAL'
    assert sections['recipient']['party_validation']['recipient']['address']['status']=='INVALID'


def test_omitted_and_null_fields_have_distinct_results():
    raw=facts();del raw['invoice_date'];raw['invoice_number']=None
    parsed,sections=report(raw)
    assert sections['metadata']['fields']['invoice_date']['status']=='UNAVAILABLE'
    assert sections['metadata']['fields']['invoice_number']['status']=='MISSING'


def test_arithmetic_failure_is_independent_of_parsing_success():
    raw=facts();raw['total']='109.00'
    parsed,sections=report(raw)
    assert sections['totals']['status']=='PARSED'
    assert sections['totals']['arithmetic_status']=='FAIL'
    assert parsed.invoice.total==109


def test_bom_adjustment_math_does_not_invent_tax():
    raw={'document_type':'bill_of_materials','sender':{'name':'Rostral Medtech'},
         'recipient':None,'vendor_name':None,'invoice_number':None,'invoice_date':None,
         'currency':'INR','subtotal':'10282.00','total':'10000.00','tax_amount':None,
         'adjustments':[{'description':'Round-off','amount':'-282.00'}],
         'line_items':[{'description':'Components','amount':'10282.00'}]}
    parsed,sections=report(raw)
    assert parsed.invoice.tax_amount is None
    assert parsed.invoice.adjustments[0].amount==-282
    assert sections['line_items']['arithmetic_status']=='PARTIAL'
    assert sections['totals']['arithmetic_status']=='PARTIAL'
    assert sections['totals']['arithmetic'][0]['passed'] is True
    assert sections['totals']['arithmetic'][0]['scope']=='printed_total'


@pytest.mark.parametrize('raw_change',[{'invoice_date':'bad-date'},{'recipient':{'name':'Acme','address':42}}])
def test_pipeline_retains_partial_data_and_never_autoapproves_it(tmp_path,raw_change):
    raw=facts();raw.update(raw_change)
    class Provider:
        name='partial-test'
        def extract(self,*args,**kwargs):return ProviderResponse(raw)
    db=Db(tmp_path/'db.sqlite3');reset(db)
    try:
        llm=LlmClient('live',tmp_path/'cache',provider=Provider(),model='test')
        events=list(run_invoice(ROOT/'data/examples/office_furniture.png',db=db,policy=Policy.load(),llm=llm))
        assert events[-1].payload['decision']['outcome']=='NEEDS_REVIEW'
        extract=next(e for e in events if e.stage=='extract' and e.state=='completed')
        assert extract.payload['invoice']['total']=='108.00'
        assert extract.payload['invoice']['line_items'][0]['description']=='Desk'
        assert extract.payload['validation_issues']
        assert db.billed('PO-1001')==0
        stored=db.rows("SELECT payload_json FROM events WHERE run_id=? AND stage='extract' AND state='completed'",(events[-1].run_id,))
        assert json.loads(stored[0]['payload_json'])['sections']==extract.payload['sections']
    finally:db.close()


def test_bom_reports_successful_parts_without_vendor_invoice_rejection(tmp_path):
    raw=facts();raw.update(document_type='bill_of_materials',vendor_name=None,invoice_number=None,currency='INR')
    class Provider:
        name='bom-test'
        def extract(self,*args,**kwargs):return ProviderResponse(raw)
    db=Db(tmp_path/'db.sqlite3');reset(db)
    try:
        events=list(run_invoice(ROOT/'data/examples/office_furniture.png',db=db,policy=Policy.load(),
                               llm=LlmClient('live',tmp_path/'cache',provider=Provider(),model='test')))
        final=events[-1].payload['decision']
        assert final['outcome']=='NEEDS_REVIEW'
        assert 'workflow_applicability' in final['driving_checks']
        assert db.runs()[0]['vendor_id'] is None
        assert db.runs()[0]['net_amount'] is None
    finally:db.close()
