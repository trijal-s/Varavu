"""Shop isolation: each shop has its own database and inbox, and tools only ever see the caller's shop."""
import json

import anyio
import pytest
from mcp import Client
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import backend.app.mcp_server.server as varavu
from backend.app.db import db_path_for
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.mcp_server.context import current_shop
from backend.app.mcp_server.http_app import ShopKeyMiddleware, load_shop_keys
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem

KEY_A, KEY_B = "a" * 32, "b" * 32


class FakeProvider(ExtractionProvider):
    name = "fake"

    def extract(self, image_bytes, mime_type, prompt):
        entry = BillEntry(vendor_name="SHOP A SUPPLIER", bill_number="77", date_as_written="1/3/24",
                          line_items=[LineItem(description="secret feed", quantity=1, rate=500, amount=500)],
                          total=500)
        return DocumentExtraction(document_type="cash_bill", is_readable=True, is_obscured=False, entries=[entry])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("VARAVU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VARAVU_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("VARAVU_EXPORTS", str(tmp_path / "exports"))
    monkeypatch.setattr(varavu, "get_providers", lambda: (FakeProvider(), None))
    (tmp_path / "inbox" / "shopA").mkdir(parents=True)
    (tmp_path / "inbox" / "shopA" / "bill.png").write_bytes(b"photo")


def call(tool, **arguments):
    """Call one MCP tool in-process; returns (is_error, result)."""
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


def test_shop_b_cannot_see_shop_a_bills(setup):
    token = current_shop.set("shopA")
    try:
        assert not call("scan_inbox")[0]
        _, drafts = call("scan_bill", upload_id=1)
        _, saved = call("confirm_entry", draft_id=drafts[0]["draft_id"], transaction_type="purchase",
                        category="feed")
        assert saved["total"] == 500
        assert len(call("list_transactions")[1]) == 1  # shop A sees its own bill
    finally:
        current_shop.reset(token)

    token = current_shop.set("shopB")
    try:
        assert call("list_transactions")[1] == []
        assert call("list_drafts")[1] == []
        assert call("list_pending")[1] == []
        assert call("search_bills", query="secret")[1] == []
        assert call("query_ledger", sql="SELECT count(*) FROM transactions")[1]["rows"] == [[0]]
        assert call("monthly_summary", month="2024-03")[1]["by_type"] == {}
        assert call("supplier_dues")[1] == []
        assert call("get_draft", draft_id=1)[0]          # shop B has no draft 1
        assert call("show_bill", upload_id=1)[0]          # ...or upload 1
    finally:
        current_shop.reset(token)


def test_each_shop_has_its_own_database_file(setup):
    assert db_path_for("shopA") != db_path_for("shopB")
    assert db_path_for("shopA").endswith("shopA.db")
    assert db_path_for("local") != db_path_for("shopA")


def test_middleware_sets_the_shop_from_the_key():
    async def who(request):
        return PlainTextResponse(current_shop.get())
    app = ShopKeyMiddleware(Starlette(routes=[Route("/mcp", who)]), {"shopA": KEY_A, "shopB": KEY_B})
    client = TestClient(app)
    assert client.get("/mcp", headers={"Authorization": f"Bearer {KEY_B}"}).text == "shopB"
    assert client.get("/mcp", headers={"Authorization": f"Bearer {KEY_A}"}).text == "shopA"


@pytest.mark.parametrize("name", ["../evil", "Shop One", "local", "a/b"])
def test_unsafe_shop_names_are_refused(name):
    with pytest.raises(ValueError):
        load_shop_keys(f"{name}:{KEY_A}")
