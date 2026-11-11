"""Application-service tests with a deliberately in-memory persistence port, no SQL emulation."""
import json
from decimal import Decimal
import pytest
from invoicedesk.application.review import ReviewService, report_from
from invoicedesk.domain.approval import ApprovalBlocked, Conflict
from invoicedesk.domain.contracts import ProcurementSnapshot, canonical, fingerprint
from invoicedesk.domain.evaluation import evaluate
from invoicedesk.domain.models import ExtractedInvoice
from invoicedesk.domain.reconciliation import reconcile
from invoicedesk.policy import Policy


class ReviewMemory:
    def __init__(self):
        self.p = Policy.load()
        self.current = dict(id='job',revision=1,state='completed',review_state='pending')
        self.artifacts = {}
        self.entries = []
        self.commands = {}
        self.audits = []
        inv = ExtractedInvoice(document_type='invoice',vendor_name='Example Vendor',invoice_number='ORIGINAL',
            invoice_date='2026-01-01',currency='USD',po_reference='PO-123',subtotal='100',tax_amount='0',total='100')
        findings = reconcile(inv,Decimal('.02'))
        rec = evaluate(inv,findings,self.snapshot(None),self.p)
        self.artifacts[(1,'report')] = report_from(rec,inv,findings)
        self.original = canonical(self.artifacts[(1,'report')])

    def snapshot(self,c,exclude=None):
        return ProcurementSnapshot(1,canonical([dict(vendor_id='V1',name='Example Vendor',aliases_json='[]',status='approved',notes='')]),
            canonical([dict(po_number='PO-123',vendor_id='V1',description='Services',net_amount='1000',tax_rate='0',
                currency='USD',status='open',issue_date='2026-01-01')]),'[]',(('PO-123',str(sum(self.entries,Decimal(0)))),))
    def policy(self,c): return self.p
    def job(self,c,job_id,actor,roles,review=False):
        if job_id != 'job': raise LookupError()
        if review and not roles & {'reviewer','admin'}: raise PermissionError()
        return dict(self.current)
    def report_at(self,c,job): return json.loads(canonical(self.artifacts[(job['revision'],'report')]))
    def artifact(self,c,job_id,revision,kind,data):
        assert (revision,kind) not in self.artifacts
        self.artifacts[(revision,kind)] = data
    def document(self,c,job): return {'sha256':'0'*64}
    def update_job(self,c,job_id,**values): self.current.update(values)
    def audit(self,c,*args): self.audits.append(args)
    def approved_duplicate(self,c,*args): return bool(self.entries)
    def post_ledger(self,c,job,report,amount,actor,reason): self.entries.append(amount)
    def command(self,actor,key,payload,action):
        if key in self.commands:
            digest,result = self.commands[key]
            if digest != fingerprint(payload): raise Conflict('Key reused.')
            return result
        result = action(None,{'revision':1})
        self.commands[key] = (fingerprint(payload),result)
        return result


def test_correction_keeps_original_facts_and_requires_new_review():
    repo = ReviewMemory()
    service = ReviewService(repo)
    result = service.correct('job',actor='reviewer',roles={'reviewer'},key='fix',revision=1,
        changes={'invoice_number':'CORRECTED'},reason='Printed number checked')
    assert result['revision'] == 2
    assert canonical(repo.artifacts[(1,'report')]) == repo.original
    assert repo.artifacts[(2,'facts')]['provenance'] == 'reviewer_correction'
    assert repo.artifacts[(2,'facts')]['parent_revision'] == 1
    assert repo.artifacts[(2,'report')]['extraction']['invoice_number'] == 'CORRECTED'
    with pytest.raises(Conflict):
        service.act('job',actor='reviewer',roles={'reviewer'},key='stale',revision=1,approve=True,reason='')
    with pytest.raises(ApprovalBlocked):
        service.act('job',actor='reviewer',roles={'reviewer'},key='no-source-confirmation',revision=2,approve=True,reason='Checked')
    service.act('job',actor='reviewer',roles={'reviewer'},key='approve',revision=2,approve=True,reason='Checked source',confirmed_source=True)
    assert repo.entries == [Decimal('100')]
    with pytest.raises(Conflict):
        service.correct('job',actor='reviewer',roles={'reviewer'},key='later-fix',revision=2,
            changes={'total':'200'},reason='Cannot mutate committed approval')


def test_review_permissions_are_checked_before_idempotent_result():
    repo = ReviewMemory()
    service = ReviewService(repo)
    service.act('job',actor='reviewer',roles={'reviewer'},key='approve',revision=1,approve=True,reason='Checked source',confirmed_source=True)
    with pytest.raises(PermissionError):
        service.act('job',actor='reviewer',roles={'uploader'},key='approve',revision=1,approve=True,reason='Checked source',confirmed_source=True)
    service.act('job',actor='reviewer',roles={'reviewer'},key='approve',revision=1,approve=True,reason='Checked source',confirmed_source=True)
    assert len(repo.entries) == 1


def test_unrelated_correction_does_not_erase_partial_failure():
    repo = ReviewMemory()
    repo.artifacts[(1,'report')]['extraction']['warnings'] = ['Partial extraction: line_items.0.amount (invalid)']
    service = ReviewService(repo)
    service.correct('job',actor='reviewer',roles={'reviewer'},key='fix',revision=1,
        changes={'invoice_number':'CORRECTED'},reason='Printed number checked')
    with pytest.raises(ApprovalBlocked,match='extraction issues'):
        service.act('job',actor='reviewer',roles={'reviewer'},key='approve',revision=2,approve=True,reason='Checked source',confirmed_source=True)
    assert not repo.entries
