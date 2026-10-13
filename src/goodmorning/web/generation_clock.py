"""Trusted request time, separate from queue wait, model runtime and regeneration."""
from contextvars import ContextVar
from datetime import datetime, timezone
import math

REQUESTED_AT = ContextVar('generation_requested_at', default=None)


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Invalid generation timestamp')
    try:
        datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise ValueError('Invalid generation timestamp') from None
    return value
