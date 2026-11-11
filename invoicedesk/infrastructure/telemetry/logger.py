"""Shared rotating-file and terminal logging."""
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
import sys
from threading import RLock

LOGGING_DIR = Path(os.getenv('LOGGING_DIR', str(Path(__file__).resolve().parents[3]/'logs')))
LOGGING_LIMIT_DAYS = int(os.getenv('LOGGING_LIMIT_DAYS', '1'))
LOG_TO_CONSOLE = os.getenv('LOG_TO_CONSOLE', 'true').lower() in {'1', 'true', 'yes', 'on'}
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | [%(name)-15s] %(message)s'
COLORS = {'DEBUG': '\033[36m', 'INFO': '\033[37m', 'WARNING': '\033[33m',
          'ERROR': '\033[31m', 'CRITICAL': '\033[1;31m'}
_lock = RLock()


class ColoredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if sys.stderr.isatty() and not os.getenv('NO_COLOR'):
            return COLORS.get(record.levelname, '') + message + '\033[0m'
        return message


class ConsoleHandler(logging.StreamHandler):
    """Use the current stderr so redirection and repeated CLI calls keep working."""
    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def _namer(default_name: str) -> str:
    base_with_ext, date = default_name.rsplit('.', 1)
    root, ext = os.path.splitext(base_with_ext)
    return f'{root}.{date}{ext}'


def configure_logging(*, level: int | str | None = None, console: bool | None = None,
                      log_dir: Path | str | None = None) -> logging.Logger:
    """Configure one set of handlers shared by all InvoiceDesk modules."""
    with _lock:
        logger = logging.getLogger('invoicedesk')
        selected_level = level if level is not None else os.getenv('LOG_LEVEL', 'INFO')
        logger.setLevel(selected_level)
        # Permit embedding applications and pytest to capture records at the root.
        logger.propagate = True
        directory = Path(log_dir) if log_dir is not None else Path(os.getenv('LOGGING_DIR', str(LOGGING_DIR)))
        filename = str((directory/'app.log').resolve())
        enabled_file = os.getenv('LOG_TO_FILE', 'true').lower() in {'1', 'true', 'yes', 'on'}
        enabled_console = os.getenv('LOG_TO_CONSOLE', str(LOG_TO_CONSOLE)).lower() in {'1', 'true', 'yes', 'on'} if console is None else console
        owned = [h for h in logger.handlers if getattr(h, '_invoicedesk', False)]
        for handler in owned:
            if ((isinstance(handler, TimedRotatingFileHandler) and (handler.baseFilename != filename or not enabled_file))
                    or (isinstance(handler, ConsoleHandler) and not enabled_console)):
                logger.removeHandler(handler)
                handler.close()
        owned = [h for h in logger.handlers if getattr(h, '_invoicedesk', False)]
        if enabled_file and not any(isinstance(h, TimedRotatingFileHandler) for h in owned):
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = TimedRotatingFileHandler(
                filename, when='midnight', interval=1,
                backupCount=LOGGING_LIMIT_DAYS, encoding='utf-8', utc=False,
            )
            file_handler.suffix = '%Y-%m-%d'
            file_handler.namer = _namer
            file_handler.setFormatter(logging.Formatter(LOG_FORMAT, '%Y-%m-%d %H:%M:%S'))
            _add_handler(logger, file_handler)
        if enabled_console and not any(isinstance(h, ConsoleHandler) for h in owned):
            handler = ConsoleHandler()
            handler.setFormatter(ColoredFormatter(LOG_FORMAT, '%Y-%m-%d %H:%M:%S'))
            _add_handler(logger, handler)
        for handler in logger.handlers:
            if getattr(handler, '_invoicedesk', False):
                handler.setLevel(selected_level)
        return logger


def _add_handler(logger: logging.Logger, handler: logging.Handler) -> None:
    handler._invoicedesk = True
    logger.addHandler(handler)


def get_logger(name: str, level: int | str | None = None, console: bool | None = None) -> logging.Logger:
    """Use __name__ at call sites; module loggers inherit the package configuration."""
    if not (name == 'invoicedesk' or name.startswith('invoicedesk.')):
        name = f'invoicedesk.{name}'
    package = logging.getLogger('invoicedesk')
    if level is not None or console is not None or not any(getattr(h, '_invoicedesk', False) for h in package.handlers):
        configure_logging(level=level, console=console)
    return logging.getLogger(name)

