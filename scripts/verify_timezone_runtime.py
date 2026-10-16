"""Read-only portable-runtime acceptance: exercise packaged IANA data, not host data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.metadata
import json
import zoneinfo


def verify() -> dict:
    original = zoneinfo.TZPATH
    try:
        zoneinfo.reset_tzpath(())
        # no_cache avoids relying on zones loaded before the packaged-data check.
        zones = {name: zoneinfo.ZoneInfo.no_cache(name) for name in (
            "UTC", "Europe/London", "America/New_York"
        )}
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expected = {"UTC": 0, "Europe/London": 0, "America/New_York": -5}
        for name, zone in zones.items():
            assert stamp.astimezone(zone).utcoffset() == timedelta(hours=expected[name]), name
        summer = datetime(2026, 7, 1, tzinfo=zones["America/New_York"])
        assert summer.utcoffset() == timedelta(hours=-4), "New York DST"
        assert importlib.metadata.version("tzdata") == "2026.5"
        return {"passed": True, "tzdata": "2026.5", "system_tzpath_used": False,
                "zones": list(zones), "dst_verified": True, "model_calls": False}
    finally:
        zoneinfo.reset_tzpath(original)


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
