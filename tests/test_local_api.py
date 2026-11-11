"""Local HTTP contract tests; the worker stays stopped and no providers are used."""
import pytest
pytest.importorskip('fastapi')
pytest.importorskip('httpx')
import asyncio
from functools import partial
import httpx
from invoicedesk.interfaces.local_api import create_app
from invoicedesk.interfaces.local_workspace import Workspace
from invoicedesk.policy import ROOT


@pytest.fixture
def client(tmp_path):
    workspace=Workspace(tmp_path/'ui',tmp_path/'absent')
    app=create_app(workspace,start_worker=False)
    app.state.workspace=workspace
    return InProcessClient(app)


class InProcessClient:
    """Exercise real ASGI routes with no TCP sockets or cross-thread test portal."""
    def __init__(self,app):self.app=app
    def request(self,method,path,**kwargs):
        async def send():
            # Some restricted hosts cannot signal asyncio's socket-based thread wakeup.
            # A timer keeps the real HTTP stack responsive without permitting network I/O.
            async def heartbeat():
                while True:await asyncio.sleep(.01)
            tick=asyncio.create_task(heartbeat())
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://testserver') as client:
                    return await client.request(method,path,**kwargs)
            finally:
                tick.cancel()
                try:await tick
                except asyncio.CancelledError:pass
        return asyncio.run(send())
    def __getattr__(self,name):
        return partial(self.request,name.upper())


def test_local_shell_routes_validation_and_origins(client):
    assert client.get('/invoices').status_code==200
    assert client.get('/assets/app.js').headers['content-type'].startswith(('text/javascript','application/javascript'))
    assert client.get('/vendors/V001').status_code==200
    assert client.get('/api/v1/config').json()['mode']=='live'
    assert client.get('/api/v1/invoices?page=0').status_code==422
    assert client.get('/api/v1/invoices/absent').status_code==404
    denied=client.post('/api/v1/vendors',headers={'Origin':'https://elsewhere.example','Idempotency-Key':'denied'},json={})
    assert denied.status_code==403
    assert client.get('/api/v1/vendors',headers={'host':'attacker.example'}).status_code==400
    assert 'credentials' not in client.get('/api/v1/config').json()


def test_vendor_crud_search_and_conflict(client):
    body=dict(vendor_id='NEW',name='New supplier',aliases=['Alias'])
    headers={'Idempotency-Key':'create'}
    created=client.post('/api/v1/vendors',json=body,headers=headers)
    assert created.status_code==201
    assert client.post('/api/v1/vendors',json=body,headers=headers).json()==created.json()
    assert client.get('/api/v1/vendors?q=New%20supplier').json()['total']==1
    blocked=client.post('/api/v1/vendors/NEW/block',json={'revision':1,'reason':'Verify'},headers={'Idempotency-Key':'block'})
    assert blocked.status_code==200
    assert client.get('/api/v1/vendors?status=blocked').json()['total']==2
    stale=client.put('/api/v1/vendors/NEW',json=dict(body,revision=1),headers={'Idempotency-Key':'stale'})
    assert stale.status_code==409 and stale.json()['error']['code']=='conflict'
    invalid=client.post('/api/v1/vendors',json={'vendor_id':'MISSING'},headers={'Idempotency-Key':'invalid'})
    assert invalid.status_code==422 and invalid.json()['error']['fields']
    deleted=client.request('DELETE','/api/v1/vendors/NEW',json={'revision':2,'confirmation':'NEW'},headers={'Idempotency-Key':'delete'})
    assert deleted.status_code==200
    assert client.get('/api/v1/activity?action=deleted').json()['total']==1


def test_upload_202_events_artifacts_and_retry_conflicts(client):
    source=ROOT/'data/invoices/01_clean_exact.pdf'
    result=client.post('/api/v1/invoices/upload',files={'file':('uploaded.pdf',source.read_bytes(),'application/pdf')},headers={'Idempotency-Key':'upload'})
    assert result.status_code==202
    identity=result.json()['id']
    detail=client.get('/api/v1/invoices/'+identity).json()
    assert detail['state']=='queued' and detail['status']=='Not started'
    assert client.get('/api/v1/invoices').json()['total']==1
    assert client.get('/api/v1/invoices/'+identity+'/events').json()['items']==[]
    assert client.get('/api/v1/invoices/'+identity+'/document').content==source.read_bytes()
    assert client.get('/api/v1/invoices/'+identity+'/report').json()['report'] is None
    artifacts=client.get('/api/v1/developer/runs/'+identity).json()
    assert artifacts['raw_available'] is False
    retry=client.post('/api/v1/invoices/'+identity+'/retry',json={'revision':1},headers={'Idempotency-Key':'retry'})
    assert retry.status_code==409
    recheck=client.post('/api/v1/invoices/'+identity+'/recheck',json={'revision':1},headers={'Idempotency-Key':'queued-recheck'})
    assert recheck.status_code==409 and recheck.json()['error']['code']=='conflict'
    assert client.post('/api/v1/invoices/upload',files={'file':('bad.txt',b'not an invoice','text/plain')},headers={'Idempotency-Key':'invalid'}).status_code==422


def test_po_validation_filters_and_referenced_vendor(client):
    body=dict(po_number='PO-NEW',vendor_id='V001',description='A service',net_amount='100.00',tax_rate='0.08',currency='USD',issue_date='2026-11-01')
    created=client.post('/api/v1/purchase-orders',json=body,headers={'Idempotency-Key':'po'})
    assert created.status_code==201
    detail=client.get('/api/v1/purchase-orders/PO-NEW').json()
    assert detail['approved_amount']=='0' and detail['receipt_count']==0
    assert client.get('/api/v1/purchase-orders?vendor_id=V001&q=PO-NEW').json()['total']==1
    denied=client.request('DELETE','/api/v1/vendors/V001',json={'revision':1,'confirmation':'V001'},headers={'Idempotency-Key':'delete-vendor'})
    assert denied.status_code==409
    invalid=client.post('/api/v1/purchase-orders',json=dict(body,net_amount=100.0),headers={'Idempotency-Key':'invalid-money'})
    assert invalid.status_code==422


def test_clean_launch_flag_clears_only_invoices_before_starting_server(client,monkeypatch,capsys):
    import invoicedesk.interfaces.local_api as local_api
    workspace=client.app.state.workspace
    workspace.submit('invoice.pdf',(ROOT/'data/invoices/01_clean_exact.pdf').read_bytes(),'before-clean')
    vendors=workspace.records('vendors');pos=workspace.records('purchase-orders')
    monkeypatch.setattr(local_api,'Workspace',lambda:workspace)
    import uvicorn
    calls=[]
    monkeypatch.setattr(uvicorn,'run',lambda app,**options:calls.append(options))
    local_api.main(['--clean-invoices'])
    assert workspace.invoices()==[]
    assert workspace.records('vendors')==vendors and workspace.records('purchase-orders')==pos
    assert calls==[dict(host='127.0.0.1',port=8000,workers=1)]
    assert 'vendors and purchase orders preserved' in capsys.readouterr().out
