"""Enumerations for task-control skill."""

from enum import Enum


class TaskType(str, Enum):
    DELEGATE = "delegate"
    COLLAB = "collab"
    INFORM = "inform"
    BOSS_CONTROL = "boss_control"
    REPORT_UP = "report_up"
    REGULATORY = "regulatory"
    SKILL_UPDATE = "skill_update"
    PERSONAL = "personal"
    BACKLOG = "backlog"
    BOSS_DEADLINE = "boss_deadline"


class Status(str, Enum):
    DRAFT = "draft"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    HANDED_OVER = "handed_over"
    WAITING_INPUT = "waiting_input"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ControlLoop(str, Enum):
    DOWN = "down"
    UP = "up"
    REGULATORY = "regulatory"
    INTERNAL = "internal"


class OwnerAction(str, Enum):
    DELEGATE = "delegate"
    CHECK = "check"
    REPORT = "report"
    CLOSE = "close"
    NONE = "none"


class DeliveryMethod(str, Enum):
    YOUGILE = "yougile"
    EMAIL = "email"
    VERBAL = "verbal"
    MESSENGER = "messenger"
    PLAN = "plan"


class ScheduleType(str, Enum):
    SHIFT_12H = "shift_12h"
    OFFICE_5X2 = "office_5x2"


class ShiftType(str, Enum):
    DAY = "day"
    NIGHT = "night"
    REST = "rest"
    OFF = "off"


class PlanItemStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CARRIED_OVER = "carried_over"


class PeriodType(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class RegulatoryStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    OVERDUE = "overdue"


class Recurrence(str, Enum):
    ONE_TIME = "one_time"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ONGOING = "ongoing"


class EventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    STATUS_CHANGE = "status_change"
    DEADLINE_MOVED = "deadline_moved"
    HANDOVER = "handover"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    COMMENT = "comment"
