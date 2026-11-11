from invoicedesk.domain.models import Decision, Comms, Outcome

def draft(decision: Decision, invoice_number: str | None) -> Comms | None:
    if decision.outcome==Outcome.AUTO_APPROVE:return None
    internal=decision.outcome==Outcome.NEEDS_REVIEW or any(x in decision.driving_checks for x in ['vendor_status','vendor_identity','duplicate_exact','po_status'])
    audience='internal' if internal else 'vendor'
    label = 'Document workflow review' if 'workflow_applicability' in decision.driving_checks else f"Invoice {invoice_number or '(number missing)'}"
    return Comms(audience=audience,subject=f"{label}: {decision.outcome.value.replace('_',' ').lower()}",
        body='Hello,\n\n'+ '\n'.join(decision.reasons)+'\n\n'+decision.recommended_action+'\n\nAccounts Payable')
