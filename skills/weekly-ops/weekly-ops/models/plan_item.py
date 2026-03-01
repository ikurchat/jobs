"""Data models for plan and report items."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums (subset from task-control)
# ---------------------------------------------------------------------------

class Status(str, Enum):
    DRAFT = "draft"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    HANDED_OVER = "handed_over"
    WAITING_INPUT = "waiting_input"


class PlanItemStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CARRIED_OVER = "carried_over"


class PeriodType(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class DocType(str, Enum):
    PLAN = "plan"
    REPORT = "report"


# ---------------------------------------------------------------------------
# PlanItem — single row in plan/report table
# ---------------------------------------------------------------------------

@dataclass
class PlanItem:
    """A single plan/report table row."""
    item_number: int = 0
    description: str = ""
    deadline: str = ""
    responsible: str = ""
    completion_note: str = ""
    status: PlanItemStatus = PlanItemStatus.PLANNED
    is_unplanned: bool = False
    linked_task_ids: list[int] = field(default_factory=list)
    baserow_row_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["linked_task_ids"] = list(self.linked_task_ids)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> PlanItem:
        status = data.get("status", "planned")
        if isinstance(status, str):
            try:
                status = PlanItemStatus(status)
            except ValueError:
                status = PlanItemStatus.PLANNED
        return cls(
            item_number=data.get("item_number", 0),
            description=data.get("description", ""),
            deadline=data.get("deadline", ""),
            responsible=data.get("responsible", ""),
            completion_note=data.get("completion_note", ""),
            status=status,
            is_unplanned=data.get("is_unplanned", False),
            linked_task_ids=data.get("linked_task_ids", []),
            baserow_row_id=data.get("baserow_row_id") or data.get("id"),
        )

    @classmethod
    def from_baserow(cls, row: dict) -> PlanItem:
        """Create from Baserow row (user_field_names=true)."""
        linked = row.get("linked_tasks", "")
        if isinstance(linked, str) and linked:
            try:
                linked_ids = [int(x.strip()) for x in linked.split(",") if x.strip()]
            except ValueError:
                linked_ids = []
        elif isinstance(linked, list):
            linked_ids = [x.get("id", x) if isinstance(x, dict) else int(x) for x in linked]
        else:
            linked_ids = []

        return cls(
            item_number=row.get("item_number", 0),
            description=row.get("description", ""),
            deadline=row.get("deadline", ""),
            responsible=row.get("responsible", ""),
            completion_note=row.get("completion_note", ""),
            status=PlanItemStatus(row.get("status", "planned")),
            is_unplanned=row.get("is_unplanned", False),
            linked_task_ids=linked_ids,
            baserow_row_id=row.get("id"),
        )


# ---------------------------------------------------------------------------
# ReportItem — enriched PlanItem with mark data
# ---------------------------------------------------------------------------

@dataclass
class ReportItem:
    """Plan item enriched with report mark and source info."""
    plan_item: PlanItem
    mark_text: str = ""
    mark_source: str = ""  # "memory", "auto", "manual"
    matched_tasks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = self.plan_item.to_dict()
        d["mark_text"] = self.mark_text
        d["mark_source"] = self.mark_source
        d["completion_note"] = self.mark_text or d.get("completion_note", "")
        return d
