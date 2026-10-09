"""SQLite storage. One file for data; photos live in a folder next to it.

Design rules (confirmed 2026-10-08):
- Blend rates are copied onto the project at creation (snapshot).
- The spice mix is locked by "Done"; Unlock is explicit and logged.
- Temperature/RH readings belong to a chamber; projects link to a chamber.
- Weigh-ins are gross weights (wrap + net); tare is stored on the project.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import calc

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chamber (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    sensor      TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS chamber_reading (
    id          INTEGER PRIMARY KEY,
    chamber_id  INTEGER NOT NULL REFERENCES chamber(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL,              -- ISO datetime
    temp_c      REAL,
    rh_pct      REAL,
    source      TEXT NOT NULL DEFAULT 'manual',  -- manual | tapo_export | tapo_api
    UNIQUE (chamber_id, ts, source)
);

CREATE TABLE IF NOT EXISTS project (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
    created_at          TEXT NOT NULL,
    start_date          TEXT,                       -- day the meat was trimmed and spiced
    closed_at           TEXT,
    -- stage 1: spice mix
    blend               TEXT NOT NULL,
    ecocure             INTEGER NOT NULL,           -- 0/1
    green_weight_g      REAL NOT NULL,
    spice_locked_at     TEXT,
    spice_note          TEXT,
    -- stage 2: cure
    shape               TEXT CHECK (shape IN ('flat','tubular')),
    thickness_cm        REAL,
    length_cm           REAL,
    thickness_estimated INTEGER NOT NULL DEFAULT 0,
    cure_method         TEXT,
    cure_start          TEXT,
    cure_end_planned    TEXT,
    cure_end_actual     TEXT,
    cure_note           TEXT,
    -- stage 3: dry
    chamber_id          INTEGER REFERENCES chamber(id),
    dry_start           TEXT,
    dry_start_gross_g   REAL,
    tare_g              REAL NOT NULL DEFAULT 0,
    tare_estimated      INTEGER NOT NULL DEFAULT 1,
    target_loss_pct     REAL NOT NULL DEFAULT 35,
    dry_end             TEXT,
    dry_note            TEXT,
    -- stage 4: equalise (optional)
    equalise_start      TEXT,
    equalise_end        TEXT,
    equalise_end_gross_g REAL,
    equalise_note       TEXT,
    -- close
    final_notes         TEXT
);

CREATE TABLE IF NOT EXISTS ingredient_line (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    name        TEXT NOT NULL,
    unit        TEXT NOT NULL CHECK (unit IN ('pct','per_kg')),
    rate        REAL NOT NULL,
    planned     REAL NOT NULL,
    actual      REAL,
    note        TEXT,
    UNIQUE (project_id, position)
);

CREATE TABLE IF NOT EXISTS reading (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,              -- ISO date
    gross_g     REAL NOT NULL,
    note        TEXT,
    UNIQUE (project_id, day)
);

CREATE TABLE IF NOT EXISTS photo (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    reading_id  INTEGER REFERENCES reading(id) ON DELETE SET NULL,
    taken_at    TEXT NOT NULL,
    path        TEXT NOT NULL,              -- relative to the photo folder
    caption     TEXT,
    stage       TEXT                        -- spice | cure | dry | equalise; NULL = other
);

CREATE TABLE IF NOT EXISTS project_event (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,              -- spice_locked, spice_unlocked, target_changed, ...
    detail      TEXT
);
"""


class Locked(Exception):
    """Raised when editing something that has been locked or closed."""


TZ = ZoneInfo(os.environ.get("BRESAOLA_TZ", "Europe/Berlin"))


def now_local() -> datetime:
    """Wall-clock time where the meat is, not where the server is (Streamlit Cloud runs on UTC)."""
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return now_local().date()


def _now() -> str:
    return now_local().isoformat(timespec="seconds")


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, (date, datetime)) else d


# columns added after v0.2.0; older databases (and backups) get them on open
MIGRATIONS = {"project": [("start_date", "TEXT"), ("spice_note", "TEXT")],
              "photo": [("stage", "TEXT")]}


def connect(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.execute("UPDATE project SET start_date = substr(created_at, 1, 10) WHERE start_date IS NULL")
    con.commit()
    return con


def log(con, project_id: int, kind: str, detail: str = "") -> None:
    con.execute("INSERT INTO project_event (project_id, ts, kind, detail) VALUES (?,?,?,?)",
                (project_id, _now(), kind, detail))


# ----------------------------- chamber ------------------------------------- #

def get_or_create_chamber(con, name: str, sensor: str | None = None) -> int:
    row = con.execute("SELECT id FROM chamber WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    return con.execute("INSERT INTO chamber (name, sensor) VALUES (?,?)", (name, sensor)).lastrowid


def add_chamber_reading(con, chamber_id: int, ts, temp_c=None, rh_pct=None, source="manual"):
    con.execute("""INSERT OR REPLACE INTO chamber_reading (chamber_id, ts, temp_c, rh_pct, source)
                   VALUES (?,?,?,?,?)""", (chamber_id, _iso(ts), temp_c, rh_pct, source))


# ----------------------------- project ------------------------------------- #

def project(con, project_id: int) -> sqlite3.Row:
    row = con.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise KeyError(project_id)
    return row


def _require_open(con, project_id: int):
    if project(con, project_id)["status"] == "closed":
        raise Locked("Project is closed")


def create_project(con, name: str, blend: str, ecocure: bool, green_weight_g: float,
                   start_date=None) -> int:
    """New project with a snapshot of the blend's rates and planned amounts."""
    rates = calc.blend_rates(blend)
    pid = con.execute("""INSERT INTO project (name, created_at, start_date, blend, ecocure, green_weight_g)
                         VALUES (?,?,?,?,?,?)""",
                      (name, _now(), _iso(start_date or today()), blend, int(ecocure),
                       green_weight_g)).lastrowid
    _write_plan(con, pid, green_weight_g, ecocure, rates)
    log(con, pid, "created", f"{blend}, {green_weight_g} g, EcoCure {'yes' if ecocure else 'no'}")
    return pid


def _stored_rates(con, pid) -> list[tuple[str, str, float]]:
    rows = con.execute("""SELECT name, unit, rate FROM ingredient_line
                          WHERE project_id=? ORDER BY position""", (pid,)).fetchall()
    # EcoCure and salt are derived, not part of the blend snapshot
    return [(r["name"], r["unit"], r["rate"]) for r in rows
            if r["name"] != "EcoCure #2" and not r["name"].startswith("Kosher salt")]


def _write_plan(con, pid, weight, ecocure, rates):
    """(Re)write planned amounts; actuals reset to the plan."""
    con.execute("DELETE FROM ingredient_line WHERE project_id=?", (pid,))
    for i, l in enumerate(calc.spice_plan(weight, ecocure, rates)):
        con.execute("""INSERT INTO ingredient_line (project_id, position, name, unit, rate, planned, actual)
                       VALUES (?,?,?,?,?,?,?)""", (pid, i, l.name, l.unit, l.rate, l.planned, l.planned))


def update_spice_inputs(con, pid: int, green_weight_g: float | None = None,
                        ecocure: bool | None = None) -> None:
    """Change weight or EcoCure before the mix is locked. Recalculates the plan."""
    p = project(con, pid)
    if p["spice_locked_at"]:
        raise Locked("Spice mix is locked; unlock it first")
    w = p["green_weight_g"] if green_weight_g is None else green_weight_g
    e = bool(p["ecocure"]) if ecocure is None else ecocure
    rates = _stored_rates(con, pid)
    con.execute("UPDATE project SET green_weight_g=?, ecocure=? WHERE id=?", (w, int(e), pid))
    _write_plan(con, pid, w, e, rates)


def set_actual(con, pid: int, position: int, actual: float | None, note: str | None = None) -> None:
    if project(con, pid)["spice_locked_at"]:
        raise Locked("Spice mix is locked; unlock it first")
    con.execute("""UPDATE ingredient_line SET actual=?, note=COALESCE(?, note)
                   WHERE project_id=? AND position=?""", (actual, note, pid, position))


def set_spice_note(con, pid: int, note: str | None) -> None:
    if project(con, pid)["spice_locked_at"]:
        raise Locked("Spice mix is locked; unlock it first")
    con.execute("UPDATE project SET spice_note=? WHERE id=?", (note or None, pid))


def display_name(p) -> str:
    """'26/08/15 Palermo Spicy' – start date as YY/MM/DD, then the name."""
    d = p["start_date"] or p["created_at"][:10]
    return f"{date.fromisoformat(d):%y/%m/%d} {p['name']}"


def lock_spice(con, pid: int) -> None:
    con.execute("UPDATE project SET spice_locked_at=? WHERE id=?", (_now(), pid))
    log(con, pid, "spice_locked")


def unlock_spice(con, pid: int, reason: str) -> None:
    _require_open(con, pid)
    con.execute("UPDATE project SET spice_locked_at=NULL WHERE id=?", (pid,))
    log(con, pid, "spice_unlocked", reason)


def ingredient_lines(con, pid: int) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM ingredient_line WHERE project_id=? ORDER BY position",
                       (pid,)).fetchall()


def set_cure(con, pid: int, *, shape: str, thickness_cm: float, start, length_cm=None,
             thickness_estimated=False, method=None, end_actual=None, note=None) -> None:
    _require_open(con, pid)
    planned = calc.cure_end_date(date.fromisoformat(_iso(start)), thickness_cm, shape)
    con.execute("""UPDATE project SET shape=?, thickness_cm=?, length_cm=?, thickness_estimated=?,
                   cure_method=?, cure_start=?, cure_end_planned=?, cure_end_actual=?, cure_note=?
                   WHERE id=?""",
                (shape, thickness_cm, length_cm, int(thickness_estimated), method,
                 _iso(start), planned.isoformat(), _iso(end_actual), note, pid))


def set_drying(con, pid: int, *, start, start_gross_g: float, chamber_id: int | None = None,
               tare_g: float = 0.0, tare_estimated: bool = True,
               target_loss_pct: float = 35.0, note=None) -> None:
    _require_open(con, pid)
    con.execute("""UPDATE project SET dry_start=?, dry_start_gross_g=?, chamber_id=?, tare_g=?,
                   tare_estimated=?, target_loss_pct=?, dry_note=? WHERE id=?""",
                (_iso(start), start_gross_g, chamber_id, tare_g, int(tare_estimated),
                 target_loss_pct, note, pid))
    con.execute("INSERT OR REPLACE INTO reading (project_id, day, gross_g, note) VALUES (?,?,?,?)",
                (pid, _iso(start), start_gross_g, "Start of drying"))


def change_target(con, pid: int, new_pct: float, reason: str = "") -> None:
    _require_open(con, pid)
    old = project(con, pid)["target_loss_pct"]
    con.execute("UPDATE project SET target_loss_pct=? WHERE id=?", (new_pct, pid))
    log(con, pid, "target_changed", f"{old} % -> {new_pct} % {reason}".strip())


def add_reading(con, pid: int, day, gross_g: float, note: str | None = None) -> int:
    _require_open(con, pid)
    return con.execute("""INSERT INTO reading (project_id, day, gross_g, note) VALUES (?,?,?,?)
                          ON CONFLICT(project_id, day) DO UPDATE SET gross_g=excluded.gross_g,
                          note=excluded.note""", (pid, _iso(day), gross_g, note)).lastrowid


def readings(con, pid: int) -> list[tuple[date, float]]:
    rows = con.execute("SELECT day, gross_g FROM reading WHERE project_id=? ORDER BY day",
                       (pid,)).fetchall()
    return [(date.fromisoformat(r["day"]), r["gross_g"]) for r in rows]


def change_blend(con, pid: int, blend: str) -> None:
    """Pick a different blend before the mix is locked: new snapshot, plan rewritten."""
    p = project(con, pid)
    if p["spice_locked_at"]:
        raise Locked("Spice mix is locked; unlock it first")
    con.execute("UPDATE project SET blend=? WHERE id=?", (blend, pid))
    _write_plan(con, pid, p["green_weight_g"], bool(p["ecocure"]), calc.blend_rates(blend))
    log(con, pid, "blend_changed", blend)


def set_equalise(con, pid: int, *, start=None, end=None, end_gross_g=None, note=None) -> None:
    _require_open(con, pid)
    con.execute("""UPDATE project SET equalise_start=?, equalise_end=?, equalise_end_gross_g=?,
                   equalise_note=? WHERE id=?""", (_iso(start), _iso(end), end_gross_g, note, pid))


def end_drying(con, pid: int, day) -> None:
    _require_open(con, pid)
    con.execute("UPDATE project SET dry_end=? WHERE id=?", (_iso(day), pid))


def delete_reading(con, pid: int, day) -> None:
    _require_open(con, pid)
    con.execute("DELETE FROM reading WHERE project_id=? AND day=?", (pid, _iso(day)))


def reading_rows(con, pid: int) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM reading WHERE project_id=? ORDER BY day", (pid,)).fetchall()


STAGES = ("spice", "cure", "dry", "equalise")


def add_photo(con, pid: int, path: str, taken_at, caption: str | None = None,
              reading_id: int | None = None, stage: str | None = None) -> int:
    _require_open(con, pid)
    if stage is not None and stage not in STAGES:
        raise ValueError(f"Unknown stage {stage!r}")
    return con.execute("""INSERT INTO photo (project_id, reading_id, taken_at, path, caption, stage)
                          VALUES (?,?,?,?,?,?)""",
                       (pid, reading_id, _iso(taken_at), path, caption, stage)).lastrowid


def photos(con, pid: int, stage: str | None = None) -> list[sqlite3.Row]:
    """All photos of a project, or only those belonging to one stage."""
    if stage is None:
        return con.execute("SELECT * FROM photo WHERE project_id=? ORDER BY taken_at, id",
                           (pid,)).fetchall()
    return con.execute("SELECT * FROM photo WHERE project_id=? AND stage=? ORDER BY taken_at, id",
                       (pid, stage)).fetchall()


def chambers(con) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM chamber ORDER BY name").fetchall()


def chamber_readings(con, chamber_id: int, start=None, end=None) -> list[sqlite3.Row]:
    q, args = "SELECT * FROM chamber_reading WHERE chamber_id=?", [chamber_id]
    if start:
        q += " AND ts >= ?"; args.append(_iso(start))
    if end:
        q += " AND ts <= ?"; args.append(_iso(end) + "T23:59:59")
    return con.execute(q + " ORDER BY ts", args).fetchall()


def projects(con) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM project ORDER BY status, start_date DESC, id DESC").fetchall()


def events(con, pid: int) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM project_event WHERE project_id=? ORDER BY id", (pid,)).fetchall()


def delete_project(con, pid: int) -> list[str]:
    """Delete a project and all its rows. Returns photo paths so the caller can remove files.
    Chambers and their readings are shared and stay."""
    paths = [r["path"] for r in photos(con, pid)]
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("DELETE FROM project WHERE id=?", (pid,))
    return paths


def close_project(con, pid: int, final_notes: str = "") -> None:
    con.execute("UPDATE project SET status='closed', closed_at=?, final_notes=? WHERE id=?",
                (_now(), final_notes, pid))
    log(con, pid, "closed")


def drying_status(con, pid: int) -> dict:
    """Everything the drying screen needs, in one place."""
    p = project(con, pid)
    rs = readings(con, pid)
    start, tare, pct = p["dry_start_gross_g"], p["tare_g"], p["target_loss_pct"]
    latest_day, latest = rs[-1]
    return {
        "start_gross_g": start,
        "target_gross_g": calc.target_gross_weight(start, pct, tare),
        "latest_day": latest_day,
        "latest_gross_g": latest,
        "loss_pct": calc.loss_pct(start, latest, tare),
        "progress": calc.progress_to_target(start, latest, pct, tare),
        "eta": calc.drying_eta(rs, start, pct, tare),
    }
