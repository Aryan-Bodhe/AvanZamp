"""Opt-in local PostgreSQL tests. No external services or model calls.

Set INVOICEDESK_TEST_POSTGRES_URL to a dedicated, disposable local database.
The test creates an isolated schema and drops only that schema afterwards.
"""
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
sa = pytest.importorskip('sqlalchemy')
URL = os.getenv('INVOICEDESK_TEST_POSTGRES_URL')
pytestmark = pytest.mark.skipif(not URL, reason='Requires a dedicated local PostgreSQL test database')
from invoicedesk.infrastructure.repository import Repository
from invoicedesk.infrastructure import schema as s
from invoicedesk.application.jobs import JobService
from invoicedesk.application.review import ReviewService
from invoicedesk.infrastructure.storage import LocalStorage
from invoicedesk.domain.approval import ApprovalBlocked, Conflict
from invoicedesk.policy import Policy
from test_pilot_repository import completed_job

# Save before the autouse network guard, restoring only loopback PostgreSQL below.
_connect = socket.socket.connect
_getaddrinfo = socket.getaddrinfo


@pytest.fixture
def pg_repo(monkeypatch):
    from sqlalchemy.engine import make_url
    parsed = make_url(URL)
    if parsed.host not in {'127.0.0.1', 'localhost', '::1'}:
        pytest.fail('PostgreSQL tests only allow a local disposable database.')
    def local_address(host, *args, **kwargs):
        if host not in {'127.0.0.1','localhost','::1',None}:
            raise AssertionError('External network disabled in tests.')
        return _getaddrinfo(host,*args,**kwargs)
    def local_connect(sock,address):
        if not isinstance(address,tuple) or address[0] not in {'127.0.0.1','::1'} or address[1] != (parsed.port or 5432):
            raise AssertionError('Only the configured local PostgreSQL endpoint is permitted.')
        return _connect(sock,address)
    monkeypatch.setattr(socket,'getaddrinfo',local_address)
    monkeypatch.setattr(socket.socket,'connect',local_connect)
    schema = 'test_'+uuid.uuid4().hex
    engine = sa.create_engine(URL)
    with engine.begin() as c:
        c.exec_driver_sql('CREATE SCHEMA '+schema)
    repo = Repository(URL)
    repo.engine.dispose()
    repo.engine = sa.create_engine(URL,connect_args={'options':'-csearch_path='+schema})
    s.metadata.create_all(repo.engine)
    repo.initialize(Policy.load(), [dict(vendor_id='V1',name='Example Vendor',aliases_json='[]',status='approved',notes='')],
        [dict(po_number='PO-123',vendor_id='V1',description='Services',net_amount='1500',tax_rate='0',currency='USD',status='open',issue_date='2026-01-01')])
    try:
        yield repo
    finally:
        repo.engine.dispose()
        with engine.begin() as c:
            c.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        engine.dispose()


def test_postgres_simultaneous_approvals_and_same_command_retries(pg_repo,tmp_path):
    first = completed_job(pg_repo,tmp_path,'FIRST','2026-01-01')
    second = completed_job(pg_repo,tmp_path,'SECOND','2026-03-01')
    barrier = threading.Barrier(2)
    def act(job):
        barrier.wait(timeout=10)
        try:
            return ReviewService(pg_repo).act(job,actor='reviewer',roles={'reviewer'},key='approve-'+job,
                       revision=1,approve=True,reason='Verified')
        except ApprovalBlocked:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(act,[first,second]))
    assert sum(result is not None for result in results) == 1
    accepted = next(result for result in results if result is not None)
    for _ in range(3):
        assert ReviewService(pg_repo).act(accepted['job_id'],actor='reviewer',roles={'reviewer'},
            key='approve-'+accepted['job_id'],revision=1,approve=True,reason='Verified') == accepted
    with pg_repo.engine.connect() as c:
        assert c.execute(sa.select(sa.func.count()).select_from(s.ledger)).scalar_one() == 1


def test_postgres_skip_locked_queue_and_expired_lease_fencing(pg_repo,tmp_path):
    jobs = JobService(pg_repo,LocalStorage(tmp_path/'docs'))
    for number in range(10):
        jobs.submit(b'%PDF-1.4\nsynthetic '+str(number).encode(),'example.pdf',actor='uploader',roles={'uploader'},key=str(number))
    with ThreadPoolExecutor(max_workers=5) as pool:
        claimed = list(pool.map(lambda _:pg_repo.claim(),range(10)))
    assert len({job['id'] for job in claimed}) == 10
    expired = claimed[0]
    with pg_repo.engine.begin() as c:
        pg_repo.update_job(c,expired['id'],lease_until=time.time()-1)
    assert pg_repo.claim() is None
    assert not pg_repo.heartbeat(expired['id'],expired['lease_token'])
    with pytest.raises(Conflict):
        pg_repo.append_event(expired['id'],expired['lease_token'],{'stage':'complete'})
