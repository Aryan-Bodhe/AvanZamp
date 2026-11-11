"""Run real invoices as independent layout tests in disposable local workspaces."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from invoicedesk.application.evaluation import score_case
from invoicedesk.config import ROOT
from invoicedesk.db import Db
from invoicedesk.domain.contracts import fingerprint
from invoicedesk.infrastructure.extraction.llm import extraction_schema, provider_settings, recording_matches_model
from invoicedesk.infrastructure.extraction.prompt import EXTRACTION_PROMPT, PREPROCESSING_VERSION
import os
from invoicedesk.interfaces.local_workspace import Workspace

SUFFIXES = {'.pdf','.png','.jpg','.jpeg','.webp'}


def label_result(expected, report, sha256):
    if not expected:
        return None
    if expected.get('sha256') != sha256:
        raise ValueError('Labels do not match the source document hash.')
    # Currency labels describe the backend's standardized code, including explicit PO context.
    scoring_report = dict(report,extraction=dict(report['extraction'],currency=report['normalized']['currency']))
    scored = score_case(dict(expected,safe_to_recommend_approval=True),scoring_report)
    rows_ok = scored['row_count'] is None or (scored['row_complete']==scored['row_count'] and len(report['extraction']['line_items'])==scored['row_count'])
    return dict(scored,passed=scored['field_correct']==scored['field_count'] and rows_ok)


def master_database(path, vendors, pos):
    db = Db(path)
    try:
        with db.conn:
            for table,rows in [('vendors',vendors),('purchase_orders',pos)]:
                for row in rows:
                    db.conn.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
    finally:
        db.close()


def verify_folder(folder: Path, *, output: Path, labels: dict | None=None, batch: dict | None=None):
    folder = folder.resolve()
    files = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUFFIXES)
    if not files:
        raise ValueError('No supported invoice documents were found.')
    if output.exists():
        raise ValueError('Choose a new output directory to preserve earlier verification runs.')
    output.mkdir(parents=True,mode=0o700)
    source = Workspace()
    if batch:
        vendors,pos = batch['master']['vendors'],batch['master']['pos']
        origins = {row['file']:row for row in batch['cases']}
    else:
        with source.db() as db:
            vendors,pos = db.vendors(),db.pos()
        origins = {}
    if not vendors or not pos:
        raise ValueError('Load approved vendors and purchase orders before verifying invoice layouts.')
    master_path = output/'procurement.sqlite3'
    master_database(master_path,vendors,pos)
    master_path.chmod(0o600)
    results = []
    for index,path in enumerate(files,1):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        workspace = Workspace(output/f'{index:02d}-{path.stem}',master_path)
        origin = None
        if batch:
            case = origins.get(path.name)
            if not case or case['sha256']!=digest:
                raise ValueError('Batch manifest does not match '+path.name)
            origin_job = source.job(case['job_id'])
            if origin_job['state'] not in {'completed','errored'}:
                raise ValueError('Wait for the UI worker to finish '+path.name)
            artifacts = source.developer(case['job_id'])['artifacts']
            origin = artifacts.get('provider',{})
            if origin.get('provenance') not in {'api_recording','api_recording_partial'}:
                raise ValueError('No genuine provider recording is available for '+path.name)
            recording_id = origin.get('fingerprint','')
            if len(recording_id)!=64 or any(ch not in '0123456789abcdef' for ch in recording_id):
                raise ValueError('Invalid recording fingerprint.')
            recording = source.root/'extraction-cache'/(recording_id+'.json')
            envelope = json.loads(recording.read_text())
            provider_name = os.getenv('LLM_PROVIDER','openai')
            model = os.getenv('LLM_MODEL','')
            identity = fingerprint(dict(document=digest,preprocessing=PREPROCESSING_VERSION,
                provider=provider_name,model=envelope.get('requested_model',envelope.get('model')),
                prompt=EXTRACTION_PROMPT,schema=extraction_schema(),settings=provider_settings(provider_name)))
            if (envelope.get('provider')!=provider_name or not recording_matches_model(envelope,model)
                    or envelope.get('fingerprint')!=identity or envelope.get('provenance') not in {'api_recording','api_recording_partial'}):
                raise ValueError('The genuine recording is incompatible with current extraction settings; run a fresh verification instead.')
            cache = workspace.root/'extraction-cache';cache.mkdir(mode=0o700)
            shutil.copyfile(recording,cache/recording.name)
            (cache/recording.name).chmod(0o600)
        print('Processing '+path.name+' in an independent workspace…',flush=True)
        job_id = workspace.submit(path.name,path.read_bytes(),'layout-'+digest)['id']
        assert workspace.claim()==job_id
        workspace.process(job_id)
        detail = workspace.detail(job_id)
        report = detail['report']
        artifacts = workspace.developer(job_id)['artifacts']
        provider = artifacts.get('provider',{})
        label_score = label_result((labels or {}).get(path.name),report,digest) if report else None
        error = detail['error']
        if batch and not provider.get('cache_hit'):
            error = dict(code='recording_not_reused',message='The recorded response was incompatible; this case was not a verified replay.')
        ready = bool(report and report['decision']['outcome']=='AUTO_APPROVE' and detail['state']=='completed'
                     and not error and (label_score is None or label_score['passed']))
        if ready:
            # These are disposable case ledgers, never the operator's live ledger.
            workspace.review(job_id,True,detail['revision'],'User-authorized isolated layout verification.',False,'approve-layout-'+digest)
            detail = workspace.detail(job_id)
        case = dict(file=path.name,sha256=digest,job_id=job_id,workspace=str(workspace.root),
            mode='independent',status=detail['status'],passed=ready and detail['status']=='Approved',
            decision=(report or {}).get('decision'),label_score=label_score,error=error,
            provider={k:v for k,v in provider.items() if k!='raw_response'},
            live_origin={k:v for k,v in (origin or {}).items() if k!='raw_response'} if origin else None,
            source_job=origins.get(path.name,{}).get('job_id'),
            report=detail['report'],events=detail['events'])
        results.append(case)
        case_path=workspace.root/'verification.json';case_path.write_text(json.dumps(case,indent=2)+'\n');case_path.chmod(0o600)
        print(path.name+': '+detail['status']+'; labels '+('pass' if label_score and label_score['passed'] else 'not supplied' if label_score is None else 'FAIL'),flush=True)
        summary = dict(mode='independent_layout_verification',cases=len(files),finished=len(results),passed=sum(r['passed'] for r in results),
            main_workspace_ledger_changed=False,release_accepted=False,results=results)
        report_path=output/'report.json';report_path.write_text(json.dumps(summary,indent=2)+'\n');report_path.chmod(0o600)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--labels',type=Path,help='Private, human-labeled expected fields and rows keyed by filename.')
    parser.add_argument('--from-batch',type=Path,help='Replay genuine recordings from a completed UI-worker batch manifest.')
    args=parser.parse_args(argv)
    output=args.output or ROOT/'private/layout-verification'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6])
    labels=json.loads(args.labels.read_text()) if args.labels else None
    batch=json.loads(args.from_batch.read_text()) if args.from_batch else None
    result=verify_folder(args.folder,output=output,labels=labels,batch=batch)
    print(f"{result['passed']}/{result['cases']} independent cases passed. Report: {output/'report.json'}")
    return 0 if result['passed']==result['cases'] else 1


if __name__=='__main__':
    raise SystemExit(main())
