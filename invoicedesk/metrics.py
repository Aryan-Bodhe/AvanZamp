"""Compatibility import for invoicedesk.infrastructure.telemetry.metrics."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.infrastructure.telemetry.metrics')
