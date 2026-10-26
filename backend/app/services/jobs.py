"""Background scanning, so the MCP tool can return immediately instead of timing out.

start_scan queues uploads and starts a worker thread; scan_status reports progress.
Upload status moves: pending -> queued -> scanning -> processed | failed.
"""
import sqlite3
import sys
import threading
from typing import Callable

from backend.app.db import connect
from backend.app.services.drafts import claim_upload, scan_upload


def queue_uploads(conn: sqlite3.Connection, upload_ids: list[int] | None = None) -> list[int]:
    """Mark pending uploads as queued (all of them, or only the ids given). Returns the queued ids."""
    rows = conn.execute("SELECT id FROM uploads WHERE status = 'pending' ORDER BY id").fetchall()
    wanted = [r["id"] for r in rows if upload_ids is None or r["id"] in upload_ids]
    for upload_id in wanted:
        conn.execute("UPDATE uploads SET status = 'queued' WHERE id = ? AND status = 'pending'", (upload_id,))
    conn.commit()
    return wanted


def claim_next(conn: sqlite3.Connection) -> int | None:
    """Take the oldest queued upload, or None when the queue is empty."""
    while True:
        row = conn.execute("SELECT id FROM uploads WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        if claim_upload(conn, row["id"], "queued"):
            return row["id"]


def process_queue(conn: sqlite3.Connection, get_providers: Callable) -> int:
    """Scan queued uploads one by one until none are left. Returns how many were processed."""
    provider, fallback = get_providers()
    done = 0
    while (upload_id := claim_next(conn)) is not None:
        try:
            scan_upload(conn, upload_id, provider, fallback, already_claimed=True)
        except Exception as error:  # scan_upload already marked it failed; keep going with the rest
            print(f"Scan of upload {upload_id} failed: {error}", file=sys.stderr)
        done += 1
    return done


def recover_stuck_scans(conn: sqlite3.Connection) -> int:
    """At startup no scan can be running, so 'scanning' means the server stopped mid-scan. Requeue those."""
    cursor = conn.execute("UPDATE uploads SET status = 'queued' WHERE status = 'scanning'")
    conn.commit()
    return cursor.rowcount


def retry_failed(conn: sqlite3.Connection, upload_id: int) -> dict:
    cursor = conn.execute("UPDATE uploads SET status = 'pending', error = NULL WHERE id = ? AND status = 'failed'",
                          (upload_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"Upload {upload_id} is not a failed upload.")
    return {"upload_id": upload_id, "status": "pending"}


def scan_status(conn: sqlite3.Connection) -> dict:
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM uploads GROUP BY status")}
    failed = [{"upload_id": r["id"], "error": r["error"]}
              for r in conn.execute("SELECT id, error FROM uploads WHERE status = 'failed' ORDER BY id")]
    drafts = conn.execute("SELECT count(*) AS n FROM drafts WHERE status = 'pending'").fetchone()["n"]
    busy = counts.get("queued", 0) + counts.get("scanning", 0)
    return {"uploads": counts, "failed": failed, "drafts_waiting_for_review": drafts,
            "message": f"{busy} bill(s) still being scanned." if busy else "All scans finished."}


class ScanWorker:
    """One background thread per shop that drains that shop's queue. Starting it while it runs does nothing."""

    def __init__(self, get_providers: Callable, shop: str = "local"):
        self.get_providers = get_providers
        self.shop = shop
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def start(self) -> bool:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.thread = threading.Thread(target=self._run, name=f"varavu-scanner-{self.shop}", daemon=True)
            self.thread.start()
            return True

    def _run(self) -> None:
        conn = connect(shop=self.shop)  # each thread needs its own connection, to this shop's database
        try:
            recover_stuck_scans(conn)   # no scan of this shop is running now, so 'scanning' means interrupted
            process_queue(conn, self.get_providers)
        except Exception as error:
            print(f"Scan worker for {self.shop} stopped: {error}", file=sys.stderr)
        finally:
            conn.close()
