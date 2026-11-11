"""Deterministic checks; no model calls and no writes."""
import json
import re
from datetime import date
from decimal import Decimal
from invoicedesk.domain.models import CheckResult, CheckStatus, Outcome, Quality
from invoicedesk.domain.normalize import key, normalize

from .matching import similarity as match_similarity
from .validation import blocking_warnings

def check(cid: str, stage: str, status: str, detail: str, proposed: str | None = None, **evidence) -> CheckResult:
    return CheckResult(check_id=cid,stage=stage,status=status,title=cid.replace('_',' ').title(),detail=detail,proposed=proposed,evidence=evidence)

def vendor_key(name: str) -> str:
    return re.sub(r'\b(ltd|inc|llc|co)\b','',' '.join(re.findall(r'\w+',name.lower()))).strip()

def completeness(inv,policy) -> list[CheckResult]:
    if inv.document_type not in {'invoice', 'unknown'}:
        return [check('workflow_applicability','completeness','INFO',f'Document sections were parsed as {inv.document_type}; vendor-invoice approval requires a different workflow.','NEEDS_REVIEW')]
    missing=[k for k in policy.critical_fields if inv.field_quality.get(k)==Quality.MISSING]
    if inv.extraction_path=='failed':
        return [check('completeness','completeness','SKIP','Field absence cannot be confirmed because extraction is incomplete.')]
    unresolved = [k for k in policy.critical_fields if getattr(inv, k) is None and inv.field_quality.get(k) != Quality.MISSING]
    if unresolved and not missing:
        return [check('completeness','completeness','SKIP','Critical fields unresolved after partial extraction: ' + ', '.join(unresolved))]
    return [check('completeness','completeness','FAIL' if missing else 'PASS',
        'Missing critical fields: '+', '.join(missing) if missing else 'All critical fields are present.',
        'HOLD_MISSING_INFO' if missing else None,missing=missing)]

def integrity(inv,findings,policy) -> list[CheckResult]:
    problems=blocking_warnings(inv)
    optional_warnings=[w for w in inv.warnings if w not in problems]
    notes=[]
    invoice_workflow=inv.document_type in {'invoice','unknown'}
    if inv.extraction_path=='failed': problems.append('Extraction incomplete')
    full_total=any(f.get('scope')=='total' and f['passed'] for f in findings)
    printed_total=any(f.get('scope')=='printed_total' and f['passed'] for f in findings)
    if printed_total and not full_total:
        notes.append('Printed subtotal plus adjustments reconcile with the grand total')
        if inv.prices_include_tax and inv.tax_amount is None:
            notes.append('Tax is included in printed prices but not separately itemized')
        if invoice_workflow:
            problems.append('Net/tax basis requires confirmation before invoice payment approval')
    elif not full_total:
        problems.append('Printed total arithmetic could not be independently confirmed')
    required=policy.critical_fields if invoice_workflow else ['sender','document_date','total']
    unverified=[key for key in required if inv.field_quality.get(key)==Quality.UNVERIFIED]
    if unverified and inv.extraction_path!='failed':
        problems.append('Document fields need source confirmation: '+', '.join(unverified))
    if any(not finding['passed'] for finding in findings):
        problems.append('One or more arithmetic checks failed')
    detail='; '.join(problems+notes) if problems or notes else 'Extracted amounts reconcile.'
    results = [check('extraction_integrity','extract','WARN' if problems else 'PASS',detail,
                  'NEEDS_REVIEW' if problems else None,findings=findings)]
    if optional_warnings:
        results.append(check('optional_fields','extract','INFO','Optional scheduling or reference fields need attention; payment checks remain independent.',warnings=optional_warnings))
    return results

def vendor(inv,db,policy):
    if not inv.vendor_name: return None,[check('vendor_identity','vendor','SKIP','Vendor name unavailable.')]
    ranked=sorted([(max(match_similarity(vendor_key(inv.vendor_name),vendor_key(n),policy.matching_adapter) for n in [v['name'],*json.loads(v['aliases_json'])]),v) for v in db.vendors()],key=lambda x:x[0],reverse=True)
    if not ranked: return None,[check('vendor_identity','vendor','FAIL','Vendor master is empty.','REJECT')]
    score,v=ranked[0]; ambiguous=score<policy.vendor_match.accept or (len(ranked)>1 and ranked[1][0]>=policy.vendor_match.accept)
    if score<policy.vendor_match.ambiguous_low:
        return None,[check('vendor_identity','vendor','FAIL','Unknown vendor; route to vendor onboarding.','REJECT',score=score)]
    checks=[check('vendor_identity','vendor','WARN' if ambiguous else 'PASS',f"Vendor match: {v['name']} ({score:.1f}).",'NEEDS_REVIEW' if ambiguous else None,score=score)]
    if ambiguous:return None,checks
    checks.append(check('vendor_status','vendor','FAIL' if v['status']!='approved' else 'PASS',f"Vendor is {v['status']}. {v['notes']}",'REJECT' if v['status']!='approved' else None))
    return v,checks

def duplicates(inv,norm,v,db,policy) -> list[CheckResult]:
    if not v: return [check('duplicate_exact','duplicates','SKIP','No confirmed vendor for duplicate comparison.')]
    exact=[]; near=[]
    for row in db.runs():
        if row['vendor_id']!=v['vendor_id']:continue
        decision=json.loads(row['decision_json'])
        if 'duplicate_exact' in decision['driving_checks']:continue
        old=json.loads(row['normalized_json'])
        if norm.invoice_number_key and norm.invoice_number_key==old['invoice_number_key']:exact.append(row['run_id'])
        if norm.gross_amount is None or not old['gross_amount'] or not norm.invoice_date or not old['invoice_date']:continue
        previous=Decimal(old['gross_amount']); difference=abs(norm.gross_amount-previous)
        pct=difference/abs(previous)*100 if previous else Decimal(0) if not difference else Decimal('Infinity')
        days=abs((norm.invoice_date-date.fromisoformat(old['invoice_date'])).days)
        similarity=match_similarity(norm.description_text,old['description_text'],policy.matching_adapter)/100
        same_po=bool(norm.po_reference_key and norm.po_reference_key==old['po_reference_key'])
        if pct<=policy.duplicates.near_total_pct and days<=policy.duplicates.near_window_days and (same_po or similarity>=policy.duplicates.near_desc_similarity):
            near.append(dict(run_id=row['run_id'],invoice_number=old['invoice_number'],days=days,total_difference_pct=str(pct),description_similarity=similarity,same_po=same_po))
    return [check('duplicate_exact','duplicates','FAIL' if exact else 'PASS','Invoice number already processed.' if exact else 'No exact duplicate found.','REJECT' if exact else None,previous_runs=exact),
        check('duplicate_near','duplicates','WARN' if near else 'PASS','Probable renumbered duplicate; compare previous invoices.' if near else 'No probable duplicate found.','NEEDS_REVIEW' if near else None,candidates=near)]

def resolve_po(inv,norm,v,db,policy):
    if not v:return None,None,[check('po_resolution','po_match','SKIP','PO matching requires a confirmed vendor.')]
    pos=db.pos(); po=None; match_type=None; checks=[]
    if norm.po_reference_key:
        po=next((p for p in pos if key(p['po_number'])==norm.po_reference_key),None);match_type='explicit'
        if not po:return None,None,[check('po_resolution','po_match','WARN','Printed PO reference was not found.','NEEDS_REVIEW')]
    else:
        ranked=[]
        for p in pos:
            if p['vendor_id']!=v['vendor_id'] or p['status']!='open':continue
            remaining=max(Decimal(0),db.remaining(p)); net=norm.net_amount
            if net is None and norm.gross_amount is not None:net=norm.gross_amount/(1+Decimal(p['tax_rate']))
            fit=float(min(Decimal(1),remaining/net)) if net and net>0 else 0
            desc=match_similarity(norm.description_text,p['description'],policy.matching_adapter)/100
            age=max(0,((norm.invoice_date or date.fromisoformat(p['issue_date']))-date.fromisoformat(p['issue_date'])).days)
            recency=max(0,1-age/365)
            w=policy.implied_po.weights; score=w['amount']*fit+w['description']*desc+w['recency']*recency
            ranked.append(dict(po=p,score=score))
        ranked.sort(key=lambda r:r['score'],reverse=True)
        margin=ranked[0]['score']-(ranked[1]['score'] if len(ranked)>1 else 0) if ranked else 0
        if not ranked or ranked[0]['score']<policy.implied_po.min_confidence or margin<policy.implied_po.min_margin:
            return None,None,[check('po_resolution','po_match','WARN','Implied PO match is weak or ambiguous.','NEEDS_REVIEW',candidates=ranked,margin=margin)]
        po=ranked[0]['po'];match_type='implied'
        checks.append(check('po_resolution','po_match','INFO',f"Implied match: {po['po_number']} (score {ranked[0]['score']:.3f}).",candidates=ranked,margin=margin))
    if match_type=='explicit': checks.append(check('po_resolution','po_match','PASS',f"Explicit match: {po['po_number']}."))
    mismatch=po['vendor_id']!=v['vendor_id']
    checks.append(check('po_vendor_consistency','po_match','WARN' if mismatch else 'PASS','PO vendor differs from invoice vendor.' if mismatch else 'Invoice and PO vendor agree.','NEEDS_REVIEW' if mismatch else None))
    checks.append(check('po_status','po_match','FAIL' if po['status']!='open' else 'PASS',f"PO is {po['status']}.",'REJECT' if po['status']!='open' else None))
    return po,match_type,checks

def amounts(inv,norm,po,match_type,db,policy) -> list[CheckResult]:
    if not po:return [check('amount_vs_balance','amounts','SKIP','Amount comparison requires a resolved PO.')]
    from .normalize import normalize_po
    norm = normalize_po(norm, po)
    if norm.net_amount is None:return [check('amount_vs_balance','amounts','SKIP','Net amount is unavailable.')]
    if norm.currency!=po['currency'] or norm.currency!=policy.currency:
        return [check('currency_consistency','amounts','WARN',f'Invoice currency {norm.currency} does not match the PO and approval currency ({po["currency"]}, {policy.currency}); confirm currency without converting amounts.','NEEDS_REVIEW'),
                check('amount_vs_balance','amounts','SKIP','Balance comparison requires a confirmed matching currency.')]
    net=norm.net_amount;remaining=db.remaining(po); over=net-remaining
    if net<=0:return [check('amount_vs_balance','amounts','WARN','Non-positive invoices require manual review.','NEEDS_REVIEW')]
    pct=over/remaining*100 if remaining>0 else Decimal('Infinity')
    outcome=None if over<=0 or pct<=policy.tolerance.auto_pct else 'NEEDS_REVIEW' if pct<=policy.tolerance.review_pct else 'REJECT'
    detail=f"Net {policy.currency} {net:,.2f}; PO remaining {policy.currency} {remaining:,.2f}. "
    detail+=f"Over balance by {policy.currency} {over:,.2f} ({pct:.1f}%)." if over>0 else f"Remaining after approval: {policy.currency} {remaining-net:,.2f}."
    results=[check('amount_vs_balance','amounts','FAIL' if outcome=='REJECT' else 'WARN' if outcome or over>0 else 'PASS',detail,outcome,net=str(net),remaining=str(remaining),over=str(max(over,Decimal(0))),over_pct=str(max(pct,Decimal(0))),net_is_inferred=norm.net_is_inferred)]
    stacked=match_type=='implied' and any(inv.field_quality.get(k)==Quality.UNVERIFIED for k in policy.critical_fields)
    if inv.currency == '$' and normalize(inv).currency == '$' and norm.currency != '$':
        results.append(check('currency_resolution','amounts','INFO',f'Printed $ resolved to {norm.currency} from explicitly referenced {po["po_number"]}; no currency conversion.',source='explicit_po',printed_currency='$',currency=norm.currency))
    results.append(check('stacked_uncertainty','amounts','WARN' if stacked else 'PASS',
        f"Unverified scan plus implied PO; confirm approval against {po['po_number']}." if stacked else 'No stacked extraction and PO uncertainty.', 'NEEDS_REVIEW' if stacked else None))
    return results
