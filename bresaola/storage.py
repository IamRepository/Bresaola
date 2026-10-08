"""Where data lives, and backup/restore as a single zip file.

BRESAOLA_DATA   folder for the database and photos (default ./data)
BRESAOLA_MODE   "persistent" on the NAS/PC; anything else shows the test-mode banner
"""
from __future__ import annotations

import io
import os
import shutil
import sqlite3
import uuid
import zipfile
from pathlib import Path

DB_NAME = "bresaola.sqlite"
PHOTO_DIR = "photos"


def data_dir() -> Path:
    d = Path(os.environ.get("BRESAOLA_DATA", "data"))
    (d / PHOTO_DIR).mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / DB_NAME


def is_test_mode() -> bool:
    return os.environ.get("BRESAOLA_MODE", "").lower() != "persistent"


def save_photo(project_id: int, filename: str, data: bytes) -> str:
    """Store bytes under photos/<project>/<uuid>.<ext>; return the relative path."""
    ext = Path(filename).suffix.lower() or ".jpg"
    rel = Path(PHOTO_DIR) / str(project_id) / f"{uuid.uuid4().hex}{ext}"
    full = data_dir() / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return rel.as_posix()


def photo_file(rel: str) -> Path:
    return data_dir() / rel


def make_backup() -> bytes:
    """Zip of a consistent database copy plus all photos."""
    buf = io.BytesIO()
    d = data_dir()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if db_path().exists():
            src = sqlite3.connect(db_path())
            tmp = d / f".backup-{uuid.uuid4().hex}.sqlite"
            dst = sqlite3.connect(tmp)
            src.backup(dst)
            dst.close(); src.close()
            z.write(tmp, DB_NAME)
            tmp.unlink()
        for p in (d / PHOTO_DIR).rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(d).as_posix())
    return buf.getvalue()


def restore_backup(data: bytes) -> None:
    """Replace the database and photos with the contents of a backup zip."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if DB_NAME not in names:
            raise ValueError("Not a Bresaola backup: no database inside")
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError(f"Unsafe path in backup: {n}")
        d = data_dir()
        shutil.rmtree(d / PHOTO_DIR, ignore_errors=True)
        if db_path().exists():
            db_path().unlink()
        z.extractall(d)
    (data_dir() / PHOTO_DIR).mkdir(parents=True, exist_ok=True)
