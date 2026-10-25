"""The inbox: a folder where bill photos are dropped. New photos become pending uploads."""
import hashlib
import os
import sqlite3
from pathlib import Path

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


def inbox_dir() -> Path:
    return Path(os.getenv("VARAVU_INBOX", "inbox"))


def register_inbox(conn: sqlite3.Connection, folder: Path | None = None) -> list[dict]:
    """Register every new image in the inbox folder. Returns the newly added uploads."""
    folder = Path(folder) if folder else inbox_dir()
    folder.mkdir(parents=True, exist_ok=True)
    added = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in IMAGE_TYPES:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if conn.execute("SELECT 1 FROM uploads WHERE file_hash = ?", (digest,)).fetchone():
            continue  # this exact photo is already registered
        cursor = conn.execute("INSERT INTO uploads (file_path, file_hash) VALUES (?, ?)", (str(path), digest))
        added.append({"upload_id": cursor.lastrowid, "file": path.name})
    conn.commit()
    return added


def list_pending(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, file_path, created_at FROM uploads WHERE status = 'pending' ORDER BY id")
    return [{"upload_id": r["id"], "file": Path(r["file_path"]).name, "added": r["created_at"]} for r in rows]


def get_upload(conn: sqlite3.Connection, upload_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    if row is None:
        raise ValueError(f"No upload with id {upload_id}")
    return row
