"""
audit.py
--------
Small helper around writing audit trail rows. Every meaningful ticket
lifecycle event (created / assigned / resolved) goes through here so
there is a single, consistent place that defines what gets logged.
"""

import sqlite3

from app.utils import utc_now_iso


def log_event(db: sqlite3.Connection, ticket_id: int, action: str, details: str = "") -> None:
    db.execute(
        "INSERT INTO audit_logs (ticket_id, action, details, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (ticket_id, action, details, utc_now_iso()),
    )


def log_ticket_created(db: sqlite3.Connection, ticket_id: int, priority: str) -> None:
    log_event(db, ticket_id, "Ticket Created", f"Priority set to {priority}")


def log_ticket_assigned(db: sqlite3.Connection, ticket_id: int, level: str, agent_name: str) -> None:
    log_event(db, ticket_id, "Ticket Assigned", f"Routed to {level} - {agent_name}")


def log_ticket_resolved(db: sqlite3.Connection, ticket_id: int, note: str = "") -> None:
    details = f"Resolution note: {note}" if note else "Marked resolved"
    log_event(db, ticket_id, "Ticket Resolved", details)
