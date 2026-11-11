"""Compatibility import for pure domain validation."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.domain.validation')
