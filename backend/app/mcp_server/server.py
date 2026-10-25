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
from backend.app.services import drafts, export, inbox, ledger, reports  # noqa: E402

READ_ONLY = ToolAnnotations(read_only_hint=True)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False)

server = MCPServer(
    "varavu",
    instructions=(
        "Varavu turns photos of Indian bills into a ledger. Typical flow: scan_inbox, scan_pending, then for "
        "each draft show the user its fields, needs_review list and suggestions (use show_bill to look at the "
        "photo). Only call confirm_entry after the user has approved the values, and pass their corrections. "
        "Never invent values that are not on the bill. Amounts are in rupees; dates are day-first."
    ),
)


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
    """Read one uploaded bill with the extraction agent and save it as draft(s) for review.
    Does not add anything to the ledger."""
    provider, fallback = get_providers()
    with db() as conn:
        return drafts.scan_upload(conn, upload_id, provider, fallback)


@server.tool(annotations=WRITES)
def scan_pending(max_bills: int = 5) -> list[dict]:
    """Scan up to max_bills pending uploads into drafts. Failed bills are reported, not skipped silently."""
    provider, fallback = get_providers()
    results = []
    with db() as conn:
        for upload in inbox.list_pending(conn)[:max_bills]:
            try:
                results += drafts.scan_upload(conn, upload["upload_id"], provider, fallback)
            except Exception as error:
                results.append({"upload_id": upload["upload_id"], "file": upload["file"], "error": str(error)})
    return results


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
        return Image(path=inbox.get_upload(conn, upload_id)["file_path"])


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


if __name__ == "__main__":
    server.run("stdio")
