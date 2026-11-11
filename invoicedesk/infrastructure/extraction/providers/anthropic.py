"""Anthropic-specific transport. Credentials and SDK details stay in this adapter."""
import base64
import os
from time import perf_counter
from pathlib import Path
from typing import Any
from invoicedesk.infrastructure.documents import inspect_document
from . import ProviderResponse, ProviderUnavailable

from ..prompt import EXTRACTION_PROMPT


def document_block(path: Path) -> dict[str, Any]:
    document = inspect_document(path)
    data = path.read_bytes()
    if not document.is_pdf:
        from io import BytesIO
        from PIL import Image, ImageOps
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2500, 2500))
            out = BytesIO()
            image.save(out, format='JPEG', quality=95)
            data = out.getvalue()
        media_type = 'image/jpeg'
    else:
        media_type = 'application/pdf'
    return {'type': 'document' if document.is_pdf else 'image', 'source': {
        'type': 'base64', 'media_type': media_type, 'data': base64.b64encode(data).decode(),
    }}


class AnthropicProvider:
    name = 'anthropic'

    def extract(self, path: Path, *, model: str, schema: dict[str, Any]) -> ProviderResponse:
        if not os.getenv('ANTHROPIC_API_KEY'):
            raise ProviderUnavailable('Anthropic extraction needs ANTHROPIC_API_KEY configured locally.')
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderUnavailable('Anthropic SDK is not installed; install requirements.txt before live extraction.') from exc
        block = document_block(path)
        client = Anthropic(timeout=45, max_retries=0)
        started = perf_counter()
        response_ms = None
        usage: dict[str, Any] = {}
        try:
            response = client.messages.create(
                model=model, max_tokens=8192, temperature=0, system=EXTRACTION_PROMPT,
                messages=[{'role': 'user', 'content': [block, {'type': 'text', 'text': 'Extract this invoice with the tool.'}]}],
                tools=[{'name': 'extract_invoice', 'description': 'Printed invoice fields and their evidence', 'input_schema': schema}],
                tool_choice={'type': 'tool', 'name': 'extract_invoice'},
            )
            response_ms = (perf_counter()-started)*1000
            usage = response.usage.model_dump()
            if response.stop_reason == 'max_tokens':
                raise ProviderUnavailable('Extraction response was truncated.', api_calls=1, usage=usage, response_ms=response_ms)
            result = next(b.input for b in response.content if b.type == 'tool_use' and b.name == 'extract_invoice')
            return ProviderResponse(result, usage, response_ms=response_ms, resolved_model=getattr(response, 'model', None))
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable(f'Anthropic extraction unavailable ({type(exc).__name__}).', api_calls=1,
                                      category='ambiguous_timeout' if 'Timeout' in type(exc).__name__ or 'Connection' in type(exc).__name__ else 'provider_error',
                                      usage=usage, response_ms=response_ms if response_ms is not None else (perf_counter()-started)*1000) from exc
