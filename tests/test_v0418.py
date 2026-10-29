"""v0.4.18 (owner, 29 Oct 2026): active projects as radio buttons, closed ones in a dropdown below;
the left-out / no-readings list folded behind a one-line summary."""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, sensors, storage
from bresaola.demo import seed_demo

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TODAY = date(2026, 10, 11)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    for k in ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_HUB_IP", "TAPO_SENSORS"):
        monkeypatch.delenv(k, raising=False)
    con = db.connect(storage.db_path())
    seed_demo(con)
    with con:
        rome = db.create_project(con, "Rome", "Classic Italian", False, 1000, start_date=date(2026, 9, 1))
        old = db.create_project(con, "Old", "Classic Italian", False, 1000, start_date=date(2026, 9, 2))
        con.execute("UPDATE project SET status='closed', closed_at='2026-10-05T12:00:00' WHERE id=?", (old,))
    return con, rome, old


def widgets(at):
    radio = next((r for r in at.sidebar.radio if r.label == "Active projects"), None)
    box = next((s for s in at.sidebar.selectbox if s.label == "Closed projects"), None)
    return radio, box


def header(at):
    return at.header[0].value


def run(at):
    at.run()
    assert not at.exception, at.exception
    return at


def test_active_as_radio_closed_in_dropdown(env):
    con, rome, old = env
    at = run(AppTest.from_file(APP, default_timeout=30))
    radio, box = widgets(at)
    assert len(radio.options) == 2 and "Old" not in " ".join(radio.options)
    assert len(box.options) == 1 and "Old" in box.options[0]
    assert box.value is None and radio.value is not None                 # one project selected
    assert not [s for s in at.sidebar.selectbox if s.label == "Project"]


def test_picking_one_clears_the_other(env):
    con, rome, old = env
    at = run(AppTest.from_file(APP, default_timeout=30))
    widgets(at)[1].set_value(old)
    run(at)
    radio, box = widgets(at)
    assert (radio.value, box.value) == (None, old) and "Old" in header(at)
    radio.set_value(rome)
    run(at)
    radio, box = widgets(at)
    assert (radio.value, box.value) == (rome, None) and "Rome" in header(at)


def test_stale_pick_of_a_project_closed_elsewhere(env):
    """Like full-audit fix #1: another tab closes the batch this tab shows; this tab follows the database."""
    con, rome, old = env
    at = run(AppTest.from_file(APP, default_timeout=30))
    widgets(at)[0].set_value(rome)
    run(at)
    with con:
        con.execute("UPDATE project SET status='closed', closed_at='2026-10-10T12:00:00' WHERE id=?", (rome,))
    run(at)
    radio, box = widgets(at)
    assert radio.value is None and box.value == rome and "Rome" in header(at)
    assert len(radio.options) == 1


def test_no_closed_projects_no_dropdown(env):
    con, rome, old = env
    with con:
        db.delete_project(con, old)
    at = run(AppTest.from_file(APP, default_timeout=30))
    assert widgets(at)[1] is None


def test_gap_list_folded_behind_a_summary(env):
    con, rome, old = env
    rows = [(datetime(2026, 9, 20) + timedelta(minutes=15 * i), 2.0, 80.0) for i in range(4 * 24 * 21)]
    rows = [r for r in rows if not (datetime(2026, 9, 25) <= r[0] <= datetime(2026, 9, 26)
                                    or datetime(2026, 10, 1) <= r[0] <= datetime(2026, 10, 1, 12))]
    with con:
        sensors.import_readings(con, 1, rows, "tapo_export")
    at = AppTest.from_file(APP, default_timeout=30)
    run(at)
    widgets(at)[0].set_value(1)
    run(at)
    exp = next(e for e in at.expander if e.label == "Show the periods")
    outside = [c.value for c in at.caption if "**No readings**" in c.value and c not in list(exp.caption)]
    # gaps run from the reading before to the one after: 24 h 15 min + 12 h 15 min
    assert outside == ["**No readings**: 2 gaps of 6 h or more, 1 d 13 h in total"], outside
    inside = " ".join(c.value for c in exp.caption)
    assert "24 Sep 23:45 to 26 Sep 00:15" in inside and "30 Sep 23:45 to 01 Oct 12:15" in inside and "Only save a gap as left-out" in inside
