"""Reproductions of audit findings 9-12, 14, 15 (11 Oct 2026). Each failed before v0.3.6."""
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
    """Persistent-mode data folder with the demo batch; returns an open connection."""
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(storage.db_path())
    seed_demo(con)
    return con


def start(step=None):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    if step:
        next(b for b in at.button if b.key == f"rail_{step}").click()
        at.run()
        assert not at.exception, at.exception
    return at


def html(at):
    return " ".join(m.value for m in at.markdown)


def sql(con, q, *a):
    with con:
        con.execute(q, a)


# 9: Finish says what the numbers really are (meat vs gross)
def test_finish_separates_meat_and_packaging(env):
    sql(env, "UPDATE project SET tare_g=100 WHERE id=1")
    h = html(start("finish"))
    assert "6.8 % of the meat at the start of drying" in h       # 137 / (2100 - 100)
    assert "89 %" in h and "meat only, without wrap + net" in h  # (1963 - 100) / 2088
    assert "6.8 % of the start weight" not in h


# 10: after the target is reached every message agrees
def test_target_reached_messages_agree(env):
    with env:
        db.add_reading(env, 1, date(2026, 10, 10), 1360, confirmed=True)          # below the 1365 g target
    at = start()
    h = html(at)
    assert "Target weight reached." in h
    assert "next weigh-in by" not in h and "target reached" in h
    m = {x.label: x.value for x in at.metric}
    assert m["Earliest finish"] == "Reached"


# 11 is a file-upload flow (AppTest cannot upload); checked in the browser.

# 12a: Day 0 locked but no cure data (v0.2 databases) does not crash
def test_legacy_day0_locked_without_cure_data(env):
    sql(env, "UPDATE project SET cure_locked_at=NULL, cure_start=NULL, thickness_cm=NULL, "
             "dry_start=NULL, cure_end_actual=NULL WHERE id=1")
    sql(env, "DELETE FROM reading WHERE project_id=1")
    at = start()
    assert "bag date and thickness are missing" in html(at)
    start("cure")


# 12b: an Equalise start left over from v0.2.11 does not block closing
def test_legacy_equalise_start_does_not_block_close(env):
    sql(env, "UPDATE project SET equalise_start='2026-10-09' WHERE id=1")
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8))
    assert db.close_problems(env, 1) == []


# 12c: the old cure "Method" text is folded into the notes once, never duplicated
def test_legacy_cure_method_folded_into_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "today", lambda: TODAY)
    path = tmp_path / "old.sqlite"
    con = db.connect(path)
    seed_demo(con)
    sql(con, "UPDATE project SET cure_method='Vacuum bag, fridge', cure_note='Flipped daily' WHERE id=1")
    con.close()
    con = db.connect(path)                                         # migration runs on connect
    p = db.project(con, 1)
    assert p["cure_method"] is None and p["cure_note"] == "Vacuum bag, fridge\nFlipped daily"
    con.close()
    con = db.connect(path)                                         # and only once
    assert db.project(con, 1)["cure_note"] == "Vacuum bag, fridge\nFlipped daily"


# 14: a blend that is no longer in the blend list does not crash day 0
def test_day0_with_blend_missing_from_list(env):
    sql(env, "UPDATE project SET blend='Spicy Calabrian v1' WHERE id=1")
    at = start("day0")
    sb = next(s for s in at.selectbox if s.key == "b1")
    assert sb.value == "Spicy Calabrian v1"


# 15a: closing date is written like every other date
def test_closed_date_format(env):
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8))
        db.close_project(env, 1, "")
    at = start("finish")
    assert any("Closed on " in s.value and "2026-" not in s.value for s in at.success)


# 15b: a 35.5 % target is shown as 35.5 %, not 36 %
def test_half_percent_target_not_rounded(env):
    sql(env, "UPDATE project SET target_loss_pct=35.5 WHERE id=1")
    h = html(start())
    assert "of 35.5 % lost" in h


# 15c: a blank chamber name is refused and no stray chamber is created
def test_blank_chamber_name_refused(env):
    pid = db.create_project(env, "Second", "Classic Italian", False, 1000, start_date=date(2026, 9, 1))
    with env:
        db.lock_spice(env, pid)
        db.set_cure(env, pid, shape="flat", thickness_cm=4, start=date(2026, 9, 1), end_actual=date(2026, 9, 5))
        db.lock_cure(env, pid)
    sql(env, "UPDATE project SET chamber_id=NULL")
    sql(env, "DELETE FROM chamber_reading")
    sql(env, "DELETE FROM chamber")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(s for s in at.sidebar.selectbox if s.label == "Project").set_value(pid)
    at.run()
    next(b for b in at.button if b.key == "rail_dry").click()
    at.run()
    next(t for t in at.text_input if t.label == "New chamber name").input("  ")
    next(n for n in at.number_input if n.label == "Start weight incl. wrap + net [g]").set_value(950)
    next(b for b in at.button if b.label == "Start drying").click()
    at.run()
    assert not at.exception, at.exception
    assert any("chamber" in e.value.lower() for e in at.error)
    assert [c["name"] for c in db.chambers(env)] == []
