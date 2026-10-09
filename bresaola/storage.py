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


PHOTO_MAX_PX = 1600          # longest side; plenty for screen and the PDF summary
PHOTO_QUALITY = 82           # JPEG quality: ~200-400 KB for a phone photo
UPLOAD_TYPES = ["jpg", "jpeg", "png", "webp", "heic", "heif"]

try:                         # iPhone photos (HEIC); optional
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:          # pragma: no cover
    UPLOAD_TYPES = UPLOAD_TYPES[:4]


def shrink_image(data: bytes) -> bytes:
    """Upright (phone orientation applied), at most PHOTO_MAX_PX, JPEG, metadata stripped.
    Raises ValueError if the file is not a readable image."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
    except (UnidentifiedImageError, OSError):
        raise ValueError("This file is not a photo the app can read (JPG, PNG, WEBP or HEIC)") from None
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, "white")
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    im.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=PHOTO_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def save_photo(project_id: int, filename: str, data: bytes) -> str:
    """Shrink and store a photo under photos/<project>/<uuid>.jpg; return the relative path."""
    small = shrink_image(data)
    rel = Path(PHOTO_DIR) / str(project_id) / f"{uuid.uuid4().hex}.jpg"
    full = data_dir() / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(small)
    return rel.as_posix()


def shrink_existing_photos(limit_bytes: int = 600_000) -> int:
    """One-off tidy-up: re-save photos stored before shrinking existed. Keeps the file name,
    so database paths stay valid. Returns how many files were shrunk."""
    n = 0
    for f in (data_dir() / PHOTO_DIR).rglob("*"):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg") and f.stat().st_size > limit_bytes:
            try:
                from PIL import Image
                with Image.open(f) as im:          # reads the header only
                    if max(im.size) <= PHOTO_MAX_PX:
                        continue                   # already shrunk, just a detailed photo
            except Exception:
                continue
            try:
                f.write_bytes(shrink_image(f.read_bytes()))
                n += 1
            except ValueError:
                pass                     # unreadable file: leave it, the gallery shows a warning
    return n


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
