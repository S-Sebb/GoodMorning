"""Secretary uses edition colours according to the account's local clock."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def clock_theme(zone=None, now=None):
    # A profile without a usable timezone stays on UTC until setup is completed.
    zone = zone or 'UTC'
    try:
        local_zone = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        zone, local_zone = 'UTC', ZoneInfo('UTC')
    local = (now if now is not None else datetime.now(timezone.utc)).astimezone(local_zone)
    return {'timezone': zone, 'theme': 'gm' if 6 <= local.hour < 18 else 'gn'}
