"""Demo data: the Palermo Spicy batch as entered so far (8 Oct 2026).

Used to fill an empty database in test mode, so the app has something to show
without the original workbook. Values match seed_from_xlsx (with corrections).
"""
from __future__ import annotations

from datetime import date

from . import db

NAME = "Palermo Spicy"
ACTUALS = {"Fennel seed, powder": (4.2, "Used less fennel than planned")}
READINGS = [(date(2026, 9, 26), 2057), (date(2026, 9, 30), 2026),
            (date(2026, 10, 4), 1990), (date(2026, 10, 8), 1963)]


def seed_demo(con) -> int:
    with con:
        pid = db.create_project(con, NAME, "Spicy Calabrian", False, 2088, start_date=date(2026, 8, 15))
        for line in db.ingredient_lines(con, pid):
            if line["name"] in ACTUALS:
                a, note = ACTUALS[line["name"]]
                db.set_actual(con, pid, line["position"], a, note)
        db.lock_spice(con, pid)
        db.set_cure(con, pid, shape="tubular", thickness_cm=17, start=date(2026, 8, 15),
                    thickness_estimated=True, end_actual=date(2026, 9, 20),
                    note="Equilibrium dry cure, vacuum-sealed, fridge, flipped and massaged daily.\n"
                         "17 cm = widest side of an oval piece; cured longer than needed.")
        db.lock_cure(con, pid)
        ch = db.get_or_create_chamber(con, "Fridge drawer", "TP-Link Tapo T315 via H100 hub")
        db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100, chamber_id=ch,
                      tare_g=0, tare_estimated=True, target_loss_pct=35,
                      note="Weights include dry-curing wrap and cotton netting.")
        for d, w in READINGS:
            db.add_reading(con, pid, d, w)
    return pid


def seed_demo_readings(con, pid: int | None = None) -> int:
    """Made-up sensor readings for the demo batch (test mode only, owner 29 Oct 2026): every 15 minutes
    from the start of drying for 18 days, a daily swing, a warm door-open hour and a left-out period, so
    the sensor chart and its zoom can be tried on Streamlit Cloud. Never used on the NAS."""
    import math
    from datetime import datetime, timedelta

    from . import sensors
    pid = pid or con.execute("SELECT id FROM project ORDER BY id LIMIT 1").fetchone()[0]
    ch = db.project(con, pid)["chamber_id"]
    t0 = datetime(2026, 9, 20, 12)
    rows = []
    for i in range(4 * 24 * 18):
        t = t0 + timedelta(minutes=15 * i)
        day = 2 * math.pi * (t.hour * 60 + t.minute) / 1440
        temp = 2.2 + 0.5 * math.sin(day) + 0.15 * math.sin(i / 7.0)
        rh = 82 - 3 * math.sin(day) + 1.5 * math.sin(i / 50.0)
        if datetime(2026, 9, 28, 18) <= t < datetime(2026, 9, 28, 19):    # door open: warm and dry
            temp, rh = temp + 2.5, rh - 9
        if not (datetime(2026, 10, 3, 12) <= t < datetime(2026, 10, 4, 9)):   # sensor out of the fridge
            rows.append((t, round(temp, 2), round(rh, 1)))
    with con:
        sensors.import_readings(con, ch, rows, "tapo_export")
        db.add_exclusion(con, ch, datetime(2026, 10, 3, 12), datetime(2026, 10, 4, 9))
    return len(rows)
