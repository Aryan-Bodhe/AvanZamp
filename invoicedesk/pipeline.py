"""Compatibility import for invoicedesk.application.processing."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.application.processing')
