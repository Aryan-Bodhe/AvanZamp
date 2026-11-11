"""Private content-addressed storage; identifiers are never sender filenames."""
import hashlib
import os
from pathlib import Path
import re
import tempfile


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def path(self, digest: str) -> Path:
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Invalid document identifier.')
        path = self.root / digest
        if path.is_symlink():
            raise ValueError('Document storage must not contain symlinks.')
        return path

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.path(digest)
        fd, temporary = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return digest
