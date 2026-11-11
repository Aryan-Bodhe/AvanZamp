"""Compatibility import for pure domain reconciliation."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.domain.reconciliation')
