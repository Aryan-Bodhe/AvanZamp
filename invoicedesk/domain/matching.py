"""Explicit matching algorithms. Production never silently substitutes scoring."""
from difflib import SequenceMatcher


def similarity(a: str, b: str, adapter: str = 'rapidfuzz') -> float:
    if adapter == 'rapidfuzz':
        from rapidfuzz.fuzz import token_set_ratio
        return token_set_ratio(a, b)
    if adapter != 'development':
        raise ValueError('Unknown matching adapter.')
    left, right = set(a.lower().split()), set(b.lower().split())
    if left and right and (left <= right or right <= left):
        return 100.0
    return 100 * SequenceMatcher(None, ' '.join(sorted(left)), ' '.join(sorted(right))).ratio()
