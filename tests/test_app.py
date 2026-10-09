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
    assert app.header[0].value == "26/08/15 Palermo Spicy 2026 (demo)"
    m = metrics(app)
    assert m["Total planned [g]"] == "126.3"
    assert m["Total actual [g]"] == "120.1"
    assert m["Cure time"] == "34 days"
    assert m["Target weight"] == "1365 g"
    assert m["Latest weight"] == "1963 g"


def test_add_weigh_in(app, tmp_path):
    next(n for n in app.number_input if n.label == "Weight incl. wrap + net [g]").set_value(1950)
    next(b for b in app.button if b.label == "Save weigh-in").click()
    app.run()
    assert not app.exception, app.exception
    con = db.connect(tmp_path / storage.DB_NAME)
    assert db.readings(con, 1)[-1][1] == 1950


def test_create_new_project(app):
    next(t for t in app.sidebar.text_input if t.label == "Name").input("Test batch")
    next(n for n in app.sidebar.number_input if n.label == "Meat weight [g]").set_value(1000)
    next(b for b in app.sidebar.button if b.label == "Create project").click()
    app.run()
    assert not app.exception, app.exception
    assert app.header[0].value.endswith(" Test batch")
    assert app.header[0].value[:8] == db.today().strftime("%y/%m/%d")
    assert metrics(app)["Total planned [g]"] == "46.5"   # Classic Italian, 1000 g


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


def test_delete_project_needs_exact_name(app, tmp_path):
    btn = lambda: next(b for b in app.button if b.label == "Delete project permanently")
    assert btn().disabled
    next(t for t in app.text_input if t.label.startswith("Type the project name")).input("wrong")
    app.run()
    assert btn().disabled
    next(t for t in app.text_input if t.label.startswith("Type the project name")).input(
        "Palermo Spicy 2026 (demo)")
    app.run()
    btn().click()
    app.run()
    assert not app.exception, app.exception
    # demo is not re-seeded after deleting it
    assert any("Create a project" in i.value for i in app.info)


def test_cure_tab_live_recalc_and_save(app, tmp_path):
    # demo is saved, so nothing to save yet
    save = lambda: next(b for b in app.button if b.label == "Save cure")
    assert save().disabled
    next(n for n in app.number_input if n.label == "Thickness [cm]").set_value(10.0)
    app.run()
    assert {m.label: m.value for m in app.metric}["Cure time"] == "12 days"   # recalculated live
    assert not save().disabled
    save().click()
    app.run()
    assert not app.exception, app.exception
    assert db.project(db.connect(tmp_path / storage.DB_NAME), 1)["thickness_cm"] == 10.0


def test_new_project_with_own_start_date(app, tmp_path):
    from datetime import date
    next(t for t in app.sidebar.text_input if t.label == "Name").input("Back-dated")
    next(d for d in app.sidebar.date_input if d.label == "Start date").set_value(date(2026, 9, 1))
    next(b for b in app.sidebar.button if b.label == "Create project").click()
    app.run()
    assert not app.exception, app.exception
    assert app.header[0].value == "26/09/01 Back-dated"


def test_spice_notes_saved(app, tmp_path):
    next(t for t in app.text_input if t.label == "Reason (saved in history)").input("notes")
    app.run()
    next(b for b in app.button if b.label == "Unlock spice mix").click()
    app.run()
    next(t for t in app.text_area if t.label == "Notes").input("Mixed by hand")
    next(b for b in app.button if b.label == "Save actual amounts").click()
    app.run()
    assert not app.exception, app.exception
    assert db.project(db.connect(tmp_path / storage.DB_NAME), 1)["spice_note"] == "Mixed by hand"
