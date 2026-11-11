"""Production dependency and resource validation; development is explicit."""
import importlib
import os
from pathlib import Path
import warnings
from PIL import Image
from .documents import inspect_document, MAX_PIXELS

MAX_PAGES = 40
MAX_PAGE_POINTS = 14400


def require_production_dependencies() -> None:
    for name in ('pdfplumber', 'rapidfuzz', 'sqlalchemy', 'psycopg', 'authlib', 'fastapi'):
        try:
            importlib.import_module(name)
        except ImportError as exc:
            raise RuntimeError(f'Required pilot dependency is missing: {name}') from exc
    if os.getenv('INVOICEDESK_PARSER', 'pdfplumber') != 'pdfplumber' or os.getenv('INVOICEDESK_MATCHER', 'rapidfuzz') != 'rapidfuzz':
        raise RuntimeError('Development parsing and matching adapters are not permitted in the pilot.')


def validate_pilot_document(path: Path):
    document = inspect_document(path)
    if document.is_pdf:
        import pdfplumber
        try:
            with pdfplumber.open(path) as pdf:
                if getattr(pdf.doc, 'encryption', None) is not None or getattr(pdf.doc, 'is_extractable', True) is False:
                    raise ValueError('Encrypted PDFs are unsupported.')
                if not 1 <= len(pdf.pages) <= MAX_PAGES:
                    raise ValueError('PDF must contain 1–40 pages; split larger documents explicitly.')
                total_pixels = 0
                for page in pdf.pages:
                    if not 0 < page.width <= MAX_PAGE_POINTS or not 0 < page.height <= MAX_PAGE_POINTS:
                        raise ValueError('PDF page dimensions exceed resource limits.')
                    for image in page.images:
                        width, height = image.get('srcsize', (0, 0))
                        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                            raise ValueError('Embedded image dimensions exceed resource limits.')
                        total_pixels += width * height
                    if total_pixels > 100_000_000:
                        raise ValueError('PDF image resources exceed the document limit.')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF is malformed, encrypted, or unreadable.') from exc
    else:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image.load()
    return document


def require_evaluated_model(*, mode: str | None = None) -> None:
    import re
    mode = mode or os.getenv('LLM_MODE', 'off')
    if mode not in {'live', 'off'}:
        raise RuntimeError('Only live and off extraction modes are permitted in the pilot.')
    if mode != 'live':
        return
    model = os.getenv('LLM_MODEL', '')
    provider = os.getenv('LLM_PROVIDER', 'anthropic')
    if not model or model != os.getenv('INVOICEDESK_EVALUATED_MODEL'):
        raise RuntimeError('Set the evaluated model snapshot explicitly in both model settings.')
    pattern = r'.*-\d{4}-\d{2}-\d{2}$' if provider == 'openai' else r'.*-\d{8}$' if provider == 'anthropic' else None
    if pattern and not re.fullmatch(pattern, model):
        raise RuntimeError('Pilot extraction requires a dated model snapshot; moving aliases are unsupported.')
