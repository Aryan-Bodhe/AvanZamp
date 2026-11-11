"""Compatibility import for invoicedesk.domain.models."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.domain.models')
