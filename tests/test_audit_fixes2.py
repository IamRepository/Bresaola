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
    assert m["Estimated finish"] == "Reached"


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
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
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
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
        db.close_project(env, 1, "")
    at = start("finish")
    assert any("Closed on " in s.value and "2026-" not in s.value for s in at.success)


# 15b: a 35.5 % target is shown as 35.5 %, not 36 %
def test_half_percent_target_not_rounded(env):
    sql(env, "UPDATE project SET target_loss_pct=35.5 WHERE id=1")
    h = html(start())
    assert "of 35.5 % lost" in h


# ---- editable start date (v0.3.7) ---------------------------------------------------

def test_start_date_change_moves_unlocked_bag_date(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(tmp_path / "s.sqlite")
    pid = db.create_project(con, "S", "Classic Italian", False, 1000, start_date=date(2026, 10, 5))
    db.set_cure(con, pid, shape="flat", thickness_cm=4, start=date(2026, 10, 5))   # Save, not locked
    db.set_start_date(con, pid, date(2026, 10, 3))
    p = db.project(con, pid)
    assert (p["start_date"], p["cure_start"]) == ("2026-10-03", "2026-10-03")
    assert db.display_name(p) == "26/10/03 S"
    assert db.events(con, pid)[-1]["kind"] == "start_date_changed"


def test_start_date_cannot_pass_a_fixed_bag_date(env):
    with pytest.raises(ValueError, match="after the bag date"):
        db.set_start_date(env, 1, date(2026, 8, 20))               # demo bagged 15 Aug, day 0 locked
    db.set_start_date(env, 1, date(2026, 8, 14))                   # earlier is fine
    assert db.project(env, 1)["cure_start"] == "2026-08-15"        # locked bag date stays


def test_bag_date_not_before_start_date(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(tmp_path / "b.sqlite")
    pid = db.create_project(con, "B", "Classic Italian", False, 1000, start_date=date(2026, 10, 5))
    with pytest.raises(ValueError, match="before the start date"):
        db.set_cure(con, pid, shape="flat", thickness_cm=4, start=date(2026, 10, 1))


def test_start_date_changed_from_sidebar(env):
    at = start()
    next(d for d in at.date_input if d.key == "sd1").set_value(date(2026, 8, 14))
    at.run()
    next(b for b in at.button if b.label == "Change start date").click()
    at.run()
    assert not at.exception, at.exception
    assert at.header[0].value == "26/08/14 Palermo Spicy"
