"""Smoke tests: the Streamlit app renders every tab and core actions work."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.delenv("BRESAOLA_MODE", raising=False)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def metrics(at):
    return {m.label: m.value for m in at.metric}


def test_renders_demo_project_in_test_mode(app):
    assert any("Test mode" in w.value for w in app.warning)
    assert app.header[0].value == "Palermo Spicy 2026 (demo)"
    m = metrics(app)
    assert m["Total planned (g)"] == "126.3"
    assert m["Total actual (g)"] == "120.1"
    assert m["Cure time (+20 %)"] == "34 days"
    assert m["Target weight"] == "1365 g"
    assert m["Latest weight"] == "1963 g"


def test_add_weigh_in(app, tmp_path):
    next(n for n in app.number_input if n.label == "Weight incl. wrap + net (g)").set_value(1950)
    next(b for b in app.button if b.label == "Save weigh-in").click()
    app.run()
    assert not app.exception, app.exception
    con = db.connect(tmp_path / storage.DB_NAME)
    assert db.readings(con, 1)[-1][1] == 1950


def test_create_new_project(app):
    next(t for t in app.text_input if t.label == "Name").input("Test batch")
    next(n for n in app.number_input if n.label == "Meat weight after trimming (g)").set_value(1000)
    next(b for b in app.button if b.label == "Create project").click()
    app.run()
    assert not app.exception, app.exception
    assert app.header[0].value == "Test batch"
    assert metrics(app)["Total planned (g)"] == "46.5"   # Classic Italian, 1000 g


def test_persistent_mode_has_no_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert not any("Test mode" in w.value for w in at.warning)
    assert any("Create a project" in i.value for i in at.info)   # no demo data


def test_backup_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path / "a"))
    from bresaola.demo import seed_demo
    con = db.connect(storage.db_path())
    seed_demo(con)
    rel = storage.save_photo(1, "x.jpg", b"fake")
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
