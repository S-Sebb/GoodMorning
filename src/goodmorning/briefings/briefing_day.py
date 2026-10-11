"""Shared secretary day: local calendar date, with a 04:00 rollover."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def briefing_day(timezone="", now=None):
    local = (now or datetime.now().astimezone())
    if timezone:
        local = local.astimezone(ZoneInfo(timezone))
    # Compare wall-clock hours, not an elapsed four-hour subtraction across DST.
    day = local.date()
    return (day - timedelta(days=1) if local.hour < 4 else day).isoformat()
