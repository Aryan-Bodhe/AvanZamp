"""Terminal rendering for the same StageEvents consumed by other clients."""
import logging
from invoicedesk.domain.models import StageEvent
from invoicedesk.infrastructure.telemetry.logger import get_logger


def log_event(event: StageEvent) -> None:
    logger = get_logger('invoicedesk.application.processing')
    level = logging.ERROR if event.state == 'failed' else logging.INFO
    logger.log(level, '%-12s %-9s %s%s', event.stage,
               event.state, event.title, f' — {event.detail}' if event.detail else '')
    for check in event.checks:
        level = logging.WARNING if check.status in {'WARN', 'FAIL'} else logging.INFO
        logger.log(level, '  %-5s %-24s %s',
                   check.status.value, check.check_id, check.detail)
    if event.stage == 'extract' and event.state == 'completed':
        payload = event.payload
        for section in payload.get('sections', []):
            logger.info('Section %-12s %-11s arithmetic=%s source=%s issues=%d', section['section'], section['status'], section['arithmetic_status'], section.get('verification_status', 'NOT_CHECKED'), len(section['issues']))
            if section.get('row_arithmetic_counts'):
                counts = section['row_arithmetic_counts']
                logger.info('  Row arithmetic: passed=%d failed=%d not_checked=%d; subtotal=%s', counts['PASS'], counts['FAIL'], counts['NOT_CHECKED'], section['subtotal_arithmetic_status'])
        logger.info('  source=%s api_calls=%s cache_hit=%s',
                    payload.get('provenance') or ('unavailable' if event.detail == 'failed' else 'local'), payload.get('llm_calls', 0),
                    payload.get('cache_hit', False))
        if not payload.get('llm_calls'):
            logger.info('API metrics: no request made; response_time_ms=0 input_tokens=0 output_tokens=0 total_tokens=0')
