"""Gmail IMAP клиент (только чтение).

Gmail используется ИСКЛЮЧИТЕЛЬНО для получения данных.
Отправка писем НЕ поддерживается — не нужна.

CLI: python -m services.gmail_client <command> [args]
Commands:
    fetch [--since DAYS] [--limit N] [--unseen]  — получить письма
    get <message_id>                              — одно письмо
    mark_read <message_id>                        — пометить прочитанным
    labels                                        — список меток
"""

import argparse
import email
import email.header
import email.message
import email.utils
import imaplib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import load_config, get_gmail_credentials, output_json, output_error


def _connect_imap() -> imaplib.IMAP4_SSL:
    cfg = load_config()["gmail"]
    email_addr, app_password = get_gmail_credentials()
    conn = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
    conn.login(email_addr, app_password)
    return conn


def _decode_header(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _decode_content_disposition(raw: str) -> str:
    """Декодирует Content-Disposition, включая RFC 2047 (=?utf-8?b?...?=)."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded).lower()


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    """Возвращает (text, html)."""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = _decode_content_disposition(str(part.get("Content-Disposition", "")))
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain":
                text_body = decoded
            elif ct == "text/html":
                html_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded
    return text_body, html_body


def _extract_filename_from_disp(raw_disp: str, part: email.message.Message) -> str:
    """Извлекает filename из Content-Disposition (включая RFC 2047)."""
    # Сначала пробуем стандартный метод
    fn = part.get_filename()
    if fn:
        return _decode_header(fn)
    # Fallback: парсим декодированный Content-Disposition вручную
    decoded = _decode_content_disposition(raw_disp)
    import re
    m = re.search(r'filename\s*=\s*"?([^";\r\n]+)"?', decoded)
    if m:
        return m.group(1).strip()
    return ""


_SAVE_EXTENSIONS = {".docx", ".xlsx", ".pdf", ".zip", ".doc", ".xls", ".pptx", ".rar"}
_SKIP_EXTENSIONS = {".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp", ".ico", ".svg"}
_ATTACHMENTS_DIR = Path("/dev/shm/email-monitor/attachments")
_ENCRYPTED_DOCX_MAGIC = b"\xd0\xcf\x11\xe0"
_DECRYPT_PASSWORD = "favl9xfr7"


def _save_attachment(part: email.message.Message, filename: str, uid: str) -> Optional[str]:
    """Сохраняет вложение на диск, расшифровывает если нужно. Возвращает путь или None."""
    ext = Path(filename).suffix.lower()
    if ext in _SKIP_EXTENSIONS or ext not in _SAVE_EXTENSIONS:
        return None
    payload = part.get_payload(decode=True)
    if not payload:
        return None

    uid_dir = _ATTACHMENTS_DIR / uid
    uid_dir.mkdir(parents=True, exist_ok=True)
    # Безопасное имя файла
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = uid_dir / safe_name

    # Проверяем зашифрованный .docx (OLE2 magic = d0cf11e0)
    if ext in (".docx", ".doc") and payload[:4] == _ENCRYPTED_DOCX_MAGIC:
        encrypted_path = uid_dir / f"_encrypted_{safe_name}"
        encrypted_path.write_bytes(payload)
        try:
            import msoffcrypto
            with open(encrypted_path, "rb") as f_in:
                office_file = msoffcrypto.OfficeFile(f_in)
                office_file.load_key(password=_DECRYPT_PASSWORD)
                with open(dest, "wb") as f_out:
                    office_file.decrypt(f_out)
        except Exception:
            # Не удалось расшифровать — сохраняем как есть
            dest.write_bytes(payload)
        finally:
            encrypted_path.unlink(missing_ok=True)
    else:
        dest.write_bytes(payload)

    return str(dest)


def _get_attachments(msg: email.message.Message) -> list[str]:
    names = []
    if msg.is_multipart():
        for part in msg.walk():
            raw_disp = str(part.get("Content-Disposition", ""))
            disp = _decode_content_disposition(raw_disp)
            if "attachment" in disp:
                fn = _extract_filename_from_disp(raw_disp, part)
                if fn:
                    names.append(fn)
    return names


def _parse_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    parsed = email.utils.parsedate_to_datetime(raw)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_sender(raw: str) -> tuple[str, str]:
    """Возвращает (name, email)."""
    decoded = _decode_header(raw)
    name, addr = email.utils.parseaddr(decoded)
    return name, addr


def _strip_html_quick(html: str) -> str:
    """Быстрая очистка HTML для preview."""
    import re
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|tr|div|li)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:td|th)[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _save_all_attachments(msg: email.message.Message, uid: str) -> list[str]:
    """Сохраняет все подходящие вложения, возвращает список путей."""
    paths = []
    if not msg.is_multipart():
        return paths
    for part in msg.walk():
        raw_disp = str(part.get("Content-Disposition", ""))
        disp = _decode_content_disposition(raw_disp)
        if "attachment" not in disp:
            continue
        fn = _extract_filename_from_disp(raw_disp, part)
        if not fn:
            continue
        saved = _save_attachment(part, fn, uid)
        if saved:
            paths.append(saved)
    return paths


def _msg_to_dict(msg: email.message.Message, uid: str) -> dict:
    sender_name, sender_email = _parse_sender(msg.get("From", ""))
    text_body, html_body = _extract_body(msg)
    attachments = _get_attachments(msg)
    attachment_paths = _save_all_attachments(msg, uid)

    # Генерируем чистый preview
    if text_body:
        preview = text_body[:500]
    elif html_body:
        preview = _strip_html_quick(html_body)[:500]
    else:
        preview = ""

    return {
        "message_id": msg.get("Message-ID", uid),
        "uid": uid,
        "thread_id": msg.get("In-Reply-To", ""),
        "sender": sender_email,
        "sender_name": sender_name,
        "to": _decode_header(msg.get("To", "")),
        "cc": _decode_header(msg.get("Cc", "")),
        "subject": _decode_header(msg.get("Subject", "")),
        "body_text": text_body,
        "body_html": html_body,
        "body_preview": preview,
        "received_at": _parse_date(msg.get("Date", "")),
        "has_attachments": len(attachments) > 0,
        "attachment_names": attachments,
        "attachment_paths": attachment_paths,
        "is_reply": bool(msg.get("In-Reply-To")),
        "labels": [],
    }


def fetch_emails(since_days: int = 3, limit: int = 20, unseen_only: bool = False) -> list[dict]:
    conn = _connect_imap()
    try:
        conn.select("INBOX")
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        criteria = f'(SINCE {since_date})'
        if unseen_only:
            criteria = f'(UNSEEN SINCE {since_date})'
        _, data = conn.search(None, criteria)
        uids = data[0].split()
        if not uids:
            return []
        # Берём последние N
        uids = uids[-limit:]
        results = []
        for uid in uids:
            _, msg_data = conn.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            results.append(_msg_to_dict(msg, uid.decode()))
        return results
    finally:
        conn.logout()


def get_email(message_uid: str) -> dict:
    conn = _connect_imap()
    try:
        conn.select("INBOX")
        _, msg_data = conn.fetch(message_uid.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            output_error(f"Письмо с UID {message_uid} не найдено")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        result = _msg_to_dict(msg, message_uid)
        return result
    finally:
        conn.logout()


def mark_read(message_uid: str) -> dict:
    conn = _connect_imap()
    try:
        conn.select("INBOX")
        conn.store(message_uid.encode(), "+FLAGS", "\\Seen")
        return {"status": "ok", "uid": message_uid}
    finally:
        conn.logout()


def list_labels() -> list[str]:
    conn = _connect_imap()
    try:
        _, labels = conn.list()
        result = []
        for label in labels:
            decoded = label.decode()
            # Извлекаем имя папки
            parts = decoded.split('" "')
            if len(parts) >= 2:
                result.append(parts[-1].strip('"'))
            else:
                result.append(decoded)
        return result
    finally:
        conn.logout()


def main():
    parser = argparse.ArgumentParser(description="Gmail IMAP client (read-only)")
    sub = parser.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("--since", type=int, default=3, help="Дней назад")
    p_fetch.add_argument("--limit", type=int, default=20, help="Макс. писем")
    p_fetch.add_argument("--unseen", action="store_true", help="Только непрочитанные")

    p_get = sub.add_parser("get")
    p_get.add_argument("uid", help="UID письма")

    p_mark = sub.add_parser("mark_read")
    p_mark.add_argument("uid", help="UID письма")

    sub.add_parser("labels")

    args = parser.parse_args()

    if args.command == "fetch":
        output_json(fetch_emails(args.since, args.limit, args.unseen))
    elif args.command == "get":
        output_json(get_email(args.uid))
    elif args.command == "mark_read":
        output_json(mark_read(args.uid))
    elif args.command == "labels":
        output_json(list_labels())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
