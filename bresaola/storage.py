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


def delete_project_photos(project_id: int) -> None:
    shutil.rmtree(data_dir() / PHOTO_DIR / str(project_id), ignore_errors=True)


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


REQUIRED_TABLES = {"project", "ingredient_line", "reading", "photo", "chamber"}


def _check_backup_db(path: Path) -> None:
    """Raise ValueError unless path is a readable Bresaola database."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("The database in this backup is damaged")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except sqlite3.DatabaseError:
        raise ValueError("The file inside this backup is not a Bresaola database") from None
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError("Not a Bresaola backup: missing " + ", ".join(sorted(missing)))


def restore_backup(data: bytes) -> None:
    """Replace the database and photos with the contents of a backup zip.

    Nothing is touched until the backup has been unpacked to a side folder and
    its database has passed a check. The data it replaces is kept in
    'before-restore/' (one generation) and put back if the swap fails.
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This file is not a zip backup") from None
    d = data_dir()
    live_db, live_photos = d / DB_NAME, d / PHOTO_DIR     # fixed paths: data_dir() recreates folders
    staging = d / f".restore-{uuid.uuid4().hex}"
    keep = d / "before-restore"
    try:
        with z:
            names = z.namelist()
            if DB_NAME not in names:
                raise ValueError("Not a Bresaola backup: no database inside")
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts or not (n == DB_NAME or n.startswith(PHOTO_DIR + "/")):
                    raise ValueError(f"Unexpected file in backup: {n}")
            z.extractall(staging)
        _check_backup_db(staging / DB_NAME)

        # swap: current data -> before-restore/, staged data -> live
        shutil.rmtree(keep, ignore_errors=True)
        keep.mkdir()
        if live_db.exists():
            shutil.move(str(live_db), keep / DB_NAME)
        if (live_photos).exists():
            shutil.move(str(live_photos), keep / PHOTO_DIR)
        try:
            shutil.move(str(staging / DB_NAME), live_db)
            if (staging / PHOTO_DIR).exists():
                shutil.move(str(staging / PHOTO_DIR), live_photos)
        except Exception:
            # put the old data back
            if (keep / DB_NAME).exists():
                if live_db.exists():
                    live_db.unlink()
                shutil.move(str(keep / DB_NAME), live_db)
            if (keep / PHOTO_DIR).exists():
                shutil.rmtree(live_photos, ignore_errors=True)
                shutil.move(str(keep / PHOTO_DIR), live_photos)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        (live_photos).mkdir(parents=True, exist_ok=True)
