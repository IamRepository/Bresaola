"""Smoke tests: the Streamlit app renders every tab and core actions work."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def raw_photo(pid: int, name: str, data: bytes) -> str:
    """Write bytes straight into the photo folder (bypasses shrinking), return relative path."""
    rel = f"{storage.PHOTO_DIR}/{pid}/{name}"
    f = storage.data_dir() / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return rel


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
    assert app.header[0].value == "26/08/15 Palermo Spicy"
    m = metrics(app)
    assert m["Total planned [g]"] == "126.3"
    assert m["Total actual [g]"] == "120.1"
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


def test_delete_project_needs_exact_name(app, tmp_path):
    btn = lambda: next(b for b in app.button if b.label == "Delete project permanently")
    assert btn().disabled
    next(t for t in app.text_input if t.label.startswith("Type the project name")).input("wrong")
    app.run()
    assert btn().disabled
    next(t for t in app.text_input if t.label.startswith("Type the project name")).input(
        "Palermo Spicy")
    app.run()
    btn().click()
    app.run()
    assert not app.exception, app.exception
    # demo is not re-seeded after deleting it
    assert any("Create a project" in i.value for i in app.info)


def band(at) -> str:
    return next(m.value for m in at.markdown if "cureband" in m.value)


def test_cure_band_shows_dates_and_days(app):
    html = band(app)
    for text in ("15 Aug 2026", "18 Sep 2026", "20 Sep 2026", "28.0 days", "34 days", "36 days", "+2 vs plan"):
        assert text in html, text


def unlock(app, step_label):
    i = [b.label for b in app.button].index(f"Unlock {step_label}")
    reasons = [t for t in app.text_input if t.label == "Reason (saved in history)"]
    # the reason field sits right before its button; pick by key suffix
    key = {"spice mix": "unlspice", "cure": "unlcure", "drying": "unldry"}[step_label]
    next(t for t in reasons if t.key.startswith(key)).input("test")
    app.run()
    next(b for b in app.button if b.label == f"Unlock {step_label}").click()
    app.run()
    assert not app.exception, app.exception


def test_cure_locked_in_demo_notes_still_editable(app, tmp_path):
    assert any(b.label == "Unlock cure" for b in app.button)
    assert next(n for n in app.number_input if n.label == "Thickness [cm]").disabled
    notes = [t for t in app.text_area if t.label == "Notes"]
    cure_notes = next(t for t in notes if "Equilibrium dry cure" in (t.value or ""))
    assert not cure_notes.disabled
    cure_notes.input("Equilibrium dry cure. Bag leaked on day 3.")
    app.run()
    next(b for b in app.button if b.label == "Save notes" and b.key.startswith("cure")).click()
    app.run()
    assert not app.exception, app.exception
    assert "leaked" in db.project(db.connect(tmp_path / storage.DB_NAME), 1)["cure_note"]


def test_cure_tab_live_recalc_and_save(app, tmp_path):
    unlock(app, "cure")
    # demo is saved, so nothing to save yet
    save = lambda: next(b for b in app.button if b.label == "Save cure")
    assert save().disabled
    next(n for n in app.number_input if n.label == "Thickness [cm]").set_value(10.0)
    app.run()
    assert "12 days" in band(app)   # recalculated live
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
    # notes can be saved while locked
    next(t for t in app.text_area if t.label == "Notes").input("Mixed by hand")
    app.run()
    next(b for b in app.button if b.label == "Save notes").click()
    app.run()
    assert not app.exception, app.exception
    assert db.project(db.connect(tmp_path / storage.DB_NAME), 1)["spice_note"] == "Mixed by hand"


def test_photos_belong_to_their_step(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    from bresaola.demo import seed_demo
    con = db.connect(storage.db_path())
    seed_demo(con)
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (8, 8), "brown").save(buf, "PNG"); png = buf.getvalue()
    with con:
        db.add_photo(con, 1, storage.save_photo(1, "a.png", png), "2026-08-15", "spice rub", stage="spice")
        db.add_photo(con, 1, raw_photo(1, "b.jpg", b"not an image"), "2026-09-20", "unbagged",
                     stage="cure")   # unreadable file: page must still render
    con.close()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    heads = [m.value for m in at.markdown if m.value.startswith("##### ")]
    assert "##### Photos: spice mix" in heads and "##### Photos: cure" in heads
    assert any("Can't show this photo" in w.value for w in at.warning)
    captions = " ".join(c.value for c in at.caption)
    assert "spice rub" in captions and "unbagged" in captions
    con = db.connect(storage.db_path())
    assert [r["caption"] for r in db.photos(con, 1, "spice")] == ["spice rub"]
    assert [r["caption"] for r in db.photos(con, 1, "cure")] == ["unbagged"]


def test_lock_drying_blocks_weigh_ins(app, tmp_path):
    next(b for b in app.button if b.label == "Done: lock drying").click()
    app.run()
    assert not app.exception, app.exception
    assert next(b for b in app.button if b.label == "Save weigh-in").disabled
    con = db.connect(tmp_path / storage.DB_NAME)
    assert db.project(con, 1)["dry_locked_at"] and db.project(con, 1)["dry_end"]


def test_weigh_in_typo_asks_for_confirmation(app, tmp_path):
    next(n for n in app.number_input if n.label == "Weight incl. wrap + net [g]").set_value(196)
    next(b for b in app.button if b.label == "Save weigh-in").click()
    app.run()
    assert not app.exception, app.exception
    assert any("Check this weigh-in" in w.value for w in app.warning)
    next(b for b in app.button if b.label == "Cancel").click()
    app.run()
    con = db.connect(tmp_path / storage.DB_NAME)
    assert db.readings(con, 1)[-1][1] == 1963            # nothing saved


def test_close_button_disabled_until_steps_locked(app):
    assert any("Before this project can be closed: lock drying" in i.value for i in app.info)
    assert next(b for b in app.button if b.label == "Close project").disabled


def test_rename_to_existing_name_shows_message(app):
    next(t for t in app.sidebar.text_input if t.label == "Name").input("Rome")
    next(b for b in app.sidebar.button if b.label == "Create project").click()
    app.run()
    next(t for t in app.text_input if t.key and t.key.startswith("rn")).input("Palermo Spicy")
    app.run()
    next(b for b in app.button if b.label == "Rename").click()
    app.run()
    assert not app.exception, app.exception
    assert any("already exists" in e.value for e in app.error)


def test_drying_start_editable_in_app(app, tmp_path):
    from datetime import date
    exp_date = next(d for d in app.date_input if d.label == "Drying start")
    assert not exp_date.disabled
    next(n for n in app.number_input if n.label == "Packaging: wrap + net [g]").set_value(30)
    next(b for b in app.button if b.label == "Save drying start").click()
    app.run()
    assert not app.exception, app.exception
    assert db.project(db.connect(tmp_path / storage.DB_NAME), 1)["tare_g"] == 30


def test_start_drying_needs_a_weighed_start(app):
    next(t for t in app.sidebar.text_input if t.label == "Name").input("New piece")
    next(b for b in app.sidebar.button if b.label == "Create project").click()
    app.run()
    w = next(n for n in app.number_input if n.label == "Start weight incl. wrap + net [g]")
    assert w.value is None                                    # no raw-weight placeholder
    next(b for b in app.button if b.label == "Start drying").click()
    app.run()
    assert not app.exception, app.exception
    assert any("Enter the start weight" in e.value for e in app.error)


def test_changing_weight_asks_before_resetting_actuals(app, tmp_path):
    unlock(app, "spice mix")                                  # demo has fennel 4.2 vs 10.4 planned
    next(n for n in app.number_input if n.label == "Meat weight after trimming [g]").set_value(2000)
    app.run()
    assert any("replaces them with the new plan" in w.value for w in app.warning)
    con = db.connect(tmp_path / storage.DB_NAME)
    assert db.project(con, 1)["green_weight_g"] == 2088       # nothing changed yet
    next(b for b in app.button if b.label == "Keep my amounts").click()
    app.run()
    assert not app.exception, app.exception
    assert next(n for n in app.number_input if n.label == "Meat weight after trimming [g]").value == 2088


def test_equalise_tab_lock_flow(app, tmp_path):
    from datetime import date
    next(b for b in app.button if b.label == "Done: lock drying").click()      # drying ends today
    app.run()
    next(d for d in app.date_input if d.label == "Into the vacuum bag").set_value(db.today())
    next(d for d in app.date_input if d.label == "Out of the bag").set_value(db.today())
    app.run()
    next(b for b in app.button if b.label == "Done: lock equalising").click()
    app.run()
    assert not app.exception, app.exception
    p = db.project(db.connect(tmp_path / storage.DB_NAME), 1)
    assert p["equalise_locked_at"] and p["equalise_start"] == db.today().isoformat()
