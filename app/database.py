"""
database.py
------------
Handles all raw SQLite connection and schema setup logic using the
built-in sqlite3 module (no ORM).
"""

import csv
import json
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from app.utils import utc_now_iso

# The database file lives next to this package, at the project root.
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "tickets.db"
HISTORY_FILE = BASE_DIR / "app" / "data" / "tickets_batch.json"
CLEANED_CSV = BASE_DIR / "app" / "data" / "cleaned_tickets.csv"


def get_connection() -> sqlite3.Connection:
    """
    Create a new SQLite connection with sensible defaults:
    - row_factory so rows can be read like dicts
    - foreign_keys enforcement turned on
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """
    Context manager for use inside request handlers:

        with get_db() as db:
            db.execute(...)

    Commits on success, rolls back on exception, always closes.
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_ticket_columns(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(tickets)").fetchall()}
    extra_columns = {
        "external_ref": "TEXT",
        "customer_id": "TEXT",
        "category": "TEXT",
        "channel": "TEXT",
        "metadata": "TEXT",
    }
    for name, definition in extra_columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE tickets ADD COLUMN {name} {definition}")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_external_ref ON tickets(external_ref)")


def _normalize_priority(priority: str | None) -> str:
    if not priority or not isinstance(priority, str):
        return "LOW"
    value = priority.strip().upper()
    if value in ("LOW", "MEDIUM", "HIGH"):
        return value
    if value in ("HIGH","HIGHER","P1","P0"):
        return "HIGH"
    if value in ("MEDIUM","MID","P2"):
        return "MEDIUM"
    return "LOW"


def _normalize_category(category: str | None) -> str:
    if not category or not isinstance(category, str):
        return "Other"
    normalized = category.strip().title()
    if normalized in {"Billing", "Technical", "Account", "Delivery", "Other"}:
        return normalized
    return "Other"


def _normalize_channel(channel: str | None) -> str:
    if not channel or not isinstance(channel, str):
        return "web_app"
    value = channel.strip().lower()
    if value in {"web_app", "mobile_app", "phone", "email", "other"}:
        return value
    return "web_app"


def _clean_email(email: str | None) -> str | None:
    if not email or not isinstance(email, str):
        return None
    clean = email.strip()
    if not clean:
        return None
    if re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", clean):
        return clean
    return None


def _clean_history_entry(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None

    customer = entry.get("customer") or {}
    if not isinstance(customer, dict):
        return None

    email = _clean_email(customer.get("email"))
    name = customer.get("name")
    subject = entry.get("subject")
    description = entry.get("description")
    if not email or not name or not subject or not description:
        return None

    priority = _normalize_priority(entry.get("priority"))
    category = _normalize_category(entry.get("category"))
    channel = _normalize_channel(entry.get("channel"))
    created_at = entry.get("created_at") or utc_now_iso()
    metadata = entry.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "external_ref": entry.get("external_ref") or _generate_external_ref(),
        "customer_id": customer.get("customer_id"),
        "customer_name": name.strip(),
        "customer_email": email,
        "title": subject.strip(),
        "description": description.strip(),
        "priority": priority,
        "category": category,
        "channel": channel,
        "created_at": created_at,
        "metadata": metadata,
    }


def _export_cleaned_csv(records: list[dict]) -> None:
    if not CLEANED_CSV.parent.exists():
        CLEANED_CSV.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "external_ref",
        "customer_id",
        "customer_name",
        "customer_email",
        "title",
        "description",
        "priority",
        "category",
        "channel",
        "created_at",
        "metadata",
    ]
    with CLEANED_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({
                **row,
                "metadata": json.dumps(row.get("metadata") or {}, ensure_ascii=False),
            })


def _generate_external_ref() -> str:
    if not HISTORY_FILE.exists():
        return "web-0001"
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "web-0001"
    if isinstance(data, list):
        return f"web-{len(data)+1:04d}"
    return "web-0001"


def _import_ticket_history(db: sqlite3.Connection) -> None:
    if not HISTORY_FILE.exists():
        return
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            history = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(history, list):
        return

    cleaned_records: list[dict] = []
    seen_signatures = set()

    for entry in history:
        cleaned = _clean_history_entry(entry)
        if cleaned is None:
            continue

        signature = (
            cleaned["customer_email"],
            cleaned["title"],
            cleaned["created_at"],
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        existing = db.execute(
            "SELECT 1 FROM tickets WHERE external_ref = ? OR (customer_email = ? AND title = ? AND created_at = ?)",
            (
                cleaned["external_ref"],
                cleaned["customer_email"],
                cleaned["title"],
                cleaned["created_at"],
            ),
        ).fetchone()
        if existing:
            continue

        db.execute(
            "INSERT INTO tickets (customer_name, customer_email, customer_id, title, description, priority, status, assigned_level, assigned_agent_id, assigned_agent_name, assigned_agent_email, created_at, resolved_at, external_ref, category, channel, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, 'OPEN', NULL, NULL, NULL, NULL, ?, NULL, ?, ?, ?, ?)",
            (
                cleaned["customer_name"],
                cleaned["customer_email"],
                cleaned["customer_id"],
                cleaned["title"],
                cleaned["description"],
                cleaned["priority"],
                cleaned["created_at"],
                cleaned["external_ref"],
                cleaned["category"],
                cleaned["channel"],
                json.dumps(cleaned["metadata"], ensure_ascii=False),
            ),
        )
        cleaned_records.append(cleaned)

    if cleaned_records:
        _export_cleaned_csv(cleaned_records)


def _append_ticket_history(ticket: dict) -> str:
    try:
        history = []
        if HISTORY_FILE.exists():
            with HISTORY_FILE.open("r", encoding="utf-8") as f:
                history = json.load(f) or []
        if not isinstance(history, list):
            history = []
    except (json.JSONDecodeError, OSError):
        history = []

    if not ticket.get("external_ref"):
        ticket["external_ref"] = _generate_external_ref()

    history.append({
        "external_ref": ticket["external_ref"],
        "customer": {
            "customer_id": ticket.get("customer_id"),
            "name": ticket["customer_name"],
            "email": ticket["customer_email"],
        },
        "subject": ticket["title"],
        "description": ticket["description"],
        "category": ticket.get("category"),
        "priority": ticket.get("priority"),
        "channel": ticket.get("channel"),
        "created_at": ticket.get("created_at"),
        "metadata": ticket.get("metadata") or {},
    })
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    return ticket["external_ref"]


def append_ticket_history(db: sqlite3.Connection, ticket: dict) -> None:
    if not ticket.get("external_ref"):
        ticket["external_ref"] = _generate_external_ref()
        db.execute(
            "UPDATE tickets SET external_ref = ? WHERE id = ?",
            (ticket["external_ref"], ticket["id"]),
        )
    _append_ticket_history(ticket)


def log_notification(
    db: sqlite3.Connection,
    ticket_id: int | None,
    notification_type: str,
    recipient: str,
    recipient_email: str,
    subject: str,
    body: str,
) -> None:
    db.execute(
        "INSERT INTO notification_logs (ticket_id, notification_type, recipient, recipient_email, subject, body, sent_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, notification_type, recipient, recipient_email, subject, body, utc_now_iso()),
    )


def init_db() -> None:
    """
    Create tables if they do not already exist. Safe to call every
    time the app starts.
    """
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name       TEXT NOT NULL,
                customer_email      TEXT NOT NULL,
                title               TEXT NOT NULL,
                description         TEXT NOT NULL,
                priority            TEXT NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH')),
                status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED')),
                assigned_level      TEXT,
                assigned_agent_id   TEXT,
                assigned_agent_name TEXT,
                assigned_agent_email TEXT,
                created_at          TEXT NOT NULL,
                resolved_at         TEXT
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL,
                action      TEXT NOT NULL,
                details     TEXT,
                timestamp   TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets (id)
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_logs (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id          INTEGER,
                notification_type TEXT NOT NULL,
                recipient          TEXT NOT NULL,
                recipient_email    TEXT NOT NULL,
                subject            TEXT NOT NULL,
                body               TEXT NOT NULL,
                sent_at            TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets (id)
            )
            """
        )

        _ensure_ticket_columns(db)
        _import_ticket_history(db)
        db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_audit_ticket_id ON audit_logs(ticket_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_notifications_sent_at ON notification_logs(sent_at)")

        # Ensure open imported tickets are assigned to the 7-agent roster.
        try:
            from app.services.assignment import assign_pending_tickets

            assigned = assign_pending_tickets(db)
            if assigned:
                print(f"Assigned {assigned} pending tickets during startup")
        except Exception:
            pass
