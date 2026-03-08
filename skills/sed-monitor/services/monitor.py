"""SED monitoring logic — sync folders, detect new documents/resolutions.

Main entry point: run_sync() — called on schedule or on-demand.
"""

import logging
import random
import time

from config.settings import load_config
from services import db, sed_client

log = logging.getLogger("sed-monitor")


def run_sync(sync_type: str = "scheduled") -> dict:
    """Full sync cycle: folders → documents → resolutions → pages.

    Returns summary dict with counts.
    """
    sync_id = db.start_sync(sync_type)
    config = load_config()
    summary = {
        "sync_id": sync_id,
        "folders_checked": 0,
        "new_documents": 0,
        "new_resolutions": 0,
        "errors": [],
    }

    try:
        # Authenticate
        if not sed_client.authenticate():
            raise RuntimeError("SED authentication failed")

        # Get all folders
        folders = sed_client.get_folders()
        if not folders:
            raise RuntimeError("No folders returned from SED")

        # Filter folders with documents
        doc_folders = [f for f in folders if f.get("hasDocuments")]
        log.info(f"Found {len(doc_folders)} folders with documents")

        for folder in doc_folders:
            try:
                _sync_folder(folder, summary, config)
                summary["folders_checked"] += 1
                # Small random delay between folders (gentle)
                time.sleep(random.uniform(0.5, 1.5))
            except Exception as e:
                log.warning(f"Error syncing folder {folder.get('name')}: {e}")
                summary["errors"].append(f"folder {folder.get('id')}: {e}")

        db.finish_sync(
            sync_id,
            folders=summary["folders_checked"],
            new_docs=summary["new_documents"],
            new_res=summary["new_resolutions"],
        )
        log.info(
            f"Sync complete: {summary['folders_checked']} folders, "
            f"{summary['new_documents']} new docs, "
            f"{summary['new_resolutions']} new resolutions"
        )

    except Exception as e:
        log.error(f"Sync failed: {e}")
        summary["errors"].append(str(e))
        db.finish_sync(sync_id, error=str(e))

    return summary


def _sync_folder(folder: dict, summary: dict, config: dict):
    """Sync all documents in a single folder."""
    folder_id = folder["id"]
    folder_name = folder.get("name", "")
    page_size = config.get("monitor", {}).get("page_size", 50)

    offset_key = None
    while True:
        result = sed_client.get_documents(folder_id, page_size, offset_key)
        docs = result.get("list", [])

        for doc in docs:
            doc["folder_id"] = folder_id
            doc["folder_name"] = folder_name
            is_new = db.upsert_document(doc)
            if is_new:
                summary["new_documents"] += 1
                log.info(f"New document: {doc.get('number', '?')} in {folder_name}")
                # Fetch details for new documents
                _fetch_document_details(doc["id"], summary)

        if not result.get("hasMore"):
            break
        # For pagination — need offsetKey from response
        # The API uses the last doc as offset; break if no more
        if len(docs) < page_size:
            break
        offset_key = docs[-1].get("id", "")
        time.sleep(random.uniform(0.3, 0.8))


def _fetch_document_details(doc_id: str, summary: dict):
    """Fetch resolutions, pages, and card for a document."""
    time.sleep(random.uniform(0.3, 0.8))

    # Resolutions
    try:
        resolutions = sed_client.get_resolutions(doc_id)
        for res in resolutions:
            is_new = db.upsert_resolution(doc_id, res)
            if is_new:
                summary["new_resolutions"] += 1
    except Exception as e:
        log.warning(f"Failed to get resolutions for {doc_id}: {e}")

    time.sleep(random.uniform(0.3, 0.8))

    # Pages (OCR text)
    try:
        pages = sed_client.get_pages(doc_id)
        if pages:
            db.save_pages(doc_id, pages)
    except Exception as e:
        log.warning(f"Failed to get pages for {doc_id}: {e}")

    # Card
    try:
        card = sed_client.get_card(doc_id)
        if card:
            db.save_card(doc_id, card)
    except Exception as e:
        log.warning(f"Failed to get card for {doc_id}: {e}")


def sync_single_document(doc_id: str) -> dict | None:
    """Fetch/update a single document by ID (on-demand)."""
    if not sed_client.authenticate():
        return None

    doc = sed_client.get_document(doc_id)
    if not doc:
        return None

    db.upsert_document(doc)

    # Fetch details
    resolutions = sed_client.get_resolutions(doc_id)
    for res in resolutions:
        db.upsert_resolution(doc_id, res)

    pages = sed_client.get_pages(doc_id)
    if pages:
        db.save_pages(doc_id, pages)

    card = sed_client.get_card(doc_id)
    if card:
        db.save_card(doc_id, card)

    return {
        "document": doc,
        "resolutions": resolutions,
        "pages_count": len(pages),
        "has_card": card is not None,
    }


def search_and_fetch(query: str) -> list[dict]:
    """Search documents in SED and sync results to local DB."""
    if not sed_client.authenticate():
        return []

    docs = sed_client.search_documents(query)
    for doc in docs:
        db.upsert_document(doc)

    return docs


def get_document_summary(doc_id: str) -> dict | None:
    """Get full document info from local DB."""
    doc = db.get_document(doc_id)
    if not doc:
        return None

    resolutions = db.get_resolutions(doc_id)
    card = db.get_card(doc_id)
    text = db.get_document_text(doc_id)

    return {
        "document": doc,
        "resolutions": resolutions,
        "card": card,
        "text": text[:2000] if text else "",
        "full_text_length": len(text) if text else 0,
    }


def get_my_summary(assignee: str = "Панков") -> dict:
    """Summary of documents/resolutions assigned to me."""
    my_res = db.get_my_resolutions(assignee)
    unviewed = db.get_unviewed_documents()
    stats = db.get_stats()
    last_sync = db.get_last_sync()

    return {
        "my_resolutions": my_res,
        "unviewed_documents": unviewed,
        "stats": stats,
        "last_sync": last_sync,
    }


def download_document(doc_id: str) -> str | None:
    """Download document as PDF. Returns file path or None."""
    from pathlib import Path
    pdf_path = sed_client.download_document_pdf(doc_id)
    return str(pdf_path) if pdf_path else None


def check_status() -> dict:
    """Full status check: connectivity + DB stats."""
    connectivity = sed_client.check_connectivity()
    stats = db.get_stats()
    last_sync = db.get_last_sync()

    return {
        "connectivity": connectivity,
        "stats": stats,
        "last_sync": last_sync,
    }
