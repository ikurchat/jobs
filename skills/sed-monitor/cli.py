#!/usr/bin/env python3
"""CLI wrapper for sed-monitor — allows agent to call functions via Bash.

Usage:
    python3 cli.py status
    python3 cli.py sync
    python3 cli.py document <doc_id>
    python3 cli.py search <query>
    python3 cli.py resolutions [assignee]
    python3 cli.py unviewed
    python3 cli.py download <doc_id>
    python3 cli.py text <doc_id>
    python3 cli.py connectivity
"""

import json
import sys
import os

# Add skill dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import db, sed_client
from services.monitor import (
    check_status, download_document, get_document_summary,
    get_my_summary, run_sync, search_and_fetch, sync_single_document,
)


def _json_out(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        _json_out(check_status())

    elif cmd == "connectivity":
        _json_out(sed_client.check_connectivity())

    elif cmd == "sync":
        _json_out(run_sync(sync_type="manual"))

    elif cmd == "document":
        if len(sys.argv) < 3:
            print("Usage: cli.py document <doc_id>")
            sys.exit(1)
        doc_id = sys.argv[2]
        # Try local DB first, then fetch from SED
        summary = get_document_summary(doc_id)
        if not summary:
            result = sync_single_document(doc_id)
            if result:
                summary = get_document_summary(doc_id)
        _json_out(summary or {"error": f"Document {doc_id} not found"})

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: cli.py search <query>")
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        docs = search_and_fetch(query)
        _json_out({"count": len(docs), "documents": docs})

    elif cmd == "resolutions":
        assignee = sys.argv[2] if len(sys.argv) > 2 else "Панков"
        _json_out(get_my_summary(assignee))

    elif cmd == "unviewed":
        docs = db.get_unviewed_documents()
        _json_out({"count": len(docs), "documents": docs})

    elif cmd == "download":
        if len(sys.argv) < 3:
            print("Usage: cli.py download <doc_id>")
            sys.exit(1)
        path = download_document(sys.argv[2])
        if path:
            print(f"PDF saved: {path}")
        else:
            print("Download failed", file=sys.stderr)
            sys.exit(1)

    elif cmd == "text":
        if len(sys.argv) < 3:
            print("Usage: cli.py text <doc_id>")
            sys.exit(1)
        doc_id = sys.argv[2]
        # Ensure we have pages
        if not db.get_pages(doc_id):
            sync_single_document(doc_id)
        text = db.get_document_text(doc_id)
        print(text or "Текст не найден")

    elif cmd == "stats":
        _json_out(db.get_stats())

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
