"""v0.4.23 (owner, 31 Oct / 1 Nov 2026): credit text, black text in light mode, dates as 14-Aug-26 after
the name, photo date editable. PDF chart and photo attachments are tested in test_report.py."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage
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


def test_credit_and_dates_in_sidebar_and_heading(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert any("Credit: Eric Pousson / 2 Guys & A Cooler" in c.value for c in at.sidebar.caption)
    radio = next(r for r in at.sidebar.radio if r.label == "Active projects")
    assert radio.options == ["Palermo Spicy (15-Aug-26)"]
    assert at.header[0].value == "Palermo Spicy (15-Aug-26)"


def test_light_theme_text_is_black():
    assert 'textColor = "#000000"' in (ROOT / ".streamlit" / "config.toml").read_text()


def test_photo_date_can_be_changed(env):
    with env:
        ph = db.add_photo(env, 1, "photos/1/x.jpg", "2026-09-20", "rub", stage="dry")
        db.set_photo_date(env, ph, date(2026, 9, 22))
    assert db.photos(env, 1)[0]["taken_at"] == "2026-09-22"
    with pytest.raises(ValueError, match="future"):
        db.set_photo_date(env, ph, TODAY + timedelta(days=1))
    with pytest.raises(ValueError, match="before the start date"):
        db.set_photo_date(env, ph, date(2026, 8, 1))


def test_photo_date_locked_when_closed(env):
    with env:
        ph = db.add_photo(env, 1, "photos/1/x.jpg", "2026-09-20", None, stage="dry")
        env.execute("UPDATE project SET status='closed' WHERE id=1")
    with pytest.raises(db.Locked):
        db.set_photo_date(env, ph, date(2026, 9, 21))


def test_photo_menu_has_date_field(env):
    with env:
        db.add_photo(env, 1, "photos/1/x.jpg", "2026-09-20", None, stage="dry")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "rail_dry").click()
    at.run()
    assert not at.exception, at.exception
    assert any(d.label == "Date taken" for d in at.date_input)


def test_test_mode_starts_from_the_snapshot(tmp_path, monkeypatch):
    """Owner, 1 Nov 2026: the test app starts from a copy of the NAS data, without photos."""
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.delenv("BRESAOLA_MODE", raising=False)
    monkeypatch.delenv("BRESAOLA_DEMO", raising=False)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    con = db.connect(storage.db_path())
    names = {r["name"] for r in db.projects(con)}
    assert {"Palermo", "Rome"} <= names
    assert con.execute("SELECT COUNT(*) FROM photo").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM chamber_reading").fetchone()[0] > 1000


def test_snapshot_has_no_photos_or_credentials():
    import sqlite3
    c = sqlite3.connect(ROOT / "bresaola" / "demo_data.sqlite")
    assert c.execute("SELECT COUNT(*) FROM photo").fetchone()[0] == 0
    dump = "\n".join(c.iterdump()).lower()
    assert "password" not in dump and "tapo_password" not in dump
