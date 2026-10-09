"""Backup and restore."""
import pytest

from bresaola import db, storage
from tests.test_app import raw_photo


def test_backup_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path / "a"))
    from bresaola.demo import seed_demo
    con = db.connect(storage.db_path())
    seed_demo(con)
    rel = raw_photo(1, "x.jpg", b"fake")
    with con:
        db.add_photo(con, 1, rel, "2026-10-08")
    con.close()
    blob = storage.make_backup()
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path / "b"))
    storage.restore_backup(blob)
    con = db.connect(storage.db_path())
    assert db.readings(con, 1)[-1][1] == 1963
    assert storage.photo_file(db.photos(con, 1)[0]["path"]).read_bytes() == b"fake"


def test_restore_rejects_other_zips(tmp_path, monkeypatch):
    import io, zipfile
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(ValueError):
        storage.restore_backup(buf.getvalue())
    with pytest.raises(ValueError, match="not a zip"):
        storage.restore_backup(b"plain bytes")


def test_bad_backup_leaves_data_untouched(tmp_path, monkeypatch):
    import io, zipfile
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    from bresaola.demo import seed_demo
    con = db.connect(storage.db_path()); seed_demo(con)
    rel = raw_photo(1, "x.jpg", b"keep me")
    with con:
        db.add_photo(con, 1, rel, "2026-10-08")
    con.close()
    for content in (b"garbage", None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            if content:
                z.writestr("bresaola.sqlite", content)          # not a database
            else:
                import sqlite3, tempfile, os
                f = tmp_path / "empty.sqlite"; sqlite3.connect(f).execute("CREATE TABLE x(a)").connection.commit()
                z.write(f, "bresaola.sqlite")                   # a database, but not ours
        with pytest.raises(ValueError):
            storage.restore_backup(buf.getvalue())
        con = db.connect(storage.db_path())
        assert db.project(con, 1)["name"] == "Palermo Spicy"
        assert storage.photo_file(rel).read_bytes() == b"keep me"
        con.close()


def test_good_restore_keeps_previous_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path / "a"))
    from bresaola.demo import seed_demo
    con = db.connect(storage.db_path()); seed_demo(con); con.close()
    blob = storage.make_backup()
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path / "b"))
    con = db.connect(storage.db_path())
    with con:
        db.create_project(con, "Only in b", "Classic Italian", False, 1000)
    con.close()
    storage.restore_backup(blob)
    con = db.connect(storage.db_path())
    assert [p["name"] for p in db.projects(con)] == ["Palermo Spicy"]
    assert (tmp_path / "b" / "before-restore" / storage.DB_NAME).exists()
