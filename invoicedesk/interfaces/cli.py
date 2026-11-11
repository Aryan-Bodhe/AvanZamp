"""Backend command line: human progress on stderr, final decision on stdout."""
import argparse
import sys
import json
from time import perf_counter
import os
from pathlib import Path
from invoicedesk.config import load_environment
from invoicedesk.infrastructure.telemetry.logger import configure_logging, get_logger
from invoicedesk.infrastructure.sqlite import Db
from invoicedesk.policy import ROOT, Policy
from invoicedesk.infrastructure.extraction.llm import LlmClient
from invoicedesk.application.processing import run_invoice
from invoicedesk.seed import reset, batch


def main(argv: list[str] | None = None) -> int:
    passed = list(argv) if argv is not None else sys.argv[1:]
    if passed and passed[0] == 'pilot':
        from .pilot_cli import main as pilot_main
        pilot_main(passed[1:])
        return 0
    started = perf_counter()
    load_environment()
    parser = argparse.ArgumentParser(description='InvoiceDesk: PDF/image to an explained AP decision')
    parser.add_argument('--db', type=Path, default=None)
    parser.add_argument('--profile', choices=['pilot','demo'], default='pilot')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=os.getenv('LOG_LEVEL', 'INFO'))
    sub = parser.add_subparsers(dest='command', required=True)
    reset_parser = sub.add_parser('reset', help='Replace history and load vendor/PO masters')
    reset_parser.add_argument('--demo', action='store_true')
    run_parser = sub.add_parser('run', help='Process a real PDF, PNG, JPEG or WebP invoice')
    run_parser.add_argument('file', type=Path)
    run_parser.add_argument('--llm-mode', choices=['live', 'cache', 'off'], default=None,
                            help='Default: LLM_MODE environment variable, otherwise off. Cache mode is for fixtures.')
    run_parser.add_argument('--provider', help='LLM_PROVIDER override: openai, anthropic or trusted module:factory')
    run_parser.add_argument('--model', help='Provider-specific model identifier; overrides LLM_MODEL')
    run_parser.add_argument('--refresh-extraction', action='store_true', help='Skip the recorded extraction cache and make a fresh live request')
    run_parser.add_argument('--json', action='store_true', help='Write final result as JSON on stdout')
    run_parser.add_argument('--output', type=Path, help='Save a full extraction/check/decision JSON report')
    sub.add_parser('batch', help='Run the ordered offline golden fixtures against current history')
    args = parser.parse_args(argv)
    configure_logging(level=args.log_level)
    try:
        return _execute(args)
    finally:
        get_logger(__name__).info('App total response time: %.2f ms', (perf_counter()-started)*1000)


def _execute(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    mode = 'demo' if args.profile == 'demo' or args.command == 'batch' or (args.command == 'reset' and args.demo) else 'pilot'
    database_path = args.db or Path(os.getenv('INVOICEDESK_DB', str(ROOT/'data'/('demo.sqlite3' if mode == 'demo' else 'local-preview.sqlite3'))))
    db = Db(database_path, mode=mode)
    try:
        if args.command == 'reset':
            reset(db)
            if args.demo:
                batch(db, demo=True)
            logger.info('Prepared demo loaded.' if args.demo else 'Vendor/PO masters loaded; history is empty.')
        elif args.command == 'batch':
            if not db.vendors():
                reset(db)
            logger.warning('Offline regression run: synthetic extraction fixtures are enabled.')
            for row in batch(db):
                print(f"{row['file']:40} {row['outcome']}")
        else:
            if not db.vendors():
                reset(db)
            llm = LlmClient(args.llm_mode, provider=args.provider, model=args.model, refresh=args.refresh_extraction)
            logger.info('Extraction mode: %s | provider: %s | model: %s', llm.mode, llm.provider_name, llm.model or 'not configured')
            if llm.mode == 'cache':
                logger.warning('Fixture/cache mode: cached synthetic extraction is not proof of real parsing.')
            elif llm.mode == 'off':
                logger.info('No model calls. Unsupported layouts and images will be routed to review.')
            events = list(run_invoice(args.file, db=db, policy=Policy.load(), llm=llm))
            run_id = events[-1].run_id
            row = db.rows('SELECT * FROM runs WHERE run_id=?', (run_id,))[0]
            extraction_event = next(event for event in events if event.stage == 'extract' and event.state == 'completed')
            sections = extraction_event.payload.get('sections', [])
            result = dict(
                sections=sections,
                run_id=run_id, file=row['filename'],
                extraction=json.loads(row['extraction_json']), normalized=json.loads(row['normalized_json']),
                decision=json.loads(row['decision_json']),
                checks=[check.model_dump(mode='json') for event in events for check in event.checks],
                events=[event.model_dump(mode='json') for event in events],
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2))
                logger.info('Full report saved to %s', args.output)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                inv = result['extraction']
                print(f"\nRun: {run_id}\nExtraction: {inv['extraction_path']}")
                if inv['document_type'] not in {'invoice', 'unknown'}:
                    print('Document type: '+inv['document_type'])
                    print('Sender: '+((inv.get('sender') or {}).get('name') or 'unresolved'))
                    print('Document date: '+(inv.get('document_date') or 'unresolved'))
                else:
                    print(f"Vendor: {inv['vendor_name'] or 'unresolved'}")
                    print(f"Invoice: {inv['invoice_number'] or 'unresolved'} | Date: {inv['invoice_date'] or 'unresolved'}")
                print(f"Total: {result['normalized']['currency'] if inv['currency'] else 'currency unconfirmed'} {inv['total'] or 'unresolved'}")
                print('\nDocument sections (parsing status; separate from approval):')
                for section in sections:
                    print(f"  {section['section']}: {section['status']} | arithmetic: {section['arithmetic_status']} | source: {section['verification_status']}")
                    if section['row_validation']:
                        counts = section['row_counts']
                        print(f"    Rows: {counts['PARSED']} parsed, {counts['PARTIAL']} partial, {counts['INVALID']} invalid")
                    if section.get('row_arithmetic_counts'):
                        math = section['row_arithmetic_counts']
                        print(f"    Row arithmetic: {math['PASS']} passed, {math['FAIL']} failed, {math['NOT_CHECKED']} not checked")
                    if section.get('tax_status'):
                        print('    Tax: '+section['tax_status'])
                    for issue in section['issues']:
                        print(f"    {issue['field']}: {issue['message']}")
                print(f"\nDecision: {result['decision']['outcome']}")
                for reason in result['decision']['reasons']:
                    print(f'  - {reason}')
                print('Next action: '+result['decision']['recommended_action'])
        return 0
    except (ValueError, OSError) as exc:
        logger.error('%s', exc)
        return 1
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
