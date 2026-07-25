"""
models.py
---------
Pydantic models used to validate incoming requests and shape outgoing
JSON responses. These are separate from the SQLite schema on purpose:
the DB layer stays plain sqlite3, and this layer is where validation
rules live.
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Status(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class Category(str, Enum):
    BILLING = "Billing"
    TECHNICAL = "Technical"
    ACCOUNT = "Account"
    DELIVERY = "Delivery"
    OTHER = "Other"


class Channel(str, Enum):
    WEB_APP = "web_app"
    MOBILE_APP = "mobile_app"
    PHONE = "phone"
    EMAIL = "email"
    OTHER = "other"


class TicketCreateRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=120)
    customer_email: EmailStr
    customer_id: Optional[str] = Field(default=None, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    category: Category = Category.OTHER
    priority: Priority
    channel: Channel = Channel.WEB_APP
    metadata: Optional[dict] = None

    @field_validator("customer_name", "title", "description")
    @classmethod
    def not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank or whitespace only")
        return stripped


class TicketResponse(BaseModel):
    id: int
    external_ref: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: str
    customer_email: str
    title: str
    description: str
    priority: str
    category: Optional[str] = None
    channel: Optional[str] = None
    metadata: Optional[dict] = None
    status: str
    assigned_level: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    assigned_agent_email: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None


class TicketResolveRequest(BaseModel):
    resolution_note: Optional[str] = Field(default=None, max_length=2000)


class AuditLogEntry(BaseModel):
    id: int
    ticket_id: int
    action: str
    details: Optional[str] = None
    timestamp: str


class AgentWorkloadEntry(BaseModel):
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    assigned_level: Optional[str] = None
    open_tickets: int


class DashboardStats(BaseModel):
    total_tickets: int
    open_tickets: int
    resolved_tickets: int
    tickets_by_priority: dict
    tickets_by_category: dict
    agent_workload: List[AgentWorkloadEntry]
    recent_audit_logs: List[AuditLogEntry]
    recent_tickets: List[TicketResponse]
