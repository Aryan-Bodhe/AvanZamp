import csv
import json
from invoicedesk.db import Db
from invoicedesk.policy import ROOT, Policy
from invoicedesk.extract.llm import LlmClient

def reset(db: Db) -> None:
    with db.conn:
        for table in ['review_commands','pilot_ledger','run_context','review_audit','events','runs','purchase_orders','vendors']:db.conn.execute(f'DELETE FROM {table}')
        for table in ['vendors','purchase_orders']:
            with (ROOT/'data'/f'{table}.csv').open() as src:
                for row in csv.DictReader(src):
                    keys=list(row);db.conn.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",tuple(row.values()))

def batch(db: Db, *, demo: bool=False) -> list[dict]:
    if db.mode != 'demo':
        raise ValueError('Golden batching requires an explicitly selected demo database.')
    from invoicedesk.pipeline import run_invoice
    oracle=json.loads((ROOT/'data/golden.json').read_text()); policy=Policy.load()
    if demo:
        oracle=[e for e in oracle if e['file'][:2] in {'02','03','04','05','06','07'}]
    results=[]
    for entry in oracle:
        final=list(run_invoice(ROOT/'data/invoices'/entry['file'],db=db,policy=policy,llm=LlmClient('cache')))[-1]
        results.append(dict(file=entry['file'],outcome=final.payload['decision']['outcome']))
    return results
