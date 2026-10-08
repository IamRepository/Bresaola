"""Demo data: the Palermo Spicy batch as entered so far (8 Oct 2026).

Used to fill an empty database in test mode, so the app has something to show
without the original workbook. Values match seed_from_xlsx (with corrections).
"""
from __future__ import annotations

from datetime import date

from . import db

NAME = "Palermo Spicy 2026 (demo)"
ACTUALS = {"Fennel seed, powder": (4.2, "Used less fennel than planned")}
READINGS = [(date(2026, 9, 26), 2057), (date(2026, 9, 30), 2026),
            (date(2026, 10, 4), 1990), (date(2026, 10, 8), 1963)]


def seed_demo(con) -> int:
    with con:
        pid = db.create_project(con, NAME, "Spicy Calabrian", False, 2088)
        for line in db.ingredient_lines(con, pid):
            if line["name"] in ACTUALS:
                a, note = ACTUALS[line["name"]]
                db.set_actual(con, pid, line["position"], a, note)
        db.lock_spice(con, pid)
        db.set_cure(con, pid, shape="tubular", thickness_cm=17, start=date(2026, 8, 15),
                    thickness_estimated=True, end_actual=date(2026, 9, 20),
                    method="Equilibrium dry cure, vacuum-sealed, fridge, flipped and massaged daily",
                    note="17 cm = widest side of an oval piece; cured longer than needed.")
        ch = db.get_or_create_chamber(con, "Fridge drawer", "TP-Link Tapo T315 via H100 hub")
        db.set_drying(con, pid, start=date(2026, 9, 20), start_gross_g=2100, chamber_id=ch,
                      tare_g=0, tare_estimated=True, target_loss_pct=35,
                      note="Weights include dry-curing wrap and cotton netting.")
        for d, w in READINGS:
            db.add_reading(con, pid, d, w)
    return pid
