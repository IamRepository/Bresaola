"""Food-safety findings from the 21 Oct 2026 audit. Each test failed before v0.4.0."""
import io
from datetime import date, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from bresaola import db, report, safety, sensors, storage
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TODAY = date(2026, 10, 26)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    c = db.connect(storage.db_path())
    seed_demo(c)                                     # Palermo Spicy: no curing salt
    return c


def app(step=None):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    if step:
        next(b for b in at.button if b.key == f"rail_{step}").click()
        at.run()
        assert not at.exception, at.exception
    return at


def pdf_text(con, pid=1):
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(report.build_pdf(con, pid))).pages)


def cured_project(con, out_day, name="Short"):
    """10 cm tubular, bagged 1 Sep: calculator minimum 9.7 days, planned 12 days."""
    pid = db.create_project(con, name, "Classic Italian", True, 1000, start_date=date(2026, 9, 1))
    with con:
        db.lock_spice(con, pid)
        db.set_cure(con, pid, shape="tubular", thickness_cm=10, start=date(2026, 9, 1), end_actual=out_day)
    return pid


# ---- 1: curing salt is a deliberate choice, and its absence is visible ---------------------

def test_new_project_needs_a_curing_salt_choice(con):
    at = app()
    next(t for t in at.sidebar.text_input if t.label == "Name").input("Rome")
    next(b for b in at.sidebar.button if b.label == "Create project").click()
    at.run()
    assert any("Choose whether this batch uses curing salt" in e.value for e in at.error)
    assert len(db.projects(con)) == 1
    next(t for t in at.sidebar.text_input if t.label == "Name").input("Rome")
    next(r for r in at.sidebar.radio if r.label == "Curing salt").set_value("With EcoCure #2")
    next(b for b in at.sidebar.button if b.label == "Create project").click()
    at.run()
    rome = next(p for p in db.projects(con) if p["name"] == "Rome")
    assert rome["ecocure"] == 1
    assert not any(safety.NO_CURE_WARNING in w.value for w in at.warning)     # cured batch: no banner


def test_no_curing_salt_message_everywhere(con):
    # Palermo dries in a fridge at about 2 °C: an information note on every step, not an alarm
    for step in ("day0", "cure", "dry", "finish"):
        at = app(step)
        assert any("No curing salt" in i.value and "Drying in a fridge" in i.value for i in at.info), step
        assert not any("No curing salt" in w.value for w in at.warning), step
    assert "Drying in a fridge" in pdf_text(con)


def test_no_curing_salt_in_a_curing_chamber_is_a_warning(con):
    with con:
        db.set_chamber_kind(con, db.project(con, 1)["chamber_id"], "chamber")
    assert any(safety.NO_CURE_WARNING in w.value for w in app().warning)
    assert "chamber temperatures" in pdf_text(con)


def test_no_curing_salt_and_a_warm_fridge_is_a_warning(con):
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 10, 8, h), 6.0, 80.0) for h in range(10, 13)], "tapo_export")
    assert any("No curing salt, and the fridge was warmer than 4 °C for 3 h" in w.value for w in app().warning)


def test_curing_salt_change_is_logged(con):
    pid = db.create_project(con, "Log", "Classic Italian", False, 1000, start_date=TODAY)
    with con:
        db.update_spice_inputs(con, pid, ecocure=True)
    assert db.events(con, pid)[-1]["kind"] == "curing_salt_changed"


# ---- 2: a short cure is never shown as fine --------------------------------------------

@pytest.mark.parametrize("actual, expected", [(12, "ok"), (15, "ok"), (10, "short"), (9, "below_min")])
def test_cure_length_classes(actual, expected):
    assert safety.cure_length(actual, 9.7, 12) == expected


def test_lock_below_minimum_needs_confirmation_and_is_logged(con):
    pid = cured_project(con, date(2026, 9, 5))                    # 4 days
    with pytest.raises(ValueError, match="shorter than the calculator minimum"):
        db.lock_cure(con, pid)
    with con:
        db.lock_cure(con, pid, confirm_short=True)
    assert "below calculator minimum" in db.events(con, pid)[-1]["detail"]
    assert "shorter than the calculator minimum" in pdf_text(con, pid)


def test_cure_screen_colours(con):
    pid = cured_project(con, date(2026, 9, 5))
    at = app()
    next(s for s in at.sidebar.selectbox if s.label == "Project").set_value(pid)
    at.run()
    next(b for b in at.button if b.key == "rail_cure").click()
    at.run()
    h = " ".join(m.value for m in at.markdown)
    assert 'class="chip over">below minimum' in h
    assert any("shorter than the calculator minimum" in e.value for e in at.error)
    done = next(b for b in at.button if b.label == "Done: lock cure and start drying")
    assert done.disabled
    next(c for c in at.checkbox if c.key == f"short_ok{pid}").check()
    at.run()
    assert not next(b for b in at.button if b.label == "Done: lock cure and start drying").disabled


def test_short_of_margin_is_amber_not_green(con):
    pid = cured_project(con, date(2026, 9, 11))                   # 10 days: past minimum, short of 12
    at = app()
    next(s for s in at.sidebar.selectbox if s.label == "Project").set_value(pid)
    at.run()
    next(b for b in at.button if b.key == "rail_cure").click()
    at.run()
    assert 'class="chip warn">-2 vs plan' in " ".join(m.value for m in at.markdown)
    assert any("20 % safety margin" in w.value for w in at.warning)


# ---- 3: weight-loss target limits ------------------------------------------------------

@pytest.mark.parametrize("pct", [1, 24.5, 50.5, 70])
def test_target_outside_limits_refused(con, pct):
    with pytest.raises(ValueError, match="between 25 and 50"):
        db.change_target(con, 1, pct)


def test_target_warning_outside_usual_range(con):
    assert safety.target_warning(35) is None
    assert "below the usual" in safety.target_warning(27)
    assert "above the usual" in safety.target_warning(45)
    with con:
        db.change_target(con, 1, 27, "test")
    assert any("below the usual" in w.value for w in app().warning)
    assert "below the usual" in pdf_text(con)


# ---- 4: the loss basis is stated -------------------------------------------------------

def test_loss_basis_is_labelled(con):
    assert "at the start of drying" in pdf_text(con)
    m = next(x for x in app().metric if x.label == "Weight lost")
    assert "start of drying" in m.help


# ---- 5: chamber and cure-fridge warnings -----------------------------------------------

def _rows(items):
    return [{"ts": t.isoformat(), "temp_c": c, "rh_pct": h} for t, c, h in items]


def test_chamber_warnings_use_hourly_averages():
    spike = _rows([(datetime(2026, 10, 1, 8, m), c, 75) for m, c in ((0, 12), (15, 18), (30, 12), (45, 12))])
    assert safety.chamber_warnings(spike)[0] == []               # 15-min spike averages to 13.5 °C
    warm = _rows([(datetime(2026, 10, 1, h), 17.0, 75) for h in (8, 9)])
    assert "Warmer than 15 °C for 2 h" in safety.chamber_warnings(warm)[0][0]
    dry = _rows([(datetime(2026, 10, 2, 8), 12.0, 55)])
    assert "case hardening" in safety.chamber_warnings(dry)[0][0]
    wet = _rows([(datetime(2026, 10, 3, 8), 12.0, 95)])
    assert "mould" in safety.chamber_warnings(wet)[0][0]


def test_cold_fridge_gives_no_warning_and_no_slow_note():
    cold = _rows([(datetime(2026, 10, 1, h), 2.0, 82) for h in range(24)])
    assert safety.chamber_warnings(cold, "fridge") == ([], [])


def test_chamber_warning_shown_and_table_flagged(con):
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 10, 8, h), 18.0, 60.0) for h in range(10, 14)], "tapo_export")
    at = app()
    assert any("Fridge warmer than 4 °C" in w.value for w in at.warning)          # Palermo: a fridge
    assert any("case hardening" in w.value for w in at.warning)
    df = at.dataframe[0].value
    row = df[df["Date"] == "08 Oct"].iloc[0]
    assert row["Day °C"].endswith("⚠") and row["Day RH [%]"].endswith("⚠")
    assert "Fridge warmer than 4 °C" in pdf_text(con)


def test_fridge_and_chamber_rules_differ():
    five = _rows([(datetime(2026, 10, 1, h), 5.0, 80) for h in range(24)])
    assert "Fridge warmer than 4 °C" in safety.chamber_warnings(five, "fridge")[0][0]
    w, notes = safety.chamber_warnings(five, "chamber")
    assert w == [] and "safe, but drying is slow" in notes[0]           # 5 °C is cold for a chamber
    assert safety.out_of_range("t", 5.0, "fridge") and not safety.out_of_range("t", 5.0, "chamber")


def test_existing_chambers_become_fridges(con):
    assert {c["kind"] for c in db.chambers(con)} == {"fridge"}
    with pytest.raises(ValueError):
        db.set_chamber_kind(con, 1, "garage")


def test_cure_fridge_temperature(con):
    assert safety.cure_fridge_warning(3.0) is None
    assert "above 4 °C" in safety.cure_fridge_warning(6.0)
    pid = cured_project(con, date(2026, 9, 13))
    with con:
        db.set_cure_fridge(con, pid, 6.0)
    assert db.project(con, pid)["cure_fridge_c"] == 6.0
    t = pdf_text(con, pid)
    assert "Cure fridge 6 °C" in t and "above 4 °C" in t
    with pytest.raises(ValueError):
        db.set_cure_fridge(con, pid, 45)
