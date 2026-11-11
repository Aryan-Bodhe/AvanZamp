"""Compatibility import for invoicedesk.domain.normalize."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.domain.normalize')
