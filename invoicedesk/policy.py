"""Policy file adapter; domain policy values perform no I/O."""
import os
from pathlib import Path
import yaml
from invoicedesk.domain.policy import Policy as DomainPolicy
ROOT = Path(__file__).resolve().parent.parent

class Policy(DomainPolicy):
    @classmethod
    def load(cls, path: Path = ROOT / 'policy.yaml') -> 'Policy':
        values = yaml.safe_load(path.read_text())
        values['matching_adapter'] = os.getenv('INVOICEDESK_MATCHER', 'rapidfuzz')
        return cls.model_validate(values)
