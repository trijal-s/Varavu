"""Questions over the ledger: full-text search, read-only SQL, and transaction details."""
import re
import sqlite3

from backend.app.db import db_path

# ---------- Full-text search (BM25 ranking via SQLite FTS5) ----------

def index_transaction(conn: sqlite3.Connection, transaction_id: int) -> None:
    """Add or refresh one confirmed transaction in the search index."""
    t = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    items = " ".join(r["description"] for r in conn.execute(
        "SELECT description FROM line_items WHERE transaction_id = ?", (transaction_id,)))
    conn.execute("DELETE FROM bill_search WHERE transaction_id = ?", (transaction_id,))
    conn.execute("INSERT INTO bill_search (transaction_id, vendor_name, bill_number, category, items) "
                 "VALUES (?, ?, ?, ?, ?)", (transaction_id, t["vendor_name"], t["bill_number"], t["category"], items))


def rebuild_search_index(conn: sqlite3.Connection) -> int:
    """Index every transaction (e.g. ones confirmed before search existed)."""
    conn.execute("DELETE FROM bill_search")
    ids = [r["id"] for r in conn.execute("SELECT id FROM transactions")]
    for transaction_id in ids:
        index_transaction(conn, transaction_id)
    conn.commit()
    return len(ids)


def search_bills(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    """Find bills by words in vendor, bill number, category or item names. Prefix matches count: 'fert' finds 'fertiliser'."""
    words = re.findall(r"\w+", query, flags=re.UNICODE)
    if not words:
        raise ValueError("Give at least one word to search for.")
    match = " ".join(f'"{w}"*' for w in words)  # quoted, so user text can't inject FTS syntax
    rows = conn.execute(
        """SELECT t.id, t.upload_id, t.bill_date, t.vendor_name, t.bill_number, t.category, t.total,
                  snippet(bill_search, 4, '[', ']', '...', 8) AS matched_items
           FROM bill_search JOIN transactions t ON t.id = bill_search.transaction_id
           WHERE bill_search MATCH ? ORDER BY bm25(bill_search) LIMIT ?""", (match, limit))
    return [dict(r) for r in rows]


# ---------- Read-only SQL ----------

LEDGER_SCHEMA = """Tables you can query:
transactions(id, bill_date 'YYYY-MM-DD', transaction_type 'purchase'|'sale'|'expense', category, vendor_name,
             bill_number, total, tax_total, amount_paid, balance_due, payment_mode, upload_id)
line_items(id, transaction_id, description, quantity, unit, rate, amount, tax_rate)
vendors(id, name, gstin, phone, default_category)"""

ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                   getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
MAX_ROWS = 200
MAX_STEPS = 2_000_000  # stops runaway queries


def run_readonly_query(sql: str, path: str | None = None) -> dict:
    """Run one SELECT on a read-only connection. Anything that writes is refused at three levels:
    the statement check, a read-only connection, and an authorizer that only allows reads."""
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"(?is)^(select|with)\b", sql):
        raise ValueError("Only SELECT queries are allowed.")

    conn = sqlite3.connect(f"file:{path or db_path()}?mode=ro", uri=True)
    try:
        conn.set_authorizer(lambda action, *args: sqlite3.SQLITE_OK if action in ALLOWED_ACTIONS
                            else sqlite3.SQLITE_DENY)
        steps = [0]

        def progress() -> int:
            steps[0] += 1
            return 1 if steps[0] > MAX_STEPS / 1000 else 0
        conn.set_progress_handler(progress, 1000)
        try:
            cursor = conn.execute(sql)
        except sqlite3.DatabaseError as error:
            raise ValueError(f"Query failed: {error}") from error
        rows = cursor.fetchmany(MAX_ROWS + 1)
        columns = [c[0] for c in cursor.description]
        return {"columns": columns, "rows": [list(r) for r in rows[:MAX_ROWS]],
                "truncated": len(rows) > MAX_ROWS}
    finally:
        conn.close()


# ---------- One transaction in full ----------

def get_transaction(conn: sqlite3.Connection, transaction_id: int) -> dict:
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    if row is None:
        raise ValueError(f"No transaction with id {transaction_id}")
    result = {k: row[k] for k in row.keys() if k not in ("data", "model_data")}
    result["line_items"] = [dict(r) for r in conn.execute(
        "SELECT description, quantity, unit, rate, amount, tax_rate FROM line_items WHERE transaction_id = ?",
        (transaction_id,))]
    return result
