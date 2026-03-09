#!/usr/bin/env python3
"""CLI for sed-monitor skill.

Usage:
    python3 cli.py doc <id_or_link>          — отчёт о документе
    python3 cli.py search <query>            — поиск по номеру/тексту
    python3 cli.py pdf <id_or_link>          — скачать PDF
    python3 cli.py check                     — проверить связь
    python3 cli.py token <dnsid> <auth_token> — установить токен авторизации
"""

import json
import re
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _extract_doc_id(raw: str) -> str:
    """Extract document ID from a link or raw string.

    Supports:
      - https://app.sd-praktika.ru/?id=875962
      - https://doc.rscc.ru:444/web/document/view?id=883493
      - plain number: 875962
    """
    m = re.search(r"[?&]id=(\d+)", raw)
    if m:
        return m.group(1)
    m = re.match(r"^\d+$", raw.strip())
    if m:
        return raw.strip()
    return raw.strip()


def _format_document_report(summary: dict) -> str:
    """Format document summary as human-readable report."""
    doc = summary.get("document", {})
    resolutions = summary.get("resolutions", [])
    card = summary.get("card")
    text = summary.get("text", "")
    full_len = summary.get("full_text_length", 0)

    lines = []

    # Header
    number = doc.get("number", "?")
    date = doc.get("reg_date") or doc.get("regDate") or "—"
    lines.append(f"📄 Документ №{number} от {date}")
    folder = doc.get("folder_name", "")
    if folder:
        lines.append(f"Папка: {folder}")
    category = doc.get("category_name") or doc.get("categoryName") or ""
    if category:
        lines.append(f"Тип: {category}")

    # Short content
    short = doc.get("short_content") or doc.get("shortContent") or ""
    if short:
        lines.append(f"\n📋 Краткое содержание:\n{short}")

    # Resolutions
    if resolutions:
        lines.append(f"\n👥 Резолюции ({len(resolutions)}):")
        for i, r in enumerate(resolutions, 1):
            author = r.get("author_name", "?")
            assignee = r.get("assignee_name", "?")
            res_text = r.get("resolution_text") or r.get("text") or ""
            status = r.get("status", "")
            deadline = r.get("deadline", "")

            lines.append(f"{i}. {author} → {assignee}")
            if res_text:
                lines.append(f'   "{res_text}"')
            parts = []
            if status:
                parts.append(f"Статус: {status}")
            if deadline:
                parts.append(f"Дедлайн: {deadline}")
            if parts:
                lines.append(f"   {' | '.join(parts)}")
    else:
        lines.append("\n👥 Резолюции: нет")

    # Card
    if card:
        card_data = card.get("card", card) if isinstance(card, dict) else card
        if isinstance(card_data, dict):
            card_fields = []
            for k, v in card_data.items():
                if k in ("doc_id", "fetched_at"):
                    continue
                if v and str(v).strip():
                    card_fields.append(f"{k}: {v}")
            if card_fields:
                lines.append("\n📑 Карточка:")
                for f in card_fields[:10]:  # max 10 fields
                    lines.append(f"  {f}")

    # OCR text
    if text:
        preview = text[:500]
        page_count = doc.get("page_count") or doc.get("pageCount") or "?"
        lines.append(f"\n📝 Текст документа (OCR):")
        lines.append(preview)
        if full_len > 500:
            lines.append(f"...\n[всего {page_count} стр., {full_len} символов]")
    else:
        lines.append("\n📝 OCR-текст: не загружен")

    return "\n".join(lines)


def _format_search_results(docs: list) -> str:
    """Format search results as human-readable list."""
    if not docs:
        return "Документы не найдены."

    lines = [f"Найдено документов: {len(docs)}\n"]
    for doc in docs[:20]:
        num = doc.get("number", "?")
        date = doc.get("regDate") or doc.get("reg_date") or ""
        short = doc.get("shortContent") or doc.get("short_content") or ""
        doc_id = doc.get("id", "")
        viewed = "👁" if doc.get("isViewed") else "🆕"
        lines.append(f"{viewed} №{num} от {date} [id:{doc_id}]")
        if short:
            lines.append(f"   {short[:80]}")
    return "\n".join(lines)


def cmd_doc(raw_id: str):
    """Get full document report."""
    from services.monitor import get_document_summary, sync_single_document

    doc_id = _extract_doc_id(raw_id)

    # Try local DB first
    summary = get_document_summary(doc_id)
    if not summary:
        # Fetch from SED
        result = sync_single_document(doc_id)
        if result:
            summary = get_document_summary(doc_id)

    if not summary:
        print(f"Документ {doc_id} не найден в СЭД.")
        sys.exit(1)

    print(_format_document_report(summary))


def cmd_search(query: str):
    """Search documents."""
    from services.monitor import search_and_fetch
    docs = search_and_fetch(query)
    print(_format_search_results(docs))


def cmd_pdf(raw_id: str):
    """Download document as PDF."""
    from services.monitor import download_document
    doc_id = _extract_doc_id(raw_id)
    path = download_document(doc_id)
    if path:
        print(f"PDF: {path}")
    else:
        print("Не удалось скачать PDF. Проверьте ID и связь с СЭД.", file=sys.stderr)
        sys.exit(1)


def cmd_check():
    """Check connectivity."""
    from services import sed_client
    result = sed_client.check_connectivity()
    parts = []
    parts.append(f"Proxy: {'✅' if result['proxy'] else '❌'}")
    parts.append(f"SED:   {'✅' if result['sed'] else '❌'}")
    parts.append(f"Token: {'✅' if result['token'] else '❌'}")
    print("\n".join(parts))

    if all(result.values()):
        print("\nВсё работает.")
    elif not result.get("token"):
        print("\nТокен не установлен или истёк. Owner должен обновить токен.")
        sys.exit(1)
    else:
        print("\nЕсть проблемы с подключением.")
        sys.exit(1)


def cmd_token(dnsid: str, auth_token: str):
    """Set auth token (obtained interactively by owner)."""
    from services import sed_client
    sed_client.set_token(dnsid, auth_token)
    print("Токен сохранён.")

    # Verify
    result = sed_client.check_connectivity()
    if result.get("token"):
        print("Проверка: ✅ токен рабочий")
    else:
        print("Проверка: ❌ токен не работает")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "doc" and len(sys.argv) >= 3:
            cmd_doc(sys.argv[2])
        elif cmd == "search" and len(sys.argv) >= 3:
            cmd_search(" ".join(sys.argv[2:]))
        elif cmd == "pdf" and len(sys.argv) >= 3:
            cmd_pdf(sys.argv[2])
        elif cmd == "check":
            cmd_check()
        elif cmd == "token" and len(sys.argv) >= 4:
            cmd_token(sys.argv[2], sys.argv[3])
        else:
            print(__doc__)
            sys.exit(1)
    except FileNotFoundError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
