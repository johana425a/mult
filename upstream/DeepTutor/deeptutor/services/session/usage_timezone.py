"""Distinguish invalid user input from missing runtime IANA time-zone data."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimezoneDataUnavailable(RuntimeError):
    """The runtime cannot resolve even UTC from its configured IANA database."""


def resolve_usage_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ValueError:
        raise
    except ZoneInfoNotFoundError as exc:
        # UTC is in every supported IANA database. It is only a health probe;
        # it must never replace the requested zone and shift daily/year bins.
        try:
            ZoneInfo.no_cache("UTC")
        except (ZoneInfoNotFoundError, ValueError) as health_exc:
            raise TimezoneDataUnavailable("Time-zone database is unavailable") from health_exc
        raise ValueError("Invalid timezone") from exc
