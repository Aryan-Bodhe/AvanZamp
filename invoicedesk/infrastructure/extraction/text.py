"""Read PDF text while retaining coverage of every page."""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess

@dataclass(frozen=True)
class DocumentText:
    pages: list[str]

    @property
    def text(self) -> str:
        return '\n'.join(self.pages)

    @property
    def needs_vision(self) -> bool:
        # A text cover page must not conceal unread scanned invoice pages.
        return not self.pages or any(len(page.strip()) < 40 for page in self.pages)


def read_document_text(path: Path) -> DocumentText:
    if os.getenv('INVOICEDESK_PARSER', 'pdfplumber') == 'poppler':
        if not shutil.which('pdftotext'):
            raise RuntimeError('Install pdfplumber or Poppler to read PDF text.')
        result = subprocess.run(
            ['pdftotext', '-layout', str(path), '-'], capture_output=True,
            text=True, check=True, timeout=20,
        )
        pages = result.stdout.split('\f')
        if pages and not pages[-1].strip():
            pages.pop()
        return DocumentText(pages)
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return DocumentText([page.extract_text() or '' for page in pdf.pages])


def read_text(path: Path) -> str:
    return read_document_text(path).text
