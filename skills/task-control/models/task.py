"""Pydantic models matching Baserow schema from ТЗ section 8."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from models.enums import (
    ControlLoop,
    DeliveryMethod,
    EventType,
    OwnerAction,
    PeriodType,
    PlanItemStatus,
    Priority,
    Recurrence,
    RegulatoryStatus,
    ScheduleType,
    ShiftType,
    Status,
    TaskType,
)


@dataclass
class Employee:
    id: int | None = None
    fio: str = ""
    position: str = ""
    schedule_type: ScheduleType = ScheduleType.OFFICE_5X2
    zone: str = ""
    strengths: str = ""
    telegram: str = ""
    phone_internal: str = ""
    email: str = ""
    active: bool = True


@dataclass
class ShiftSchedule:
    id: int | None = None
    employee: int | None = None  # link_row ID
    date: date | None = None
    shift_type: ShiftType = ShiftType.DAY
    shift_start: str = ""
    shift_end: str = ""
    month: str = ""  # YYYY-MM


@dataclass
class Task:
    id: int | None = None
    source_date: date | None = None
    source_text: str = ""
    task_type: TaskType = TaskType.DELEGATE
    control_loop: ControlLoop = ControlLoop.DOWN
    title: str = ""
    description: str = ""
    assignee: int | None = None  # link_row ID
    owner_action: OwnerAction = OwnerAction.NONE
    priority: Priority = Priority.NORMAL
    status: Status = Status.DRAFT
    delivery_method: DeliveryMethod | None = None
    assigned_date: datetime | None = None
    deadline: datetime | None = None
    completed_date: datetime | None = None
    assigned_shift: int | None = None  # link_row ID
    result: str = ""
    delay_reason: str = ""
    handed_to: int | None = None  # link_row ID
    parent_task: int | None = None  # link_row ID
    depends_on: int | None = None  # link_row ID
    plan_item: int | None = None  # link_row ID
    is_unplanned: bool = False
    boss_deadline: date | None = None
    regulatory_ref: str = ""
    notes: str = ""


@dataclass
class PlanItem:
    id: int | None = None
    period_type: PeriodType = PeriodType.WEEKLY
    period_start: date | None = None
    period_end: date | None = None
    item_number: int = 0
    description: str = ""
    deadline: str = ""
    responsible: list[int] = field(default_factory=list)  # link_row IDs
    status: PlanItemStatus = PlanItemStatus.PLANNED
    completion_note: str = ""
    linked_tasks: list[int] = field(default_factory=list)  # link_row IDs
    source_doc: str = ""


@dataclass
class RegulatoryTrack:
    id: int | None = None
    regulation: str = ""
    requirement: str = ""
    responsible: int | None = None  # link_row ID
    deadline: date | None = None
    status: RegulatoryStatus = RegulatoryStatus.NOT_STARTED
    recurrence: Recurrence = Recurrence.ONE_TIME
    next_check: date | None = None
    linked_tasks: list[int] = field(default_factory=list)
    notes: str = ""


@dataclass
class TaskLog:
    id: int | None = None
    task: int | None = None  # link_row ID
    timestamp: datetime | None = None
    event_type: EventType = EventType.CREATED
    old_value: str = ""
    new_value: str = ""
    comment: str = ""


@dataclass
class SkillUpdate:
    id: int | None = None
    source_task: int | None = None  # link_row ID
    skill_name: str = ""
    rule_text: str = ""
    applied: bool = False
    applied_date: date | None = None


@dataclass
class Setting:
    key: str = ""
    value: str = ""
