"""The ledger: confirming drafts into transactions, and listing them.

Confirming is the only way anything enters the ledger, and it always happens on a
person's say-so, with their corrections applied.
"""
import json
import re
import sqlite3

from backend.app.extraction.checks import run_checks
from backend.app.extraction.dates import parse_bill_date
from backend.app.schemas.extraction import BillEntry
from backend.app.services.drafts import NOT_FOR_LEDGER, get_draft
from backend.app.services.search import index_transaction

LEDGER_TYPES = {"purchase", "sale", "expense"}
FIELD_PATH = re.compile(r"^(\w+)(?:\[(\d+)\]\.(\w+))?$")  # "total" or "line_items[2].rate"


def apply_corrections(data: dict, corrections: dict) -> dict:
    """Apply corrections like {"total": 30000, "line_items[2].rate": 580} to a draft's data."""
    for path, value in corrections.items():
        match = FIELD_PATH.match(path)
        if not match:
            raise ValueError(f"Can't understand field '{path}'. Use e.g. 'total' or 'line_items[2].rate'.")
        name, index, sub_field = match.groups()
        if index is None:
            data[name] = value
        else:
            data[name][int(index)][sub_field] = value
    return BillEntry.model_validate(data).model_dump()  # re-check types after editing


def find_or_create_vendor(conn: sqlite3.Connection, entry: BillEntry, category: str | None) -> tuple[int | None, str | None]:
    """Match a vendor by GSTIN, then by name; create it if new. Returns (vendor_id, default_category)."""
    if not entry.vendor_name:
        return None, None
    row = None
    if entry.vendor_gstin:
        row = conn.execute("SELECT * FROM vendors WHERE gstin = ?", (entry.vendor_gstin,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM vendors WHERE lower(name) = lower(?)", (entry.vendor_name.strip(),)).fetchone()
    if row is None:
        cursor = conn.execute("INSERT INTO vendors (name, gstin, phone, default_category) VALUES (?, ?, ?, ?)",
                              (entry.vendor_name.strip(), entry.vendor_gstin, entry.vendor_phone, category))
        return cursor.lastrowid, category
    if category and not row["default_category"]:  # remember the category for next time
        conn.execute("UPDATE vendors SET default_category = ? WHERE id = ?", (category, row["id"]))
    return row["id"], row["default_category"] or category


def confirm_draft(conn: sqlite3.Connection, draft_id: int, transaction_type: str | None = None,
                  category: str | None = None, corrections: dict | None = None,
                  allow_duplicate: bool = False) -> dict:
    draft = get_draft(conn, draft_id)
    if draft["status"] != "pending":
        raise ValueError(f"Draft {draft_id} is already {draft['status']}")
    if draft["document_type"] in NOT_FOR_LEDGER:
        raise ValueError(f"Draft {draft_id} is a {draft['document_type']}, not a completed bill. Reject it instead.")

    data = apply_corrections(dict(draft["data"]), corrections or {})
    entry = BillEntry.model_validate(data)

    transaction_type = transaction_type or entry.transaction_type
    if transaction_type not in LEDGER_TYPES:
        raise ValueError("Please choose transaction_type: purchase, sale or expense.")
    bill_date = parse_bill_date(entry.date_as_written)
    if bill_date is None:
        raise ValueError(f"Date '{entry.date_as_written}' can't be read. Correct 'date_as_written' (e.g. 28/3/24).")
    if entry.total is None:
        raise ValueError("Total is missing. Correct 'total' before confirming.")

    if not allow_duplicate and entry.bill_number:
        duplicate = conn.execute(
            """SELECT id FROM transactions WHERE bill_number = ? AND abs(total - ?) < 0.01
               AND lower(coalesce(vendor_name, '')) = lower(?)""",
            (entry.bill_number, entry.total, entry.vendor_name or "")).fetchone()
        if duplicate:
            raise ValueError(f"Looks like a duplicate of transaction {duplicate['id']}. "
                             "Reject this draft, or confirm with allow_duplicate if it really is a separate bill.")

    vendor_id, vendor_category = find_or_create_vendor(conn, entry, category)
    category = category or vendor_category or "uncategorized"
    taxes = [t for t in (entry.cgst, entry.sgst, entry.igst) if t is not None]

    cursor = conn.execute(
        """INSERT INTO transactions (draft_id, upload_id, vendor_id, bill_date, transaction_type, category,
               document_type, vendor_name, bill_number, total, tax_total, amount_paid, balance_due, payment_mode,
               data, model_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (draft_id, draft["upload_id"], vendor_id, bill_date.isoformat(), transaction_type, category,
         draft["document_type"], entry.vendor_name, entry.bill_number, entry.total,
         sum(taxes) if taxes else None, entry.amount_paid, entry.balance_due, entry.payment_mode,
         entry.model_dump_json(), json.dumps(draft["data"])))
    transaction_id = cursor.lastrowid
    for item in entry.line_items:
        conn.execute("""INSERT INTO line_items (transaction_id, description, quantity, unit, rate, amount, tax_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (transaction_id, item.description, item.quantity, item.unit, item.rate, item.amount, item.tax_rate))
    conn.execute("UPDATE drafts SET status = 'confirmed' WHERE id = ?", (draft_id,))
    index_transaction(conn, transaction_id)
    conn.commit()

    warnings = [f"{i.field}: {i.message}" for i in run_checks(entry)]
    return {"transaction_id": transaction_id, "date": bill_date.isoformat(), "vendor": entry.vendor_name,
            "total": entry.total, "transaction_type": transaction_type, "category": category,
            "warnings": warnings}


def list_transactions(conn: sqlite3.Connection, start: str | None = None, end: str | None = None,
                      vendor: str | None = None, category: str | None = None,
                      transaction_type: str | None = None, limit: int = 50) -> list[dict]:
    """Dates are ISO (YYYY-MM-DD). Vendor matches any part of the name."""
    query, params = "SELECT * FROM transactions WHERE 1 = 1", []
    for clause, value in (("bill_date >= ?", start), ("bill_date <= ?", end), ("category = ?", category),
                          ("transaction_type = ?", transaction_type)):
        if value:
            query += f" AND {clause}"
            params.append(value)
    if vendor:
        query += " AND lower(vendor_name) LIKE ?"
        params.append(f"%{vendor.lower()}%")
    query += " ORDER BY bill_date DESC, id DESC LIMIT ?"
    params.append(limit)
    keys = ("id", "bill_date", "transaction_type", "category", "vendor_name", "bill_number", "total",
            "tax_total", "amount_paid", "balance_due", "payment_mode", "upload_id")
    return [{k: row[k] for k in keys} for row in conn.execute(query, params)]
