from enum import Enum


class Priority(str, Enum):
    CRITICAL = "critical"     # 9-10: VIP-руководитель, срочные поручения
    HIGH = "high"             # 7-8: контроль, сроки, важные отправители
    MEDIUM = "medium"         # 4-6: рабочая переписка
    LOW = "low"               # 1-3: информационные, рассылки
    SPAM = "spam"             # 0: спам, маркетинг


class Category(str, Enum):
    SED = "sed"               # СЭД: поручения, согласования, контроль
    TASK = "task"             # Прямые поручения/задачи
    REPORT = "report"         # Отчёты, справки, аналитика
    INCIDENT = "incident"     # Инциденты ИБ, алерты
    INFO = "info"             # Информационные письма
    MEETING = "meeting"       # Совещания, встречи
    EXTERNAL = "external"     # Внешние контрагенты
    PERSONAL = "personal"     # Личное
    NEWSLETTER = "newsletter" # Рассылки, дайджесты


class EmailStatus(str, Enum):
    NEW = "new"
    NOTIFIED = "notified"           # Уведомил owner'а
    REVIEWED = "reviewed"           # Owner посмотрел
    TASK_CREATED = "task_created"   # Создана задача в task-control
    REPLIED = "replied"             # Ответ отправлен
    ARCHIVED = "archived"           # В архив
    IGNORED = "ignored"             # Пропущено по решению owner'а


class OwnerAction(str, Enum):
    CREATE_TASK = "create_task"     # Создать задачу
    REPLY = "reply"                 # Подготовить ответ
    FORWARD = "forward"             # Переслать кому-то
    ARCHIVE = "archive"             # В архив
    IGNORE = "ignore"               # Пропустить
    ESCALATE = "escalate"           # Эскалировать руководству
    DELEGATE = "delegate"           # Делегировать подчинённому
    MONITOR = "monitor"             # На контроле (отслеживать)


class PatternType(str, Enum):
    SENDER = "sender"               # По отправителю
    SUBJECT_KEYWORD = "subject_kw"  # По ключевому слову в теме
    DOMAIN = "domain"               # По домену отправителя
    CATEGORY = "category"           # По категории
    COMBINED = "combined"           # Комбинированное правило
