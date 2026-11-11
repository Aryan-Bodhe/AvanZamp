"""Compute field/cell grounding independently of model-written evidence references."""
from datetime import date
from decimal import Decimal
from invoicedesk.domain.contracts import EvidenceReference
from invoicedesk.domain.models import FieldEvidence
from .grounding import compact, amount_supported, date_supported
from invoicedesk.domain.normalize import currency_supported


def verify_references(invoice, pages: list[str]) -> tuple[EvidenceReference, ...]:
    root = invoice.model_dump()
    references = []
    entries = list(invoice.field_evidence)
    supplied = {entry.path for entry in entries}
    # Scalar snippets are evidence even if the model omitted a duplicate path entry.
    for path, snippet in invoice.evidence.items():
        value = root.get(path)
        if path not in supplied and snippet.strip() and isinstance(value,(str,Decimal,date,bool)):
            entries.append(FieldEvidence(path=path,snippet=snippet))

    def supported(path, value, snippet, source):
        if isinstance(value, Decimal):
            return amount_supported(value, snippet)
        if isinstance(value, date):
            return date_supported(value, snippet, source=source)
        if path == 'currency' and isinstance(value, str):
            return currency_supported(value, snippet)
        if isinstance(value, str):
            return bool(value.strip()) and compact(value) in compact(snippet)
        return False

    def leaves(value, path):
        if isinstance(value, dict):
            return [(p,v) for key,part in value.items() for p,v in leaves(part,path+'.'+key)]
        if isinstance(value, list):
            return [(p,v) for index,part in enumerate(value) for p,v in leaves(part,path+'.'+str(index))]
        return [(path,value)] if value is not None else []

    for entry in entries:
        value = root
        resolved = True
        try:
            for part in entry.path.split('.'):
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, ValueError, TypeError):
            value, resolved = None, False
        # There is no claimed fact to verify for a known null with an empty snippet.
        if resolved and value is None and not entry.snippet.strip():
            continue
        source = '\n'.join(pages)
        if entry.page is not None:
            source = pages[entry.page-1] if entry.page <= len(pages) else ''
        found = bool(source.strip() and entry.snippet.strip() and compact(entry.snippet) in compact(source))
        cells = leaves(value,entry.path) if isinstance(value,(dict,list)) else [(entry.path,value)]
        verified = []
        for path,cell in cells:
            status = 'GROUNDED' if found and supported(path,cell,entry.snippet,source) else 'UNVERIFIED'
            verified.append(EvidenceReference(path=path,snippet=entry.snippet,page=entry.page,verification=status))
        if isinstance(value,(dict,list)):
            # A row/party reference supports each leaf only after independent checking.
            references.append(EvidenceReference(path=entry.path,snippet=entry.snippet,page=entry.page,
                verification='GROUNDED' if verified and all(r.verification=='GROUNDED' for r in verified) else 'UNVERIFIED'))
        references.extend(verified)
    return tuple(references)
