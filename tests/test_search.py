"""Full-text search, read-only SQL and transaction details."""
import pytest

from backend.app.db import connect
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem
from backend.app.services import search
from backend.app.services.drafts import scan_upload
from backend.app.services.inbox import register_inbox
from backend.app.services.ledger import confirm_draft


class FakeProvider(ExtractionProvider):
    name = "fake"

    def extract(self, image_bytes, mime_type, prompt):
        rows = [LineItem(description="Rice bran", quantity=10, rate=810, amount=8100),
                LineItem(description="Groundnut cake", quantity=1, rate=2200, amount=2200)]
        entry = BillEntry(vendor_name="SRI MURUGAN TRADERS", bill_number="2361", date_as_written="22-2-21",
                          line_items=rows, total=10300)
        return DocumentExtraction(document_type="cash_bill", is_readable=True, is_obscured=False, entries=[entry])


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "test.db"
    conn = connect(path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "bill.png").write_bytes(b"x")
    register_inbox(conn, inbox)
    draft = scan_upload(conn, 1, FakeProvider())[0]
    confirm_draft(conn, draft["draft_id"], "purchase", "cattle feed")
    conn.close()
    return path


def test_search_by_item_vendor_and_prefix(db_file):
    conn = connect(db_file)
    assert search.search_bills(conn, "groundnut")[0]["id"] == 1
    assert search.search_bills(conn, "murugan")[0]["total"] == 10300
    assert search.search_bills(conn, "gro")  # prefix match
    assert search.search_bills(conn, "cement") == []


def test_search_index_can_be_rebuilt(db_file):
    conn = connect(db_file)
    conn.execute("DELETE FROM bill_search")
    assert search.rebuild_search_index(conn) == 1
    assert search.search_bills(conn, "bran")


def test_readonly_query_works(db_file):
    result = search.run_readonly_query(
        "SELECT category, sum(total) AS spent FROM transactions GROUP BY category", str(db_file))
    assert result["columns"] == ["category", "spent"] and result["rows"] == [["cattle feed", 10300.0]]


@pytest.mark.parametrize("sql", [
    "DELETE FROM transactions",
    "UPDATE transactions SET total = 0",
    "DROP TABLE vendors",
    "SELECT 1; DELETE FROM transactions",
    "PRAGMA table_info(transactions)",
    "WITH x AS (SELECT 1) DELETE FROM transactions",
])
def test_writes_are_refused(db_file, sql):
    with pytest.raises(ValueError):
        search.run_readonly_query(sql, str(db_file))
    assert search.run_readonly_query("SELECT count(*) FROM transactions", str(db_file))["rows"] == [[1]]


def test_get_transaction_has_line_items(db_file):
    detail = search.get_transaction(connect(db_file), 1)
    assert detail["upload_id"] == 1 and len(detail["line_items"]) == 2
