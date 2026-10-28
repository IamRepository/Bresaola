"""Full audit 27 Oct 2026 (v0.4.8) findings fixed in v0.4.9: 1-8 and 10 (9 accepted).
Each test failed before the fix."""
import io
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from bresaola import db, report, sensors, storage, tapo_sync
from bresaola.demo import seed_demo
from tests.test_sensors import FakeSensor, fake_factory

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
    return con


def open_app(pid=None, step=None):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    if pid is not None:
        next(s for s in at.sidebar.selectbox if s.label == "Project").set_value(pid)
        at.run()
    if step:
        next(b for b in at.button if b.key == f"rail_{step}").click()
        at.run()
    assert not at.exception, at.exception
    return at


def pdf_text(con, pid=1):
    return " ".join(" ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(report.build_pdf(con, pid))).pages).split())


def lock_and_close(con):
    with con:
        db.lock_dry(con, 1, date(2026, 10, 8), below_target_ok=True)
        db.close_project(con, 1)


# 1: a stale browser tab never writes its old values back
def test_stale_tab_does_not_undo_day0_changes(env):
    with env:
        pid = db.create_project(env, "Fresh", "Classic Italian", False, 2000, start_date=TODAY)
    tab_a = open_app(pid, "day0")
    with env:                                                   # tab B (or the phone) changes the recipe
        db.update_spice_inputs(env, pid, green_weight_g=2500, ecocure=True)
    next(b for b in tab_a.button if b.key == "rail_day0").click()   # tab A reruns, still on Day 0
    tab_a.run()
    p = db.project(env, pid)
    assert (p["green_weight_g"], p["ecocure"]) == (2500, 1)
    assert [e["kind"] for e in db.events(env, pid)].count("curing_salt_changed") <= 1   # no flip back
    # and it now shows the database's values
    assert next(n for n in tab_a.number_input if (n.key or "").split("@")[0] == f"w{pid}").value == 2500
    assert next(t for t in tab_a.toggle if (t.key or "").split("@")[0] == f"e{pid}").value is True


def test_stale_tab_does_not_undo_chamber_type(env):
    ch = db.project(env, 1)["chamber_id"]
    tab_a = open_app(1, "dry")
    with env:
        db.set_chamber_kind(env, ch, "chamber")
    next(b for b in tab_a.button if b.key == "rail_dry").click()
    tab_a.run()
    assert env.execute("SELECT kind FROM chamber WHERE id=?", (ch,)).fetchone()[0] == "chamber"


def test_stale_note_is_refreshed(env):
    tab_a = open_app(1, "dry")
    with env:
        db.set_dry_note(env, 1, "written on the phone")
    next(b for b in tab_a.button if b.key == "rail_dry").click()
    tab_a.run()
    assert next(t for t in tab_a.text_area if (t.key or "").split("@")[0] == "note_dry1").value == "written on the phone"


# 2: ending drying below the target needs a confirmation, is logged and shown in the app and the PDF
def test_lock_below_target_needs_confirmation(env):
    with pytest.raises(ValueError, match="below the 35 % target"):
        db.lock_dry(env, 1, date(2026, 10, 8))
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
    assert "below target: 6.5 % of 35 %, confirmed" in db.events(env, 1)[-1]["detail"]
    assert "below the 35 % target" in pdf_text(env)
    at = open_app(1, "finish")
    assert any("below the 35 % target" in w.value for w in at.warning)


def test_reaching_target_needs_no_confirmation(env):
    with env:
        db.add_reading(env, 1, date(2026, 10, 10), 1360, confirmed=True)
        db.lock_dry(env, 1, date(2026, 10, 10))
    assert "below target" not in db.events(env, 1)[-1]["detail"]


# 3: left-out periods are remembered; nothing is written into finished drying periods
def test_left_out_period_applies_to_later_imports_and_hub_sync(env, monkeypatch):
    ch = db.project(env, 1)["chamber_id"]
    warm = [(datetime(2026, 10, 3, 14), 21.0, 40.0), (datetime(2026, 10, 10, 13), 2.0, 80.0)]
    with env:
        sensors.import_export(env, ch, warm, datetime(2026, 10, 3, 12, 15), datetime(2026, 10, 9, 4, 0))
        res = sensors.import_export(env, ch, warm)                 # same file again, no leave-out typed
    assert res.left_out == 1
    assert not [r for r in db.chamber_readings(env, ch) if r["ts"].startswith("2026-10-03T14")]
    monkeypatch.setenv("TAPO_USERNAME", "me@example.com")
    monkeypatch.setenv("TAPO_PASSWORD", "secret")
    monkeypatch.setenv("TAPO_HUB_IP", "192.168.1.50")
    monkeypatch.setenv("TAPO_SENSORS", "Fridge drawer=Bresaola sensor")
    with env:
        db.add_exclusion(env, ch, datetime(2026, 10, 17, 23), datetime(2026, 10, 18, 1))   # covers the fake hub's times
    r = tapo_sync.sync(env, fake_factory(FakeSensor()))[0]
    assert (r.stored, r.skipped) == (0, 3)


def test_import_never_changes_a_closed_batch(env):
    ch = db.project(env, 1)["chamber_id"]
    lock_and_close(env)
    before = pdf_text(env)
    with env:
        res = sensors.import_export(env, ch, [(datetime(2026, 9, 25, h), 9.0, 50.0) for h in range(24)])
    assert (res.stored, res.locked) == (0, 24)
    assert pdf_text(env) == before


# 4: a period can be left out without uploading a file, removing readings already stored
def test_leave_out_without_a_file(env):
    ch = db.project(env, 1)["chamber_id"]
    with env:
        sensors.import_readings(env, ch, [(datetime(2026, 10, 4, h), 21.0, 40.0) for h in range(24)], "tapo_export")
    at = open_app(1, "dry")
    next(d for d in at.date_input if d.key == "lo_d1").set_value(date(2026, 10, 3))
    next(d for d in at.date_input if d.key == "hi_d1").set_value(date(2026, 10, 9))
    at.run()
    next(b for b in at.button if b.key == "exadd1").click()
    at.run()
    assert not at.exception, at.exception
    assert not [r for r in db.chamber_readings(env, ch) if r["ts"].startswith("2026-10-04")]
    assert len(db.exclusions(env, ch)) == 1


# 5: a chamber the hub sync feeds is never offered as "unused"
def test_hub_fed_chamber_not_offered_for_deletion(env, monkeypatch):
    monkeypatch.setenv("TAPO_SENSORS", "  cellar =T315 cellar")
    with env:
        db.get_or_create_chamber(env, "Cellar")
    at = open_app()
    assert not [b for b in at.sidebar.button if b.label.startswith("Delete chamber")]


# 6: captions and final notes show as typed, like the PDF
def test_caption_and_final_notes_not_formatted(env):
    with env:
        db.add_photo(env, 1, "photos/1/gone.jpg", "2026-09-20", "**bold cap** :red[RED]", stage="dry")
    at = open_app(1, "dry")
    caps = [c.value for c in at.caption]
    assert any(r"\*\*bold cap\*\* \:red\[RED\]" in c for c in caps), caps
    with env:
        db.lock_dry(env, 1, date(2026, 10, 8), below_target_ok=True)
        db.close_project(env, 1, "# Heading final\nsecond line")
    at = open_app(1, "finish")
    assert any(r"\# Heading final  " in m.value and "second line" in m.value for m in at.markdown)


# 7: PDF section headings stay with what follows (no "Photos" alone at a page end)
def test_pdf_headings_keep_with_next():
    assert report.S["h2"].keepWithNext == 1


# 8: chamber chart axis labels are rounded (constant humidity showed "80.000000")
def test_chamber_axis_format(env):
    with env:
        sensors.import_readings(env, 1, [(datetime(2026, 9, 25, h), 2.0, 80.0) for h in range(24)], "tapo_export")
    at = open_app(1, "dry")
    specs = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower():
                specs.append(json.loads(c.proto.spec))
            walk(c)
    walk(at._tree)
    y_h = [layer["encoding"]["y"] for sp in specs for layer in sp.get("layer", [])
           if layer.get("encoding", {}).get("y", {}).get("field") == "h"]
    assert y_h and all(y.get("axis", {}).get("format") == ".0f" for y in y_h), y_h


# 10: the cure timeline shows the out-of-bag date even when it is near the right end
def test_cure_timeline_shows_out_date(env):
    at = open_app(1, "cure")
    assert any("planned end 18 Sep · out 20 Sep" in m.value for m in at.markdown)


# owner 27 Oct: time axes mixed "Mon 21", "Sep 27" and "October" on one axis
def test_time_axes_use_one_date_format(env):
    with env:
        sensors.import_readings(env, 1, [(datetime(2026, 9, 21) + (datetime(2026, 9, 21, 0, 15) - datetime(2026, 9, 21)) * i,
                                          2.0, 80.0) for i in range(4 * 24 * 30)], "tapo_export")
    at = open_app(1, "dry")
    specs = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower():
                specs.append(json.loads(c.proto.spec))
            walk(c)
    walk(at._tree)
    xs = [layer["encoding"]["x"] for sp in specs for layer in sp.get("layer", [])
          if isinstance(layer.get("encoding", {}).get("x"), dict) and "axis" in layer["encoding"]["x"]]
    assert xs and all(x["axis"]["format"] == "%d %b" and x["axis"].get("values") for x in xs), xs
    weight = next(x for x in xs if x["field"] == "Date")
    assert [v["date"] for v in weight["axis"]["values"]] == [20, 26, 30, 4, 8]     # the weigh-in days
    chamber = next(x for x in xs if x["field"] == "Time")
    assert [v["date"] for v in chamber["axis"]["values"]][:3] == [21, 28, 5]       # every 7 days
