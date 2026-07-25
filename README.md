# Support Ticket Automation System taryn

A complete, runnable localhost support ticket system: customers raise tickets
through a web form, tickets are automatically routed to the right support
tier based on priority, and admins get a live dashboard with stats and an
audit trail. Email notifications are mocked and printed to the terminal.

## Tech stack

- **Backend:** Flask (Python)
- **Database:** SQLite via the built-in `sqlite3` module (no ORM)
- **Frontend:** Plain HTML, CSS, and vanilla JavaScript (no build step)

## Project structure

```
support_ticket_system/
├── app/
│   ├── main.py                  Flask app, routing, static file mounts
│   ├── database.py              SQLite connection + schema setup
│   ├── models.py                response models
│   ├── utils.py                 Shared helpers (timestamps)
│   ├── data/
│   │   └── support_agents.json  Support agent roster (L1 / L2 / L3)
│   ├── routes/
│   │   ├── tickets.py           POST/GET/PUT ticket endpoints
│   │   └── dashboard.py         Dashboard stats + audit log endpoints
│   └── services/
│       ├── assignment.py        Routing rules + load-balanced auto-assign
│       ├── audit.py             Audit trail writer
│       └── notifications.py     Mock email service (prints to terminal)
├── static/
│   ├── css/style.css
│   └── js/
│       ├── customer.js          Raise-ticket form + ticket lookup
│       └── admin.js             Admin dashboard logic
├── templates/
│   ├── index.html               Customer page ("/")
│   └── admin.html                Admin dashboard ("/admin")
├── requirements.txt
└── README.md
```

`tickets.db` is created automatically in the project root the first time the
app starts — no manual setup required.

## Setup

```bash
# 1. From the project root, create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

- **Customer UI:** http://127.0.0.1:8000/
- **Support team UI:** http://127.0.0.1:8000/support
- **Admin dashboard:** http://127.0.0.1:8000/admin
- **Interactive API docs (Swagger):** http://127.0.0.1:8000/docs

Mock emails print directly to the terminal where uvicorn is running — keep
that window visible while you test.

## API reference

| Method | Path                          | Description                                   |
|--------|-------------------------------|------------------------------------------------|
| POST   | `/api/tickets`                 | Create a ticket, auto-assign it, notify        |
| GET    | `/api/tickets`                 | List tickets (`?status=`, `?priority=` filters) |
| GET    | `/api/tickets/{id}`            | Fetch a single ticket                          |
| PUT    | `/api/tickets/{id}/resolve`    | Mark a ticket resolved, notify the customer    |
| GET    | `/api/dashboard/stats`         | Aggregate counts + recent audit logs           |
| GET    | `/api/dashboard/audit-logs`    | Full audit log list (`?ticket_id=`, `?limit=`) |
                                 

### Create a ticket

```bash
curl -X POST http://127.0.0.1:8000/api/tickets \
  -H "Content-Type: application/json" \
  -d '{
        "customer_name": "Alice Johnson",
        "customer_email": "alice@example.com",
        "title": "Cannot login",
        "description": "Getting a 500 error when I try to log in.",
        "priority": "HIGH"
      }'
```

### Resolve a ticket

```bash
curl -X PUT http://127.0.0.1:8000/api/tickets/1/resolve \
  -H "Content-Type: application/json" \
  -d '{"resolution_note": "Restarted the auth service."}'
```

## Business logic

**Routing rules** (priority → support tier):

| Priority | Tier |
|----------|------|
| LOW      | L1   |
| MEDIUM   | L2   |
| HIGH     | L3   |

**Auto-assignment:** within the matched tier, the ticket goes to whichever
agent currently has the fewest OPEN tickets (simple load balancing read live
from SQLite). Edit `app/data/support_agents.json` to change the roster — it
is re-read on every ticket creation, so no restart is needed.

**Audit trail:** every ticket writes rows to the `audit_logs` table for
`Ticket Created`, `Ticket Assigned`, and `Ticket Resolved` (plus an
`Assignment Failed` entry if the agent roster is ever empty or invalid, so a
ticket is never silently lost). View them on the admin dashboard or via
`GET /api/dashboard/audit-logs`.

**Notifications (mocked):** printed to the terminal, not sent over the
network:
- Customer — when a ticket is created
- Engineer — when a ticket is assigned
- Customer — when a ticket is resolved

## Error handling & validation

- Pydantic validates all request bodies (required fields, email format,
  string length, enum values for `priority`) and returns `422` with a
  field-by-field error list on failure.
- `404` for ticket IDs that don't exist, `409` for resolving an
  already-resolved ticket.
- SQLite errors are caught and returned as clean `500` JSON responses
  instead of a stack trace; all writes for a single request run inside one
  transaction (commit on success, rollback on failure).
- A global exception handler guarantees the API never returns raw HTML or
  an unhandled traceback to the client.
- The frontend mirrors this with client-side validation (required fields,
  email format) before it ever calls the API.

## Notes

- The admin dashboard's ticket table includes a **"Mark resolved"** action
  per open ticket — a natural place to exercise the resolve endpoint from
  the UI, in addition to the API.
- Database file: SQLite stores everything in `tickets.db` in the project
  root. Delete this file (server stopped) to reset all data; it will be
  recreated automatically on next startup.
