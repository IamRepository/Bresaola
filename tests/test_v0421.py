"""v0.4.21 (owner, 29 Oct 2026): temperature and humidity zoom together from a strip below them;
the y-axes fit the window; the weight chart is unchanged."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, sensors, storage
from bresaola.demo import seed_demo

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
        sensors.import_readings(con, 1, [(datetime(2026, 9, 21) + timedelta(minutes=15 * i), 2.0, 80.0)
                                         for i in range(4 * 24 * 15)], "tapo_export")
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


def test_one_zoomable_chart_for_temperature_and_humidity(at):
    sp = [s for s in specs(at) if "concat" in s]
    assert len(sp) == 1, "temperature, humidity and the strip are one chart"
    views = sp[0]["concat"]
    assert len(views) == 3
    strip = views[-1]
    params = strip.get("params", []) + sp[0].get("params", [])          # Altair may lift it to the top
    assert any(p.get("name") == "zoom" and p["select"]["encodings"] == ["x"] for p in params), params
    for v in views[:2]:                                   # both detail charts follow the strip ...
        lines = [l for l in v["layer"] if (l.get("mark") or {}).get("type") == "line"]
        assert lines and lines[0]["encoding"]["x"]["scale"]["domain"] == {"param": "zoom"}
        # ... and every data layer is cut to the window plus one period each side (y fits, edges stay)
        data_layers = [l for l in v["layer"] if (l.get("mark") or {}).get("type") in ("line", "area", "rule", "point")]
        filters = [t.get("filter") for l in data_layers for t in l.get("transform", [])]
        assert len(filters) == len(data_layers) and all("zoom.Time[0]) - 5400000" in f_ for f_ in filters), filters
        assert all(f_.startswith("!zoom.Time ||") for f_ in filters)          # nothing selected: everything
    titles = [v["title"]["text"] for v in views[:2]]
    assert titles == ["Temperature [°C]", "Humidity [%]"]


def test_weight_chart_not_zoomable(at):
    weight = [s for s in specs(at) if "layer" in s and any(
        (l.get("encoding", {}).get("x") or {}).get("field") == "Date" for l in s["layer"])]
    assert weight and not any("params" in l for l in weight[0]["layer"]) and "params" not in weight[0]


def test_strip_covers_left_out_and_weigh_ins(at):
    strip = next(s for s in specs(at) if "concat" in s)["concat"][-1]
    marks = [(l.get("mark") or {}).get("type") for l in strip["layer"]]
    assert "line" in marks and "rule" in marks


def test_zoom_hint_shown(at):
    assert any("**Zoom**: drag across the strip" in c.value for c in at.caption)
