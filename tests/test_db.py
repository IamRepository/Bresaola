"""Storage rules and the workbook import."""
from datetime import date
from pathlib import Path

import pytest

from bresaola import db
from bresaola.seed_from_xlsx import seed

XLSX = Path(__file__).parent / "fixtures" / "bresaola_v5.xlsx"


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "t.sqlite")


def test_snapshot_survives_master_table_edit(con, monkeypatch):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    from bresaola import blends
    monkeypatch.setitem(blends.BLENDS, "Spicy Calabrian", [("Only sugar", "pct", 0.5)])
    db.update_spice_inputs(con, pid, green_weight_g=1000)
    names = [l["name"] for l in db.ingredient_lines(con, pid)]
    assert "Fennel seed, powder" in names and "Only sugar" not in names


def test_weight_drives_plan_and_resets_actuals(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.set_actual(con, pid, 4, 4.2)
    db.update_spice_inputs(con, pid, green_weight_g=1000)
    fennel = db.ingredient_lines(con, pid)[4]
    assert fennel["planned"] == pytest.approx(5.0) and fennel["actual"] == pytest.approx(5.0)


def test_lock_blocks_edits_and_unlock_is_logged(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.lock_spice(con, pid)
    with pytest.raises(db.Locked):
        db.set_actual(con, pid, 0, 60)
    with pytest.raises(db.Locked):
        db.update_spice_inputs(con, pid, green_weight_g=2000)
    db.unlock_spice(con, pid, "typo in fennel")
    db.set_actual(con, pid, 0, 60)
    kinds = [r["kind"] for r in con.execute("SELECT kind FROM project_event WHERE project_id=?", (pid,))]
    assert kinds == ["created", "spice_locked", "spice_unlocked"]


def finished_project(con, name="A"):
    pid = db.create_project(con, name, "Spicy Calabrian", False, 2088)
    db.lock_spice(con, pid)
    db.set_cure(con, pid, shape="tubular", thickness_cm=10, start=date(2026, 8, 1),
                end_actual=date(2026, 8, 13))
    db.lock_cure(con, pid)
    db.set_drying(con, pid, start=date(2026, 8, 13), start_gross_g=2100)
    db.add_reading(con, pid, date(2026, 8, 20), 2050)
    db.lock_dry(con, pid, date(2026, 10, 1))
    return pid


def test_closed_project_is_read_only(con):
    pid = finished_project(con)
    db.close_project(con, pid)
    with pytest.raises(db.Locked):
        db.add_reading(con, pid, date(2026, 9, 1), 1000)


def test_target_change_logged(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100)
    db.change_target(con, pid, 38, "firmer")
    assert db.project(con, pid)["target_loss_pct"] == 38
    assert db.drying_status(con, pid)["target_gross_g"] == pytest.approx(2100 * 0.62)


def test_two_projects_share_one_chamber(con):
    ch = db.get_or_create_chamber(con, "Fridge drawer")
    assert db.get_or_create_chamber(con, "Fridge drawer") == ch
    a = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    b = db.create_project(con, "B", "Classic Italian", False, 1500)
    for p in (a, b):
        db.set_drying(con, p, start=date(2026, 9, 20), start_gross_g=2000, chamber_id=ch)
    db.add_chamber_reading(con, ch, "2026-10-08T20:00:00", 3.1, 78)
    n = con.execute("SELECT COUNT(*) FROM chamber_reading WHERE chamber_id=?", (ch,)).fetchone()[0]
    assert n == 1


@pytest.mark.skipif(not XLSX.exists(), reason="workbook fixture not present")
def test_seed_palermo_spicy(tmp_path):
    path = tmp_path / "seed.sqlite"
    pid = seed(str(XLSX), str(path))
    con = db.connect(path)
    p = db.project(con, pid)
    assert p["blend"] == "Spicy Calabrian" and p["ecocure"] == 0
    assert p["green_weight_g"] == 2088 and p["spice_locked_at"]
    lines = {l["name"]: l for l in db.ingredient_lines(con, pid)}
    assert lines["Fennel seed, powder"]["actual"] == pytest.approx(4.2)
    assert lines["Fennel seed, powder"]["note"]
    assert sum(l["actual"] for l in lines.values() if l["unit"] == "pct") == pytest.approx(120.084)
    assert p["cure_end_planned"] == "2026-09-18" and p["cure_end_actual"] == "2026-09-20"
    assert p["thickness_estimated"] == 1
    s = db.drying_status(con, pid)
    assert s["start_gross_g"] == 2100 and s["target_gross_g"] == pytest.approx(1365)
    assert s["latest_gross_g"] == 1963 and s["latest_day"] == date(2026, 10, 8)
    assert len(db.readings(con, pid)) == 5


def test_timestamps_use_local_timezone(monkeypatch):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    utc = datetime.now(timezone.utc).replace(tzinfo=None)
    local = db.now_local()
    berlin = datetime.now(ZoneInfo("Europe/Berlin")).replace(tzinfo=None)
    assert abs((local - berlin).total_seconds()) < 5
    assert db.TZ.key == "Europe/Berlin"


def test_delete_project_removes_rows_but_keeps_chamber(con):
    ch = db.get_or_create_chamber(con, "Fridge drawer")
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100, chamber_id=ch)
    db.add_photo(con, pid, "photos/1/x.jpg", "2026-10-08")
    db.add_chamber_reading(con, ch, "2026-10-08T20:00", 3.0, 80)
    assert db.delete_project(con, pid) == ["photos/1/x.jpg"]
    for t in ("project", "ingredient_line", "reading", "photo", "project_event"):
        assert con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
    assert con.execute("SELECT COUNT(*) FROM chamber_reading").fetchone()[0] == 1


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript(db.SCHEMA.replace("    start_date          TEXT,                       -- day the meat was trimmed and spiced\n", "")
                               .replace("    spice_note          TEXT,\n", "")
                               .replace("    cure_locked_at      TEXT,\n", "")
                               .replace("    dry_locked_at       TEXT,\n", ""))
    raw.execute("INSERT INTO project (name, created_at, blend, ecocure, green_weight_g, cure_end_actual) "
                "VALUES ('Old', '2026-09-01T10:00:00', 'Classic Italian', 0, 1500, '2026-09-20')")
    raw.commit(); raw.close()
    con = db.connect(path)
    p = db.project(con, 1)
    assert p["start_date"] == "2026-09-01" and p["spice_note"] is None
    assert db.display_name(p) == "26/09/01 Old"
    assert p["cure_locked_at"] == "2026-09-20T00:00:00"   # finished cure counts as locked
    assert p["dry_locked_at"] is None


def test_cure_and_dry_locks(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.set_cure(con, pid, shape="tubular", thickness_cm=10, start=date(2026, 8, 1))
    with pytest.raises(ValueError):
        db.lock_cure(con, pid)                       # needs an end date
    db.set_cure(con, pid, shape="tubular", thickness_cm=10, start=date(2026, 8, 1),
                end_actual=date(2026, 8, 13))
    db.lock_cure(con, pid)
    with pytest.raises(db.Locked):
        db.set_cure(con, pid, shape="flat", thickness_cm=10, start=date(2026, 8, 1))
    db.set_cure_note(con, pid, "still allowed")
    db.add_photo(con, pid, "photos/1/x.jpg", "2026-08-13", stage="cure")   # photos allowed too
    db.set_drying(con, pid, start=date(2026, 8, 13), start_gross_g=2100)
    db.add_reading(con, pid, date(2026, 8, 20), 2060)
    db.lock_dry(con, pid, date(2026, 10, 1))
    for f in (lambda: db.add_reading(con, pid, date(2026, 9, 2), 2000),
              lambda: db.change_target(con, pid, 30),
              lambda: db.delete_reading(con, pid, date(2026, 8, 13))):
        with pytest.raises(db.Locked):
            f()
    db.set_dry_note(con, pid, "fine")
    db.unlock_dry(con, pid, "one more weigh-in")
    db.add_reading(con, pid, date(2026, 9, 2), 2000)
    kinds = [r["kind"] for r in db.events(con, pid)]
    assert kinds[-3:] == ["cure_locked", "dry_locked", "dry_unlocked"]


def test_rename(con):
    pid = db.create_project(con, "Palermo Spicy 2026 (demo)", "Spicy Calabrian", False, 2088,
                            start_date=date(2026, 8, 15))
    db.rename_project(con, pid, "Palermo Spicy")
    assert db.display_name(db.project(con, pid)) == "26/08/15 Palermo Spicy"
    with pytest.raises(ValueError):
        db.rename_project(con, pid, "  ")


# ---------------- audit bugs ----------------

def test_duplicate_names_are_refused_politely(con):
    db.create_project(con, "Rome", "Classic Italian", False, 1326)
    b = db.create_project(con, "Palermo", "Spicy Calabrian", False, 2088)
    with pytest.raises(ValueError, match="already exists"):
        db.create_project(con, "rome", "Classic Italian", False, 1000)   # case-insensitive
    with pytest.raises(ValueError, match="already exists"):
        db.rename_project(con, b, "Rome")
    db.rename_project(con, b, "Palermo")          # renaming to its own name is fine


def test_weigh_in_checks(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100, tare_g=30)
    db.add_reading(con, pid, date(2026, 9, 26), 2057)
    with pytest.raises(ValueError, match="before drying started"):
        db.add_reading(con, pid, date(2026, 9, 1), 2000)
    with pytest.raises(ValueError, match="future"):
        db.add_reading(con, pid, date(2099, 1, 1), 2000)
    with pytest.raises(ValueError, match="packaging"):
        db.add_reading(con, pid, date(2026, 9, 30), 25)
    with pytest.raises(ValueError, match="Typo"):             # 196 instead of 1960
        db.add_reading(con, pid, date(2026, 9, 30), 196)
    with pytest.raises(ValueError, match="more than the start"):
        db.add_reading(con, pid, date(2026, 9, 30), 2300)
    db.add_reading(con, pid, date(2026, 9, 30), 2300, confirmed=True)   # user insists
    assert db.readings(con, pid)[-1][1] == 2300


def test_same_date_weigh_in_needs_confirm(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100)
    db.add_reading(con, pid, date(2026, 9, 26), 2057)
    with pytest.raises(ValueError, match="already a weigh-in"):
        db.add_reading(con, pid, date(2026, 9, 26), 2050)
    db.add_reading(con, pid, date(2026, 9, 26), 2050, confirmed=True)
    assert db.readings(con, pid)[-1] == (date(2026, 9, 26), 2050)


def test_cure_end_before_start_refused(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    with pytest.raises(ValueError, match="cannot be before"):
        db.set_cure(con, pid, shape="tubular", thickness_cm=10, start=date(2026, 8, 15),
                    end_actual=date(2026, 8, 1))


def test_close_needs_all_steps_locked(con):
    pid = db.create_project(con, "A", "Spicy Calabrian", False, 2088)
    with pytest.raises(ValueError, match="lock the spice mix; lock the cure; lock drying"):
        db.close_project(con, pid)
    done = finished_project(con, "B")
    db.set_equalise(con, done, start=date(2026, 10, 1))
    with pytest.raises(ValueError, match="finish equalising"):
        db.close_project(con, done)
    db.set_equalise(con, done, start=date(2026, 10, 1), end=date(2026, 10, 20))
    db.close_project(con, done)
    assert db.project(con, done)["status"] == "closed"
