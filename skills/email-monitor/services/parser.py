"""Парсер и обогащение писем.

Извлекает структурированные данные, определяет тип контента,
готовит данные для классификатора и представления owner'у.
Обрабатывает форвардированные письма и HTML-контент СЭД.

CLI: python -m services.parser parse --email email.json
     python -m services.parser summary --email email.json
     python -m services.parser extract_tasks --email email.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import load_config, output_json, output_error


def _strip_html(html: str) -> str:
    """Очищает HTML до читаемого текста."""
    if not html:
        return ""
    # Заменяем <br>, <p>, <tr> на перенос строки
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|tr|div|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:td|th)[^>]*>", " | ", text, flags=re.IGNORECASE)
    # Удаляем style и script блоки целиком
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Удаляем оставшиеся теги
    text = re.sub(r"<[^>]+>", "", text)
    # Декодируем HTML-сущности
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    # Чистим лишние пробелы
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _parse_forwarded_headers(text: str) -> dict:
    """Извлекает реального отправителя и метаданные из форвардированного письма."""
    result = {}
    # Паттерн: "От: address" или "From: address"
    m = re.search(r"От:\s*(\S+@\S+)", text)
    if not m:
        m = re.search(r"From:\s*(\S+@\S+)", text)
    if m:
        result["original_sender"] = m.group(1).strip()

    # Оригинальная тема
    m = re.search(r"Тема:\s*(.+?)(?:\n|$)", text)
    if not m:
        m = re.search(r"Subject:\s*(.+?)(?:\n|$)", text)
    if m:
        result["original_subject"] = m.group(1).strip()

    # Папка форвардера
    m = re.search(r"Папка:\s*(\S+)", text)
    if m:
        result["folder"] = m.group(1).strip()

    # Дата оригинала
    m = re.search(r"Дата:\s*(\S+\s+\S+)", text)
    if m:
        result["original_date"] = m.group(1).strip()

    return result


def _extract_sed_table_data(html: str) -> dict:
    """Извлекает данные из HTML-таблиц СЭД (РСКЦ-формат)."""
    result = {
        "document_type": "",
        "document_number": "",
        "resolution_author": "",
        "resolution_text": "",
        "deadline": "",
        "executor": "",
        "controller": "",
        "status": "",
    }

    clean = _strip_html(html)

    # Ищем номер документа в теме или теле
    m = re.search(r"(?:№|Рег\.?\s*№)\s*([\w\-/]+)", clean)
    if m:
        result["document_number"] = m.group(1)

    # Ищем автора резолюции
    m = re.search(r"(?:Автор резолюции|Резолюция)\s*[:\|]\s*(.+?)(?:\n|\|)", clean)
    if m:
        result["resolution_author"] = m.group(1).strip()

    # Ищем текст резолюции
    m = re.search(r"(?:Текст резолюции|Содержание)\s*[:\|]\s*(.+?)(?:\n\n|\|)", clean, re.DOTALL)
    if m:
        result["resolution_text"] = m.group(1).strip()[:300]

    # Ищем срок
    m = re.search(r"(?:Контрольный срок|Срок|Исполнить до)\s*[:\|]\s*(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})", clean)
    if m:
        result["deadline"] = m.group(1)

    # Ищем исполнителя
    m = re.search(r"(?:Исполнитель|Ответственный)\s*[:\|]\s*(.+?)(?:\n|\|)", clean)
    if m:
        result["executor"] = m.group(1).strip()

    # Ищем контролёра
    m = re.search(r"(?:Контролёр|Контролер|На контроле у)\s*[:\|]\s*(.+?)(?:\n|\|)", clean)
    if m:
        result["controller"] = m.group(1).strip()

    # Тип документа
    for dt in ["служебная записка", "письмо", "приказ", "распоряжение",
                "протокол", "акт", "заключение", "справка", "докладная"]:
        if dt in clean.lower():
            result["document_type"] = dt
            break

    return result


def parse_email(email_data: dict) -> dict:
    """Обогащает email-данные извлечёнными метаданными."""
    subject = email_data.get("subject", "")
    body_text = email_data.get("body_text", "")
    body_html = email_data.get("body_html", "") or email_data.get("body_preview", "")

    # Если нет plain-text, конвертируем из HTML
    if not body_text and body_html:
        body_text = _strip_html(body_html)

    body = body_text or ""
    sender = email_data.get("sender", "")
    sender_name = email_data.get("sender_name", "")

    enriched = dict(email_data)

    # Обработка форвардированных писем
    fwd = _parse_forwarded_headers(body)
    if fwd:
        enriched["is_forwarded"] = True
        enriched["forward_info"] = fwd
        if fwd.get("original_sender"):
            enriched["original_sender"] = fwd["original_sender"]
        if fwd.get("original_subject"):
            enriched["original_subject"] = fwd["original_subject"]
    else:
        enriched["is_forwarded"] = False

    # Извлечение данных из СЭД-таблиц
    is_sed = "[СЭД]" in subject or "сэд" in subject.lower()
    if is_sed:
        sed_data = _extract_sed_table_data(body_html or body)
        enriched["sed_data"] = sed_data
        # Если есть автор резолюции — это может быть реальный инициатор
        if sed_data.get("resolution_author"):
            enriched["resolution_author"] = sed_data["resolution_author"]

    # Домен отправителя (реальный, с учётом форварда)
    real_sender = enriched.get("original_sender", sender)
    domain = real_sender.split("@")[-1] if "@" in real_sender else ""
    enriched["sender_domain"] = domain

    # Очищенный текст для анализа
    clean_body = body
    # Убираем заголовки форвардера
    clean_body = re.sub(
        r"Переслано форвардером\s+Папка:.*?Тема:.*?\n",
        "", clean_body, flags=re.DOTALL
    )

    # Ищем даты/дедлайны
    search_text = f"{subject} {clean_body}"
    enriched["extracted_deadlines"] = _extract_deadlines(search_text)

    # Добавляем дедлайн из СЭД если есть
    if is_sed and enriched.get("sed_data", {}).get("deadline"):
        dl = enriched["sed_data"]["deadline"]
        if dl not in enriched["extracted_deadlines"]:
            enriched["extracted_deadlines"].insert(0, dl)

    # ФИО
    enriched["mentioned_people"] = _extract_people(clean_body)

    # Номера документов
    enriched["document_refs"] = _extract_doc_refs(search_text)

    # Язык
    enriched["language"] = _detect_language(clean_body)

    # Потенциальные задачи
    enriched["potential_tasks"] = _extract_task_hints(clean_body)

    # Если СЭД и есть текст резолюции — это тоже задача
    if is_sed and enriched.get("sed_data", {}).get("resolution_text"):
        res_text = enriched["sed_data"]["resolution_text"]
        if res_text not in enriched["potential_tasks"]:
            enriched["potential_tasks"].insert(0, res_text)

    # Краткое содержание
    clean = re.sub(r"\s+", " ", clean_body).strip()
    enriched["clean_preview"] = clean[:300]

    # Чистый body для отображения
    enriched["body_clean"] = clean_body[:2000]

    return enriched


def _extract_deadlines(text: str) -> list[str]:
    """Ищет упоминания сроков и дат."""
    patterns = [
        r"до\s+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"не\s+позднее\s+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"в\s+срок\s+до\s+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"(?:контрольный\s+)?срок[:\s]+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"дедлайн[:\s]+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"deadline[:\s]+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"исполнить\s+до\s+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"до\s+конца\s+(дня|недели|месяца)",
        r"(сегодня)",
        r"(завтра)",
        r"(срочно)",
    ]
    results = []
    for pat in patterns:
        found = re.findall(pat, text, re.IGNORECASE)
        results.extend(found)
    return list(dict.fromkeys(results))  # дедупликация с сохранением порядка


def _extract_people(text: str) -> list[str]:
    """Ищет ФИО в тексте."""
    patterns = [
        r"([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.)",           # Иванов И.И.
        r"([А-ЯЁ]\.\s*[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]+)",           # И.И. Иванов
        r"([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:ич|вна|вич|овна))",  # Полное ФИО
    ]
    results = []
    for pat in patterns:
        found = re.findall(pat, text)
        results.extend(found)
    return list(set(results))


def _extract_doc_refs(text: str) -> list[str]:
    """Ищет ссылки на документы: номера, даты, резолюции."""
    patterns = [
        r"(?:№|Рег\.?\s*№)\s*([\w\-/]+(?:/\d{4}[\-\w]*)?)",
        r"((?:СЗ|Вх|Исх)[\-]\d+[\-/\w]*)",        # СЗ-70-00-06-2853/2026
        r"от\s+(\d{1,2}[\./]\d{1,2}[\./]\d{2,4})",
        r"(приказ[а-я]*\s+(?:№\s*)?[\d\-/]+)",
        r"(распоряжени[а-я]+\s+(?:№\s*)?[\d\-/]+)",
        r"(протокол[а-я]*\s+(?:№\s*)?[\d\-/]+)",
        r"(резолюци[а-я]+\s+(?:№\s*)?[\w\-/]+)",
    ]
    results = []
    for pat in patterns:
        found = re.findall(pat, text, re.IGNORECASE)
        results.extend(found)
    return list(set(results))


def _detect_language(text: str) -> str:
    if not text:
        return "unknown"
    rus = len(re.findall(r"[а-яёА-ЯЁ]", text))
    eng = len(re.findall(r"[a-zA-Z]", text))
    if rus > eng:
        return "ru"
    elif eng > rus:
        return "en"
    return "mixed"


def _extract_task_hints(text: str) -> list[str]:
    """Извлекает фразы, похожие на поручения/задачи."""
    config = load_config()
    task_keywords = config.get("task_keywords", [])
    hints = []
    sentences = re.split(r"[.!?\n]", text)
    for sentence in sentences:
        s = sentence.strip()
        if not s or len(s) < 10:
            continue
        for kw in task_keywords:
            if kw.lower() in s.lower():
                hints.append(s[:200])
                break
    return hints[:5]


def generate_summary(email_data: dict) -> dict:
    """Генерирует структурированное резюме письма для owner'а."""
    parsed = parse_email(email_data)

    # Определяем отображаемое имя отправителя
    sender_display = (
        parsed.get("resolution_author")
        or parsed.get("sender_name")
        or parsed.get("original_sender")
        or parsed.get("sender", "")
    )
    subject = parsed.get("original_subject") or parsed.get("subject", "(без темы)")

    priority_emoji = {
        "critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "spam": "⚪"
    }
    p = parsed.get("priority", "medium")
    emoji = priority_emoji.get(p, "🟡")

    category_labels = {
        "sed": "СЭД", "task": "Поручение", "report": "Отчёт",
        "incident": "Инцидент", "info": "Информация", "meeting": "Совещание",
        "external": "Внешнее", "personal": "Личное", "newsletter": "Рассылка",
    }
    cat = category_labels.get(parsed.get("category", ""), "")

    lines = [
        f"{emoji} **{sender_display}**",
        f"📋 {subject}",
    ]
    if cat:
        lines.append(f"🏷 {cat}")

    # СЭД-специфичные данные
    sed_data = parsed.get("sed_data", {})
    if sed_data.get("document_number"):
        lines.append(f"📄 Документ: {sed_data['document_number']}")
    if sed_data.get("resolution_text"):
        lines.append(f"📝 Резолюция: {sed_data['resolution_text'][:150]}")
    if sed_data.get("executor"):
        lines.append(f"👤 Исполнитель: {sed_data['executor']}")

    if parsed.get("extracted_deadlines"):
        lines.append(f"⏰ Сроки: {', '.join(parsed['extracted_deadlines'][:3])}")
    if parsed.get("mentioned_people"):
        lines.append(f"👥 Упомянуты: {', '.join(parsed['mentioned_people'][:3])}")
    if parsed.get("document_refs"):
        lines.append(f"📎 Документы: {', '.join(parsed['document_refs'][:3])}")
    if parsed.get("potential_tasks"):
        lines.append(f"📌 Возможные задачи: {len(parsed['potential_tasks'])}")
    if parsed.get("has_attachments"):
        att = parsed.get("attachment_names", [])
        lines.append(f"📎 Вложения: {', '.join(att) if att else 'есть'}")
        # Хинт для doc-review, если есть .docx
        att_paths = parsed.get("attachment_paths", [])
        docx_files = [p for p in att_paths if p.endswith((".docx", ".doc"))]
        if docx_files:
            lines.append(f"📝 doc-review: {len(docx_files)} документ(ов) для рецензии")

    preview = parsed.get("clean_preview", "")
    if preview and not sed_data.get("resolution_text"):
        lines.append(f"\n{preview[:200]}...")

    action_labels = {
        "create_task": "➡️ Создать задачу",
        "reply": "✉️ Ответить",
        "forward": "↗️ Переслать",
        "archive": "📥 В архив",
        "ignore": "⏭ Пропустить",
        "escalate": "🔺 Эскалировать",
        "delegate": "👤 Делегировать",
        "monitor": "👁 На контроле",
    }
    action = parsed.get("proposed_action", "")
    if action:
        lines.append(f"\n💡 Рекомендация: {action_labels.get(action, action)}")

    return {
        "summary_text": "\n".join(lines),
        "parsed": parsed,
    }


def main():
    parser = argparse.ArgumentParser(description="Email parser & enricher")
    sub = parser.add_subparsers(dest="command")

    p_parse = sub.add_parser("parse")
    p_parse.add_argument("--email", required=True)

    p_sum = sub.add_parser("summary")
    p_sum.add_argument("--email", required=True)

    p_tasks = sub.add_parser("extract_tasks")
    p_tasks.add_argument("--email", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    data = json.loads(Path(args.email).read_text("utf-8"))

    if args.command == "parse":
        output_json(parse_email(data))
    elif args.command == "summary":
        output_json(generate_summary(data))
    elif args.command == "extract_tasks":
        parsed = parse_email(data)
        output_json({"tasks": parsed.get("potential_tasks", [])})


if __name__ == "__main__":
    main()
