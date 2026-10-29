"""v0.4.20 (owner, 29 Oct 2026): show when readings last came from the hub; warn when the scheduled
sync seems to have stopped; clearer button and texts."""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage, tapo_sync
from bresaola.demo import seed_demo
from tests.test_sensors import FakeSensor, fake_factory

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: date(2026, 10, 18))
    monkeypatch.setenv("TAPO_USERNAME", "me@example.com")
    monkeypatch.setenv("TAPO_PASSWORD", "secret")
    monkeypatch.setenv("TAPO_HUB_IP", "192.168.1.50")
    monkeypatch.delenv("TAPO_SENSORS", raising=False)
    con = db.connect(storage.db_path())
    seed_demo(con)
    with con:
        db.set_tapo_name(con, 1, "Bresaola sensor")
    return con


def at_time(monkeypatch, t):
    monkeypatch.setattr(db, "now_local", lambda: t)


def app_text(at):
    return " ".join([c.value for c in at.caption] + [w.value for w in at.warning])


def test_sync_is_logged_and_shown(env, monkeypatch):
    at_time(monkeypatch, datetime(2026, 10, 18, 6, 0))
    tapo_sync.sync(env, fake_factory(FakeSensor()))
    ok, last_try = db.hub_sync_status(env, 1)
    assert ok == last_try and ok["stored"] == 3 and ok["at"] == "2026-10-18T06:00:00"
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    t = app_text(at)
    assert "Last loaded from the hub: 18 Oct 2026 06:00 (3 new readings, readings up to 18 Oct 00:30)" in t
    assert "hours old" not in t and "No readings from the hub yet" not in t and any(b.label == "Sync from hub now" for b in at.button)


def test_failed_sync_shown_and_last_success_kept(env, monkeypatch):
    at_time(monkeypatch, datetime(2026, 10, 18, 6, 0))
    tapo_sync.sync(env, fake_factory(FakeSensor()))
    at_time(monkeypatch, datetime(2026, 10, 18, 12, 0))
    tapo_sync.sync(env, fake_factory(FakeSensor(fail=True)))
    ok, last_try = db.hub_sync_status(env, 1)
    assert ok["at"] == "2026-10-18T06:00:00" and "hub unreachable" in last_try["error"]
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    t = app_text(at)
    assert "The last hub sync (18 Oct 12:00) failed" in t and "Last loaded from the hub: 18 Oct 2026 06:00" in t


def test_stale_sync_warns(env, monkeypatch):
    at_time(monkeypatch, datetime(2026, 10, 17, 6, 0))
    tapo_sync.sync(env, fake_factory(FakeSensor()))
    at_time(monkeypatch, datetime(2026, 10, 19, 9, 0))           # newest hub reading 18 Oct 00:30: 32 h old
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert "The newest reading from the hub is 32 hours old (18 Oct 00:30)" in app_text(at)


def test_not_yet_synced(env):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    t = app_text(at)
    assert "Not loaded from the hub yet." in t and "No readings from the hub yet" in t     # a warning, not just grey


def test_no_hub_line_without_hub_setup(env, monkeypatch):
    monkeypatch.delenv("TAPO_HUB_IP")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert "from the hub" not in app_text(at)


def test_deleting_the_chamber_removes_its_log(env):
    tapo_sync.sync(env, fake_factory(FakeSensor()))
    with env:
        db.delete_project(env, 1)
    assert env.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'hubsync%'").fetchone()[0] == 0


def test_cli_says_reading_singular(env, monkeypatch, capsys):
    monkeypatch.setattr(tapo_sync, "sync", lambda con: [tapo_sync.Result("Palermo", "s", stored=1,
                        first=datetime(2026, 10, 29, 12, 15), last=datetime(2026, 10, 29, 20))])
    tapo_sync.main()
    assert "Palermo (s): 1 new reading, 29 Oct 12:15 to 29 Oct 20:00" in capsys.readouterr().out


def test_sync_that_gets_nothing_still_warns(env, monkeypatch):
    """Diff audit v0.4.20: the hub answers but the sensor sends nothing; the page must not look healthy."""
    class Empty(FakeSensor):
        async def get_temperature_humidity_records(self):
            from types import SimpleNamespace
            return SimpleNamespace(records=[], temperature_unit="Celsius")
    at_time(monkeypatch, datetime(2026, 10, 17, 6, 0))
    tapo_sync.sync(env, fake_factory(FakeSensor()))
    at_time(monkeypatch, datetime(2026, 10, 19, 9, 0))
    tapo_sync.sync(env, fake_factory(Empty()))                    # "successful", 0 readings
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    t = app_text(at)
    assert "Last loaded from the hub: 19 Oct 2026 09:00 (0 new readings)" in t
    assert "The newest reading from the hub is 32 hours old" in t


def test_log_failure_does_not_hide_stored_readings(env, monkeypatch):
    def locked(*a, **k):
        raise db.sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(db, "log_hub_sync", locked)
    res = tapo_sync.sync(env, fake_factory(FakeSensor()))
    assert res[0].stored == 3 and res[0].error is None


def test_deleting_an_unused_chamber_removes_its_log(env):
    with env:
        ch = db.get_or_create_chamber(env, "Spare")
        db.log_hub_sync(env, ch, stored=1, error=None, last=None)
        db.delete_chamber(env, ch)
    assert not env.execute("SELECT 1 FROM meta WHERE key LIKE ?", (f"hubsync%:{ch}",)).fetchone()
