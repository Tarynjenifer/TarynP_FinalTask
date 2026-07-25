"""
notifications.py
-----------------
A mock email service. Instead of sending real email, it prints a
formatted notification to the terminal so the full workflow can be
observed while the server is running.
"""

from datetime import datetime
import os
import smtplib
import sqlite3
from email.message import EmailMessage

from app.database import get_db, log_notification


def _print_email(to_email: str, to_name: str, subject: str, body: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print(f"[MOCK EMAIL]  {timestamp}")
    print(f"To      : {to_name} <{to_email}>")
    print(f"Subject : {subject}")
    print("-" * 60)
    print(body)
    print("=" * 60 + "\n")


def _send_smtp(to_email: str, to_name: str, subject: str, body: str) -> None:
    """
    Send email via SMTP using environment variables. If any required
    SMTP settings are missing, this raises ValueError.
    Required env vars: SMTP_HOST, SMTP_PORT
    Optional: SMTP_USER, SMTP_PASS, EMAIL_FROM
    """
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    if not host or not port:
        raise ValueError("SMTP_HOST and SMTP_PORT must be set to send real email")

    msg = EmailMessage()
    msg["Subject"] = subject
    from_addr = os.getenv("EMAIL_FROM", f"support@{host}")
    msg["From"] = from_addr
    msg["To"] = f"{to_name} <{to_email}>"
    msg.set_content(body)

    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")

    with smtplib.SMTP(host, int(port), timeout=10) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)


def _deliver(to_email: str, to_name: str, subject: str, body: str) -> None:
    """Choose SMTP delivery when configured, otherwise print mock email."""
    try:
        if os.getenv("SMTP_HOST") and os.getenv("SMTP_PORT"):
            _send_smtp(to_email, to_name, subject, body)
        else:
            _print_email(to_email, to_name, subject, body)
    except Exception as exc:
        # Never raise from notifications — log to stdout so the dev can see it
        print(f"[EMAIL ERROR] Failed to deliver to {to_email}: {exc}")


def send_admin_report(admin_email: str, report_body: str) -> None:
    subject = "End-of-day ticket raise analysis"
    _deliver(admin_email, "Admin", subject, report_body)
    try:
        with get_db() as db:
            log_notification(
                db,
                None,
                "Admin Report",
                "Admin",
                admin_email,
                subject,
                report_body,
            )
    except sqlite3.Error:
        pass


def notify_ticket_created(ticket: dict) -> None:
    subject = f"Ticket #{ticket['id']} received: {ticket['title']}"
    body = (
        f"Hi {ticket['customer_name']},\n\n"
        f"We've received your support ticket and logged it as #{ticket['id']}.\n"
        f"Priority: {ticket['priority']}\n\n"
        f"Description:\n{ticket['description']}\n\n"
        f"We'll notify you again once an engineer has been assigned.\n\n"
        f"- Support Team"
    )
    _deliver(ticket["customer_email"], ticket["customer_name"], subject, body)
    try:
        with get_db() as db:
            log_notification(
                db,
                ticket["id"],
                "Ticket Created",
                ticket["customer_name"],
                ticket["customer_email"],
                subject,
                body,
            )
    except sqlite3.Error:
        pass


def notify_engineer_assigned(ticket: dict) -> None:
    subject = f"New ticket assigned: #{ticket['id']} ({ticket['priority']})"
    body = (
        f"Hi {ticket['assigned_agent_name']},\n\n"
        f"Ticket #{ticket['id']} has been assigned to you at level "
        f"{ticket['assigned_level']}.\n\n"
        f"Title: {ticket['title']}\n"
        f"Priority: {ticket['priority']}\n"
        f"Customer: {ticket['customer_name']} ({ticket['customer_email']})\n\n"
        f"Description:\n{ticket['description']}\n\n"
        f"- Ticketing System"
    )
    _deliver(ticket["assigned_agent_email"], ticket["assigned_agent_name"], subject, body)
    try:
        with get_db() as db:
            log_notification(
                db,
                ticket["id"],
                "Ticket Assigned",
                ticket["assigned_agent_name"],
                ticket["assigned_agent_email"],
                subject,
                body,
            )
    except sqlite3.Error:
        pass


def notify_ticket_resolved(ticket: dict) -> None:
    subject = f"Ticket #{ticket['id']} resolved: {ticket['title']}"
    body = (
        f"Hi {ticket['customer_name']},\n\n"
        f"Good news! Your ticket #{ticket['id']} has been marked as resolved "
        f"by {ticket.get('assigned_agent_name') or 'our support team'}.\n\n"
        f"Title: {ticket['title']}\n\n"
        f"If the issue persists, feel free to raise a new ticket.\n\n"
        f"- Support Team"
    )
    _deliver(ticket["customer_email"], ticket["customer_name"], subject, body)
