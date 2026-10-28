"""v0.4.16 (28 Oct 2026): photos only through the journal ("Add photos"), not in the weigh-in form."""
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from bresaola import db, storage
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_weigh_in_form_has_no_photo_upload_but_journal_does(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: date(2026, 10, 11))
    con = db.connect(storage.db_path())
    seed_demo(con)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    labels = [e.label for e in at.get("file_uploader")]
    assert "Photo" not in labels                       # the weigh-in's own upload is gone
    assert "Photos" in labels                          # journal: Add photos
    assert any(e.label == "More: temperature, humidity, note" for e in at.expander)
    next(n for n in at.number_input if n.label == "Weight incl. wrap + net [g]").set_value(1950)
    next(b for b in at.button if b.label == "Save weigh-in").click()
    at.run()
    assert not at.exception, at.exception
    assert db.readings(con, 1)[-1][1] == 1950
