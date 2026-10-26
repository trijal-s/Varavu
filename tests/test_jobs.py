"""Background scanning: queueing, claiming, failures and recovery, with a fake provider."""
import pytest

from backend.app.db import connect
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem
from backend.app.services import jobs
from backend.app.services.drafts import list_drafts, scan_upload
from backend.app.services.inbox import register_inbox


class FakeProvider(ExtractionProvider):
    name = "fake"

    def extract(self, image_bytes, mime_type, prompt):
        if image_bytes == b"broken":
            raise RuntimeError("model unavailable")
        entry = BillEntry(vendor_name="SHOP", bill_number=image_bytes.decode(), date_as_written="1/3/24",
                          line_items=[LineItem(description="item", quantity=1, rate=100, amount=100)], total=100)
        return DocumentExtraction(document_type="cash_bill", is_readable=True, is_obscured=False, entries=[entry])


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name, content in (("a.png", b"1"), ("b.png", b"2"), ("c.png", b"broken")):
        (inbox / name).write_bytes(content)
    register_inbox(connection, inbox)
    return connection


def providers():
    return FakeProvider(), None


def test_queue_and_process_all(conn):
    assert jobs.queue_uploads(conn) == [1, 2, 3]
    assert jobs.process_queue(conn, providers) == 3
    status = jobs.scan_status(conn)
    assert status["uploads"] == {"processed": 2, "failed": 1}
    assert status["failed"][0]["error"] == "model unavailable"
    assert len(list_drafts(conn)) == 2


def test_a_bill_cannot_be_scanned_twice(conn):
    scan_upload(conn, 1, FakeProvider())
    with pytest.raises(ValueError, match="not pending"):
        scan_upload(conn, 1, FakeProvider())


def test_claim_gives_each_upload_once(conn):
    jobs.queue_uploads(conn)
    assert [jobs.claim_next(conn), jobs.claim_next(conn), jobs.claim_next(conn), jobs.claim_next(conn)] == [1, 2, 3, None]


def test_interrupted_scan_is_requeued(conn):
    jobs.queue_uploads(conn, [1])
    jobs.claim_next(conn)  # the server "stops" while upload 1 is scanning
    assert jobs.recover_stuck_scans(conn) == 1
    assert jobs.claim_next(conn) == 1


def test_retry_failed(conn):
    jobs.queue_uploads(conn, [3])
    jobs.process_queue(conn, providers)
    assert jobs.retry_failed(conn, 3)["status"] == "pending"
    with pytest.raises(ValueError):
        jobs.retry_failed(conn, 1)  # not a failed upload


def test_worker_thread_drains_queue(tmp_path, monkeypatch, conn):
    monkeypatch.setenv("VARAVU_DB", str(tmp_path / "test.db"))
    jobs.queue_uploads(conn, [1, 2])
    worker = jobs.ScanWorker(providers)
    assert worker.start() is True
    worker.thread.join(timeout=10)
    assert jobs.scan_status(conn)["uploads"].get("processed") == 2
