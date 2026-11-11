"""Compatibility import for invoicedesk.infrastructure.telemetry.logger."""
from importlib import import_module
import sys
sys.modules[__name__] = import_module('invoicedesk.infrastructure.telemetry.logger')
