"""v0.4.17 (28 Oct 2026): each batch has its own sensor readings (one sensor per piece of meat),
imports add instead of overwrite, left-out overview, hub sync per batch."""
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from bresaola import db, report, sensors, storage, tapo_sync
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")
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
    return con


def second_batch_on_same_chamber(con, name="Rome"):
    """As before v0.4.17: a second batch dried in the same chamber as Palermo."""
    pid = db.create_project(con, name, "Classic Italian", False, 1000, start_date=date(2026, 9, 1))
    with con:
        db.lock_spice(con, pid)
        db.set_cure(con, pid, shape="flat", thickness_cm=4, start=date(2026, 9, 1), end_actual=date(2026, 9, 5))
        db.lock_cure(con, pid)
        db.set_drying(con, pid, start=date(2026, 9, 25), start_gross_g=950, chamber_id=1)
        con.execute("UPDATE chamber SET project_id=NULL")                      # as in a v0.4.16 database
    return pid


def readings_of(con, pid):
    return [(r["ts"], r["temp_c"]) for r in db.chamber_readings(con, db.project(con, pid)["chamber_id"])]


# ---- conversion of existing data -----------------------------------------------------------

def test_single_batch_keeps_its_chamber_and_readings(env, tmp_path):
    with env:
        sensors.import_readings(env, 1, [(datetime(2026, 9, 26, 12), 2.0, 80.0)], "tapo_export")
        env.execute("UPDATE chamber SET project_id=NULL")
    env.close()
    con = db.connect(storage.db_path())
    ch = con.execute("SELECT * FROM chamber WHERE id=1").fetchone()
    assert ch["project_id"] == 1 and db.project(con, 1)["chamber_id"] == 1
    assert readings_of(con, 1) == [("2026-09-26T12:00:00", 2.0)]
    assert (tmp_path / "bresaola-before-v0.4.17.sqlite").exists()          # copy made before converting


def test_shared_chamber_is_split_with_readings_and_left_out_periods(env, tmp_path):
    rome = second_batch_on_same_chamber(env)
    with env:
        sensors.import_readings(env, 1, [(datetime(2026, 9, 26, 12), 2.0, 80.0)], "tapo_export")
        env.execute("INSERT INTO chamber_exclusion (chamber_id, start_ts, end_ts) "
                    "VALUES (1, '2026-10-03T12:15:00', '2026-10-09T04:00:00')")
    env.close()
    con = db.connect(storage.db_path())
    p1, p2 = db.project(con, 1), db.project(con, rome)
    assert p1["chamber_id"] == 1 and p2["chamber_id"] != 1
    assert readings_of(con, rome) == readings_of(con, 1) == [("2026-09-26T12:00:00", 2.0)]
    assert len(db.exclusions(con, p2["chamber_id"])) == 1
    with con:                                                    # now independent
        sensors.import_readings(con, p2["chamber_id"], [(datetime(2026, 9, 27, 12), 3.0, 80.0)], "tapo_export")
    assert len(readings_of(con, rome)) == 2 and len(readings_of(con, 1)) == 1
    n = con.execute("SELECT COUNT(*) FROM chamber").fetchone()[0]
    con.close()
    con = db.connect(storage.db_path())                          # converting again changes nothing
    assert con.execute("SELECT COUNT(*) FROM chamber").fetchone()[0] == n


def test_deleting_a_batch_deletes_only_its_own_readings(env):
    rome = second_batch_on_same_chamber(env)
    env.close()
    con = db.connect(storage.db_path())
    ch_rome = db.project(con, rome)["chamber_id"]
    with con:
        sensors.import_readings(con, ch_rome, [(datetime(2026, 9, 27, 12), 3.0, 80.0)], "tapo_export")
        db.delete_project(con, rome)
    assert not con.execute("SELECT 1 FROM chamber WHERE id=?", (ch_rome,)).fetchone()
    assert not con.execute("SELECT 1 FROM chamber_reading WHERE chamber_id=?", (ch_rome,)).fetchone()
    assert con.execute("SELECT 1 FROM chamber WHERE id=1").fetchone()       # Palermo's untouched


# ---- imports add, never overwrite unless asked --------------------------------------------

def test_second_export_adds_and_keeps_what_is_there(env):
    first = [(datetime(2026, 9, 26, h), 2.0, 80.0) for h in range(3)]
    longer = [(datetime(2026, 9, 26, h), 9.9, 50.0) for h in range(6)]   # same times, other values, + 3 new
    with env:
        sensors.import_export(env, 1, first)
        res = sensors.import_export(env, 1, longer)
    assert (res.stored, res.existing) == (3, 3)
    temps = [t for _, t in readings_of(env, 1)]
    assert temps == [2.0, 2.0, 2.0, 9.9, 9.9, 9.9]                         # history kept
    with env:
        res = sensors.import_export(env, 1, longer, replace=True)       # only when asked
    assert (res.stored, res.existing) == (0, 6)
    assert {t for _, t in readings_of(env, 1)} == {9.9}


# ---- left-out overview ---------------------------------------------------------------------

def test_overview_shows_left_out_and_missing_and_saves_a_gap(env):
    ch = 1
    rows = [(datetime(2026, 9, 20, 0) + timedelta(minutes=15 * i), 2.0, 80.0) for i in range(4 * 24 * 21)]
    rows = [r for r in rows if not datetime(2026, 10, 3, 12) <= r[0] <= datetime(2026, 10, 9, 4)]
    with env:
        sensors.import_readings(env, ch, rows, "tapo_export")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    cap = " ".join(c.value for c in at.caption)
    assert "**No readings**: 03 Oct 11:45 to 09 Oct 04:15, 5 d 16 h" in cap
    assert cap.count("**No readings**") == 1          # after the last reading: not imported yet, no gap
    next(b for b in at.button if b.key == "exgap1_0").click()               # "Save as left-out"
    at.run()
    assert not at.exception, at.exception
    ex = db.exclusions(env, ch)
    assert [(e["start_ts"], e["end_ts"]) for e in ex] == [("2026-10-03T11:46:00", "2026-10-09T04:14:00")]
    assert len(db.chamber_readings(env, ch)) == len(rows)                   # the readings around it stay
    cap = " ".join(c.value for c in at.caption)
    assert "**Left out** (grey on the charts): 03 Oct 11:46 to 09 Oct 04:14" in cap
    assert "**No readings**" not in cap
    specs = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower():
                specs.append(json.loads(c.proto.spec))
            walk(c)
    walk(at._tree)
    assert any((l.get("mark") or {}).get("type") == "rect" for sp in specs for l in sp.get("layer", []))


def test_footnotes_in_caption_size(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert any("**1** · 20 Sep 2026: Start of drying" in c.value for c in at.caption)


# ---- hub sync per batch --------------------------------------------------------------------

class Sensor:
    def __init__(self, temp):
        self.temp = temp

    async def get_temperature_humidity_records(self):
        t0 = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
        return SimpleNamespace(temperature_unit="Celsius", records=[
            SimpleNamespace(recorded_at=t0 + timedelta(minutes=15 * i), temperature=self.temp, humidity=80)
            for i in range(4)])


def factory(sensors_by_name):
    class Hub:
        async def t31x(self, nickname=None):
            if nickname not in sensors_by_name:
                raise RuntimeError("no such sensor")
            return sensors_by_name[nickname]

    class Client:
        def __init__(self, *_):
            pass

        async def h100(self, ip):
            return Hub()
    return Client


def test_hub_sync_fills_each_batch_from_its_own_sensor(env, monkeypatch):
    for k, v in (("TAPO_USERNAME", "u"), ("TAPO_PASSWORD", "p"), ("TAPO_HUB_IP", "1.2.3.4")):
        monkeypatch.setenv(k, v)
    rome = second_batch_on_same_chamber(env)
    env.close()
    con = db.connect(storage.db_path())
    with con:
        db.set_tapo_name(con, db.project(con, 1)["chamber_id"], "Palermo T315")
        db.set_tapo_name(con, db.project(con, rome)["chamber_id"], "Rome T315")
    res = tapo_sync.sync(con, factory({"Palermo T315": Sensor(2.0), "Rome T315": Sensor(5.0)}))
    assert sorted((r.chamber, r.stored, r.error) for r in res) == [("Palermo Spicy", 4, None), ("Rome", 4, None)]
    assert {t for _, t in readings_of(con, 1) if t} == {2.0}
    assert {t for _, t in readings_of(con, rome) if t} == {5.0}


def test_one_wrong_sensor_name_does_not_stop_the_others(env, monkeypatch):
    for k, v in (("TAPO_USERNAME", "u"), ("TAPO_PASSWORD", "p"), ("TAPO_HUB_IP", "1.2.3.4")):
        monkeypatch.setenv(k, v)
    rome = second_batch_on_same_chamber(env)
    env.close()
    con = db.connect(storage.db_path())
    with con:
        db.set_tapo_name(con, db.project(con, 1)["chamber_id"], "Palermo T315")
        db.set_tapo_name(con, db.project(con, rome)["chamber_id"], "Typo")
    res = {r.chamber: r for r in tapo_sync.sync(con, factory({"Palermo T315": Sensor(2.0)}))}
    assert res["Palermo Spicy"].stored == 4 and res["Palermo Spicy"].error is None
    assert "sensor 'Typo'" in res["Rome"].error


def test_hub_sync_leaves_finished_batches_alone(env, monkeypatch):
    for k, v in (("TAPO_USERNAME", "u"), ("TAPO_PASSWORD", "p"), ("TAPO_HUB_IP", "1.2.3.4")):
        monkeypatch.setenv(k, v)
    with env:
        db.set_tapo_name(env, 1, "Palermo T315")
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
    assert tapo_sync.sync(env, factory({"Palermo T315": Sensor(2.0)})) == []


def test_pdf_says_where_it_dried(env):
    with env:
        db.set_tapo_name(env, 1, "Palermo T315")
    t = " ".join(" ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(report.build_pdf(env, 1))).pages).split())
    assert "Dried in a fridge, sensor Palermo T315." in t


# ---- diff audit v0.4.17 ----------------------------------------------------------------------

def test_no_false_gap_before_the_first_reading():
    rows = [{"ts": (datetime(2026, 9, 20, 14) + timedelta(minutes=15 * i)).isoformat()} for i in range(40)]
    assert sensors.gaps(rows, datetime(2026, 9, 20), datetime(2026, 9, 22)) == []


def test_delete_warning_mentions_sensor_readings(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert any("sensor readings" in c.value and "Removes the project" in c.value for c in at.sidebar.caption)


def test_drying_start_applies_type_to_an_existing_sensor_table(env):
    with env:
        pid = db.create_project(env, "Late", "Classic Italian", False, 1000, start_date=TODAY)
        ch = db.project_chamber(env, pid, "fridge")
        assert db.project_chamber(env, pid, "chamber", "T315") == ch
    row = env.execute("SELECT kind, tapo_name FROM chamber WHERE id=?", (ch,)).fetchone()
    assert (row["kind"], row["tapo_name"]) == ("chamber", "T315")


def test_failed_safety_copy_skips_the_conversion(env, tmp_path, monkeypatch):
    rome = second_batch_on_same_chamber(env)
    env.close()
    real = db.sqlite3.connect

    def no_copy(path, *a, **k):
        if str(path).endswith("-before-v0.4.17.sqlite"):
            raise db.sqlite3.OperationalError("disk full")
        return real(path, *a, **k)
    monkeypatch.setattr(db.sqlite3, "connect", no_copy)
    con = db.connect(storage.db_path())                    # starts, data as before
    assert db.project(con, rome)["chamber_id"] == 1
    assert not (tmp_path / "bresaola-before-v0.4.17.sqlite").exists()


def test_hub_sync_with_nothing_to_sync_says_so(env, monkeypatch):
    for k, v in (("TAPO_USERNAME", "u"), ("TAPO_PASSWORD", "p"), ("TAPO_HUB_IP", "1.2.3.4")):
        monkeypatch.setenv(k, v)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "tapohub1").click()
    at.run()
    assert any("No batch is drying with a Tapo sensor name" in t.value for t in at.toast)
