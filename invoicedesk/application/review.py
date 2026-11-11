"""Revision-aware review orchestration shared by CLI and HTTP interfaces."""
from decimal import Decimal
from invoicedesk.domain.approval import ApprovalBlocked, Conflict, authorize
from invoicedesk.domain.contracts import canonical, fingerprint, EvidenceReference, DocumentFacts, SectionValidation
from invoicedesk.domain.evaluation import evaluate
from invoicedesk.domain.models import ExtractedInvoice, Quality
from invoicedesk.domain.reconciliation import reconcile
from invoicedesk.domain.validation import FACT_FIELDS, parse_response


def report_from(rec, invoice: ExtractedInvoice, findings: list, sections: list | None = None) -> dict:
    import json
    return dict(extraction=invoice.model_dump(mode='json'), normalized=json.loads(rec.interpretation.normalized_json),
                interpretation=rec.interpretation.model_dump(mode='json'), context=rec.context.model_dump(mode='json'),
                decision=rec.decision.model_dump(mode='json'), checks=[c.model_dump(mode='json') for c in rec.checks],
                vendor_id=rec.vendor_id, po_number=rec.po_number, match_type=rec.match_type,
                findings=findings, sections=sections or [])


class ReviewService:
    def __init__(self, repository):
        self.repo = repository

    def act(self, job_id: str, *, actor: str, roles: set[str], key: str, revision: int,
            approve: bool, reason: str, confirmed_source: bool = False) -> dict:
        payload = dict(action='approve' if approve else 'reject', job_id=job_id, revision=revision,
                       reason=reason, confirmed_source=confirmed_source)
        def action(c, company):
            job = self.repo.job(c, job_id, actor, roles, review=True)
            if job['revision'] != revision or job['state'] != 'completed' or job['review_state'] != 'pending':
                raise Conflict('Report changed or is no longer pending review.')
            original = self.repo.report_at(c, job)
            if approve:
                policy = self.repo.policy(c)
                snapshot = self.repo.snapshot(c, exclude=job_id)
                invoice = ExtractedInvoice.model_validate(original['extraction'])
                findings = reconcile(invoice, policy.extraction.reconcile_abs_tolerance)
                current = evaluate(invoice, findings, snapshot, policy, revision,
                    source_evidence=tuple(EvidenceReference.model_validate(ref) for ref in original.get('source_evidence', [])))
                amount = authorize(current, policy, reason, confirmed_source)
                if amount >= Decimal('1e18') or amount != amount.quantize(Decimal('0.000001')):
                    raise ApprovalBlocked('Approval amounts support at most six decimal places.')
                report = report_from(current, invoice, findings, original['sections'])
                if self.repo.approved_duplicate(c, current.vendor_id, report['normalized']['invoice_number_key']):
                    raise ApprovalBlocked('This vendor invoice already has a ledger commitment.')
                self.repo.artifact(c, job_id, revision, 'approval_recheck', report)
                self.repo.post_ledger(c, job, report, amount, actor, reason)
            elif not reason.strip():
                raise ValueError('A rejection reason is required.')
            state = 'approved' if approve else 'rejected'
            self.repo.update_job(c, job_id, review_state=state)
            self.repo.audit(c, actor, state, job_id, dict(payload, report_sha256=fingerprint(original)))
            return dict(job_id=job_id, revision=revision, review_state=state)
        # Authorization is checked before looking up an idempotent response as well.
        if not roles & {'reviewer', 'admin'}:
            raise PermissionError('Reviewer role required.')
        return self.repo.command(actor, key, payload, action)

    def correct(self, job_id: str, *, actor: str, roles: set[str], key: str,
                revision: int, changes: dict, reason: str) -> dict:
        if not roles & {'reviewer', 'admin'}:
            raise PermissionError('Reviewer role required.')
        if not reason.strip() or not changes or not set(changes) <= FACT_FIELDS - {'evidence'}:
            raise ValueError('Corrections require fact fields and a recorded reason.')
        payload = dict(action='correct', job_id=job_id, revision=revision, changes=changes, reason=reason)
        def action(c, company):
            job = self.repo.job(c, job_id, actor, roles, review=True)
            if job['revision'] != revision or job['state'] != 'completed' or job['review_state'] == 'approved':
                raise Conflict('Report changed or an approval already committed it.')
            previous = self.repo.report_at(c, job)
            old = ExtractedInvoice.model_validate(previous['extraction'])
            raw = {name: value for name, value in previous['extraction'].items() if name in FACT_FIELDS}
            raw.update(changes)
            parsed = parse_response(raw)
            if parsed.issues:
                raise ValueError('Correction contains unresolved or invalid facts.')
            inv = parsed.invoice
            # A correction resolves only the issues attached to the fields it changes.
            for warning in old.warnings:
                resolved = any((warning.endswith(': '+name) or warning.startswith('Partial extraction: '+name+' ') or
                                warning.startswith('Partial extraction: '+name+'.')) for name in changes)
                resolved = resolved or ('Currency was not explicitly identified' in warning and 'currency' in changes)
                if not resolved:
                    inv.warnings.append(warning)
            inv.extraction_path = old.extraction_path
            inv.field_quality = {name: Quality.UNVERIFIED if name in changes else quality for name, quality in old.field_quality.items()}
            for name in changes:
                inv.field_quality[name] = Quality.UNVERIFIED
            findings = reconcile(inv, self.repo.policy(c).extraction.reconcile_abs_tolerance)
            new_revision = revision + 1
            current = evaluate(inv, findings, self.repo.snapshot(c, exclude=job_id), self.repo.policy(c), new_revision)
            from invoicedesk.infrastructure.extraction.sections import section_report
            sections = section_report(inv, parsed.issues, parsed.provided_fields, findings, parsed.provided_paths)
            report = report_from(current, inv, findings, sections)
            doc = self.repo.document(c, job)
            facts = DocumentFacts(document_sha256=doc['sha256'], revision=new_revision, parent_revision=revision,
                raw_response_json=canonical(raw), provenance='reviewer_correction', extractor_fingerprint=fingerprint(payload),
                evidence=tuple(EvidenceReference(path=e.path, snippet=e.snippet, page=e.page) for e in inv.field_evidence))
            self.repo.artifact(c, job_id, new_revision, 'facts', facts.model_dump(mode='json'))
            self.repo.artifact(c, job_id, new_revision, 'sections', {'sections': [SectionValidation(
                section=section['section'], status=section['status'], arithmetic_status=section['arithmetic_status'],
                verification_status=section['verification_status'], report_json=canonical(section)).model_dump(mode='json') for section in sections]})
            self.repo.artifact(c, job_id, new_revision, 'correction', dict(payload, actor=actor))
            self.repo.artifact(c, job_id, new_revision, 'report', report)
            self.repo.update_job(c, job_id, revision=new_revision, review_state='pending')
            self.repo.audit(c, actor, 'corrected', job_id, dict(payload, previous_sha256=fingerprint(previous)))
            return dict(job_id=job_id, revision=new_revision, review_state='pending')
        return self.repo.command(actor, key, payload, action)
