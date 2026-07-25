"""Test queue promotion end-to-end.

Creates one assigned ticket and one queued ticket, resolves the assigned
ticket, invokes the queue promotion, triggers notifications, and prints
the last notification_logs rows.
"""
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `import app` works when running
# this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_db
from app.services import assignment as assign_service
from app.services import audit, notifications
from app.services.assignment import load_agents
from app.utils import utc_now_iso


def row_to_dict(row):
    return dict(row) if row is not None else None


def main():
    print("Starting queue promotion test...")

    with get_db() as db:
        agents = load_agents()
        # pick first agent available from any level
        first = None
        for lvl in ("L1", "L2", "L3"):
            if agents.get(lvl):
                first = agents[lvl][0]
                break
        if not first:
            raise SystemExit("No agents configured in support_agents.json")

        agent_id = first.get("id")
        agent_name = first.get("name")
        agent_email = first.get("email")

        # Create an assigned ticket (this will be resolved)
        now = utc_now_iso()
        cur = db.execute(
            """
            INSERT INTO tickets (customer_name, customer_email, title, description, priority, category, channel, status, created_at, assigned_level, assigned_agent_id, assigned_agent_name, assigned_agent_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)
            """,
            (
                "Test User",
                "testuser@example.com",
                "Assigned ticket - will resolve",
                "This ticket is created to be resolved in the test.",
                "LOW",
                "Other",
                "web_app",
                now,
                "L1",
                agent_id,
                agent_name,
                agent_email,
            ),
        )
        assigned_id = cur.lastrowid
        audit.log_ticket_created(db, assigned_id, "LOW")

        # Create a queued ticket (no assigned agent)
        cur2 = db.execute(
            """
            INSERT INTO tickets (customer_name, customer_email, title, description, priority, category, channel, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                "Queued User",
                "queued@example.com",
                "Queued ticket - should be promoted",
                "This ticket should be assigned when capacity frees up.",
                "HIGH",
                "Technical",
                "web_app",
                utc_now_iso(),
            ),
        )
        queued_id = cur2.lastrowid
        audit.log_ticket_created(db, queued_id, "HIGH")

    # Now resolve the assigned ticket and trigger promotion
    with get_db() as db:
        db.execute("UPDATE tickets SET status = 'RESOLVED', resolved_at = ? WHERE id = ?", (utc_now_iso(), assigned_id))
        audit.log_ticket_resolved(db, assigned_id, "Test resolution")
        promoted = assign_service.assign_next_queued_ticket(db)

    # After commit, fetch records and trigger notifications (which also log sends)
    with get_db() as db:
        resolved_ticket = row_to_dict(db.execute("SELECT * FROM tickets WHERE id = ?", (assigned_id,)).fetchone())
        promoted_ticket = row_to_dict(db.execute("SELECT * FROM tickets WHERE id = ?", (promoted,)).fetchone()) if promoted else None

    print("Triggering notifications (mock or SMTP based on env)...")
    if resolved_ticket:
        notifications.notify_ticket_resolved(resolved_ticket)
    if promoted_ticket:
        notifications.notify_engineer_assigned(promoted_ticket)

    # Print recent notification logs
    with get_db() as db:
        rows = db.execute("SELECT id, ticket_id, notification_type, recipient, recipient_email, subject, sent_at FROM notification_logs ORDER BY id DESC LIMIT 10").fetchall()
        print("\nRecent notification logs:")
        for r in rows:
            print(dict(r))


if __name__ == "__main__":
    main()
