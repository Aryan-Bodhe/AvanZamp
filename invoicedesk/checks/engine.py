"""Compatibility import for invoicedesk.domain.checks."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.domain.checks')
