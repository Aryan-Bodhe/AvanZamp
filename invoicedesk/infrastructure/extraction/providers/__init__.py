"""Provider contract and configurable adapter loading. No business rules live here."""
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol


class ProviderUnavailable(Exception):
    def __init__(self, message: str, *, api_calls: int = 0,
                 usage: dict[str, Any] | None = None, response_ms: float | None = None, category: str = 'provider_error'):
        super().__init__(message)
        self.category = category
        self.api_calls = api_calls
        self.usage = usage or {}
        self.response_ms = response_ms


@dataclass
class ProviderResponse:
    extraction: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    api_calls: int = 1
    response_ms: float | None = None
    resolved_model: str | None = None


class ExtractionProvider(Protocol):
    """Return printed facts only. The caller validates facts and applies all rules."""
    name: str

    def extract(self, path: Path, *, model: str, schema: dict[str, Any]) -> ProviderResponse:
        ...


def load_provider(name: str) -> ExtractionProvider:
    if name == 'openai':
        from .openai import OpenAIProvider
        return OpenAIProvider()
    if name == 'anthropic':
        from .anthropic import AnthropicProvider
        return AnthropicProvider()
    # This is trusted local application configuration, never a document-derived value.
    if ':' not in name:
        raise ValueError('Unknown LLM_PROVIDER. Use openai, anthropic or a trusted module:factory adapter.')
    module_name, factory_name = name.split(':', 1)
    factory = getattr(import_module(module_name), factory_name)
    provider = factory()
    if not getattr(provider, 'name', None) or not callable(getattr(provider, 'extract', None)):
        raise ValueError('Provider factory must return an adapter with name and extract().')
    return provider
