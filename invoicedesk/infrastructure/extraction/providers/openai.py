"""OpenAI Responses adapter. Uses standard HTTPS without requiring an SDK."""
import base64
from copy import deepcopy
import json
import os
from time import perf_counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from invoicedesk.infrastructure.documents import inspect_document
from ..prompt import EXTRACTION_PROMPT
from . import ProviderResponse, ProviderUnavailable

ENDPOINT = 'https://api.openai.com/v1/responses'


def response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate the shared model to OpenAI's closed-object Structured Outputs schema."""
    result = deepcopy(schema)
    evidence_fields = sorted(set(result['properties']) - {'evidence'})
    result['properties']['evidence'] = {
        'type': 'object',
        'properties': {key: {'type': 'string'} for key in evidence_fields},
        'required': evidence_fields,
        'additionalProperties': False,
    }
    decimal_names = {'subtotal', 'tax_amount', 'total', 'quantity', 'unit_price', 'amount'}

    def close_objects(node: Any, path: tuple = ()) -> None:
        if isinstance(node, dict):
            node.pop('default', None)
            node.pop('format', None)
            if node.get('type') == 'object':
                props = node.setdefault('properties', {})
                node['required'] = sorted(props)
                node['additionalProperties'] = False
                # Evidence values are verbatim strings, even when their names are monetary fields.
                if path != ('properties', 'evidence'):
                    for key in decimal_names & props.keys():
                        props[key] = {'anyOf': [{'type': 'string', 'pattern': r'^-?[0-9]+(?:\.[0-9]+)?$'}, {'type': 'null'}]}
            for key, value in node.items():
                close_objects(value, (*path, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                close_objects(value, (*path, index))
    close_objects(result)
    return result


def document_input(path: Path) -> dict[str, Any]:
    document = inspect_document(path)
    data = path.read_bytes()
    if document.is_pdf:
        return {'type': 'input_file', 'filename': path.name if path.suffix.lower() == '.pdf' else 'document.pdf',
                'file_data': 'data:application/pdf;base64,'+base64.b64encode(data).decode()}
    from io import BytesIO
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((2500, 2500))
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=95)
    return {'type': 'input_image', 'detail': 'high',
            'image_url': 'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}


class OpenAIProvider:
    name = 'openai'

    def extract(self, path: Path, *, model: str, schema: dict[str, Any]) -> ProviderResponse:
        key = os.getenv('OPENAI_API_KEY')
        if not key:
            raise ProviderUnavailable('OpenAI extraction needs OPENAI_API_KEY configured locally.')
        payload = {
            'model': model, 'store': False, 'max_output_tokens': 8192,
            'instructions': EXTRACTION_PROMPT+' Use an empty evidence string for absent fields.',
            'input': [{'role': 'user', 'content': [document_input(path),
                       {'type': 'input_text', 'text': 'Extract the printed invoice facts.'}]}],
            'text': {'format': {'type': 'json_schema', 'name': 'invoice_extraction',
                                'strict': True, 'schema': response_schema(schema)}},
        }
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), method='POST',
                          headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
        started = perf_counter()
        response_ms = None

        def unavailable(message: str, usage: dict[str, Any] | None = None, category: str = 'malformed_response') -> ProviderUnavailable:
            elapsed = response_ms if response_ms is not None else (perf_counter()-started)*1000
            return ProviderUnavailable(message, api_calls=1, usage=usage, response_ms=elapsed, category=category)

        try:
            with urlopen(request, timeout=90) as response:
                body = json.load(response)
        except HTTPError as exc:
            # Never log the raw response: authentication errors may contain key fragments.
            known = {'insufficient_quota', 'invalid_api_key', 'model_not_found',
                     'invalid_json_schema', 'rate_limit_exceeded', 'unsupported_parameter'}
            code = None
            try:
                reported = json.loads(exc.read()).get('error', {}).get('code')
                if reported in known:
                    code = reported
            except (ValueError, AttributeError, TypeError):
                pass
            raise unavailable(f'OpenAI request failed (HTTP {exc.code}'+
                              (f'; {code}' if code else '')+').', category='transient_provider' if exc.code in {429,500,502,503,504} else 'configuration') from None
        except (URLError, TimeoutError, OSError):
            raise unavailable('OpenAI connection failed or timed out; explicit retry required.', category='ambiguous_timeout') from None
        except ValueError:
            raise unavailable('OpenAI returned invalid JSON.') from None
        response_ms = (perf_counter()-started)*1000
        usage = body.get('usage') or {}
        if body.get('status') != 'completed':
            raise unavailable('OpenAI response did not complete; extraction was not accepted.', usage)
        contents = [item for output in body.get('output', []) if output.get('type') == 'message'
                    for item in output.get('content', [])]
        if any(item.get('type') == 'refusal' for item in contents):
            raise unavailable('OpenAI declined this extraction.', usage, category='refusal')
        text = ''.join(item.get('text', '') for item in contents if item.get('type') == 'output_text')
        try:
            extraction = json.loads(text)
            if not isinstance(extraction, dict):
                raise ValueError('Expected an object')
        except ValueError:
            raise unavailable('OpenAI response did not contain a valid invoice object.', usage) from None
        return ProviderResponse(extraction, usage, response_ms=response_ms, resolved_model=body.get('model'))
