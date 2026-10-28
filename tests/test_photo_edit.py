"""Photo caption edit and delete (v0.4.5). Open projects only: a closed project keeps its photos."""
import io
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TODAY = date(2026, 10, 11)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(storage.db_path())
    seed_demo(con)
    return con


def jpeg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (400, 300), "brown").save(b, "JPEG")
    return b.getvalue()


def add(con, stage="spice", caption="rub"):
    rel = storage.save_photo(1, "a.jpg", jpeg())
    with con:
        return db.add_photo(con, 1, rel, "2026-08-15", caption, stage=stage), rel


def test_delete_photo_removes_row_file_and_logs(env):
    ph, rel = add(env)
    with env:
        path = db.delete_photo(env, ph)
    assert storage.delete_photo_file(path)
    assert not storage.photo_file(rel).exists()
    assert db.photos(env, 1) == []
    assert db.events(env, 1)[-1]["kind"] == "photo_deleted"


def test_caption_can_be_changed_and_cleared(env):
    ph, _ = add(env)
    with env:
        db.set_photo_caption(env, ph, "  spice rub, day 0 ")
    assert db.photos(env, 1)[0]["caption"] == "spice rub, day 0"
    with env:
        db.set_photo_caption(env, ph, "")
    assert db.photos(env, 1)[0]["caption"] is None


def test_closed_project_keeps_its_photos(env):
    ph, rel = add(env)
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
        db.close_project(env, 1)
    with pytest.raises(db.Locked):
        db.delete_photo(env, ph)
    with pytest.raises(db.Locked):
        db.set_photo_caption(env, ph, "new")
    assert len(db.photos(env, 1)) == 1 and storage.photo_file(rel).exists()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert not [b for b in at.button if b.label == "Delete photo"]


def test_file_delete_stays_inside_photos_folder(env, tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("x")
    assert not storage.delete_photo_file("keep.txt")
    assert not storage.delete_photo_file("photos/../keep.txt")
    assert outside.exists()


def test_delete_from_the_day0_screen(env):
    ph, rel = add(env)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "rail_day0").click()
    at.run()
    assert not at.exception, at.exception
    next(c for c in at.checkbox if c.key == f"phx{ph}").check()
    at.run()
    next(b for b in at.button if b.key == f"phd{ph}").click()
    at.run()
    assert not at.exception, at.exception
    assert db.photos(env, 1) == [] and not storage.photo_file(rel).exists()


def test_caption_from_the_day0_screen(env):
    ph, _ = add(env)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "rail_day0").click()
    at.run()
    next(t for t in at.text_input if (t.key or "").split("@")[0] == f"phc{ph}").input("rub before bagging")
    at.run()
    next(b for b in at.button if b.key == f"phs{ph}").click()
    at.run()
    assert not at.exception, at.exception
    assert db.photos(env, 1)[0]["caption"] == "rub before bagging"


def test_file_that_cannot_be_deleted_does_not_crash(env, monkeypatch):
    """Diff audit v0.4.5 (Low): an unlink error (NAS permissions) raised on the page."""
    _, rel = add(env)
    def boom(self, *a, **k):
        raise PermissionError("read-only")
    monkeypatch.setattr(Path, "unlink", boom)
    assert storage.delete_photo_file(rel) is False
