"""Metrics from observed extraction results; never invent scores for missing labels."""
import json
from decimal import Decimal
from invoicedesk.domain.contracts import canonical


def score_case(expected: dict, report: dict) -> dict:
    labels = expected['fields']
    facts = report['extraction']
    # Normalize equivalent decimal strings without accepting approximate floats.
    def equal(name, actual, target):
        if name in {'total', 'subtotal', 'tax_amount', 'quantity', 'unit_price', 'amount'} and actual is not None and target is not None:
            return Decimal(str(actual)) == Decimal(str(target))
        return actual == target
    correct = sum(equal(name, facts.get(name), value) for name, value in labels.items())
    expected_rows = expected.get('line_items')
    rows = facts.get('line_items', [])
    row_matches = None
    if expected_rows is not None:
        row_matches = sum(index < len(rows) and all(equal(key, rows[index].get(key), value) for key, value in row.items())
                          for index, row in enumerate(expected_rows))
    outcome = report['decision']['outcome']
    metrics = report.get('metrics', {})
    return dict(field_correct=correct, field_count=len(labels), row_complete=row_matches,
        row_count=len(expected_rows) if expected_rows is not None else None,
        incorrect_auto_approval=outcome == 'AUTO_APPROVE' and not expected['safe_to_recommend_approval'],
        review=outcome in {'NEEDS_REVIEW','HOLD_MISSING_INFO'},
        latency_ms=metrics.get('processing_ms'), usage=metrics.get('usage'),
        token_cost_usd=metrics.get('token_cost_usd'), outcome=outcome)


def aggregate(cases: list[dict], minimum: int) -> dict:
    fields = sum(c['field_count'] for c in cases)
    rows = sum(c['row_count'] or 0 for c in cases)
    false_approvals = sum(c['incorrect_auto_approval'] for c in cases)
    costs = [c['token_cost_usd'] for c in cases]
    latencies = [c['latency_ms'] for c in cases if c['latency_ms'] is not None]
    return dict(cases=len(cases), field_accuracy=sum(c['field_correct'] for c in cases)/fields if fields else None,
                row_completeness=sum(c['row_complete'] or 0 for c in cases)/rows if rows else None,
                incorrect_auto_approvals=false_approvals, review_rate=sum(c['review'] for c in cases)/len(cases) if cases else None,
                mean_latency_ms=sum(latencies)/len(latencies) if latencies else None,
                total_token_cost_usd=str(sum((Decimal(str(v)) for v in costs), Decimal(0))) if costs and all(v is not None for v in costs) else None,
                extraction_gate_passed=bool(len(cases) >= minimum and fields and not false_approvals),
                release_accepted=False)
