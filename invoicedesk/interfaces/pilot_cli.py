"""Trusted local CLI for the same durable job and review services as HTTP."""
import argparse
import json
import os
from pathlib import Path
from invoicedesk.application.jobs import JobService
from invoicedesk.application.review import ReviewService
from invoicedesk.infrastructure.repository import Repository
from invoicedesk.infrastructure.storage import LocalStorage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actor', required=True, help='OIDC subject for the auditable operator action')
    sub = parser.add_subparsers(dest='command', required=True)
    submit = sub.add_parser('submit')
    submit.add_argument('file', type=Path)
    submit.add_argument('--key', required=True)
    report = sub.add_parser('report')
    report.add_argument('job_id')
    for name in ('approve', 'reject'):
        action = sub.add_parser(name)
        action.add_argument('job_id')
        action.add_argument('--revision', type=int, required=True)
        action.add_argument('--key', required=True)
        action.add_argument('--reason', default='')
        action.add_argument('--confirmed-source', action='store_true')
    args = parser.parse_args(argv)
    roles = set(json.loads(os.environ['OIDC_ALLOWED_USERS']).get(args.actor, []))
    if not roles:
        raise PermissionError('Operator must be in the configured OIDC subject allowlist.')
    repo = Repository(os.environ['DATABASE_URL'])
    storage = LocalStorage(Path(os.environ['DOCUMENT_ROOT']))
    if args.command == 'submit':
        from invoicedesk.infrastructure.documents import MAX_BYTES
        with args.file.open('rb') as source:
            data = source.read(MAX_BYTES+1)
        result = JobService(repo, storage).submit(data, args.file.name, actor=args.actor, roles=roles, key=args.key)
    elif args.command == 'report':
        result = repo.report(args.job_id, args.actor, roles)
    else:
        result = ReviewService(repo).act(args.job_id, actor=args.actor, roles=roles, key=args.key,
                   revision=args.revision, approve=args.command == 'approve', reason=args.reason,
                   confirmed_source=args.confirmed_source)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
