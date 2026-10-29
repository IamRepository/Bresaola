"""v0.4.22 (owner, 29 Oct 2026; replaces the v0.4.21 strip): temperature and humidity in one chart with
two clearly marked y-axes; a slider with two handles and quick buttons sets the period shown; the
y-axes fit that period; the weight chart is unchanged; the test mode has demo sensor readings."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, sensors, storage
from bresaola.demo import seed_demo, seed_demo_readings
from tests.helpers import all_layers

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: date(2026, 10, 11))
    for k in ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_HUB_IP", "TAPO_SENSORS"):
        monkeypatch.delenv(k, raising=False)
    con = db.connect(storage.db_path())
    seed_demo(con)
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 9, 21) + timedelta(minutes=15 * i), 2.0 + (i % 96) / 96,
                                          80.0 + (i % 50) / 10) for i in range(4 * 24 * 15)], "tapo_export")
    a = AppTest.from_file(APP, default_timeout=30)
    a.run()
    assert not a.exception, a.exception
    return a


def specs(at):
    out = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower():
                out.append(json.loads(c.proto.spec))
            walk(c)
    walk(at._tree)
    return out


def sensor_spec(at):
    return next(s for s in specs(at) if any((l.get("encoding", {}).get("x") or {}).get("field") == "Time"
                                            for l in all_layers(s)))


def y_axes(spec):
    return [l["encoding"]["y"] for l in all_layers(spec) if "y" in l.get("encoding", {})
            and (l.get("mark") or {}).get("type") == "line"]


def test_one_chart_two_marked_axes(at):
    sp = sensor_spec(at)
    assert sp.get("resolve", {}).get("scale", {}).get("y") == "independent"
    ys = {y["field"]: y["axis"] for y in y_axes(sp)}
    assert ys["t"]["title"] == "Temperature [°C]" and ys["t"]["orient"] == "left"
    assert ys["h"]["title"] == "Humidity [%]" and ys["h"]["orient"] == "right"
    assert ys["t"]["titleColor"] == ys["t"]["labelColor"] != ys["h"]["titleColor"] == ys["h"]["labelColor"]
    assert not any("concat" in s for s in specs(at))                          # the strip is gone
    assert any("Red line: temperature, left axis. Green line: humidity, right axis." in c.value for c in at.caption)


def test_slider_and_quick_buttons_set_the_period(at):
    sl = next(s for s in at.slider if s.label == "Period shown")
    assert sl.value == (datetime(2026, 9, 21), datetime(2026, 10, 5, 23, 45))
    next(b for b in at.button if b.label == "Last 24 h").click()
    at.run()
    sl = next(s for s in at.slider if s.label == "Period shown")
    assert sl.value == (datetime(2026, 10, 4, 23, 45), datetime(2026, 10, 5, 23, 45))
    sp = sensor_spec(at)
    dom = next(l["encoding"]["x"]["scale"]["domain"] for l in all_layers(sp)
               if (l.get("mark") or {}).get("type") == "line")
    assert [(d_["date"], d_["hours"]) for d_ in dom] == [(4, 23), (5, 23)]
    next(b for b in at.button if b.label == "All").click()
    at.run()
    assert next(s for s in at.slider if s.label == "Period shown").value[0] == datetime(2026, 9, 21)


def chart_times(at):
    """Times of all rows sent with the sensor chart (Streamlit sends the data next to the spec)."""
    import pyarrow as pa
    out = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower() and '"Time"' in c.proto.spec:
                for ds in c.proto.datasets:
                    t = pa.ipc.open_stream(ds.data.data).read_all()
                    if "Time" in t.column_names and ("t" in t.column_names or "h" in t.column_names):
                        out.extend(t.column("Time").to_pylist())
            walk(c)
    walk(at._tree)
    return out


def test_only_the_period_is_drawn_so_the_axes_fit(at):
    sl = next(s for s in at.slider if s.label == "Period shown")
    sl.set_value((datetime(2026, 9, 25), datetime(2026, 9, 26)))
    at.run()
    assert not at.exception, at.exception
    times = [pd_.replace(tzinfo=None) for pd_ in chart_times(at)]
    # the day plus one 1.5 h averaging period on each side, nothing else: both y-axes fit that day
    assert times and min(times) >= datetime(2026, 9, 24, 22, 30) and max(times) <= datetime(2026, 9, 26, 1, 30), \
        (min(times), max(times))


def test_window_ending_at_newest_follows_new_readings(at, tmp_path):
    con = db.connect(storage.db_path())
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 10, 6, 0) + timedelta(minutes=15 * i), 2.0, 80.0)
                                         for i in range(8)], "tapo_export")
    next(b for b in at.button if b.label == "Last 24 h").click()      # any rerun picks up the new data
    at.run()
    assert next(s for s in at.slider if s.label == "Period shown").value[1] == datetime(2026, 10, 6, 1, 45)


def test_weight_chart_not_changed(at):
    weight = [s for s in specs(at) if "layer" in s and any(
        (l.get("encoding", {}).get("x") or {}).get("field") == "Date" for l in s["layer"])]
    assert weight and "params" not in weight[0] and "resolve" not in weight[0]


def test_test_mode_has_demo_sensor_readings(tmp_path):
    con = db.connect(tmp_path / "d.sqlite")
    pid = seed_demo(con)
    n = seed_demo_readings(con, pid)
    ch = db.project(con, pid)["chamber_id"]
    assert n > 1500 and len(db.exclusions(con, ch)) == 1
    assert max(r["temp_c"] for r in db.chamber_readings(con, ch)) > 4        # the door-open hour shows up
