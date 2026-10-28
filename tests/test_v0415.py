"""v0.4.15 (28 Oct 2026): weigh-in notes as numbered footnotes; label on the target line."""
import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: date(2026, 10, 11))
    con = db.connect(storage.db_path())
    seed_demo(con)                                     # 20 Sep note: "Start of drying"
    with con:
        con.execute("UPDATE reading SET note='Firm outside,\nsoft *centre*' WHERE project_id=1 AND day='2026-09-30'")
    a = AppTest.from_file(APP, default_timeout=30)
    a.run()
    assert not a.exception, a.exception
    return a


def test_notes_are_numbered_footnotes_below_the_table(at):
    df = next(d for d in at.dataframe if "Weight [g]" in d.value.columns).value
    assert "Note" not in df.columns
    assert list(df["Footnote"]) == ["1", "", "2", "", ""]
    text = " ".join(m.value for m in at.markdown)
    assert "**1** · 20 Sep 2026: Start of drying" in text
    assert r"**2** · 30 Sep 2026: Firm outside, soft \*centre\*" in text      # as typed, one line


def test_target_line_is_labelled(at):
    from bresaola import calc
    assert calc.target_label(1365, 35) == "Target 1365 g · 35 % weight loss"
    specs = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            if "vega" in str(getattr(c, "type", "")).lower():
                specs.append(json.loads(c.proto.spec))
            walk(c)
    walk(at._tree)
    weight = next(sp for sp in specs if any(l.get("encoding", {}).get("x", {}).get("field") == "Date"
                                            for l in sp.get("layer", [])))
    texts = [l for l in weight["layer"] if (l.get("mark") or {}).get("type") == "text"]
    assert texts and texts[0]["encoding"]["text"]["field"] == "label"
