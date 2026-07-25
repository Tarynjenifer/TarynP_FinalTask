"""
assignment.py
-------------
Loads the support agent roster from support_agents.json and implements
the auto-assignment / routing logic.

Routing rule:
    LOW    -> L1
    MEDIUM -> L2
    HIGH   -> L3

Within a level, tickets are handed to whichever agent currently has
the fewest OPEN tickets assigned to them (simple load balancing). If
several agents are tied, the first one in the roster is used, which
also gives a round-robin effect for a freshly started system.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

AGENTS_FILE = Path(__file__).resolve().parent.parent / "data" / "support_agents.json"

PRIORITY_TO_LEVEL = {
    "LOW": "L1",
    "MEDIUM": "L2",
    "HIGH": "L3",
}


class NoAgentAvailableError(Exception):
    """Raised when no agent is configured for a routing level."""


def load_agents() -> dict:
    """
    Load the agent roster from disk. Re-reads the file on every call so
    that editing support_agents.json takes effect without a restart.
    """
    if not AGENTS_FILE.exists():
        raise FileNotFoundError(f"support_agents.json not found at {AGENTS_FILE}")

    with open(AGENTS_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"support_agents.json is not valid JSON: {exc}") from exc

    # Normalize two supported formats:
    # 1) { "L1": [ {"id":..., "name":..., "email":...}, ... ], "L2": ... }
    # 2) { "support_agents": [ {"agent_id":..., "name":..., "email":..., "level": "L1"}, ... ] }
    agents_by_level: dict = {"L1": [], "L2": [], "L3": []}

    if isinstance(data, dict) and "support_agents" in data and isinstance(data["support_agents"], list):
        for a in data["support_agents"]:
            lvl = a.get("level")
            if not lvl or lvl not in agents_by_level:
                continue
            agents_by_level[lvl].append(
                {
                    "id": a.get("agent_id") or a.get("id"),
                    "name": a.get("name"),
                    "email": a.get("email"),
                    "status": a.get("status", "available"),
                    "active_tickets": a.get("active_tickets", 0),
                    "max_capacity": a.get("max_capacity", 9999),
                }
            )
    elif isinstance(data, dict):
        # Assume top-level L1/L2/L3 mapping
        for lvl in ("L1", "L2", "L3"):
            items = data.get(lvl, [])
            if not isinstance(items, list):
                continue
            for a in items:
                agents_by_level[lvl].append(
                    {
                        "id": a.get("id") or a.get("agent_id"),
                        "name": a.get("name"),
                        "email": a.get("email"),
                        "status": a.get("status", "available"),
                        "active_tickets": a.get("active_tickets", 0),
                        "max_capacity": a.get("max_capacity", 9999),
                    }
                )
    else:
        raise ValueError("Unsupported support_agents.json structure")

    # Ensure each level has at least one configured agent
    for level in ("L1", "L2", "L3"):
        if len(agents_by_level[level]) == 0:
            raise ValueError(f"support_agents.json must define a non-empty list for '{level}'")

    return agents_by_level


def get_agent_ids() -> set[str]:
    roster = load_agents()
    return {agent["id"] for agents in roster.values() for agent in agents if agent.get("id")}


def _normalize_capacity(value) -> int:
    try:
        capacity = int(value)
    except (TypeError, ValueError):
        capacity = 0
    return max(capacity, 1)


def _current_ticket_load(db: sqlite3.Connection, agent: dict) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM tickets WHERE assigned_agent_id = ? AND status = 'OPEN'",
        (agent["id"],),
    ).fetchone()
    current_open = row["cnt"] if row else 0
    return current_open + int(agent.get("active_tickets", 0) or 0)


def _agent_utilization(db: sqlite3.Connection, agent: dict) -> float:
    """Utilization is active tickets divided by max capacity."""
    capacity = _normalize_capacity(agent.get("max_capacity"))
    return _current_ticket_load(db, agent) / capacity


def _eligible_agents(db: sqlite3.Connection, level: str, allow_overflow: bool = False) -> list[dict]:
    agents = [agent for agent in load_agents().get(level, []) if agent.get("status") == "available"]
    eligible = []
    for agent in agents:
        current_load = _current_ticket_load(db, agent)
        capacity = _normalize_capacity(agent.get("max_capacity"))
        if allow_overflow and level == "L3":
            if current_load <= capacity + 1:
                eligible.append(
                    {
                        **agent,
                        "current_load": current_load,
                        "capacity": capacity,
                        "utilization": current_load / capacity,
                    }
                )
        elif current_load < capacity:
            eligible.append(
                {
                    **agent,
                    "current_load": current_load,
                    "capacity": capacity,
                    "utilization": current_load / capacity,
                }
            )
    return sorted(eligible, key=lambda a: (a["utilization"], a["current_load"]))


def level_for_priority(priority: str) -> str:
    level = PRIORITY_TO_LEVEL.get(priority.upper())
    if not level:
        raise ValueError(f"Unknown priority '{priority}'")
    return level


HIGH_PRIORITY_KEYWORDS = {
    "urgent",
    "immediately",
    "asap",
    "cannot",
    "can't",
    "unable",
    "hacked",
    "refund",
    "charged twice",
    "payment",
    "account hacked",
    "server error",
    "crashes",
    "crash",
    "not able",
}
MEDIUM_PRIORITY_KEYWORDS = {
    "issue",
    "problem",
    "not working",
    "unable to",
    "slow",
    "checkout",
    "notifications",
    "delivery",
    "delay",
}


def predict_priority(title: str, description: str) -> str:
    content = f"{title} {description}".lower()
    if any(word in content for word in HIGH_PRIORITY_KEYWORDS):
        return "HIGH"
    if any(word in content for word in MEDIUM_PRIORITY_KEYWORDS):
        return "MEDIUM"
    return "LOW"


def _select_best_agent(db: sqlite3.Connection, level: str, allow_overflow: bool = False) -> dict:
    candidates = _eligible_agents(db, level, allow_overflow=allow_overflow)
    if not candidates:
        raise NoAgentAvailableError(f"No available agents for level {level}")
    return candidates[0]


def _assign_or_queue(db: sqlite3.Connection, level: str) -> dict:
    try:
        agent = _select_best_agent(db, level)
        return {
            "level": level,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "agent_email": agent["email"],
            "queued": False,
        }
    except NoAgentAvailableError:
        fallback_levels = []
        if level == "L1":
            fallback_levels = ["L2", "L3"]
        elif level == "L2":
            fallback_levels = ["L3"]

        for fallback in fallback_levels:
            try:
                agent = _select_best_agent(db, fallback)
                return {
                    "level": fallback,
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "agent_email": agent["email"],
                    "queued": False,
                }
            except NoAgentAvailableError:
                continue

        if level == "L3":
            try:
                agent = _select_best_agent(db, "L3", allow_overflow=True)
                return {
                    "level": "L3",
                    "agent_id": agent["id"],
                    "agent_name": agent["name"],
                    "agent_email": agent["email"],
                    "queued": False,
                    "overflow": True,
                }
            except NoAgentAvailableError:
                pass

        return {
            "level": level,
            "agent_id": None,
            "agent_name": f"Queued for {level}",
            "agent_email": "queue@swiftdesk.com",
            "queued": True,
        }


def auto_assign(db: sqlite3.Connection, priority: str) -> dict:
    """
    Full routing + assignment step for a given ticket priority.
    Returns a dict with level and agent details.
    """
    level = level_for_priority(priority)
    assignment = _assign_or_queue(db, level)
    return {
        "level": assignment["level"],
        "agent_id": assignment.get("agent_id"),
        "agent_name": assignment.get("agent_name"),
        "agent_email": assignment.get("agent_email"),
        "queued": assignment.get("queued", False),
    }


def _queue_sort_key(row: sqlite3.Row) -> tuple:
    priority_rank = {
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }.get(row["priority"].upper(), 4)
    return (priority_rank, row["created_at"])


def assign_pending_tickets(db: sqlite3.Connection) -> int:
    """Assign any open tickets that are still unassigned."""
    rows = db.execute(
        "SELECT id, priority, created_at FROM tickets WHERE status = 'OPEN' AND (assigned_agent_id IS NULL OR assigned_agent_id = '')"
    ).fetchall()
    queued = sorted(rows, key=_queue_sort_key)
    assigned_count = 0
    for row in queued:
        ticket_id = row["id"]
        assignment = _assign_or_queue(db, level_for_priority(row["priority"]))
        db.execute(
            "UPDATE tickets SET assigned_level = ?, assigned_agent_id = ?, assigned_agent_name = ?, assigned_agent_email = ? WHERE id = ?",
            (
                assignment["level"],
                assignment.get("agent_id"),
                assignment.get("agent_name"),
                assignment.get("agent_email"),
                ticket_id,
            ),
        )
        if not assignment.get("queued", False):
            assigned_count += 1
    return assigned_count


def assign_next_queued_ticket(db: sqlite3.Connection) -> bool:
    """Assign the highest-priority queued ticket after a resolution."""
    rows = db.execute(
        "SELECT id, priority FROM tickets WHERE status = 'OPEN' AND (assigned_agent_id IS NULL OR assigned_agent_id = '') ORDER BY CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END, created_at"
    ).fetchall()
    for row in rows:
        assignment = _assign_or_queue(db, level_for_priority(row["priority"]))
        if not assignment.get("queued", False):
            db.execute(
                "UPDATE tickets SET assigned_level = ?, assigned_agent_id = ?, assigned_agent_name = ?, assigned_agent_email = ? WHERE id = ?",
                (
                    assignment["level"],
                    assignment.get("agent_id"),
                    assignment.get("agent_name"),
                    assignment.get("agent_email"),
                    row["id"],
                ),
            )
            return True
    return False
