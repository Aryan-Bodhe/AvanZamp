"""Normalize provider-reported token counts without estimating unknown usage."""
from typing import Any


def token_usage(usage: dict[str, Any], api_calls: int) -> dict[str, int | None]:
    if not api_calls:
        return {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}

    def count(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    incoming = count(usage.get('input_tokens'))
    outgoing = count(usage.get('output_tokens'))
    total = count(usage.get('total_tokens'))
    # Anthropic exposes cache reads/writes separately from its uncached input count.
    cache_parts = {key: count(usage[key]) for key in ('cache_read_input_tokens', 'cache_creation_input_tokens') if key in usage}
    if total is None and incoming is not None and outgoing is not None:
        if all(value is not None for value in cache_parts.values()):
            total = incoming+outgoing+sum(cache_parts.values())
    result = {'input_tokens': incoming, 'output_tokens': outgoing, 'total_tokens': total, **cache_parts}
    for details, field in [('input_tokens_details', 'cached_tokens'), ('output_tokens_details', 'reasoning_tokens')]:
        values = usage.get(details)
        if isinstance(values, dict) and field in values:
            result[field] = count(values[field])
    return result
