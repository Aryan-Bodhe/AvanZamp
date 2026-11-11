"""OIDC identity mapping, server-side opaque sessions, and CSRF checks."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlsplit
from pydantic import BaseModel, Field

COOKIE = '__Host-invoicedesk'


class Identity(BaseModel):
    subject: str
    roles: set[str] = Field(default_factory=set)


class SecuritySettings(BaseModel):
    issuer: str
    client_id: str
    client_secret: str
    origin: str
    # Keys are OIDC subject identifiers, deliberately not mutable email addresses.
    allowed_users: dict[str, set[str]]
    session_seconds: int = 8 * 3600

    @classmethod
    def from_env(cls):
        return cls(issuer=os.environ['OIDC_ISSUER'], client_id=os.environ['OIDC_CLIENT_ID'],
                   client_secret=os.environ['OIDC_CLIENT_SECRET'], origin=os.environ['PUBLIC_ORIGIN'],
                   allowed_users=json.loads(os.environ['OIDC_ALLOWED_USERS']))

    def validate_startup(self):
        for value in (self.issuer, self.origin):
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError('OIDC issuer and public origin must use HTTPS.')
        if urlsplit(self.origin).path not in {'', '/'}:
            raise ValueError('PUBLIC_ORIGIN must contain no path.')
        if not self.allowed_users or any(not roles <= {'uploader', 'reviewer', 'admin'} for roles in self.allowed_users.values()):
            raise ValueError('Configure an explicit subject allowlist and valid roles.')


def identity_from_claims(claims: dict, settings: SecuritySettings) -> Identity:
    if claims.get('iss') != settings.issuer or not claims.get('sub'):
        raise PermissionError('Invalid OIDC identity.')
    roles = settings.allowed_users.get(claims['sub'])
    if roles is None:
        raise PermissionError('User is not allowed to access InvoiceDesk.')
    return Identity(subject=claims['sub'], roles=roles)


def csrf_valid(expected: str, supplied: str, origin: str, allowed_origin: str) -> bool:
    return bool(expected and supplied and hmac.compare_digest(expected, supplied)
                and origin.rstrip('/') == allowed_origin.rstrip('/'))


class DatabaseSessions:
    def __init__(self, repository, ttl: int):
        self.repo, self.ttl = repository, ttl

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def load(self, token: str) -> dict:
        import sqlalchemy as sa
        from invoicedesk.infrastructure.schema import sessions
        if len(token) > 128:
            return {}
        with self.repo.engine.connect() as c:
            result = c.execute(sa.select(sessions.c.data).where(sessions.c.token_hash == self.digest(token),
                               sessions.c.expires_at > time.time())).first()
            return dict(result[0]) if result else {}

    def save(self, token: str, data: dict) -> None:
        from invoicedesk.infrastructure.schema import sessions
        with self.repo.engine.begin() as c:
            # A new token is created per response; old cookies cannot be replayed after rotation.
            c.execute(sessions.insert().values(token_hash=self.digest(token), data=data, expires_at=time.time()+self.ttl))

    def delete(self, token: str) -> None:
        from invoicedesk.infrastructure.schema import sessions
        with self.repo.engine.begin() as c:
            c.execute(sessions.delete().where(sessions.c.token_hash == self.digest(token)))


class ServerSessionMiddleware:
    """Only an opaque random token is exposed in the cookie, including during OIDC."""
    def __init__(self, app, store: DatabaseSessions):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        from starlette.requests import Request
        from starlette.concurrency import run_in_threadpool
        request = Request(scope)
        token = request.cookies.get(COOKIE, '')
        data = await run_in_threadpool(self.store.load, token) if token else {}
        scope['session'] = data
        original = json.dumps(data, sort_keys=True)
        async def send_session(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                # Never cache session/document responses in shared caches.
                headers.extend([(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')])
                if json.dumps(scope['session'], sort_keys=True) != original:
                    if token:
                        await run_in_threadpool(self.store.delete, token)
                    if scope['session']:
                        replacement = secrets.token_urlsafe(32)
                        await run_in_threadpool(self.store.save, replacement, scope['session'])
                        cookie = f'{COOKIE}={replacement}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={self.store.ttl}'
                    else:
                        cookie = f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'
                    headers.append((b'set-cookie', cookie.encode()))
                message['headers'] = headers
            await send(message)
        await self.app(scope, receive, send_session)
