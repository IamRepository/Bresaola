"""Backlog items done in v0.4.11 (27 Oct 2026). Each failed before."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import calc, db, storage, tapo_sync
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TODAY = date(2026, 10, 25)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(storage.db_path())
    seed_demo(con)
    with con:                                   # Palermo's real weigh-ins after 8 Oct
        for d_, g in ((date(2026, 10, 11), 1948), (date(2026, 10, 14), 1935), (date(2026, 10, 18), 1911),
                      (date(2026, 10, 21), 1895), (date(2026, 10, 23), 1877)):
            db.add_reading(con, 1, d_, g, confirmed=True)
    return con


def dry(env_):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "rail_dry").click()
    at.run()
    assert not at.exception, at.exception
    return at


def specs(at):
    out = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower():
                out.append(json.loads(c.proto.spec))
            walk(c)
    walk(at._tree)
    return out


# finish estimate from the recent pace: drying slows, a line through all weigh-ins is too early
def test_recent_pace_estimate_is_later_than_straight_line(env):
    rs = db.readings(env, 1)
    recent = calc.recent_eta(rs, 2100, 35)
    all_ = calc.drying_eta(rs, 2100, 35)
    assert recent.grams_per_day < all_.grams_per_day
    assert recent.eta_date > all_.eta_date
    at = dry(env)
    m = {x.label: x for x in at.metric}
    assert m["Estimated finish"].value == recent.eta_date.strftime("%d %b %Y")
    assert "last 21 days" in m["Estimated finish"].help and all_.eta_date.strftime("%d %b %Y") in m["Estimated finish"].help


def test_recent_pace_uses_at_least_three_weigh_ins():
    rs = [(date(2026, 1, 1), 2100), (date(2026, 1, 20), 2000), (date(2026, 2, 20), 1950)]
    assert calc.recent_eta(rs, 2100, 35).grams_per_day == pytest.approx(calc.drying_eta(rs, 2100, 35).grams_per_day)


# owner: weigh-in table values aligned left, like the headings
def test_weigh_in_table_left_aligned(env):
    at = dry(env)
    df = next(d for d in at.dataframe if "Weight [g]" in d.value.columns)
    cfg = json.loads(df.proto.columns)
    for col in ("Date", "Day", "Weight [g]", "Lost [%]", "Day °C", "Footnote"):
        assert cfg[col]["alignment"] == "left", (col, cfg[col])


# names and notes with "&copy;" or leading spaces show as typed
def test_ampersand_and_leading_spaces_as_typed(env):
    with env:
        db.rename_project(env, 1, "Fish &copy; chips")
        db.lock_dry(env, 1, date(2026, 10, 23), below_target_ok=True)
        db.close_project(env, 1, "    indented line\n&copy; 2026")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert "&amp;copy;" in at.header[0].value
    next(b for b in at.button if b.key == "rail_finish").click()
    at.run()
    notes = [m.value for m in at.markdown if "indented line" in m.value]
    assert notes and notes[0].startswith("&nbsp;" * 4) and "&amp;copy;" in notes[0]


# hub sync message says how many readings were skipped
def test_hub_sync_message_counts_skipped(env, monkeypatch):
    for k, v in (("TAPO_USERNAME", "u"), ("TAPO_PASSWORD", "p"), ("TAPO_HUB_IP", "1.2.3.4"),
                 ("TAPO_SENSORS", "Fridge drawer=x")):
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(tapo_sync, "sync", lambda con: [tapo_sync.Result("Fridge drawer", "x", stored=90, skipped=6)])
    at = dry(env)
    next(b for b in at.button if b.key == "tapohub1").click()
    at.run()
    assert any("90 readings, 6 skipped" in t.value for t in at.toast)


# left-out period can end at 23:59
def test_left_out_can_end_at_2359(env):
    at = dry(env)
    to = next(s for s in at.selectbox if s.key == "hi_t1")
    assert to.value == "23:59" and "23:45" in to.options


# many weigh-ins: weight chart ticks every 7/14 days instead of one per weigh-in
def test_weight_chart_ticks_with_many_weigh_ins(env):
    with env:                                   # daily weigh-ins in the first week: 17 in total
        for i in range(1, 6):
            db.add_reading(env, 1, date(2026, 9, 20) + timedelta(days=i), 2100 - i * 4, confirmed=True)
    at = dry(env)
    x = next(l["encoding"]["x"] for sp in specs(at) for l in sp.get("layer", [])
             if l.get("encoding", {}).get("x", {}).get("field") == "Date")
    days = [v["date"] for v in x["axis"]["values"]]
    assert len(days) < len(db.readings(env, 1)) and days[:2] == [20, 27]
