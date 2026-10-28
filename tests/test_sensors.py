"""Tapo T31x readings: app export files and the H100 hub sync."""
import io
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from pathlib import Path

from bresaola import db, sensors, storage, tapo_sync
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setattr(db, "today", lambda: date(2026, 10, 18))
    c = db.connect(storage.db_path())
    seed_demo(c)
    return c


# ---- export files ------------------------------------------------------------------

def test_plain_csv_iso_times():
    data = b"Time,Temperature(\xc2\xb0C),Humidity(%)\n2026-10-01 08:00,12.4,78\n2026-10-01 09:00,12.6,77\n"
    p = sensors.parse_export(data, "export.csv")
    assert p.rows == [(datetime(2026, 10, 1, 8), 12.4, 78.0), (datetime(2026, 10, 1, 9), 12.6, 77.0)]


def test_german_semicolon_decimal_comma_with_preamble():
    data = ("Gerät: Fridge drawer\nExportiert am 18.10.2026\n\n"
            "Zeit;Temperatur (°C);Luftfeuchtigkeit (%)\n"
            "01.10.2026 08:00;12,4;78\n13.10.2026 09:30;13,1;74\n").encode("utf-8")
    p = sensors.parse_export(data, "daten.csv")
    assert p.rows[0] == (datetime(2026, 10, 1, 8), 12.4, 78.0)
    assert p.rows[1] == (datetime(2026, 10, 13, 9, 30), 13.1, 74.0)


def test_month_first_detected_from_data():
    data = b"Date,Temperature,Humidity\n10/13/2026 08:00,12.0,70\n10/14/2026 08:00,12.5,71\n"
    p = sensors.parse_export(data, "us.csv")
    assert p.first == datetime(2026, 10, 13, 8)


def test_fahrenheit_converted():
    data = b"Time,Temperature(\xc2\xb0F),Humidity(%)\n2026-10-01 08:00,54.5,78\n"
    p = sensors.parse_export(data, "f.csv")
    assert p.fahrenheit and p.rows[0][1] == pytest.approx(12.5, abs=0.01)


def test_separate_date_and_time_columns():
    data = b"Date,Time,Temperature,Humidity\n2026-10-01,08:00,12.4,78\n"
    assert sensors.parse_export(data, "x.csv").rows[0][0] == datetime(2026, 10, 1, 8)


def test_xlsx_with_real_datetimes():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Tapo T315 Fridge drawer"])
    ws.append(["Time", "Temperature(°C)", "Humidity(%)"])
    ws.append([datetime(2026, 10, 1, 8, 0), 12.4, 78])
    ws.append([datetime(2026, 10, 1, 9, 0), None, 77])
    buf = io.BytesIO()
    wb.save(buf)
    p = sensors.parse_export(buf.getvalue(), "export.xlsx")
    assert p.rows == [(datetime(2026, 10, 1, 8), 12.4, 78.0), (datetime(2026, 10, 1, 9), None, 77.0)]


def test_wrong_file_gives_readable_error():
    with pytest.raises(ValueError, match="Couldn.t find temperature or humidity"):
        sensors.parse_export(b"name,amount\nsalt,62.6\n", "spices.csv")


def test_import_twice_does_not_duplicate_and_rejects_out_of_range(con):
    rows = [(datetime(2026, 10, 1, 8), 12.4, 78.0), (datetime(2026, 10, 1, 9), 99.0, 78.0)]
    with con:
        assert sensors.import_readings(con, 1, rows, "tapo_export") == (1, 1)
        sensors.import_readings(con, 1, rows, "tapo_export")
    n = con.execute("SELECT COUNT(*) FROM chamber_reading WHERE source='tapo_export'").fetchone()[0]
    assert n == 1


# ---- hub sync with a fake hub ---------------------------------------------------------

class FakeSensor:
    def __init__(self, unit="Celsius", fail=False):
        self.unit, self.fail = unit, fail

    async def get_temperature_humidity_records(self):
        if self.fail:
            raise RuntimeError("hub unreachable")
        t0 = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)          # 18 Oct 00:00 in Berlin
        base = 54.0 if self.unit == "Fahrenheit" else 12.0
        recs = [SimpleNamespace(recorded_at=t0.replace(minute=15 * i), temperature=base + i * 0.1, humidity=75)
                for i in range(3)]
        return SimpleNamespace(records=recs, temperature_unit=self.unit)


def fake_factory(sensor):
    class Hub:
        async def t31x(self, nickname=None, device_id=None):
            assert nickname == "Bresaola sensor"
            return sensor

    class Client:
        def __init__(self, user, pw):
            assert (user, pw) == ("me@example.com", "secret")

        async def h100(self, ip):
            assert ip == "192.168.1.50"
            return Hub()
    return Client


@pytest.fixture
def tapo_env(monkeypatch):
    monkeypatch.setenv("TAPO_USERNAME", "me@example.com")
    monkeypatch.setenv("TAPO_PASSWORD", "secret")
    monkeypatch.setenv("TAPO_HUB_IP", "192.168.1.50")
    monkeypatch.setenv("TAPO_SENSORS", "Fridge drawer=Bresaola sensor")


def test_sensor_map_and_configured(tapo_env):
    assert tapo_sync.sensor_map("Fridge drawer=Bresaola sensor; Cellar = T315 cellar ;bad") == \
        {"Fridge drawer": "Bresaola sensor", "Cellar": "T315 cellar"}
    assert tapo_sync.is_configured()


def test_not_configured_without_env(monkeypatch):
    for k in ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_HUB_IP", "TAPO_SENSORS"):
        monkeypatch.delenv(k, raising=False)
    assert not tapo_sync.is_configured()


def test_sync_stores_local_times_under_the_chamber(con, tapo_env):
    res = tapo_sync.sync(con, fake_factory(FakeSensor()))
    assert res[0].error is None and res[0].stored == 3
    rows = db.chamber_readings(con, 1)
    ts = [r["ts"] for r in rows if r["source"] == "tapo_api"]
    assert ts == ["2026-10-18T00:00:00", "2026-10-18T00:15:00", "2026-10-18T00:30:00"]   # UTC → Berlin


def test_sync_converts_fahrenheit(con, tapo_env):
    tapo_sync.sync(con, fake_factory(FakeSensor(unit="Fahrenheit")))
    t = con.execute("SELECT temp_c FROM chamber_reading WHERE source='tapo_api' ORDER BY ts").fetchone()[0]
    assert t == pytest.approx((54.0 - 32) * 5 / 9, abs=0.01)   # 12.2 °C


def test_sync_failure_is_reported_not_raised(con, tapo_env):
    res = tapo_sync.sync(con, fake_factory(FakeSensor(fail=True)))
    assert "hub unreachable" in res[0].error


# ---- screen ---------------------------------------------------------------------------

def test_dry_step_shows_chamber_section(con, monkeypatch):
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert 'class="blk">Sensor readings' in " ".join(m.value for m in at.markdown)      # v0.4.17: per batch
    assert any(e.label == "Sensor settings, import and remove" for e in at.expander)
    assert any("Import from the Tapo app" in m.value for m in at.markdown)
    assert not any(b.label == "Sync last 24 h from hub" for b in at.button)       # not configured here


# ---- the real Tapo export layout (22 Oct 2026 file) -----------------------------------

REAL_HEADER = "2026/09/20 00:00:00 - 2026/10/23 00:00:00,Temperature(℃),Abnormal,Humidity(%),Abnormal"


def test_real_tapo_csv_layout():
    data = ("﻿" + REAL_HEADER + "\n20/09/2026 16:30,1.3,,63,*\n03/10/2026 15:00,-16.9,*,68,*\n"
            "22/10/2026 09:00,2.1,,84,*\n").encode("utf-8")
    p = sensors.parse_export(data, "tapo_export.csv")
    assert p.columns == (REAL_HEADER.split(",")[0], "Temperature(℃)", "Humidity(%)")
    assert p.rows == [(datetime(2026, 9, 20, 16, 30), 1.3, 63.0), (datetime(2026, 10, 3, 15, 0), -16.9, 68.0),
                      (datetime(2026, 10, 22, 9, 0), 2.1, 84.0)]
    assert not p.fahrenheit


def test_real_tapo_excel_layout_xlsm():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(REAL_HEADER.split(","))
    ws.append([datetime(2026, 9, 20, 16, 30), 1.3, None, 63, "*"])
    ws.append([datetime(2026, 9, 20, 16, 45), 1.6, None, 67, "*"])
    buf = io.BytesIO()
    wb.save(buf)
    p = sensors.parse_export(buf.getvalue(), "tapo_export.xlsm")
    assert [r[0] for r in p.rows] == [datetime(2026, 9, 20, 16, 30), datetime(2026, 9, 20, 16, 45)]


def test_leave_out_a_period():
    rows = [(datetime(2026, 10, 3, 12, 0), 2.0, 80.0), (datetime(2026, 10, 3, 12, 15), 4.1, 82.0),
            (datetime(2026, 10, 9, 4, 0), 2.0, 81.0), (datetime(2026, 10, 9, 4, 15), 2.0, 81.0)]
    kept, n = sensors.leave_out(rows, datetime(2026, 10, 3, 12, 15), datetime(2026, 10, 9, 4, 0))
    assert n == 2 and [r[0].hour for r in kept] == [12, 4] and kept[1][0].minute == 15
    assert sensors.leave_out(rows, None, None) == (rows, 0)


# ---- weigh-ins matched to chamber readings (noon rule) --------------------------------

def _rows(*items):
    return [{"ts": t, "temp_c": c, "rh_pct": h} for t, c, h in items]


def test_weigh_in_gets_the_day_average():
    full = [(f"2026-09-26T{h:02d}:00:00", 2.0 + (h % 2) * 0.4, 80 + (h % 2) * 2) for h in range(24)]   # 24 h
    cr = _rows(*full, ("2026-09-20T16:30:00", 1.3, 63), ("2026-09-20T17:30:00", 3.1, 74),
               ("2026-09-25T23:45:00", 9.9, 99))                                  # previous day: not used
    m = sensors.day_averages([date(2026, 9, 26), date(2026, 9, 20), date(2026, 10, 4)], cr)
    assert m[date(2026, 9, 26)] == (2.2, 81.0, 24, False)        # whole day: not partial
    assert m[date(2026, 9, 20)] == (2.2, 68.0, 2, True)          # sensor started 16:30: partial
    assert m[date(2026, 10, 4)] is None                         # no readings that day


def test_remove_readings_by_source_and_period(con):
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 10, d, 12), 2.0, 80.0) for d in (1, 2, 3)], "tapo_export")
        db.add_chamber_reading(con, 1, "2026-10-02T12:00:00", 2.5, 81, source="manual")
        assert db.delete_chamber_readings(con, 1, "tapo_export", datetime(2026, 10, 2), datetime(2026, 10, 2, 23, 59, 59)) == (1, 0)
    assert db.chamber_reading_counts(con, 1)["tapo_export"][0] == 2
    with con:
        assert db.delete_chamber_readings(con, 1, "tapo_export") == (2, 0)
    assert "tapo_export" not in db.chamber_reading_counts(con, 1)
    assert db.chamber_reading_counts(con, 1)["manual"][0] == 1     # other sources untouched


def test_weigh_in_table_and_pdf_show_chamber_values(con, monkeypatch):
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 9, 26, 12, 0), 2.7, 81.0),
                                         (datetime(2026, 10, 8, 11, 45), 1.9, 79.0)], "tapo_export")
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    df = at.dataframe[0].value
    assert list(df.columns)[4:9] == ["Day °C", "Day RH [%]", "Since last °C", "Since last RH [%]", "Data [%]"]
    by_date = {r["Date"]: (r["Day °C"], r["Day RH [%]"]) for _, r in df.iterrows()}
    since = {r["Date"]: (r["Since last °C"], r["Since last RH [%]"], r["Data [%]"]) for _, r in df.iterrows()}
    assert since["20 Sep"] == ("–", "–", "–")                         # first weigh-in has no period
    assert since["26 Sep"] == ("–", "–", "–")                         # a 12:00 reading starts the next period
    assert since["30 Sep"] == ("2.7*", "81*", "1")                    # one reading in 4 days
    assert by_date["26 Sep"] == ("2.7*", "81*") and by_date["08 Oct"] == ("1.9*", "79*")   # 1 reading = partial
    assert by_date["30 Sep"] == ("–", "–")                          # no reading near noon
    assert any("Dashed lines: weigh-ins" in c.value for c in at.caption)
    assert any(b.label == "Remove readings" for b in at.button)
    from pypdf import PdfReader
    from bresaola import report
    t = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(report.build_pdf(con, 1))).pages)
    assert "average of all chamber readings" in t and "previous weigh-in" in t and "2.7*" in t


def test_period_average_since_previous_weigh_in():
    # every hour from 26 Sep 12:00 to 30 Sep 11:00 → full coverage; a reading after 30 Sep noon belongs to the next period
    cr = _rows(*[((datetime(2026, 9, 26, 12) + timedelta(hours=h)).isoformat(), 2.0 + (h % 2) * 0.2, 80)
                 for h in range(96)], ("2026-09-30T12:00:00", 9.0, 99))
    m = sensors.period_averages([date(2026, 9, 30), date(2026, 9, 26), date(2026, 10, 4)], cr)   # any order
    assert m[date(2026, 9, 30)] == (2.1, 80.0, 96, False, 1.0)
    assert m[date(2026, 10, 4)] == (9.0, 99.0, 1, True, 0.01)          # 1 of 96 hours covered
    assert date(2026, 9, 26) not in m                                 # first weigh-in: no period


def test_aggregate_per_hour_12h_and_day():
    cr = _rows(("2026-10-10T00:00:00", 1.0, 80), ("2026-10-10T00:45:00", 2.0, 82), ("2026-10-10T11:15:00", 3.0, 84),
               ("2026-10-10T13:00:00", 4.0, 86), ("2026-10-12T09:00:00", 2.0, 80))
    h1 = sensors.aggregate(cr, 1)
    assert [b["start"].hour for b in h1[:3]] == [0, 11, 13] and h1[0]["t"] == 1.5 and h1[0]["n"] == 2
    h12 = sensors.aggregate(cr, 12)
    assert [(b["mid"], b["t"], b["t_min"], b["t_max"]) for b in h12[:2]] == [
        (datetime(2026, 10, 10, 6), 2.0, 1.0, 3.0), (datetime(2026, 10, 10, 18), 4.0, 4.0, 4.0)]
    d24 = sensors.aggregate(cr, 24)
    assert [b["mid"] for b in d24] == [datetime(2026, 10, 10, 12), datetime(2026, 10, 12, 12)]   # gap day left out
    assert d24[0]["t"] == 2.5 and d24[0]["h"] == 83.0 and d24[0]["n"] == 4


def test_chamber_view_switch(con, monkeypatch):
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 9, 26, h), 2.0 + h / 10, 80.0) for h in range(24)], "tapo_export")
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    for view in ("15 min", "12 hours", "24 hours", "1 hour"):
        next(s for s in at.button_group if s.key == "chview1").set_value(view)
        at.run()
        assert not at.exception, (view, at.exception)
        assert any(("average per " + view) in c.value or (view == "15 min" and "as recorded" in c.value)
                   for c in at.caption), view


def test_chamber_charts_visible_without_opening_anything(con, monkeypatch):
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 9, 26, h), 2.0, 80.0) for h in range(24)], "tapo_export")
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    settings = next(e for e in at.expander if e.label == "Sensor settings, import and remove")
    assert not any(b.key == "chview1" for b in settings.button_group)           # chart controls outside
    assert any(b.key == "chview1" for b in at.button_group)
    assert any(b.key == "chkind1" for b in settings.button_group)               # type setting folded away
