"""Call the MCP tools through a real MCP client (in memory), with a fake model provider."""
import json

import anyio
import pytest
from mcp import Client

import backend.app.mcp_server.server as varavu
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem


class FakeProvider(ExtractionProvider):
    name = "fake"

    def extract(self, image_bytes, mime_type, prompt):
        rows = [LineItem(description="feed", quantity=10, rate=810, amount=8100),
                LineItem(description="bran", quantity=5, rate=680, amount=2900)]  # rate misread
        entry = BillEntry(vendor_name="SRI MURUGAN TRADERS", bill_number="2361", date_as_written="22-2-21",
                          line_items=rows, total=11000)
        return DocumentExtraction(document_type="cash_bill", is_readable=True, is_obscured=False, entries=[entry])


@pytest.fixture
def env(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "bill.png").write_bytes(b"\x89PNG fake image")
    monkeypatch.setenv("VARAVU_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("VARAVU_INBOX", str(inbox))
    monkeypatch.setenv("VARAVU_EXPORTS", str(tmp_path / "exports"))
    monkeypatch.setattr(varavu, "get_providers", lambda: (FakeProvider(), None))


def call(tool: str, **arguments):
    """Call one tool and return (is_error, parsed result)."""
    async def run():
        async with Client(varavu.server) as client:
            return await client.call_tool(tool, arguments)
    result = anyio.run(run)
    if result.is_error:
        return True, result.content[0].text
    if result.structured_content is not None:
        data = result.structured_content
        return False, data["result"] if set(data) == {"result"} else data
    if result.content and result.content[0].type == "text":
        return False, json.loads(result.content[0].text)
    return False, result.content


def test_full_flow_through_mcp(env):
    error, scanned = call("scan_inbox")
    assert not error and len(scanned["new"]) == 1

    error, drafts = call("scan_bill", upload_id=1)
    assert not error and "line_items[1].rate" in drafts[0]["needs_review"]
    draft_id = drafts[0]["draft_id"]

    error, saved = call("confirm_entry", draft_id=draft_id, transaction_type="purchase",
                        category="cattle feed", corrections={"line_items[1].rate": 580})
    assert not error and saved["warnings"] == []

    error, summary = call("monthly_summary", month="2021-02")
    assert summary["by_type"]["purchase"]["amount"] == 11000

    error, exported = call("export_year", financial_year="2020-21")
    assert not error and exported["transactions"] == 1


def test_errors_come_back_as_messages(env):
    call("scan_inbox")
    _, drafts = call("scan_bill", upload_id=1)
    error, message = call("confirm_entry", draft_id=drafts[0]["draft_id"], transaction_type="unknown")
    assert error and "purchase, sale or expense" in message


def test_show_bill_returns_image(env):
    call("scan_inbox")
    _, content = call("show_bill", upload_id=1)
    assert content[0].type == "image"


def test_tools_are_annotated():
    async def run():
        async with Client(varavu.server) as client:
            return (await client.list_tools()).tools
    tools = {t.name: t for t in anyio.run(run)}
    assert tools["monthly_summary"].annotations.read_only_hint is True
    assert tools["confirm_entry"].annotations.read_only_hint is False


def test_background_scan_and_questions(env):
    call("scan_inbox")
    error, started = call("start_scan")
    assert not error and started["queued"] == [1]
    varavu.worker_for("local").thread.join(timeout=10)
    _, status = call("scan_status")
    assert status["drafts_waiting_for_review"] == 1

    _, drafts = call("list_drafts")
    call("confirm_entry", draft_id=drafts[0]["draft_id"], transaction_type="purchase", category="cattle feed",
         corrections={"line_items[1].rate": 580})
    _, found = call("search_bills", query="bran")
    assert found[0]["vendor_name"] == "SRI MURUGAN TRADERS"
    _, answer = call("query_ledger", sql="SELECT id, total FROM transactions WHERE category = 'cattle feed'")
    assert answer["rows"] == [[1, 11000.0]]
    error, message = call("query_ledger", sql="DELETE FROM transactions")
    assert error and "Only SELECT" in message


def test_draft_from_chat_image(env):
    entry = {"vendor_name": "SAI BOOK & XEROX HOUSE", "bill_number": "584", "date_as_written": "25/02/2026",
             "line_items": [{"description": "Ink pad", "quantity": 2, "rate": 40, "amount": 80},
                            {"description": "Fevistick", "quantity": 1, "rate": 25, "amount": 25}],
             "total": 150}  # misread total: rows add up to 105
    error, draft = call("draft_from_chat_image", document_type="cash_bill", entry=entry, description="sai_book.png")
    assert not error and "total" in draft["needs_review"]

    error, message = call("draft_from_chat_image", document_type="cash_bill", entry=entry)
    assert error and "already exists" in message  # the same reading twice is refused

    error, message = call("show_bill", upload_id=draft["upload_id"])
    assert error and "no photo is stored" in message

    error, saved = call("confirm_entry", draft_id=draft["draft_id"], transaction_type="purchase",
                        category="stationery", corrections={"total": 105})
    assert not error and saved["total"] == 105
