"""Reproductions of the 11 Oct 2026 audit findings 1-8 and 13. Each failed before v0.3.5."""
import io
import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.helpers import pick_project
from bresaola import db, storage

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TODAY = date(2026, 10, 11)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "today", lambda: TODAY)
    return db.connect(tmp_path / "t.sqlite")


def drying_batch(con, *, lock_dry=False):
    """Day 0 + cure locked, drying from 20 Sep with weigh-ins on 26 Sep and 30 Sep."""
    pid = db.create_project(con, "P", "Spicy Calabrian", False, 2088, start_date=date(2026, 8, 15))
    db.lock_spice(con, pid)
    db.set_cure(con, pid, shape="tubular", thickness_cm=17, start=date(2026, 8, 15),
                end_actual=date(2026, 9, 20))
    db.lock_cure(con, pid)
    db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100)
    db.add_reading(con, pid, date(2026, 9, 26), 2057)
    db.add_reading(con, pid, date(2026, 9, 30), 2026)
    if lock_dry:
        db.lock_dry(con, pid, date(2026, 10, 1), below_target_ok=True)
    return pid


# ---- 3: drying end date checked -------------------------------------------------------

@pytest.mark.parametrize("end, msg", [
    (date(2026, 9, 1), "before drying started"),
    (date(2026, 9, 28), "last weigh-in"),
    (date(2027, 3, 1), "future"),
])
def test_drying_end_date_is_checked(con, end, msg):
    pid = drying_batch(con)
    with pytest.raises(ValueError, match=msg):
        db.lock_dry(con, pid, end, below_target_ok=True)
    assert not db.project(con, pid)["dry_locked_at"]
    db.lock_dry(con, pid, date(2026, 9, 30), below_target_ok=True)           # last weigh-in day is fine


# ---- 4: earlier steps cannot be changed behind a later one -----------------------------

def test_unlock_order_follows_the_steps(con):
    pid = drying_batch(con, lock_dry=True)
    with pytest.raises(db.Locked, match="Unlock drying first"):
        db.unlock_cure(con, pid, "x")
    with pytest.raises(db.Locked, match="Unlock the cure first"):
        db.unlock_spice(con, pid, "x")


def test_cure_end_cannot_move_past_drying_start(con):
    pid = drying_batch(con)                             # drying started, not locked
    db.unlock_cure(con, pid, "typo")
    with pytest.raises(ValueError, match="(?i)drying started"):
        db.set_cure(con, pid, shape="tubular", thickness_cm=17, start=date(2026, 8, 15),
                    end_actual=date(2026, 10, 5))
    with pytest.raises(ValueError, match="(?i)drying started"):     # can't clear it either
        db.set_cure(con, pid, shape="tubular", thickness_cm=17, start=date(2026, 8, 15), end_actual=None)


# ---- 5: unlocking drying forgets the end date ------------------------------------------

def test_unlock_dry_clears_end_date(con):
    pid = drying_batch(con, lock_dry=True)
    db.unlock_dry(con, pid, "kept drying")
    assert db.project(con, pid)["dry_end"] is None


# ---- 6: no future dates in the cure ----------------------------------------------------

def test_cure_dates_cannot_be_in_the_future(con):
    pid = db.create_project(con, "F", "Classic Italian", False, 1000, start_date=TODAY)
    with pytest.raises(ValueError, match="'Into the bag' is in the future"):
        db.set_cure(con, pid, shape="flat", thickness_cm=4, start=date(2026, 10, 20))
    with pytest.raises(ValueError, match="'Taken out of the bag' is in the future"):
        db.set_cure(con, pid, shape="flat", thickness_cm=4, start=TODAY, end_actual=date(2026, 12, 24))


# ---- 7: cure needs day 0 locked ---------------------------------------------------------

def test_cure_cannot_lock_before_day0(con):
    pid = db.create_project(con, "D", "Classic Italian", False, 1000, start_date=date(2026, 9, 1))
    db.set_cure(con, pid, shape="flat", thickness_cm=4, start=date(2026, 9, 1), end_actual=date(2026, 9, 5))
    with pytest.raises(db.Locked, match="Lock day 0 first"):
        db.lock_cure(con, pid)


# ---- 13: huge photos are refused, not a crash ------------------------------------------

def test_decompression_bomb_is_a_value_error(monkeypatch):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), "brown").save(buf, "PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)      # 400×400 counts as "too big" now
    with pytest.raises(ValueError, match="too large"):
        storage.shrink_image(buf.getvalue())


# ---- UI ------------------------------------------------------------------------------

@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.delenv("BRESAOLA_MODE", raising=False)
    monkeypatch.setattr(db, "today", lambda: TODAY)
    a = AppTest.from_file(APP, default_timeout=30)
    a.run()
    assert not a.exception, a.exception
    return a


def run(a):
    a.run()
    assert not a.exception, a.exception


def btn(a, label):
    return next(b for b in a.button if b.label == label)


def new_project(a, name, weight=1000):
    next(t for t in a.sidebar.text_input if t.label == "Name").input(name)
    next(n for n in a.sidebar.number_input if n.label == "Meat weight [g]").set_value(weight)
    next(r for r in a.sidebar.radio if r.label == "Curing salt").set_value("Without curing salt")
    btn(a.sidebar, "Create project").click()
    run(a)


def pick(a, pid):
    pick_project(a, pid)
    run(a)


# 1: switching projects takes effect every time
def test_project_switch_works_every_time(at):
    new_project(at, "Second")
    assert at.header[0].value.endswith("Second")
    pick(at, 1)
    assert at.header[0].value.endswith("Palermo Spicy")
    pick(at, 2)
    assert at.header[0].value.endswith("Second")
    pick(at, 1)
    assert at.header[0].value.endswith("Palermo Spicy")


# 2: unsaved table edits do not move to another blend's rows
def test_blend_switch_does_not_carry_table_edits(at, tmp_path):
    from streamlit.proto.WidgetStates_pb2 import WidgetState  # noqa: F401  (proto import check)
    new_project(at, "X", 1000)
    next(s for s in at.selectbox if (s.key or "").split("@")[0] == "b2").set_value("Spicy Calabrian")
    run(at)

    def editor_id():
        found = []

        def walk(n):
            if hasattr(n, "children"):
                for c in n.children.values():
                    walk(c)
            elif n.type == "dataframe" and "-sw" in n.proto.id:
                found.append(n.proto.id)
        walk(at._tree)
        return found[0]

    edit = {"edited_rows": {"4": {"Actual [g]": 9.9}}, "added_rows": [], "deleted_rows": []}

    def run_with_edit():
        ws = at._tree.get_widget_states()
        w = ws.widgets.add()
        w.id = editor_id()
        w.string_value = json.dumps(edit)
        at._run(ws)
        assert not at.exception, at.exception

    run_with_edit()                                            # 9.9 g typed for Fennel, not saved
    old = editor_id()
    next(s for s in at.selectbox if (s.key or "").split("@")[0] == "b2").set_value("Bresaola della Valtellina")
    run(at)
    assert editor_id() != old                                  # fresh table for the new blend
    btn(at, "Save").click()
    run(at)
    lines = db.ingredient_lines(db.connect(tmp_path / storage.DB_NAME), 2)
    assert all(abs(l["actual"] - l["planned"]) < 1e-9 for l in lines), \
        [(l["name"], l["planned"], l["actual"]) for l in lines if l["actual"] != l["planned"]]


# 7: the Cure step waits for day 0 to be locked
def test_cure_step_waits_for_day0_lock(at):
    new_project(at, "Y", 1000)
    btn(at, "Save").click()                                    # saves the bag date, does not lock
    run(at)
    next(b for b in at.button if b.key == "rail_cure").click()
    run(at)
    assert any("Lock day 0 first" in i.value for i in at.info)
    assert not any(b.label.startswith("Done: lock cure") for b in at.button)


# 8: Done waits while the reset question is open
def test_day0_done_waits_for_reset_answer(at, tmp_path):
    new_project(at, "Z", 1000)
    con = db.connect(tmp_path / storage.DB_NAME)
    with con:
        db.set_actual(con, 2, 0, 11.0)                         # an actual amount already saved
    run(at)
    next(n for n in at.number_input if n.label == "Meat weight after trimming [g]").set_value(1500)
    run(at)
    assert any("replaces them with the new plan" in w.value for w in at.warning)
    assert btn(at, "Done: lock day 0 and start curing").disabled
    assert btn(at, "Save").disabled


# 4 (UI): the unlock panel says what to unlock first
def test_unlock_panel_explains_order(at):
    next(b for b in at.button if b.key == "rail_day0").click()
    run(at)
    assert any("unlock the cure first" in c.value for c in at.caption)
    assert not any(b.label == "Unlock day 0" for b in at.button)


# 4 (UI): an unlocked step says so instead of repeating its first-time instructions
def test_unlocked_cure_says_unlocked_not_unbag(at):
    next(b for b in at.button if b.key == "rail_cure").click()
    run(at)
    next(t for t in at.text_input if t.key == "unlcure1").input("typo")
    run(at)
    btn(at, "Unlock cure").click()
    run(at)
    h = " ".join(m.value for m in at.markdown)
    assert "Cure is unlocked for editing." in h and "Unbag:" not in h
    assert "unlocked for editing" in h            # status line under the step too
