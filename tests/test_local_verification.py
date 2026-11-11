"""Evaluation gates compare labels; no provider or API provenance is simulated."""
import pytest
from invoicedesk.interfaces.local_verify import label_result


def report():
    return dict(extraction=dict(total='108.00',invoice_number='INV-1',currency='US$',line_items=[dict(description='Desk',quantity='1.00',unit_price='100',amount='100.00')]),
        normalized=dict(currency='USD'),decision=dict(outcome='AUTO_APPROVE'))


def labels():
    return dict(sha256='document-hash',fields=dict(total='108',invoice_number='INV-1',currency='USD'),
        line_items=[dict(description='Desk',quantity='1',unit_price='100.00',amount='100')])


def test_label_gate_accepts_decimal_and_currency_standardization():
    score=label_result(labels(),report(),'document-hash')
    assert score['passed'] and score['field_correct']==3 and score['row_complete']==1


def test_label_gate_rejects_wrong_identity_amount_or_extra_rows():
    wrong=report();wrong['extraction']['invoice_number']='INV-2'
    assert not label_result(labels(),wrong,'document-hash')['passed']
    wrong=report();wrong['extraction']['total']='109'
    assert not label_result(labels(),wrong,'document-hash')['passed']
    wrong=report();wrong['extraction']['line_items']*=2
    assert not label_result(labels(),wrong,'document-hash')['passed']


def test_label_gate_rejects_changed_document():
    with pytest.raises(ValueError,match='hash'):
        label_result(labels(),report(),'different-document')
