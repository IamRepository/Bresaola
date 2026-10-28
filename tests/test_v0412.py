"""v0.4.12 (28 Oct 2026): scale logo; switching EcoCure #2 off on Day 0 asks first. Each failed before."""
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage
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
    with con:
        pid = db.create_project(con, "Cured", "Classic Italian", True, 2000, start_date=TODAY)
    return con, pid


def day0(pid):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(s for s in at.sidebar.selectbox if s.label == "Project").set_value(pid)
    at.run()
    next(b for b in at.button if b.key == "rail_day0").click()
    at.run()
    assert not at.exception, at.exception
    return at


def switch_off(at, pid):
    next(t for t in at.toggle if t.key == f"e{pid}").set_value(False)
    at.run()
    assert not at.exception, at.exception


def test_switching_ecocure_off_asks_first(env):
    con, pid = env
    at = day0(pid)
    switch_off(at, pid)
    assert db.project(con, pid)["ecocure"] == 1                     # nothing saved yet
    assert any("Switch off EcoCure #2?" in w.value for w in at.warning)
    assert next(b for b in at.button if b.label.startswith("Done: lock day 0")).disabled


def test_keep_ecocure_changes_nothing(env):
    con, pid = env
    at = day0(pid)
    switch_off(at, pid)
    next(b for b in at.button if b.key == f"nocure_no{pid}").click()
    at.run()
    assert db.project(con, pid)["ecocure"] == 1
    assert next(t for t in at.toggle if t.key == f"e{pid}").value is True


def test_confirm_switches_ecocure_off(env):
    con, pid = env
    at = day0(pid)
    switch_off(at, pid)
    next(b for b in at.button if b.key == f"nocure_ok{pid}").click()
    at.run()
    assert db.project(con, pid)["ecocure"] == 0
    assert any("No curing salt" in i.value for i in at.info)       # the no-cure notice appears


def test_switching_ecocure_on_needs_no_question(env):
    con, pid = env
    with con:
        db.update_spice_inputs(con, pid, green_weight_g=2000, ecocure=False)
    at = day0(pid)
    next(t for t in at.toggle if t.key == f"e{pid}").set_value(True)
    at.run()
    assert db.project(con, pid)["ecocure"] == 1


def test_scale_logo(env):
    src = Path(APP).read_text()
    assert 'APP_ICON = ":material/scale:"' in src and "page_icon=APP_ICON" in src
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert at.sidebar.title[0].value == ":material/scale: Bresaola Tracker"


def test_ecocure_toggle_explains_it_is_the_creation_choice(env):
    """v0.4.13 (owner, 28 Oct): the Day 0 toggle looked like a second, separate question."""
    con, pid = env
    at = day0(pid)
    t = next(t for t in at.toggle if t.key == f"e{pid}")
    assert "Chosen when you created the project" in t.help and "switching it off asks first" in t.help
