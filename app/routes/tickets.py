"""
routes/tickets.py
------------------
API endpoints for the ticket lifecycle:
    POST /api/tickets            create + auto-assign a ticket
    GET  /api/tickets            list tickets (optional filters)
    GET  /api/tickets/{id}       fetch a single ticket
    PUT  /api/tickets/{id}/resolve   mark a ticket resolved
"""

import json
import logging
import sqlite3
from typing import Optional

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from app.database import append_ticket_history, get_db
from app.models import TicketCreateRequest, TicketResponse, TicketResolveRequest
from app.services import assignment, notifications, audit
from app.services.ml import predict_ticket
from app.utils import utc_now_iso

bp = Blueprint("tickets", __name__, url_prefix="/api/tickets")
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


def _fetch_ticket(db: sqlite3.Connection, ticket_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _row_to_dict(row) if row else None


@bp.route("", methods=["POST"])
def create_ticket():
    """
    Create a new ticket, auto-assign it to a support agent based on
    priority, write audit trail entries, and fire mock notifications.
    """
    try:
        payload_data = request.get_json(force=True)
    except BadRequest:
        raise BadRequest("Invalid JSON payload")

    try:
        payload = TicketCreateRequest.model_validate(payload_data)
    except Exception as exc:
        raise BadRequest(str(exc))

    # Try to predict category and priority from title/description using ML model.
    # If prediction fails or model not present, fall back to provided values.
    try:
        predicted_category, predicted_priority = predict_ticket(payload.title, payload.description)
    except Exception:
        predicted_category, predicted_priority = None, None

    try:
        with get_db() as db:
            created_at = utc_now_iso()
            duplicate = db.execute(
                "SELECT id FROM tickets WHERE customer_email = ? AND title = ? AND description = ? AND status = 'OPEN'",
                (
                    payload.customer_email,
                    payload.title,
                    payload.description,
                ),
            ).fetchone()
            if duplicate:
                raise Conflict(
                    description="A ticket with the same customer, title, and description is already open."
                )

            cursor = db.execute(
                """
                INSERT INTO tickets
                    (customer_name, customer_email, customer_id, title, description,
                     priority, category, channel, status, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """,
                (
                    payload.customer_name,
                    payload.customer_email,
                    payload.customer_id,
                    payload.title,
                    payload.description,
                    (predicted_priority or payload.priority.value),
                    (predicted_category or payload.category.value),
                    payload.channel.value,
                    created_at,
                    json.dumps(payload.metadata or {}, ensure_ascii=False),
                ),
            )
            ticket_id = cursor.lastrowid

            # Log using the final priority (predicted or provided)
            audit.log_ticket_created(db, ticket_id, (predicted_priority or payload.priority.value))

            # Attempt auto-assignment. If the agent roster is missing or
            # misconfigured, keep the ticket open/unassigned rather than
            # failing the whole request.
            try:
                # Use predicted priority (if available) for routing decisions
                assignment_info = assignment.auto_assign(db, (predicted_priority or payload.priority.value))
                db.execute(
                    """
                    UPDATE tickets
                    SET assigned_level = ?, assigned_agent_id = ?,
                        assigned_agent_name = ?, assigned_agent_email = ?
                    WHERE id = ?
                    """,
                    (
                        assignment_info["level"],
                        assignment_info["agent_id"],
                        assignment_info["agent_name"],
                        assignment_info["agent_email"],
                        ticket_id,
                    ),
                )
                audit.log_ticket_assigned(
                    db, ticket_id, assignment_info["level"], assignment_info["agent_name"]
                )
            except (assignment.NoAgentAvailableError, FileNotFoundError, ValueError) as exc:
                logger.error("Auto-assignment failed for ticket %s: %s", ticket_id, exc)
                audit.log_event(db, ticket_id, "Assignment Failed", str(exc))
                assignment_info = None

            ticket = _fetch_ticket(db, ticket_id)
            append_ticket_history(db, ticket)

        # Notifications happen after the transaction commits successfully.
        logger.info("Calling notify_ticket_created for ticket %s", ticket_id)
        notifications.notify_ticket_created(ticket)
        if assignment_info:
            logger.info("Calling notify_engineer_assigned for ticket %s", ticket_id)
            notifications.notify_engineer_assigned(ticket)

        return jsonify(ticket), 201

    except sqlite3.Error as exc:
        logger.exception("Database error while creating ticket")
        return jsonify({"detail": f"Database error: {exc}"}), 500


@bp.route("", methods=["GET"])
def list_tickets():
    status = request.args.get("status")
    priority = request.args.get("priority")

    query = "SELECT * FROM tickets WHERE 1=1"
    params: list = []

    if status:
        status_upper = status.upper()
        if status_upper not in ("OPEN", "RESOLVED"):
            raise BadRequest("status must be OPEN or RESOLVED")
        query += " AND status = ?"
        params.append(status_upper)

    if priority:
        priority_upper = priority.upper()
        if priority_upper not in ("LOW", "MEDIUM", "HIGH"):
            raise BadRequest("priority must be LOW, MEDIUM, or HIGH")
        query += " AND priority = ?"
        params.append(priority_upper)

    query += " ORDER BY created_at DESC"

    try:
        with get_db() as db:
            rows = db.execute(query, params).fetchall()
            return jsonify([_row_to_dict(r) for r in rows])
    except sqlite3.Error as exc:
        logger.exception("Database error while listing tickets")
        return jsonify({"detail": f"Database error: {exc}"}), 500


@bp.route("/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id: int):
    with get_db() as db:
        ticket = _fetch_ticket(db, ticket_id)
    if not ticket:
        raise NotFound(f"Ticket {ticket_id} not found")
    return jsonify(ticket)


@bp.route("/<int:ticket_id>/resolve", methods=["PUT"])
def resolve_ticket(ticket_id: int):
    """Mark a ticket resolved, log the audit trail, and notify the customer."""
    payload_data = request.get_json(silent=True) or {}
    try:
        payload = TicketResolveRequest.model_validate(payload_data)
    except Exception as exc:
        raise BadRequest(str(exc))

    try:
        with get_db() as db:
            ticket = _fetch_ticket(db, ticket_id)
            if not ticket:
                raise NotFound(f"Ticket {ticket_id} not found")

            if ticket["status"] == "RESOLVED":
                raise Conflict(f"Ticket {ticket_id} is already resolved")

            resolved_at = utc_now_iso()
            db.execute(
                "UPDATE tickets SET status = 'RESOLVED', resolved_at = ? WHERE id = ?",
                (resolved_at, ticket_id),
            )
            audit.log_ticket_resolved(db, ticket_id, payload.resolution_note or "")
            ticket = _fetch_ticket(db, ticket_id)

            # After resolving a ticket, try to promote and assign the next queued ticket.
            try:
                promoted_id = assignment.assign_next_queued_ticket(db)
            except Exception as exc:
                promoted_id = None

            promoted_ticket = None
            if promoted_id:
                promoted_ticket = _fetch_ticket(db, promoted_id)
                if promoted_ticket:
                    audit.log_ticket_assigned(db, promoted_id, promoted_ticket.get("assigned_level"), promoted_ticket.get("assigned_agent_name"))

        logger.info("Calling notify_ticket_resolved for ticket %s", ticket_id)
        notifications.notify_ticket_resolved(ticket)
        # Send notifications for the promoted ticket outside the DB transaction.
        if promoted_ticket:
            logger.info("Calling notify_engineer_assigned for promoted ticket %s", promoted_ticket.get('id'))
            notifications.notify_engineer_assigned(promoted_ticket)
        return jsonify(ticket)

    except sqlite3.Error as exc:
        logger.exception("Database error while resolving ticket")
        return jsonify({"detail": f"Database error: {exc}"}), 500
