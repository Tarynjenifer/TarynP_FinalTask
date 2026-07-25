"""
utils.py
--------
Small shared helpers used across the app.
"""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
