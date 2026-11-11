"""Offline tests must never read a developer's real credentials or live configuration."""
import socket
import pytest


@pytest.fixture(autouse=True)
def isolate_environment_file(monkeypatch, tmp_path):
    monkeypatch.setenv('INVOICEDESK_ENV_FILE', str(tmp_path/'unused.env'))
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-key')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'offline-test-key')
    monkeypatch.setenv('LLM_PROVIDER', 'anthropic')
    monkeypatch.setenv('LLM_MODEL', '')
    monkeypatch.setenv('LLM_MODE', 'off')
    monkeypatch.setenv('INVOICEDESK_PARSER', 'poppler')
    monkeypatch.setenv('INVOICEDESK_MATCHER', 'development')
    def deny_network(*args, **kwargs):
        raise AssertionError('Network access is disabled in offline tests.')
    monkeypatch.setattr(socket, 'getaddrinfo', deny_network)
    monkeypatch.setattr(socket.socket, 'connect', deny_network)
