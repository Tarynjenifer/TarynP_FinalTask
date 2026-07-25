"""
routes/dashboard.py
--------------------
Read-only endpoints that power the admin dashboard: aggregate ticket
counts and the most recent audit trail entries.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest

from app.database import get_db
from app.models import AgentWorkloadEntry, DashboardStats
from app.services.notifications import send_admin_report

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")
logger = logging.getLogger("ticket_system")


def _row_to_dict(row: sqlite3.Row) -> dict:
    ticket = dict(row)
    metadata = ticket.get("metadata")
    if isinstance(metadata, str):
        try:
            ticket["metadata"] = json.loads(metadata)
        except json.JSONDecodeError:
            ticket["metadata"] = {}
    return ticket


@bp.route("/stats", methods=["GET"])
def get_dashboard_stats():
    try:
        recent_logs = request.args.get("recent_logs", "15")
        try:
            recent_logs = int(recent_logs)
        except ValueError:
            raise BadRequest("recent_logs must be a number")

        with get_db() as db:
            total = db.execute("SELECT COUNT(*) AS cnt FROM tickets").fetchone()["cnt"]
            open_count = db.execute(
                "SELECT COUNT(*) AS cnt FROM tickets WHERE status = 'OPEN'"
            ).fetchone()["cnt"]
            resolved_count = db.execute(
                "SELECT COUNT(*) AS cnt FROM tickets WHERE status = 'RESOLVED'"
            ).fetchone()["cnt"]

            priority_rows = db.execute(
                "SELECT priority, COUNT(*) AS cnt FROM tickets GROUP BY priority"
            ).fetchall()
            tickets_by_priority = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
            for row in priority_rows:
                tickets_by_priority[row["priority"]] = row["cnt"]

            category_rows = db.execute(
                "SELECT category, COUNT(*) AS cnt FROM tickets GROUP BY category"
            ).fetchall()
            tickets_by_category = {"Billing": 0, "Technical": 0, "Account": 0, "Delivery": 0, "Other": 0}
            for row in category_rows:
                tickets_by_category[row["category"] or "Other"] = row["cnt"]

            workload_rows = db.execute(
                "SELECT assigned_level, assigned_agent_id, assigned_agent_name, COUNT(*) AS cnt "
                "FROM tickets WHERE assigned_agent_id IS NOT NULL AND status = 'OPEN' "
                "GROUP BY assigned_agent_id, assigned_level, assigned_agent_name"
            ).fetchall()
            agent_workload = [
                {
                    "agent_id": row["assigned_agent_id"],
                    "agent_name": row["assigned_agent_name"],
                    "assigned_level": row["assigned_level"],
                    "open_tickets": row["cnt"],
                }
                for row in workload_rows
            ]

            recent_ticket_rows = db.execute(
                "SELECT * FROM tickets ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

            log_rows = db.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                (recent_logs,),
            ).fetchall()

            return jsonify({
                "total_tickets": total,
                "open_tickets": open_count,
                "resolved_tickets": resolved_count,
                "tickets_by_priority": tickets_by_priority,
                "tickets_by_category": tickets_by_category,
                "agent_workload": agent_workload,
                "recent_audit_logs": [dict(r) for r in log_rows],
                "recent_tickets": [_row_to_dict(r) for r in recent_ticket_rows],
            })
    except sqlite3.Error as exc:
        logger.exception("Database error while building dashboard stats")
        return jsonify({"detail": f"Database error: {exc}"}), 500


def _build_daily_report(db: sqlite3.Connection) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    tickets_today = db.execute(
        "SELECT COUNT(*) AS cnt FROM tickets WHERE date(created_at) = ?",
        (today,),
    ).fetchone()["cnt"]
    open_count = db.execute("SELECT COUNT(*) AS cnt FROM tickets WHERE status = 'OPEN'").fetchone()["cnt"]
    resolved_count = db.execute("SELECT COUNT(*) AS cnt FROM tickets WHERE status = 'RESOLVED'").fetchone()["cnt"]

    priority_rows = db.execute(
        "SELECT priority, COUNT(*) AS cnt FROM tickets GROUP BY priority"
    ).fetchall()
    tickets_by_priority = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for row in priority_rows:
        tickets_by_priority[row["priority"]] = row["cnt"]

    report_lines = [
        "End-of-day ticket raise analysis",
        "--------------------------------",
        f"Date: {today}",
        f"Total tickets in system: {open_count + resolved_count}",
        f"Open tickets: {open_count}",
        f"Resolved tickets: {resolved_count}",
        f"Tickets created today: {tickets_today}",
        "",
        "Tickets by priority:",
    ]
    for priority in ("HIGH", "MEDIUM", "LOW"):
        report_lines.append(f"  {priority}: {tickets_by_priority[priority]}")

    report_lines.append("")
    report_lines.append("Recent activity:")
    recent = db.execute(
        "SELECT ticket_id, action, details, timestamp FROM audit_logs ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if recent:
        for row in recent:
            report_lines.append(
                f"  {row['timestamp']} — Ticket #{row['ticket_id']} — {row['action']} — {row['details']}"
            )
    else:
        report_lines.append("  No audit activity available.")

    return "\n".join(report_lines)


@bp.route("/daily-report", methods=["POST"])
def send_daily_report():
    admin_email = os.getenv("ADMIN_EMAIL")
    if not admin_email:
        return jsonify({"detail": "ADMIN_EMAIL environment variable is required to send end-of-day reports."}), 500

    try:
        with get_db() as db:
            report_body = _build_daily_report(db)
            send_admin_report(admin_email, report_body)
            return jsonify({"status": "sent", "admin_email": admin_email})
    except sqlite3.Error as exc:
        logger.exception("Database error while generating daily report")
        return jsonify({"detail": f"Database error: {exc}"}), 500
    except Exception as exc:
        logger.exception("Failed to send daily report")
        return jsonify({"detail": f"Failed to send report: {exc}"}), 500


@bp.route("/audit-logs", methods=["GET"])
def get_audit_logs():
    ticket_id = request.args.get("ticket_id")
    limit_value = request.args.get("limit", "50")

    try:
        limit = int(limit_value)
    except ValueError:
        raise BadRequest("limit must be an integer")

    query = "SELECT * FROM audit_logs"
    params: list = []
    if ticket_id is not None:
        query += " WHERE ticket_id = ?"
        params.append(ticket_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    try:
        with get_db() as db:
            rows = db.execute(query, params).fetchall()
            return jsonify([dict(r) for r in rows])
    except sqlite3.Error as exc:
        logger.exception("Database error while fetching audit logs")
        return jsonify({"detail": f"Database error: {exc}"}), 500
