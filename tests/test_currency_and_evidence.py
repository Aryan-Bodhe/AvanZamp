"""Offline normalization/source safety tests; no extraction provider is used."""
from datetime import date
from decimal import Decimal
import pytest
from invoicedesk.domain.normalize import currency_code, normalize, normalize_po
from invoicedesk.domain.models import ExtractedInvoice, Quality
from invoicedesk.infrastructure.extraction.grounding import ground
from invoicedesk.infrastructure.extraction.evidence import verify_references
from invoicedesk.infrastructure.extraction.tier1 import parse_date
from invoicedesk.domain.checks import amounts
from invoicedesk.policy import Policy


@pytest.mark.parametrize('printed',['USD','usd',' US$ ','U.S.$','$US','US Dollars','U.S. Dollar','United States Dollars'])
def test_explicit_us_dollar_spellings(printed):
    assert currency_code(printed)=='USD'


@pytest.mark.parametrize('printed,expected',[('C$','CAD'),('CA$','CAD'),('A$','AUD'),('AU$','AUD'),('NZ$','NZD'),('HK$','HKD'),('S$','SGD'),('€','EUR'),('£','GBP'),('₹','INR'),('$','$'),('¥','¥')])
def test_other_currencies_do_not_become_usd(printed,expected):
    assert currency_code(printed)==expected


def invoice(currency='$',reference='PO-1001',evidence=None):
    return ExtractedInvoice(document_type='invoice',currency=currency,po_reference=reference,subtotal='100',tax_amount='8',total='108',evidence=evidence or {})


def test_bare_dollar_requires_explicit_po_or_document_anchor():
    inv=invoice()
    norm=normalize(inv)
    assert norm.currency=='$'
    po=dict(po_number='PO-1001',currency='USD',tax_rate='.08')
    assert normalize_po(norm,po).currency=='USD'
    assert normalize_po(normalize(invoice(reference=None)),po).currency=='$'
    assert normalize_po(normalize(invoice(reference='PO-OTHER')),po).currency=='$'
    assert normalize_po(normalize(invoice('C$')),po).currency=='CAD'
    assert normalize_po(normalize(invoice(evidence={'currency':'CA$ 108'})),po).currency=='CAD'
    assert normalize(invoice(evidence={'currency':'USD and CAD'})).currency=='CONFLICT'


def test_bare_dollar_resolution_is_audited_and_currency_mismatch_is_not_a_variance():
    po=dict(po_number='PO-1001',currency='USD',tax_rate='.08')
    class Balance:
        def remaining(self,po):return Decimal('200')
    checks=amounts(invoice(),normalize(invoice()),po,'explicit',Balance(),Policy.load())
    assert any(c.check_id=='currency_resolution' and c.evidence['source']=='explicit_po' for c in checks)
    mismatch=amounts(invoice('C$'),normalize(invoice('C$')),po,'explicit',Balance(),Policy.load())
    assert mismatch[0].check_id=='currency_consistency' and mismatch[0].proposed.value=='NEEDS_REVIEW'
    assert mismatch[1].check_id=='amount_vs_balance' and mismatch[1].status.value=='SKIP'


@pytest.mark.parametrize('printed,expected',[('20/11/2026',date(2026,11,20)),('11/20/2026',date(2026,11,20)),('11/11/2026',date(2026,11,11)),('03/04/2026',None),('31/02/2026',None),('99/99/2026',None)])
def test_numeric_dates_are_standardized_only_when_unambiguous(printed,expected):
    assert parse_date(printed)==expected


def test_currency_date_and_zero_amount_are_independently_grounded():
    inv=ExtractedInvoice(currency='USD',invoice_date='2026-11-20',adjustments=[dict(description='SHIPPING',amount='0')],
        field_evidence=[dict(path='currency',snippet='US$ 108'),dict(path='invoice_date',snippet='20/11/2026'),
            dict(path='adjustments.0.description',snippet='SHIPPING'),dict(path='adjustments.0.amount',snippet='$ 0')])
    source='Invoice date: 20/11/2026\nSHIPPING $0\nUS$ 108'
    refs=verify_references(inv,[source])
    assert all(r.verification=='GROUNDED' for r in refs)
    ground(inv,source)
    assert inv.field_quality['currency']==Quality.GROUNDED and inv.field_quality['adjustments']==Quality.GROUNDED
    assert not inv.warnings


def test_table_cells_can_be_verified_without_fabricated_aggregate_snippet():
    inv=ExtractedInvoice(line_items=[dict(description='Desk',quantity='1',unit_price='50',amount='50')],
        field_evidence=[dict(path='line_items.0.'+key,snippet='Desk 1 50 50') for key in ('description','quantity','unit_price','amount')],
        evidence={'line_items':'A paraphrase that is absent from the document'})
    ground(inv,'Desk 1 50 50')
    assert inv.field_quality['line_items']==Quality.GROUNDED
    assert 'Grounding failed: field_evidence' not in inv.warnings
    inv.line_items[0].quantity=Decimal('2')
    ground(inv,'Desk 1 50 50')
    assert inv.field_quality['line_items']==Quality.UNVERIFIED


def test_ambiguous_date_and_wrong_currency_stay_unverified():
    inv=ExtractedInvoice(currency='USD',invoice_date='2026-04-03',field_evidence=[dict(path='currency',snippet='CA$ 108'),dict(path='invoice_date',snippet='03/04/2026')])
    assert all(r.verification=='UNVERIFIED' for r in verify_references(inv,['CA$ 108\n03/04/2026']))


def test_explicit_printed_date_order_can_ground_an_otherwise_ambiguous_date():
    inv=ExtractedInvoice(invoice_date='2026-04-03',field_evidence=[dict(path='invoice_date',snippet='03/04/2026')])
    assert verify_references(inv,['Date format: DD/MM/YYYY\n03/04/2026'])[0].verification=='GROUNDED'
    assert verify_references(inv,['Date format: MM/DD/YYYY\n03/04/2026'])[0].verification=='UNVERIFIED'
    assert verify_references(inv,['DD/MM/YYYY or MM/DD/YYYY\n03/04/2026'])[0].verification=='UNVERIFIED'


def test_row_scoped_evidence_is_checked_for_every_present_cell():
    inv=ExtractedInvoice(line_items=[dict(description='Desk',quantity='2',unit_price='50.00',amount='100.00')],
        field_evidence=[dict(path='line_items.0',snippet='Desk 2 $50.00 $100.00',page=1)])
    refs=verify_references(inv,['Desk 2 $50.00 $100.00'])
    assert {r.path for r in refs}=={'line_items.0','line_items.0.description','line_items.0.quantity','line_items.0.unit_price','line_items.0.amount'}
    assert all(r.verification=='GROUNDED' for r in refs)
    ground(inv,'Desk 2 $50.00 $100.00')
    assert inv.field_quality['line_items']==Quality.GROUNDED
    inv.line_items[0].amount=Decimal('99.00')
    refs=verify_references(inv,['Desk 2 $50.00 $100.00'])
    assert next(r for r in refs if r.path=='line_items.0.amount').verification=='UNVERIFIED'
    assert next(r for r in refs if r.path=='line_items.0').verification=='UNVERIFIED'


def test_row_snippet_must_occur_on_its_claimed_page():
    inv=ExtractedInvoice(line_items=[dict(description='Desk',quantity='2',unit_price='50',amount='100')],
        field_evidence=[dict(path='line_items.0',snippet='Desk 2 50 100',page=2)])
    assert all(r.verification=='UNVERIFIED' for r in verify_references(inv,['Desk 2 50 100','Other page']))


def test_null_empty_references_are_not_reported_as_unverified_facts():
    inv=ExtractedInvoice(sender=dict(name='Supplier',address=None),field_evidence=[dict(path='sender.address',snippet=''),dict(path='sender.name',snippet='Supplier')])
    refs=verify_references(inv,['Supplier'])
    assert len(refs)==1 and refs[0].path=='sender.name' and refs[0].verification=='GROUNDED'
