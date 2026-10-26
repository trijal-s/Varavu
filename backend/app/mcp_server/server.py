"""Varavu MCP server: lets an AI assistant scan bills, review drafts, and query the ledger.

Run directly (Claude Desktop starts it this way):
    python backend/app/mcp_server/server.py

Important for stdio servers: never print() to stdout here. Stdout carries the MCP
protocol; anything else written there breaks the connection. Use stderr for logs.
"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

# Make the project importable and use project-relative paths, wherever we're started from.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from backend.app.db import connect  # noqa: E402
from backend.app.schemas.extraction import BillEntry, DocumentType  # noqa: E402
from backend.app.services import drafts, export, inbox, jobs, ledger, reports, search  # noqa: E402

READ_ONLY = ToolAnnotations(read_only_hint=True)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False)

server = MCPServer(
    "varavu",
    instructions=(
        "Varavu holds the user's bills and accounts ledger. For ANY question about the user's own bills, "
        "vendors, spending, payments or expenses (e.g. 'why was my electricity bill high?', 'what did I spend "
        "on food?'), check the ledger first with search_bills or query_ledger, then get_transaction. "
        "Don't answer from general knowledge before checking the ledger. "
        "To add bills: scan_inbox then start_scan (runs in the background; check with scan_status), or "
        "draft_from_chat_image for images attached in the chat. For each draft show the user its fields, "
        "needs_review list and suggestions (use show_bill when a photo is stored). Only call confirm_entry "
        "after the user has approved the values. Cite the transaction ids behind every answer. "
        "Describe bills only with what is written on them; don't infer how many people, why, or for whom. "
        "If you add general knowledge (e.g. how tariffs work), say clearly that it is general, not from the bill. "
        "Amounts are in rupees; dates are day-first (DD/MM/YY)."),)


@contextmanager
def db():
    """Open the database for one tool call and always close it afterwards.

    Our services raise ValueError with a message meant for the user (e.g. "Total is missing").
    ToolError passes that message back to the assistant; other exceptions are treated as crashes.
    """
    conn = connect()
    try:
        yield conn
    except ValueError as error:
        raise ToolError(str(error)) from error
    finally:
        conn.close()


def get_providers():
    """Main and fallback extraction providers, from .env (EXTRACTION_PROVIDER, FALLBACK_PROVIDER)."""
    from backend.app.extraction.providers.factory import get_provider
    fallback = os.getenv("FALLBACK_PROVIDER")
    return get_provider(), (get_provider(fallback) if fallback else None)


# ---------- Getting bills in ----------

@server.tool(annotations=WRITES)
def scan_inbox() -> dict:
    """Register new bill photos from the inbox folder. Returns the new uploads and everything still pending."""
    with db() as conn:
        return {"new": inbox.register_inbox(conn), "pending": inbox.list_pending(conn)}


@server.tool(annotations=READ_ONLY)
def list_pending() -> list[dict]:
    """List uploaded bill photos that have not been scanned yet."""
    with db() as conn:
        return inbox.list_pending(conn)


@server.tool(annotations=WRITES)
def scan_bill(upload_id: int) -> list[dict]:
    """Scan ONE upload and wait for the result (usually 10 to 60 seconds). For several bills, or if this
    times out, use start_scan instead. Saves draft(s) for review; does not add anything to the ledger."""
    provider, fallback = get_providers()
    with db() as conn:
        return drafts.scan_upload(conn, upload_id, provider, fallback)


worker = jobs.ScanWorker(lambda: get_providers())


@server.tool(annotations=WRITES)
def start_scan(upload_ids: list[int] | None = None) -> dict:
    """Start scanning pending uploads in the background (all of them, or only upload_ids) and return at once.
    Use scan_status to see progress; drafts appear as each bill finishes."""
    with db() as conn:
        queued = jobs.queue_uploads(conn, upload_ids)
    started = worker.start()
    return {"queued": queued, "worker": "started" if started else "already running",
            "next": "Call scan_status in a little while; each bill usually takes 10 to 60 seconds."}


@server.tool(annotations=READ_ONLY)
def scan_status() -> dict:
    """Progress of background scans: uploads by status, failures with their errors, drafts waiting for review."""
    with db() as conn:
        return jobs.scan_status(conn)


@server.tool(annotations=WRITES)
def retry_failed_scan(upload_id: int) -> dict:
    """Put a failed upload back to pending so it can be scanned again."""
    with db() as conn:
        return jobs.retry_failed(conn, upload_id)


# ---------- Reviewing drafts ----------

@server.tool(annotations=READ_ONLY)
def list_drafts(status: str = "pending") -> list[dict]:
    """List drafts by status: pending, confirmed or rejected."""
    with db() as conn:
        return drafts.list_drafts(conn, status)


@server.tool(annotations=READ_ONLY)
def get_draft(draft_id: int) -> dict:
    """Full detail of one draft: all fields, remaining problems, fields needing review,
    suggestions, automatic corrections and the agent's steps."""
    with db() as conn:
        return drafts.get_draft(conn, draft_id)


@server.tool(annotations=READ_ONLY)
def show_bill(upload_id: int) -> Image:
    """Return the original bill photo, so the values can be checked against it."""
    with db() as conn:
        path = inbox.get_upload(conn, upload_id)["file_path"]
    if path.startswith(drafts.CHAT_SOURCE):
        raise ToolError("This bill came from a chat attachment, so no photo is stored. Use the image in the chat.")
    return Image(path=path)


@server.tool(annotations=WRITES)
def draft_from_chat_image(document_type: DocumentType, entry: BillEntry, description: str = "") -> dict:
    """Create a draft from a bill image the user ATTACHED IN THE CHAT (MCP tools can't receive the file itself).
    Read the image carefully and pass values exactly as written: copy numbers, keep dates as written
    (day-first), leave out anything unclear and list it in low_confidence_fields. Never calculate or guess
    missing values. Use one call per bill; skip duplicates and things that aren't bills (e.g. a shopping
    list). The draft goes through the same checks, and still needs the user's confirmation.
    description: a short label such as the file name or vendor."""
    with db() as conn:
        return drafts.create_draft_from_reading(conn, document_type, entry, description)


@server.tool(annotations=WRITES)
def confirm_entry(draft_id: int, transaction_type: str, category: str | None = None,
                  corrections: dict | None = None, allow_duplicate: bool = False) -> dict:
    """Save a reviewed draft to the ledger. ONLY call this after the user has approved the values.

    transaction_type: purchase, sale or expense.
    category: e.g. 'cattle feed', 'rent'. If omitted, the vendor's usual category is used.
    corrections: fixes from the user, e.g. {"total": 30000, "line_items[2].rate": 580}.
    allow_duplicate: only if the user says a matching bill really is a separate purchase.
    """
    with db() as conn:
        return ledger.confirm_draft(conn, draft_id, transaction_type, category, corrections, allow_duplicate)


@server.tool(annotations=WRITES)
def reject_draft(draft_id: int, reason: str) -> dict:
    """Discard a draft (duplicate, wrong photo, quotation, unreadable). It is kept in history, not in the ledger."""
    with db() as conn:
        return drafts.reject_draft(conn, draft_id, reason)


# ---------- Ledger and reports ----------

@server.tool(annotations=READ_ONLY)
def list_transactions(start: str | None = None, end: str | None = None, vendor: str | None = None,
                      category: str | None = None, transaction_type: str | None = None,
                      limit: int = 50) -> list[dict]:
    """Ledger entries, newest first. Dates as YYYY-MM-DD; vendor matches part of the name."""
    with db() as conn:
        return ledger.list_transactions(conn, start, end, vendor, category, transaction_type, limit)


@server.tool(annotations=READ_ONLY)
def monthly_summary(month: str) -> dict:
    """Totals for a month (YYYY-MM) by type and category, top vendors, and change from the previous month."""
    with db() as conn:
        return reports.monthly_summary(conn, month)


@server.tool(annotations=READ_ONLY)
def supplier_dues() -> list[dict]:
    """Unpaid balances on purchase bills, per supplier, largest first."""
    with db() as conn:
        return reports.supplier_dues(conn)


@server.tool(annotations=WRITES)
def export_year(financial_year: str) -> dict:
    """Create the year-end Excel workbook for the CA, e.g. financial_year='2023-24'. Returns the file path."""
    with db() as conn:
        return export.export_year(conn, financial_year)


# ---------- Questions over the ledger ----------

@server.tool(annotations=READ_ONLY)
def search_bills(query: str, limit: int = 10) -> list[dict]:
    """Look up the user's own bills by vendor, item, category or bill number, e.g. 'electricity', 'Adani',
    'bran', 'hotel'. Use this first for any question about a specific bill or expense, then get_transaction
    for details. Ranked by relevance (BM25)."""
    with db() as conn:
        return search.search_bills(conn, query, limit)


@server.tool(annotations=READ_ONLY, description=(
    "Answer numeric questions with ONE read-only SQL SELECT on the ledger (max 200 rows). Include "
    "transactions.id in results so answers can cite their bills.\n" + search.LEDGER_SCHEMA))
def query_ledger(sql: str) -> dict:
    try:
        return search.run_readonly_query(sql)
    except ValueError as error:
        raise ToolError(str(error)) from error


@server.tool(annotations=READ_ONLY)
def get_transaction(transaction_id: int) -> dict:
    """One ledger entry in full, with its line items and upload_id (use show_bill with it to see the photo).Report only what the bill states. If you add general knowledge (e.g. how tariffs work),
       say clearly that it is general, not from this bill."""
    with db() as conn:
        return search.get_transaction(conn, transaction_id)


def startup() -> None:
    """Requeue scans interrupted by a restart, resume them, and make sure the search index is complete."""
    with db() as conn:
        if jobs.recover_stuck_scans(conn) or conn.execute(
                "SELECT 1 FROM uploads WHERE status = 'queued' LIMIT 1").fetchone():
            worker.start()
        indexed = conn.execute("SELECT count(*) FROM bill_search").fetchone()[0]
        total = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
        if indexed != total:
            search.rebuild_search_index(conn)


if __name__ == "__main__":
    startup()
    server.run("stdio")
