"""Content-based intake shared by the pipeline and extraction adapters."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 25_000_000
IMAGE_TYPES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}

@dataclass(frozen=True)
class Document:
    path: Path
    media_type: str
    sha256: str
    size_bytes: int

    @property
    def is_pdf(self) -> bool:
        return self.media_type == 'application/pdf'


def inspect_document(path: Path) -> Document:
    """Trust file content rather than an extension supplied by the sender."""
    if not path.is_file():
        raise FileNotFoundError(f'Invoice file does not exist: {path}')
    size = path.stat().st_size
    if not size or size > MAX_BYTES:
        raise ValueError('Invoice must be non-empty and at most 20 MB.')
    data = path.read_bytes()
    if data.startswith(b'%PDF-'):
        media_type = 'application/pdf'
    else:
        try:
            with Image.open(path) as image:
                media_type = IMAGE_TYPES.get(image.format)
                if media_type is None:
                    raise ValueError('Supported inputs: PDF, PNG, JPEG and WebP.')
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError('Invoice image exceeds the 25 megapixel limit.')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Use a PDF for a document with multiple image frames.')
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('Input is not a readable PDF, PNG, JPEG or WebP image.') from exc
    return Document(path, media_type, hashlib.sha256(data).hexdigest(), size)
