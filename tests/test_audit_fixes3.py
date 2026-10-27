"""Reproductions of full-audit findings (26 Oct 2026), fixed in v0.4.3. Each failed before the fix.
Numbers in the comments are the order in the issue list sent to the owner."""
import io
from datetime import date, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from bresaola import db, report, safety, sensors, storage
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


def second_batch_ready_to_dry(con) -> int:
    pid = db.create_project(con, "Second", "Classic Italian", False, 1000, start_date=date(2026, 9, 1))
    with con:
        db.lock_spice(con, pid)
        db.set_cure(con, pid, shape="flat", thickness_cm=4, start=date(2026, 9, 1), end_actual=date(2026, 9, 5))
        db.lock_cure(con, pid)
    return pid


def open_dry_start(pid):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(s for s in at.sidebar.selectbox if s.label == "Project").set_value(pid)
    at.run()
    next(b for b in at.button if b.key == "rail_dry").click()
    at.run()
    assert not at.exception, at.exception
    return at


# 1: "+ New chamber" shows its name and type fields straight away, not only after submitting
def test_new_chamber_fields_appear_before_submit(env):
    pid = second_batch_ready_to_dry(env)
    at = open_dry_start(pid)
    assert not [t for t in at.text_input if t.label == "New chamber name"]      # existing chamber picked
    next(s for s in at.selectbox if s.label == "Drying chamber").set_value("+ New chamber")
    at.run()
    assert not at.exception, at.exception
    next(t for t in at.text_input if t.label == "New chamber name").input("Curing cabinet")
    next(r for r in at.radio if r.label == "New chamber type").set_value("chamber")
    next(n for n in at.number_input if n.label == "Start weight incl. wrap + net [g]").set_value(950)
    next(b for b in at.button if b.label == "Start drying").click()
    at.run()
    assert not at.exception, at.exception
    p = db.project(env, pid)
    ch = env.execute("SELECT * FROM chamber WHERE id=?", (p["chamber_id"],)).fetchone()
    assert (ch["name"], ch["kind"]) == ("Curing cabinet", "chamber")


def test_new_chamber_needs_a_type(env):
    pid = second_batch_ready_to_dry(env)
    at = open_dry_start(pid)
    next(s for s in at.selectbox if s.label == "Drying chamber").set_value("+ New chamber")
    at.run()
    next(t for t in at.text_input if t.label == "New chamber name").input("Cabinet")
    next(n for n in at.number_input if n.label == "Start weight incl. wrap + net [g]").set_value(950)
    next(b for b in at.button if b.label == "Start drying").click()
    at.run()
    assert any("type" in e.value for e in at.error)
    assert db.project(env, pid)["dry_start"] is None


def test_new_chamber_name_must_be_new(env):
    pid = second_batch_ready_to_dry(env)
    at = open_dry_start(pid)
    next(s for s in at.selectbox if s.label == "Drying chamber").set_value("+ New chamber")
    at.run()
    next(r for r in at.radio if r.label == "New chamber type").set_value("chamber")
    next(n for n in at.number_input if n.label == "Start weight incl. wrap + net [g]").set_value(950)
    next(b for b in at.button if b.label == "Start drying").click()       # default name "Fridge drawer" exists
    at.run()
    assert any("already exists" in e.value for e in at.error)
    assert db.project(env, pid)["dry_start"] is None


# 2: a long note or caption no longer breaks the PDF; the full text is under Notes
def test_pdf_with_very_long_texts(env):
    long = ("The meat felt a bit soft on the outside today, " * 60).strip()     # ~2,800 characters
    lines = "\n".join(f"line {i}" for i in range(80))
    with env:
        env.execute("UPDATE reading SET note=? WHERE project_id=1 AND day=(SELECT MAX(day) FROM reading)", (long,))
        env.execute("UPDATE ingredient_line SET note=? WHERE project_id=1 AND position=1", (lines,))
        db.add_photo(env, 1, "photos/1/gone.jpg", "2026-09-20", long, stage="cure")
        env.execute("UPDATE project SET dry_note=? WHERE id=1", (long * 3,))
    pdf = report.build_pdf(env, 1)
    t = " ".join(" ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(pdf)).pages).split())
    assert "full text under Notes" in t
    assert "Weigh-in note" in t and "Ingredient note" in t and "Photo caption" in t
    assert "line 79" in t


# 3: changing the chamber type, or removing readings, leaves batches with locked drying alone
def test_locked_drying_keeps_its_chamber_type(env):
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
    assert db.project(env, 1)["dry_kind"] == "fridge"
    ch = db.project(env, 1)["chamber_id"]
    with env:
        db.set_chamber_kind(env, ch, "chamber")
    assert db.chamber_kind(env, db.project(env, 1)) == "fridge"
    with env:
        db.unlock_dry(env, 1, "test")
    assert db.chamber_kind(env, db.project(env, 1)) == "chamber"       # still drying: follows the chamber


def test_migration_freezes_type_of_already_locked_batches(env, tmp_path):
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
        env.execute("UPDATE project SET dry_kind=NULL")                  # as in a v0.4.2 database
    env.close()
    con = db.connect(storage.db_path())
    assert db.project(con, 1)["dry_kind"] == "fridge"


def test_removing_readings_keeps_locked_drying_periods(env):
    ch = db.project(env, 1)["chamber_id"]
    with env:
        sensors.import_readings(env, ch, [(datetime(2026, 9, 25, 12), 3.0, 80.0),
                                          (datetime(2026, 10, 10, 12), 3.0, 80.0)], "tapo_export")
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)                           # drying 20 Sep - 8 Oct
        removed, kept = db.delete_chamber_readings(env, ch, "tapo_export")
    assert (removed, kept) == (1, 1)
    assert [r["ts"][:10] for r in db.chamber_readings(env, ch) if r["source"] == "tapo_export"] == ["2026-09-25"]


# 4: moving day 0 can't push the bag date past the out-of-bag date
def test_start_date_cannot_pass_out_of_bag_date(env):
    pid = db.create_project(env, "Late", "Classic Italian", False, 1000, start_date=date(2026, 10, 1))
    with env:
        db.set_cure(env, pid, shape="flat", thickness_cm=4, start=date(2026, 10, 1), end_actual=date(2026, 10, 5))
    with pytest.raises(ValueError, match="out-of-bag"):
        db.set_start_date(env, pid, date(2026, 10, 7))
    p = db.project(env, pid)
    assert (p["start_date"], p["cure_start"]) == ("2026-10-01", "2026-10-01")
    db.set_start_date(env, pid, date(2026, 10, 4))                       # still before: allowed, bag moves
    assert db.project(env, pid)["cure_start"] == "2026-10-04"


# 5: drying can't be locked while the cure is unlocked
def test_drying_lock_needs_cure_lock(env):
    with env:
        env.execute("UPDATE project SET cure_locked_at=NULL WHERE id=1")
    with pytest.raises(ValueError, match="Lock the cure first"):
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
