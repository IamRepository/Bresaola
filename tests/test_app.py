"""The Streamlit app: journey rail, each step, and the Done → next step flow."""
import io
from datetime import date
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


def ok(at):
    assert not at.exception, at.exception


def metrics(at):
    return {m.label: m.value for m in at.metric}


def goto(at, step):
    """Click a step on the journey rail: day0, cure, dry, finish."""
    next(b for b in at.button if b.key == f"rail_{step}").click()
    at.run()
    ok(at)


def btn(at, label):
    return next(b for b in at.button if b.label == label)


def html(at) -> str:
    return " ".join(m.value for m in at.markdown)


def project(tmp_path, pid=1):
    return db.project(db.connect(tmp_path / storage.DB_NAME), pid)


def new_project(at, name="New piece", weight=1000):
    next(t for t in at.sidebar.text_input if t.label == "Name").input(name)
    next(n for n in at.sidebar.number_input if n.label == "Meat weight [g]").set_value(weight)
    btn(at.sidebar, "Create project").click()
    at.run()
    ok(at)


def unlock(at, step):
    """step: spice, cure, dry (the unlock panel of the open step)."""
    label = {"spice": "Unlock day 0", "cure": "Unlock cure", "dry": "Unlock drying"}[step]
    next(t for t in at.text_input if t.key == f"unl{step}1").input("test")
    at.run()
    btn(at, label).click()
    at.run()
    ok(at)


# ---------------- rail and next action ----------------

def test_demo_opens_on_current_step_dry(app):
    assert any("Test mode" in w.value for w in app.warning)
    assert app.header[0].value == "26/08/15 Palermo Spicy"
    m = metrics(app)
    assert m["Target weight"] == "1365 g" and m["Latest weight"] == "1963 g"
    assert "Weigh today." in html(app)
    assert [b.key for b in app.button if b.key and b.key.startswith("rail_")] == \
        ["rail_day0", "rail_cure", "rail_dry", "rail_finish"]


def test_rail_navigation_and_go_back_button(app):
    goto(app, "day0")
    assert metrics(app)["Total planned [g]"] == "126.3"
    assert metrics(app)["Total actual [g]"] == "120.1"
    btn(app, "Go to Dry").click()            # next-action card offers a way back
    app.run(); ok(app)
    assert "Latest weight" in metrics(app)


# ---------------- day 0 ----------------

def test_new_project_starts_on_day0_and_done_jumps_to_cure(app, tmp_path):
    new_project(app, "Rome", 1838)
    assert app.header[0].value.endswith(" Rome")
    assert "Day 0:" in html(app)
    assert metrics(app)["Total planned [g]"] == "85.5"          # Classic Italian, 1838 g
    next(n for n in app.number_input if n.label == "Thickness [cm]").set_value(10.0)
    app.run(); ok(app)
    assert any("**12 days**" in c.value for c in app.caption)    # cure time shown live
    btn(app, "Done: lock day 0 and start curing").click()
    app.run(); ok(app)
    p = project(tmp_path, 2)
    assert p["spice_locked_at"] and p["thickness_cm"] == 10.0 and p["cure_start"] == db.today().isoformat()
    assert "cureband" in html(app)                               # now on the Cure step
    assert "Curing:" in html(app)


def test_new_project_with_own_start_date(app):
    next(t for t in app.sidebar.text_input if t.label == "Name").input("Back-dated")
    next(d for d in app.sidebar.date_input if d.label == "Start date").set_value(date(2026, 9, 1))
    btn(app.sidebar, "Create project").click()
    app.run(); ok(app)
    assert app.header[0].value == "26/09/01 Back-dated"
    assert next(d for d in app.date_input if d.label == "Into the bag").value == date(2026, 9, 1)


def test_day0_notes_editable_after_lock(app, tmp_path):
    goto(app, "day0")
    next(t for t in app.text_area if t.label == "Notes").input("Mixed by hand")
    app.run()
    btn(app, "Save notes").click()
    app.run(); ok(app)
    assert project(tmp_path)["spice_note"] == "Mixed by hand"


def test_changing_weight_asks_before_resetting_actuals(app, tmp_path):
    goto(app, "day0")
    unlock(app, "spice")
    next(n for n in app.number_input if n.label == "Meat weight after trimming [g]").set_value(2000)
    app.run(); ok(app)
    assert any("replaces them with the new plan" in w.value for w in app.warning)
    assert project(tmp_path)["green_weight_g"] == 2088
    btn(app, "Keep my amounts").click()
    app.run(); ok(app)
    assert next(n for n in app.number_input if n.label == "Meat weight after trimming [g]").value == 2088


def test_ecocure_toggle(app):
    goto(app, "day0")
    unlock(app, "spice")
    next(t for t in app.toggle if t.label == "EcoCure #2").set_value(True)
    app.run(); ok(app)
    btn(app, "Recalculate and reset").click()
    app.run(); ok(app)
    m = metrics(app)
    assert m["Total planned [g]"] == "136.8" and m["Salt [% of meat]"] == "3.0"
    assert m["EcoCure [% of meat]"] == "1.0"


# ---------------- cure ----------------

def test_cure_band_and_locked_state(app, tmp_path):
    goto(app, "cure")
    h = html(app)
    for text in ("15 Aug 2026", "18 Sep 2026", "20 Sep 2026", "28.0 days", "34 days", "36 days", "+2 vs plan"):
        assert text in h, text
    assert next(d for d in app.date_input if d.label == "Taken out of the bag").disabled
    notes = next(t for t in app.text_area if t.label == "Notes")
    assert not notes.disabled and "Equilibrium dry cure" in notes.value
    notes.input("Equilibrium dry cure. Bag leaked on day 3.")
    app.run()
    btn(app, "Save notes").click()
    app.run(); ok(app)
    assert "leaked" in project(tmp_path)["cure_note"]


def test_cure_done_jumps_to_dry_start(app, tmp_path):
    new_project(app, "Rome", 1838)
    next(n for n in app.number_input if n.label == "Thickness [cm]").set_value(4.0)
    next(d for d in app.date_input if d.label == "Into the bag").set_value(date(2026, 9, 1))
    app.run()
    btn(app, "Done: lock day 0 and start curing").click()
    app.run(); ok(app)
    assert btn(app, "Done: lock cure and start drying").disabled          # no out-of-bag date yet
    next(d for d in app.date_input if d.label == "Taken out of the bag").set_value(date(2026, 9, 5))
    app.run()
    btn(app, "Done: lock cure and start drying").click()
    app.run(); ok(app)
    assert project(tmp_path, 2)["cure_locked_at"]
    assert next(d for d in app.date_input if d.label == "Drying start").value == date(2026, 9, 5)
    w = next(n for n in app.number_input if n.label == "Start weight incl. wrap + net [g]")
    assert w.value is None
    btn(app, "Start drying").click()
    app.run(); ok(app)
    assert any("Enter the start weight" in e.value for e in app.error)


# ---------------- dry ----------------

def test_add_weigh_in(app, tmp_path):
    next(n for n in app.number_input if n.label == "Weight incl. wrap + net [g]").set_value(1950)
    btn(app, "Save weigh-in").click()
    app.run(); ok(app)
    assert db.readings(db.connect(tmp_path / storage.DB_NAME), 1)[-1][1] == 1950


def test_weigh_in_typo_asks_for_confirmation(app, tmp_path):
    next(n for n in app.number_input if n.label == "Weight incl. wrap + net [g]").set_value(196)
    btn(app, "Save weigh-in").click()
    app.run(); ok(app)
    assert any("Check this weigh-in" in w.value for w in app.warning)
    btn(app, "Cancel").click()
    app.run()
    assert db.readings(db.connect(tmp_path / storage.DB_NAME), 1)[-1][1] == 1963


def test_drying_start_editable(app, tmp_path):
    next(n for n in app.number_input if n.label == "Packaging: wrap + net [g]").set_value(30)
    btn(app, "Save drying start").click()
    app.run(); ok(app)
    assert project(tmp_path)["tare_g"] == 30


def test_dry_done_jumps_to_finish_and_blocks_weigh_ins(app, tmp_path):
    btn(app, "Done: lock drying and finish").click()
    app.run(); ok(app)
    p = project(tmp_path)
    assert p["dry_locked_at"] and p["dry_end"]
    assert "Final weight" in html(app) and "1963 g" in html(app)          # on Finish now
    goto(app, "dry")
    assert not any(b.label == "Save weigh-in" for b in app.button)      # weigh-in form hidden


# ---------------- finish ----------------

def test_finish_close_needs_all_locked(app):
    goto(app, "finish")
    assert any("Before this batch can be closed: lock drying" in i.value for i in app.info)
    assert btn(app, "Close project").disabled


def test_rename_to_existing_name_shows_message(app):
    new_project(app, "Rome")
    goto(app, "finish")
    next(t for t in app.text_input if t.key and t.key.startswith("rn")).input("Palermo Spicy")
    app.run()
    btn(app, "Rename").click()
    app.run(); ok(app)
    assert any("already exists" in e.value for e in app.error)


def test_delete_project_needs_exact_name(app):
    goto(app, "finish")
    b = lambda: btn(app, "Delete project permanently")
    assert b().disabled
    next(t for t in app.text_input if t.label.startswith("Type the project name")).input("Palermo Spicy")
    app.run()
    b().click()
    app.run(); ok(app)
    assert any("Create a project" in i.value for i in app.info)      # demo not re-seeded


# ---------------- photos and modes ----------------

def test_photos_belong_to_their_step(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.delenv("BRESAOLA_MODE", raising=False)
    from PIL import Image
    from bresaola.demo import seed_demo
    con = db.connect(storage.db_path())
    seed_demo(con)
    buf = io.BytesIO(); Image.new("RGB", (8, 8), "brown").save(buf, "PNG")
    with con:
        db.add_photo(con, 1, storage.save_photo(1, "a.png", buf.getvalue()), "2026-08-15", "spice rub",
                     stage="spice")
        db.add_photo(con, 1, raw_photo(1, "b.jpg", b"not an image"), "2026-09-20", "unbagged", stage="cure")
    con.close()
    at = AppTest.from_file(APP, default_timeout=30).run(); ok(at)
    goto(at, "day0")
    caps = " ".join(c.value for c in at.caption)
    assert "spice rub" in caps and "unbagged" not in caps
    goto(at, "cure")
    assert any("Can't show this photo" in w.value for w in at.warning)
    goto(at, "finish")                                           # all photos, by step
    caps = " ".join(c.value for c in at.caption)
    assert "spice rub" in caps and "unbagged" in caps


def test_persistent_mode_has_no_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30).run(); ok(at)
    assert not any("Test mode" in w.value for w in at.warning)
    assert any("Create a project" in i.value for i in at.info)
