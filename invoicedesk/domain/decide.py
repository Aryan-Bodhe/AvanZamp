from invoicedesk.domain.models import Decision, PRECEDENCE, Outcome, CheckResult

def decide(checks: list[CheckResult], po: dict | None) -> Decision:
    outcome=next((o for o in PRECEDENCE if any(c.proposed==o for c in checks)),Outcome.AUTO_APPROVE)
    driving=[c for c in checks if c.proposed==outcome]
    reasons=[c.detail for c in driving]+[c.detail for c in checks if c not in driving and c.status in {'WARN','INFO'}]
    actions={Outcome.AUTO_APPROVE:'Recommend approval; an authorized reviewer must confirm before ledger posting.',Outcome.HOLD_MISSING_INFO:'Request a corrected invoice with the missing fields.',
        Outcome.REJECT:'Reject this invoice and resolve the flagged checks.',Outcome.NEEDS_REVIEW:'Review the evidence before authorizing payment.'}
    ids={c.check_id for c in driving}; action=actions[outcome]
    if 'vendor_status' in ids:action='Escalate to procurement: vendor is blocked.'
    elif 'workflow_applicability' in ids:action='Route the parsed document to the appropriate project-budget or advance-request review; vendor-invoice payment is not authorized.'
    elif 'duplicate_exact' in ids:action='Do not pay again; compare the original submission.'
    elif 'duplicate_near' in ids:action='Compare the prior invoice and confirm whether this is a resubmission.'
    elif 'stacked_uncertainty' in ids and po:action=f"Confirm the scan and approve against {po['po_number']} if correct."
    elif 'currency_consistency' in ids:action='Confirm the printed currency against the purchase order; no FX conversion is performed.'
    elif 'source_grounding' in ids or 'extraction_integrity' in ids:action='Check the extracted values against the source document before approving.'
    elif 'amount_vs_balance' in ids:action='Review the variance with procurement.' if outcome==Outcome.NEEDS_REVIEW else 'Dispute the overbilling with the vendor.'
    summary = 'Document sections parsed; vendor-invoice approval is not applicable.' if 'workflow_applicability' in ids else 'Invoice '+outcome.value.lower().replace('_',' ')+'.'
    return Decision(outcome=outcome,summary=summary,reasons=reasons or ['All applicable checks passed.'],driving_checks=[c.check_id for c in driving],recommended_action=action)
