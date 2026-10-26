"""Scanning: run the extraction agent on an upload and save the result as drafts.

A draft is the agent's reading of one bill, waiting for a person to confirm or reject it.
Nothing reaches the ledger without that confirmation.
"""
import hashlib
import json
import mimetypes
import sqlite3
from dataclasses import asdict
from pathlib import Path

from backend.app.extraction.agent import apply_safe_fixes, process_bill, review_fields
from backend.app.extraction.checks import run_checks
from backend.app.extraction.cleanup import clean_document
from backend.app.schemas.extraction import BillEntry, DocumentExtraction
from backend.app.extraction.prompts import EXTRACTION_PROMPT
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.services.inbox import get_upload

NOT_FOR_LEDGER = {"quotation", "estimate", "challan"}


def claim_upload(conn: sqlite3.Connection, upload_id: int, from_status: str) -> bool:
    """Atomically move an upload to 'scanning'. Only one caller can win, so a bill is never scanned twice."""
    cursor = conn.execute("UPDATE uploads SET status = 'scanning' WHERE id = ? AND status = ?",
                          (upload_id, from_status))
    conn.commit()
    return cursor.rowcount == 1


def scan_upload(conn: sqlite3.Connection, upload_id: int, provider: ExtractionProvider,
                fallback: ExtractionProvider | None = None, already_claimed: bool = False) -> list[dict]:
    """Extract one upload into drafts. Returns a short summary of each draft."""
    upload = get_upload(conn, upload_id)
    if not already_claimed and not claim_upload(conn, upload_id, "pending"):
        raise ValueError(f"Upload {upload_id} is {upload['status']}, not pending; it may already be scanning.")

    path = Path(upload["file_path"])
    try:
        result = process_bill(path.read_bytes(), mimetypes.guess_type(path)[0] or "image/jpeg",
                              EXTRACTION_PROMPT, provider, fallback=fallback)
    except Exception as error:
        conn.execute("UPDATE uploads SET status = 'failed', error = ? WHERE id = ?", (str(error), upload_id))
        conn.commit()
        raise

    summaries = []
    for index, entry in enumerate(result.document.entries):
        issues = [asdict(issue) for issue in result.issues[index]]
        cursor = conn.execute(
            """INSERT INTO drafts (upload_id, entry_index, document_type, data, issues, needs_review,
                                   suggestions, corrections, steps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (upload_id, index, result.document.document_type, entry.model_dump_json(), json.dumps(issues),
             json.dumps(result.needs_review[index]), json.dumps(result.suggestions),
             json.dumps(result.corrections), json.dumps(result.steps)))
        summaries.append(draft_summary(get_draft(conn, cursor.lastrowid)))
    conn.execute("UPDATE uploads SET status = 'processed' WHERE id = ?", (upload_id,))
    conn.commit()
    return summaries


def get_draft(conn: sqlite3.Connection, draft_id: int) -> dict:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise ValueError(f"No draft with id {draft_id}")
    draft = dict(row)
    for key in ("data", "issues", "needs_review", "suggestions", "corrections", "steps"):
        draft[key] = json.loads(draft[key])
    if draft["document_type"] in NOT_FOR_LEDGER:
        draft["warning"] = f"This is a {draft['document_type']}, not a completed bill; usually it should be rejected."
    return draft


def draft_summary(draft: dict) -> dict:
    data = draft["data"]
    return {"draft_id": draft["id"], "upload_id": draft["upload_id"], "document_type": draft["document_type"],
            "vendor": data.get("vendor_name"), "bill_number": data.get("bill_number"),
            "date": data.get("date_as_written"), "total": data.get("total"),
            "needs_review": draft["needs_review"], "status": draft["status"],
            **({"warning": draft["warning"]} if "warning" in draft else {})}


def list_drafts(conn: sqlite3.Connection, status: str = "pending") -> list[dict]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM drafts WHERE status = ? ORDER BY id", (status,))]
    return [draft_summary(get_draft(conn, i)) for i in ids]


def reject_draft(conn: sqlite3.Connection, draft_id: int, reason: str) -> dict:
    draft = get_draft(conn, draft_id)
    if draft["status"] != "pending":
        raise ValueError(f"Draft {draft_id} is already {draft['status']}")
    conn.execute("UPDATE drafts SET status = 'rejected', reject_reason = ? WHERE id = ?", (reason, draft_id))
    conn.commit()
    return {"draft_id": draft_id, "status": "rejected", "reason": reason}


CHAT_SOURCE = "chat:"  # file_path prefix for bills read from a chat attachment (no photo stored)


def create_draft_from_reading(conn: sqlite3.Connection, document_type: str, entry: BillEntry,
                              description: str = "") -> dict:
    """Save a draft from values the assistant read off an image attached in the chat.

    MCP tools can't receive chat attachments, but the assistant can see them. So the assistant
    does the reading, and the same clean-up, checks, safe fixes and review flags run here.
    The draft still needs the user's confirmation before it reaches the ledger.
    """
    doc = clean_document(DocumentExtraction(document_type=document_type, is_readable=True,
                                            is_obscured=False, entries=[entry]))
    suggestions, corrections = [], []
    fixed = apply_safe_fixes(doc.entries[0], suggestions, corrections)
    issues = run_checks(fixed)

    # The same reading submitted twice is refused, like the same photo dropped in the inbox twice.
    digest = hashlib.sha256(fixed.model_dump_json().encode()).hexdigest()
    if conn.execute("SELECT 1 FROM uploads WHERE file_hash = ?", (digest,)).fetchone():
        raise ValueError("A draft with exactly these values already exists.")
    upload_id = conn.execute(
        "INSERT INTO uploads (file_path, file_hash, status) VALUES (?, ?, 'processed')",
        (f"{CHAT_SOURCE}{description or 'chat attachment'}", digest)).lastrowid

    review = review_fields(fixed, issues)
    steps = ["values read by the assistant from a chat attachment (no photo stored)",
             "all checks passed" if not issues else f"{len(issues)} problem(s) left for review"]
    draft_id = conn.execute(
        """INSERT INTO drafts (upload_id, entry_index, document_type, data, issues, needs_review,
                               suggestions, corrections, steps) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?)""",
        (upload_id, document_type, fixed.model_dump_json(), json.dumps([asdict(i) for i in issues]),
         json.dumps(review), json.dumps(suggestions), json.dumps(corrections), json.dumps(steps))).lastrowid
    conn.commit()
    return draft_summary(get_draft(conn, draft_id))
