"""Deployment-only commands. Use a trusted operator shell with database credentials."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from invoicedesk.domain.master import Vendor, PurchaseOrder
from invoicedesk.domain.policy import Policy
from invoicedesk.infrastructure.storage import LocalStorage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('initialize')
    init.add_argument('--vendors', type=Path, required=True)
    init.add_argument('--pos', type=Path, required=True)
    init.add_argument('--policy', type=Path, required=True)
    archive = sub.add_parser('archive-prototype')
    archive.add_argument('--source', type=Path, required=True)
    archive.add_argument('--destination', type=Path, required=True)
    retention = sub.add_parser('retention')
    retention.add_argument('--apply', action='store_true', help='Default is a count-only dry run.')
    sub.add_parser('worker-health')
    args = parser.parse_args(argv)
    if args.command == 'archive-prototype':
        if args.source.resolve() == args.destination.resolve() or args.destination.exists():
            raise ValueError('Choose a new private archive directory.')
        args.destination.mkdir(mode=0o700, parents=True)
        for path in args.source.glob('*.sqlite3'):
            # SQLite backup includes committed WAL contents; a plain file copy would not.
            with sqlite3.connect(path) as source, sqlite3.connect(args.destination/path.name) as destination:
                source.backup(destination)
            (args.destination/path.name).chmod(0o600)
        for dirname in ('extraction-cache',):
            if (args.source/dirname).exists():
                shutil.copytree(args.source/dirname, args.destination/dirname)
        print('Prototype copied to private archive; originals preserved. Pilot imports no prototype rows.')
        return
    if args.command == 'worker-health':
        heartbeat = Path('/tmp/invoicedesk-worker-heartbeat')
        if not heartbeat.exists() or time.time()-heartbeat.stat().st_mtime > 60:
            raise SystemExit(1)
        return
    from invoicedesk.infrastructure.repository import Repository
    repo = Repository(os.environ['DATABASE_URL'])
    if args.command == 'initialize':
        import yaml
        policy = Policy.model_validate(yaml.safe_load(args.policy.read_text()))
        if policy.matching_adapter != 'rapidfuzz':
            raise ValueError('Production initialization requires rapidfuzz.')
        with args.vendors.open() as source:
            vendors = [Vendor.model_validate(row).model_dump(mode='json') for row in csv.DictReader(source)]
        with args.pos.open() as source:
            pos = [PurchaseOrder.model_validate(row).model_dump(mode='json') for row in csv.DictReader(source)]
        ids = {row['vendor_id'] for row in vendors}
        if any(row['vendor_id'] not in ids for row in pos):
            raise ValueError('All POs must reference a known vendor.')
        repo.initialize(policy, vendors, pos)
        print('Fresh pilot initialized. No historical invoices or approvals imported.')
    elif args.command == 'retention':
        import sqlalchemy as sa
        from invoicedesk.infrastructure import schema as s
        days = int(os.environ['DOCUMENT_RETENTION_DAYS'])
        if days < 1:
            raise ValueError('Retention must be at least one day.')
        storage = LocalStorage(Path(os.environ['DOCUMENT_ROOT']))
        cutoff = time.time()-days*86400
        with repo.engine.begin() as c:
            repo.lock(c)
            latest = dict(c.execute(sa.select(s.documents.c.sha256, sa.func.max(s.documents.c.created_at)).group_by(s.documents.c.sha256)))
            # Do not expire uploads while a worker is using them.
            active = set(c.execute(sa.select(s.documents.c.sha256).join(s.jobs, s.jobs.c.document_id == s.documents.c.id)
                         .where(s.jobs.c.state.in_(['queued', 'running']))).scalars())
            expired = [p for p in storage.root.iterdir() if p.is_file() and len(p.name) == 64
                       and p.name not in active and latest.get(p.name, p.stat().st_mtime) < cutoff]
            cache_root = Path(os.environ.get('LLM_CACHE_DIR', '/private/extraction-cache')).resolve()
            expired_caches = [p for p in cache_root.rglob('*.json') if p.is_file() and not p.is_symlink() and p.stat().st_mtime < cutoff]
            if args.apply:
                for path in expired_caches:
                    path.unlink(missing_ok=True)
                for path in expired:
                    storage.path(path.name).unlink(missing_ok=True)
                c.execute(s.sessions.delete().where(s.sessions.c.expires_at < time.time()))
                repo.audit(c, 'operator', 'retention', 'documents', {'count': len(expired), 'caches': len(expired_caches), 'days': days})
            print(json.dumps({'expired_documents': len(expired), 'expired_caches': len(expired_caches), 'applied': args.apply}))


if __name__ == '__main__':
    main()
