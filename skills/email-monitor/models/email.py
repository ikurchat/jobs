from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .enums import Priority, Category, EmailStatus, OwnerAction, PatternType


@dataclass
class Email:
    message_id: str = ""
    thread_id: str = ""
    sender: str = ""
    sender_name: str = ""
    to: str = ""
    cc: str = ""
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    body_preview: str = ""          # первые 500 символов
    received_at: Optional[datetime] = None
    priority: Priority = Priority.MEDIUM
    priority_score: int = 5
    category: Category = Category.INFO
    status: EmailStatus = EmailStatus.NEW
    proposed_action: OwnerAction = OwnerAction.ARCHIVE
    owner_decision: Optional[OwnerAction] = None
    task_id: Optional[int] = None   # ID задачи в task-control
    has_attachments: bool = False
    attachment_names: list = field(default_factory=list)
    attachment_paths: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    is_reply: bool = False
    baserow_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "subject": self.subject,
            "body_preview": self.body_preview,
            "received_at": self.received_at.isoformat() if self.received_at else "",
            "priority": self.priority.value,
            "priority_score": self.priority_score,
            "category": self.category.value,
            "status": self.status.value,
            "proposed_action": self.proposed_action.value,
            "owner_decision": self.owner_decision.value if self.owner_decision else "",
            "task_id": self.task_id or "",
            "has_attachments": self.has_attachments,
            "attachment_names": ", ".join(self.attachment_names),
            "attachment_paths": self.attachment_paths,
            "is_reply": self.is_reply,
        }


@dataclass
class Feedback:
    """Запись обратной связи owner'а для обучения."""
    id: Optional[int] = None
    sender_email: str = ""
    sender_name: str = ""
    pattern_type: PatternType = PatternType.SENDER
    pattern_value: str = ""         # email, keyword, domain
    learned_priority: Optional[Priority] = None
    learned_category: Optional[Category] = None
    learned_action: Optional[OwnerAction] = None
    confidence: float = 0.5         # 0.0-1.0, растёт с каждым подтверждением
    times_confirmed: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "sender_email": self.sender_email,
            "sender_name": self.sender_name,
            "pattern_type": self.pattern_type.value,
            "pattern_value": self.pattern_value,
            "learned_priority": self.learned_priority.value if self.learned_priority else "",
            "learned_category": self.learned_category.value if self.learned_category else "",
            "learned_action": self.learned_action.value if self.learned_action else "",
            "confidence": self.confidence,
            "times_confirmed": self.times_confirmed,
        }


@dataclass
class SenderProfile:
    """Профиль отправителя, собранный из feedback."""
    email: str = ""
    name: str = ""
    domain: str = ""
    default_priority: Priority = Priority.MEDIUM
    default_category: Category = Category.INFO
    default_action: OwnerAction = OwnerAction.ARCHIVE
    is_vip: bool = False
    total_emails: int = 0
    total_feedbacks: int = 0
    confidence: float = 0.0
    notes: str = ""
