"""Shared logs remain readable and free of duplicate handlers."""
import logging
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
import pytest
from invoicedesk.logger import (
    ConsoleHandler, LOGGING_DIR, configure_logging, get_logger,
)


@pytest.fixture
def log_dir(tmp_path):
    package = logging.getLogger('invoicedesk')
    original_level = package.level
    original_console = any(isinstance(h, ConsoleHandler) for h in package.handlers)
    original_file = next((h for h in package.handlers if isinstance(h, TimedRotatingFileHandler)), None)
    original_dir = LOGGING_DIR if original_file is None else Path(original_file.baseFilename).parent
    configure_logging(log_dir=tmp_path, console=False, level='DEBUG')
    yield tmp_path
    configure_logging(log_dir=original_dir, console=original_console, level=original_level)


def test_one_shared_file_handler_without_ids(log_dir):
    first = get_logger('invoicedesk.pipeline')
    second = get_logger('invoicedesk.extract.llm')
    get_logger('invoicedesk.pipeline')
    handlers = [h for h in logging.getLogger('invoicedesk').handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].when == 'MIDNIGHT'
    first.info('stage-complete')
    second.warning('provider-unavailable')
    text = (log_dir/'app.log').read_text()
    assert text.count('stage-complete') == 1
    assert text.count('provider-unavailable') == 1
    assert 'session_id=' not in text and 'req_id=' not in text
    assert '\033[' not in text


def test_console_toggle_and_level_changes(log_dir, capsys):
    configure_logging(log_dir=log_dir, console=True, level='WARNING')
    logger = get_logger('invoicedesk.pipeline')
    logger.info('hidden-info')
    logger.warning('visible-warning')
    output = capsys.readouterr()
    assert 'visible-warning' in output.err and 'hidden-info' not in output.err
    assert output.out == ''
    configure_logging(log_dir=log_dir, console=True, level='DEBUG')
    logger.debug('visible-debug')
    assert capsys.readouterr().err.count('visible-debug') == 1
    configure_logging(log_dir=log_dir, console=False, level='DEBUG')
    logger.info('file-only')
    assert capsys.readouterr().err == ''
    assert 'file-only' in (log_dir/'app.log').read_text()


def test_pipeline_logs_total_time_without_ids(log_dir, tmp_path):
    from invoicedesk.db import Db
    from invoicedesk.seed import reset
    from invoicedesk.pipeline import run_invoice
    from invoicedesk.policy import ROOT, Policy
    from invoicedesk.extract.llm import LlmClient
    db = Db(tmp_path/'test.sqlite3')
    reset(db)
    stream = run_invoice(ROOT/'data/invoices/01_clean_exact.pdf', db=db, policy=Policy.load(), llm=LlmClient('off'))
    try:
        events = []
        for event in stream:
            events.append(event)
        text = (log_dir/'app.log').read_text()
        assert events[-1].run_id[:8] not in text
        assert 'Pipeline total response time:' in text
        assert 'response_time_ms=0 input_tokens=0 output_tokens=0 total_tokens=0' in text
        assert 'complete' in text
    finally:
        stream.close()
        db.close()
