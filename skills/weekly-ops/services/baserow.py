"""Baserow REST client — re-exported from shared module.

All functionality lives in skills/shared/baserow.py.
This file provides backward-compatible imports for task-control.
"""

import sys
from pathlib import Path

# Add shared/ to path
_shared = str(Path(__file__).resolve().parent.parent.parent / "shared")
if _shared not in sys.path:
    sys.path.insert(0, _shared)

from baserow import (  # noqa: E402, F401
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
)

if __name__ == "__main__":
    main()
