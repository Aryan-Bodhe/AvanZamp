"""Compatibility entry point; implementation lives in interfaces."""
from invoicedesk.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
