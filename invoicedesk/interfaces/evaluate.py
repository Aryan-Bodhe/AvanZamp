"""Opt-in real-model holdout runner. Default validates labels without making calls."""
import argparse
import csv
import json
from pathlib import Path
import time
from decimal import Decimal
from invoicedesk.application.evaluation import score_case, aggregate
from invoicedesk.application.review import report_from
from invoicedesk.domain.contracts import ProcurementSnapshot, canonical, fingerprint
from invoicedesk.domain.evaluation import evaluate
from invoicedesk.extract.llm import LlmClient
from invoicedesk.extract.router import extract_document
from invoicedesk.infrastructure.extraction.evidence import verify_references
from invoicedesk.infrastructure.extraction.text import read_document_text
from invoicedesk.infrastructure.preflight import validate_pilot_document
from invoicedesk.policy import Policy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--vendors',type=Path,required=True)
    parser.add_argument('--pos',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true',help='Opt in to billable extraction requests; pins must match deployment configuration')
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--input-per-million',type=Decimal)
    parser.add_argument('--output-per-million',type=Decimal)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    cases = manifest['cases']
    expected_tags = {'unfamiliar_layout', 'scan', 'bundled_items', 'tax_inclusive', 'adjustments', 'missing_fields', 'confusing_references'}
    found_tags = set()
    for case in cases:
        if not isinstance(case.get('safe_to_recommend_approval'),bool) or not case.get('fields') or not case.get('tags'):
            raise ValueError('Each case requires human fact labels, tags, and an approval-safety label.')
        found_tags.update(case['tags'])
        candidate = (args.manifest.parent/case['file']).resolve()
        if not candidate.is_relative_to(args.manifest.parent.resolve()):
            raise ValueError('Holdout documents must stay within the private dataset directory.')
        if not candidate.is_file():
            raise ValueError('A labeled holdout document is missing.')
    if args.live and (len(cases) < max(1, manifest.get('release_min_cases', 30)) or not expected_tags <= found_tags):
        raise ValueError('Release evaluation requires the configured minimum cases and every required edge-case category.')
    if not args.live:
        result = {'mode':'labels-only','cases':len(cases),'dataset_version':manifest['version'],'measured':False,'release_accepted':False}
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.output.write_text(json.dumps(result, indent=2))
        args.output.chmod(0o600)
        print(json.dumps(result))
        return
    import os
    from invoicedesk.infrastructure.preflight import require_production_dependencies
    require_production_dependencies()
    from invoicedesk.infrastructure.preflight import require_evaluated_model
    require_evaluated_model(mode='live')
    if not os.getenv('LLM_MODEL') or os.getenv('LLM_MODEL') != os.getenv('INVOICEDESK_EVALUATED_MODEL'):
        raise ValueError('Pin the exact candidate model in LLM_MODEL and INVOICEDESK_EVALUATED_MODEL.')
    policy = Policy.load()
    with args.vendors.open() as source:
        vendors = list(csv.DictReader(source))
    with args.pos.open() as source:
        pos = list(csv.DictReader(source))
    snapshot = ProcurementSnapshot(1, canonical(vendors),canonical(pos),'[]',())
    results = []
    for case in cases:
        path = args.manifest.parent/case['file']
        validate_pilot_document(path)
        # Held-out measurements use fresh calls. Artifacts remain private and retain API provenance.
        client = LlmClient('live',cache_dir=args.output.parent/'recordings',refresh=True)
        started = time.monotonic()
        result = extract_document(path,policy,client)
        inv, findings = result.invoice, result.findings
        try:
            pages = read_document_text(path).pages if path.read_bytes().startswith(b'%PDF-') else []
        except Exception:
            pages = []
        refs = verify_references(inv,pages)
        case_snapshot = snapshot
        if case.get('snapshot'):
            labeled = case['snapshot']
            case_snapshot = ProcurementSnapshot(labeled.get('revision', 1), canonical(labeled.get('vendors', vendors)),
                canonical(labeled.get('pos', pos)), canonical(labeled.get('runs', [])),
                tuple(sorted((po, str(amount)) for po, amount in labeled.get('balances', {}).items())))
        rec = evaluate(inv,findings,case_snapshot,policy,source_evidence=refs)
        report = report_from(rec,inv,findings)
        usage = result.token_usage
        cost = None
        # Cached-token/reasoning pricing needs a separately reviewed billing export; do not silently misprice it.
        if args.input_per_million is not None and args.output_per_million is not None and not result.usage.get('input_tokens_details'):
            if usage.get('input_tokens') is not None and usage.get('output_tokens') is not None:
                cost = str((Decimal(usage['input_tokens'])*args.input_per_million+Decimal(usage['output_tokens'])*args.output_per_million)/1_000_000)
        report['metrics'] = dict(processing_ms=int((time.monotonic()-started)*1000),usage=usage,token_cost_usd=cost)
        results.append(dict(case_id=case['id'], tags=case['tags'], score=score_case(case,report),report=report,
                            provenance=result.provenance,model=result.model,extraction_fingerprint=result.fingerprint))
    output = dict(dataset_version=manifest['version'],manifest_sha256=fingerprint(manifest),
                  summary=aggregate([row['score'] for row in results],max(1,manifest.get('release_min_cases',30))),results=results,
                  policy=policy.model_dump(mode='json'))
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        if baseline['manifest_sha256'] != output['manifest_sha256']:
            raise ValueError('Baseline and candidate must use the identical held-out set.')
        output['baseline_summary'] = baseline['summary']
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    args.output.write_text(json.dumps(output,indent=2))
    args.output.chmod(0o600)
    print(json.dumps(output['summary']))


if __name__ == '__main__':
    main()
