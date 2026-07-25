"""
routes/support.py
------------------
Support team endpoints for engineer-facing ticket lists and assignment status.
"""

import json
import logging
import sqlite3
from typing import Optional

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest

from app.database import get_db
from app.models import TicketResponse

bp = Blueprint("support", __name__, url_prefix="/api/support")
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


@bp.route("/tickets", methods=["GET"])
def get_support_tickets():
    level = request.args.get("level")
    status = request.args.get("status")

    query = "SELECT * FROM tickets WHERE 1=1"
    params: list = []

    if level:
        level_upper = level.upper()
        if level_upper not in ("L1", "L2", "L3"):
            raise BadRequest("level must be L1, L2, or L3")
        query += " AND assigned_level = ?"
        params.append(level_upper)

    if status:
        status_upper = status.upper()
        if status_upper not in ("OPEN", "RESOLVED"):
            raise BadRequest("status must be OPEN or RESOLVED")
        query += " AND status = ?"
        params.append(status_upper)

    query += " ORDER BY created_at DESC"

    try:
        with get_db() as db:
            rows = db.execute(query, params).fetchall()
            return jsonify([_row_to_dict(r) for r in rows])
    except sqlite3.Error as exc:
        logger.exception("Database error while listing support tickets")
        return jsonify({"detail": f"Database error: {exc}"}), 500
