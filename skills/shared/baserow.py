"""Baserow-compatible client — now backed by local SQLite.

All operations delegated to local_db.py. This file preserves
the same CLI interface and Python API so that all skills
(task-control, weekly-ops, email-monitor) continue to work
without any changes to their code or SKILL.md.

Original Baserow REST client saved as baserow.py.bak.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add shared/ to path so local_db can be imported
_shared = str(Path(__file__).resolve().parent)
if _shared not in sys.path:
    sys.path.insert(0, _shared)

from local_db import (  # noqa: E402, F401
    list_rows,
    list_all_rows,
    get_row,
    create_row,
    update_row,
    delete_row,
    batch_create,
    batch_update,
    get_baserow_url,
    get_baserow_token,
    output_json,
    output_error,
    main,
    MAX_RETRIES,
    BACKOFF_BASE,
)

# Backward compat: _make_request is no longer needed but some code may import it
def _make_request(*args, **kwargs):
    raise NotImplementedError("Direct HTTP requests removed. Use local SQLite functions.")

if __name__ == "__main__":
    main()
