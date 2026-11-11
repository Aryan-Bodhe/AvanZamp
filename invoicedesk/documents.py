"""Compatibility import for invoicedesk.infrastructure.documents."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.infrastructure.documents')
