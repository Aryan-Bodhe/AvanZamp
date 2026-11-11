"""Report parsing coverage, source verification and arithmetic as separate results."""
from typing import Any
from invoicedesk.domain.models import ExtractedInvoice, Quality
from invoicedesk.domain.normalize import currency_code

SECTIONS = {
    'sender': ('sender', 'vendor_name'),
    'recipient': ('recipient',),
    'metadata': ('document_type', 'document_date', 'invoice_number', 'invoice_date', 'due_date', 'po_reference', 'reference_text'),
    'line_items': ('line_items',),
    'totals': ('currency', 'subtotal', 'tax_amount', 'total', 'prices_include_tax', 'adjustments'),
    'evidence': ('evidence',),
}
INVOICE_ONLY = {'vendor_name', 'invoice_number', 'invoice_date', 'due_date'}


def _present(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_present(item) for item in value.values())
    if isinstance(value, list):
        return any(_present(item) for item in value)
    return value is not None and value != ''


def section_report(invoice: ExtractedInvoice, issues: list[dict] | None = None,
                   provided_fields: set[str] | None = None, findings: list[dict] | None = None,
                   provided_paths: set[str] | None = None, *, source_evidence=()) -> list[dict[str, Any]]:
    issues = issues or []
    provided_fields = provided_fields or set()
    findings = findings or []
    raw = invoice.model_dump(mode='json')
    grounded_paths = {ref.path for ref in source_evidence if ref.verification in {'VERIFIED', 'GROUNDED'}}
    non_invoice = invoice.document_type not in {'invoice', 'unknown'}

    def status(path: str, value: Any, quality: Quality | None = None) -> str:
        if non_invoice and path in INVOICE_ONLY:
            return 'NOT_APPLICABLE'
        rejected = [issue for issue in issues if issue['field'] == path]
        if rejected:
            return 'UNAVAILABLE' if all(i['type'] == 'not_returned' for i in rejected) else 'INVALID'
        if path == 'document_type' and value == 'unknown':
            return 'UNAVAILABLE'
        if _present(value):
            return 'PARSED'
        if provided_paths is not None:
            known = path in provided_paths
        else:
            known = path.split('.')[0] in provided_fields or quality == Quality.MISSING
        return 'MISSING' if known else 'UNAVAILABLE'

    reports = []
    for name, keys in SECTIONS.items():
        relevant = [issue for issue in issues if issue['field'].split('.')[0] in keys]
        fields = {}
        for key in keys:
            quality = invoice.field_quality.get(key)
            fields[key] = {'value': raw[key], 'status': status(key, raw[key], quality),
                           'quality': quality.value if quality else None}
            if key == 'currency':
                fields[key]['normalized_value'] = currency_code(invoice.currency)
        recovered = [key for key in keys if fields[key]['status'] == 'PARSED']
        has_facts = bool(recovered)
        section_status = (
            ('PARTIAL' if has_facts else 'UNAVAILABLE' if all(i['type'] == 'not_returned' for i in relevant) else 'INVALID') if relevant else
            'PARSED' if has_facts else
            'MISSING' if any(f['status'] == 'MISSING' for f in fields.values()) else 'UNAVAILABLE'
        )
        party_validation = {}
        for key in ('sender', 'recipient'):
            if key in keys and isinstance(raw[key], dict):
                party_validation[key] = {part: {'value': value, 'status': status(f'{key}.{part}', value)}
                                         for part, value in raw[key].items()}

        checks = [check for check in findings if
                  (name == 'line_items' and check['scope'] in {'line', 'subtotal'}) or
                  (name == 'totals' and check['scope'] in {'total', 'printed_total'})]
        rows = raw['line_items'] if name == 'line_items' else None
        row_validation = []
        for index, row in enumerate(rows or []):
            row_issues = [issue for issue in relevant if issue['field'] == f'line_items.{index}' or issue['field'].startswith(f'line_items.{index}.')]
            row_checks = [check for check in checks if check['scope'] == 'line' and check.get('row_index') == index]
            missing_math = [key for key in ('quantity', 'unit_price', 'amount') if row[key] is None]
            row_validation.append({
                'index': index, 'row_number': index+1,
                'status': ('PARTIAL' if _present(row) else 'INVALID') if row_issues else 'PARSED',
                'issues': row_issues,
                'fields': {key: {'value': value, 'status': status(f'line_items.{index}.{key}', value)} for key, value in row.items()},
                'verification_status': ('GROUNDED' if all(f'line_items.{index}.{key}' in grounded_paths for key, value in row.items() if value is not None) else 'UNVERIFIED'),
                'arithmetic': row_checks,
                'arithmetic_status': 'FAIL' if any(not c['passed'] for c in row_checks) else 'PASS' if row_checks else 'NOT_CHECKED',
                'arithmetic_note': 'Quantity × unit price cannot be checked: ' + ', '.join(missing_math) + ' unavailable.' if missing_math else '',
            })
        row_math = {state: sum(row['arithmetic_status'] == state for row in row_validation)
                    for state in ('PASS', 'FAIL', 'NOT_CHECKED')}
        subtotal_checks = [c for c in checks if c['scope'] == 'subtotal']
        incomplete_math = (bool(relevant) or (name == 'line_items' and row_math['NOT_CHECKED'] > 0)
                           or (name == 'totals' and not any(c['scope'] == 'total' for c in checks)
                               and invoice.prices_include_tax is not True))
        arithmetic_status = ('FAIL' if any(not c['passed'] for c in checks) else
                             'PARTIAL' if checks and incomplete_math else 'PASS' if checks else 'NOT_CHECKED')
        qualities = [invoice.field_quality.get(key) for key in recovered]
        if not has_facts:
            verification = 'NOT_CHECKED'
        elif name == 'evidence' and source_evidence and all(ref.verification in {'VERIFIED','GROUNDED'} for ref in source_evidence):
            verification = 'GROUNDED'
        elif qualities and all(q == Quality.VERIFIED for q in qualities):
            verification = 'VERIFIED'
        elif qualities and all(q in {Quality.VERIFIED, Quality.GROUNDED} for q in qualities):
            verification = 'GROUNDED'
        else:
            verification = 'UNVERIFIED'
        report = {
            'section': name, 'status': section_status, 'fields': fields, 'issues': relevant,
            'verification_status': verification,
            'verification_note': 'Model-reported values/snippets have no independent text/OCR verification.' if verification == 'UNVERIFIED' else '',
            'party_validation': party_validation, 'rows': rows, 'row_validation': row_validation,
            'row_counts': {state: sum(row['status'] == state for row in row_validation) for state in ('PARSED', 'PARTIAL', 'INVALID')},
            'arithmetic': checks, 'arithmetic_status': arithmetic_status,
        }
        if name == 'line_items':
            report['row_arithmetic_counts'] = row_math
            report['subtotal_arithmetic_status'] = 'FAIL' if any(not c['passed'] for c in subtotal_checks) else 'PASS' if subtotal_checks else 'NOT_CHECKED'
        if name == 'totals':
            report['tax_status'] = 'ITEMIZED' if invoice.tax_amount is not None else 'INCLUDED_NOT_ITEMIZED' if invoice.prices_include_tax else 'NOT_PROVIDED'
            report['net_tax_basis_status'] = 'NOT_APPLICABLE' if non_invoice else 'REQUIRES_CONFIRMATION' if invoice.tax_amount is None else 'ITEMIZED'
        reports.append(report)
    return reports
