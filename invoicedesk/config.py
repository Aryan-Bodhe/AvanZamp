"""Load local CLI configuration without executing shell commands or overriding exports."""
import os
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parents[1]


def load_environment(path: Path | None = None) -> None:
    selected = path if path is not None else Path(os.getenv('INVOICEDESK_ENV_FILE', str(ROOT/'.env')))
    if not selected.is_file():
        return
    settings: dict[str, str] = {}
    for number, raw in enumerate(selected.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, value = line.partition('=')
        key = key.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError(f'Invalid environment setting on line {number}; expected NAME=value.')
        try:
            parts = shlex.split(value, comments=True, posix=True)
        except ValueError:
            raise ValueError(f'Invalid quoting for environment setting {key} on line {number}.') from None
        if len(parts) > 1:
            raise ValueError(f'Quote whitespace in environment setting {key} on line {number}.')
        settings[key] = parts[0] if parts else ''
    for key, value in settings.items():
        os.environ.setdefault(key, value)
