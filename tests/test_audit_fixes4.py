"""Reproductions of full-audit findings (26 Oct 2026) fixed in v0.4.4: the owner's list 6-13
(audit #2, #8, #9, #10, #11, #13, #15, #17). Each failed before the fix."""
import io
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from bresaola import db, report, safety, sensors, storage, tapo_sync
from bresaola.demo import seed_demo

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TODAY = date(2026, 10, 11)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(storage.db_path())
    seed_demo(con)
    return con


def rows(con, ch):
    return [(r["ts"], r["temp_c"]) for r in db.chamber_readings(con, ch)]


# 6 (audit #2): clocks back on 25 Oct 2026 - 02:00-02:59 happens twice
def test_hub_sync_keeps_the_repeated_hour():
    # 00:00-01:45 UTC = 02:00-02:45 summer time, then 02:00-02:45 winter time again
    t0 = datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)
    recs = SimpleNamespace(temperature_unit="Celsius", records=[
        SimpleNamespace(recorded_at=t0 + timedelta(minutes=15 * i), temperature=2.0 if i < 4 else 4.0, humidity=80)
        for i in range(8)])
    out = tapo_sync.records_to_rows(recs)
    assert [t.strftime("%H:%M") for t, _, _ in out] == ["02:00", "02:15", "02:30", "02:45"]
    assert {temp for _, temp, _ in out} == {3.0}          # both passes averaged, none silently dropped


def test_export_averages_the_repeated_hour():
    csv = "Time,Temperature(℃),Humidity(%)\n25/10/2026 02:00,2.0,80\n25/10/2026 02:00,4.0,90\n25/10/2026 03:00,3.0,85\n"
    p = sensors.parse_export(csv.encode(), "x.csv")
    assert p.rows[0] == (datetime(2026, 10, 25, 2, 0), 3.0, 85.0)


@pytest.mark.parametrize("prev,cur", [(date(2026, 3, 28), date(2026, 3, 30)),     # clocks forward 29 Mar
                                      (date(2026, 10, 24), date(2026, 10, 26))])  # clocks back 25 Oct
def test_full_coverage_across_a_clock_change(prev, cur):
    # a reading every 15 real minutes, stored in local time like the hub sync does
    t = datetime.combine(prev, sensors.WEIGH_IN_TIME).replace(tzinfo=db.TZ).astimezone(timezone.utc)
    end = datetime.combine(cur, sensors.WEIGH_IN_TIME).replace(tzinfo=db.TZ).astimezone(timezone.utc)
    raw = []
    while t < end:
        raw.append((tapo_sync.to_local(t), 2.0, 80.0))
        t += timedelta(minutes=15)
    cr = [{"ts": x.isoformat(), "temp_c": a, "rh_pct": b} for x, a, b in sensors.merge_same_time(raw)]
    assert sensors.period_averages([prev, cur], cr)[cur][4] == 1.0


# 7 (audit #8): an ingredient note can be cleared
def test_ingredient_note_can_be_cleared(env):
    pid = db.create_project(env, "N", "Classic Italian", False, 1000, start_date=TODAY)
    with env:
        db.set_actual(env, pid, 0, 30.0, "typo")
        db.set_actual(env, pid, 0, 30.0, None)
    assert db.ingredient_lines(env, pid)[0]["note"] is None
    with env:
        db.set_actual(env, pid, 0, 30.0, "kept")
        db.set_actual(env, pid, 0, 31.0)                    # no note given: left as it is
    assert db.ingredient_lines(env, pid)[0]["note"] == "kept"


# 8 (audit #9): "Leave out a period" also removes readings already stored for that period
def test_leave_out_removes_earlier_imports(env):
    ch = db.project(env, 1)["chamber_id"]
    bad = [(datetime(2026, 10, 3, 13), -3.0, 50.0), (datetime(2026, 10, 9, 12), 2.0, 80.0)]
    with env:
        sensors.import_readings(env, ch, bad, "tapo_export")          # the wrong import, without leave-out
        db.add_chamber_reading(env, ch, "2026-10-04T08:00:00", 21.0, 40, source="tapo_api")
        stored, rejected, removed = sensors.import_export(
            env, ch, bad, datetime(2026, 10, 3, 12, 15), datetime(2026, 10, 9, 4, 0))
    assert (stored, removed) == (1, 2)
    assert [ts for ts, _ in rows(env, ch) if ts.startswith("2026-10-0")] == ["2026-10-09T12:00:00"]


# 9 (audit #10): the same 15 minutes from the export and the hub count once
def test_export_and_hub_of_same_time_count_once(env):
    ch = db.project(env, 1)["chamber_id"]
    with env:
        sensors.import_readings(env, ch, [(datetime(2026, 10, 1, 12), 2.0, 80.0)], "tapo_export")
        sensors.import_readings(env, ch, [(datetime(2026, 10, 1, 12), 2.1, 80.0)], "tapo_api")
    assert rows(env, ch).count(("2026-10-01T12:00:00", 2.0)) == 1
    assert [ts for ts, _ in rows(env, ch)].count("2026-10-01T12:00:00") == 1
    assert db.chamber_reading_counts(env, ch)["tapo_api"][0] == 1       # both kept, each removable


# 10 (audit #11): the tapo library is pinned to the versions that have recorded_at
def test_tapo_requirement_is_pinned():
    line = next(l for l in (ROOT / "requirements-local.txt").read_text().splitlines() if l.startswith("tapo"))
    assert re.match(r"tapo>=0\.1[1-9],<\d", line), line


# 11 (audit #13): day 0 can't be in the future
def test_day0_not_in_future(env):
    with pytest.raises(ValueError, match="future"):
        db.create_project(env, "Later", "Classic Italian", False, 1000, start_date=TODAY + timedelta(days=3))
    with env:
        db.lock_spice(env, 1)
    with pytest.raises(ValueError, match="future"):
        db.set_start_date(env, 1, TODAY + timedelta(days=1))


# 12 (audit #15): a target saved before v0.4.0 outside 25-50 % gives one consistent message
def test_out_of_range_target_one_message(env):
    with env:
        env.execute("UPDATE project SET target_loss_pct=60 WHERE id=1")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    msgs = [m.value for m in list(at.warning) + list(at.error)]
    assert not [m for m in msgs if "above the usual" in m], msgs        # neither for 60 % nor the clamped 50 %
    assert any("outside the allowed" in m for m in msgs)
    assert "Set a new one" not in safety.target_message(60, hint=False)


# 13 (audit #17): the PDF weigh-in table marks values outside the safe range, like the app
def test_pdf_marks_unsafe_day_values(env):
    ch = db.project(env, 1)["chamber_id"]
    with env:
        sensors.import_readings(env, ch, [(datetime(2026, 9, 26, h), 7.0, 80.0) for h in range(24)], "tapo_export")
    t = " ".join(" ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(report.build_pdf(env, 1))).pages).split())
    assert "7.0 ⚠" in t and "outside the safe range for a fridge" in t


def test_leave_out_count_skips_locked_drying(env):
    """Diff audit v0.4.4 (Low): the caption counted readings that the delete keeps."""
    ch = db.project(env, 1)["chamber_id"]
    with env:
        sensors.import_readings(env, ch, [(datetime(2026, 10, 3, 13), 2.0, 80.0),
                                          (datetime(2026, 10, 10, 13), 2.0, 80.0)], "tapo_export")
        db.lock_dry(env, 1, date(2026, 10, 8))                          # 3 Oct is inside the locked period
    assert db.sensor_readings_between(env, ch, datetime(2026, 10, 1), datetime(2026, 10, 11)) == 1
