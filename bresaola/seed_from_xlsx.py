"""Import the 'Palermo Spicy' batch from the original workbook (v5).

Usage:  python -m bresaola.seed_from_xlsx <workbook.xlsx> <database.sqlite>

Corrections confirmed with the user on 2026-10-08 are applied here, not in
the workbook:
- Drying start weight is 2100 g (2102 in the sheet was a typo).
- No EcoCure was used.
- 17 cm was the widest side of an oval piece -> thickness marked estimated.
- Cure ended (meat unbagged) on the drying start date, 20 Sep; 18 Sep was planned.
- The fennel note sat on the salt row; it belongs to fennel.
- Packaging (wrap + net) weight unknown -> tare 0, marked estimated.
"""
from __future__ import annotations

import sys
from datetime import date, datetime

import openpyxl

from . import db

PROJECT_NAME = "Palermo Spicy 2026"
SHEET_SPICE, SHEET_CURE, SHEET_DRY = "1. Spice mix", "2. Brining time", "3. Drying weight"
CALABRIAN_ROWS = range(19, 29)          # salt .. bay leaf (EcoCure row 18 is NIL)
CORRECT_DRY_START_G = 2100.0


def _d(v) -> date:
    return v.date() if isinstance(v, datetime) else v


def seed(xlsx_path: str, db_path: str) -> int:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    sp, cu, dr = wb[SHEET_SPICE], wb[SHEET_CURE], wb[SHEET_DRY]

    con = db.connect(db_path)
    with con:
        weight = float(sp["C2"].value)
        ecocure = str(sp["C3"].value).strip().lower() == "yes"
        pid = db.create_project(con, PROJECT_NAME, "Spicy Calabrian", ecocure, weight,
                                start_date=_d(cu["C2"].value))

        # actual amounts and notes
        for pos, row in enumerate(CALABRIAN_ROWS):
            actual = sp[f"E{row}"].value
            if isinstance(actual, (int, float)):
                db.set_actual(con, pid, pos, round(float(actual), 3))
        fennel = next(l for l in db.ingredient_lines(con, pid) if l["name"].startswith("Fennel"))
        db.set_actual(con, pid, fennel["position"], fennel["actual"],
                      note="Used less fennel than planned (sheet note: '50 % fennel seed powder')")
        db.lock_spice(con, pid)

        # cure
        dry_start = _d(dr["C2"].value)
        db.set_cure(con, pid, shape=str(cu["C3"].value).lower(), thickness_cm=float(cu["C4"].value),
                    start=_d(cu["C2"].value), thickness_estimated=True,
                    method="Equilibrium dry cure, vacuum-sealed, fridge, flipped and massaged daily",
                    end_actual=dry_start,
                    note="17 cm = widest side of an oval piece; cured longer than needed. "
                         "Unbagged 2 days after plan (travelling).")

        # drying
        chamber = db.get_or_create_chamber(con, "Fridge drawer", "TP-Link Tapo T315 via H100 hub")
        db.set_drying(con, pid, start=dry_start, start_gross_g=CORRECT_DRY_START_G,
                      chamber_id=chamber, tare_g=0.0, tare_estimated=True,
                      target_loss_pct=float(dr["C4"].value),
                      note="Weights include dry-curing wrap and cotton netting; packaging weight not "
                           "measured.")
        for r in range(9, 30):
            day, w = dr[f"B{r}"].value, dr[f"C{r}"].value
            if day and isinstance(w, (int, float)):
                db.add_reading(con, pid, _d(day), float(w))
    return pid


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print("Created project id", seed(sys.argv[1], sys.argv[2]))
