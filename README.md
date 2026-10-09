# Bresaola Tracker

Records home-cured bresaola batches from spice mix to slicing: calculated amounts, cure time, weigh-ins, chamber temperature/humidity and photos, then a PDF summary when the batch is closed.

**Status: v0.3.3 — journey layout: one screen per step, Done locks the step and jumps to the next. PDF export not yet built.**

## Steps (journey rail at the top; a next-action card says what to do today)
1. **Day 0: spice and bag** – meat weight, EcoCure on/off, blend → planned grams, actual amounts; measure the piece and seal the bag (cure time shown live). *Done* locks day 0 and starts the cure.
2. **Cure** – equilibrium dry cure in a vacuum bag. Days = genuineideas formula `1.25 × inches²` (flat; ÷2 tubular) + 20 %, rounded up. Enter the out-of-bag date; *Done* locks it and opens drying.
3. **Dry** – weigh-in first; weights are gross (wrap + net), tare stored once; target % per project; progress, chart, ETA. *Done* locks drying.
4. **Finish** – result summary, close the batch (read-only; PDF later), all photos by step, history.

Rename or delete a project from the "Rename or delete" menu under the project list. "Dark mode" (under New project) switches light/dark; the choice is saved in the browser and the page reloads. Under each step, a status line shows DONE / NOW / NEXT; the "Weigh today" reminder appears only when the last weigh-in is 7 or more days old.

Every step has the same blocks: work → journal (notes + photos, allowed after locking) → Done / unlock with a reason.
Equalise (vacuum-sealed rest after drying) is in the backlog: database code and tests exist, no screen.

## Layout
```
bresaola/blends.py          master blend table (copied onto each project at creation)
bresaola/calc.py            pure calculations
bresaola/db.py              SQLite schema and storage rules
bresaola/seed_from_xlsx.py  imports the Palermo Spicy batch from workbook v5
bresaola/demo.py            demo data used in test mode
bresaola/storage.py         data folder, photos, backup/restore
app.py                      Streamlit UI
tests/                      pins every number to the workbook and the calculator
```

## Run on your PC
```
pip install -r requirements.txt
streamlit run app.py
```
Opens at http://localhost:8501. Data and photos go to `data/` (not committed).

### Test mode vs persistent
- Default is **test mode**: a banner on every screen, and an empty database is filled with a demo copy of Palermo Spicy.
- Set `BRESAOLA_MODE=persistent` (and optionally `BRESAOLA_DATA=/path/to/data`) on the PC/NAS for real use: no banner, no demo data.
- **Download backup** / **Restore from backup** in the sidebar move everything (database + photos) as one zip.

### Streamlit Community Cloud (testing only)
Deploy this repo with main file `app.py`. Data is wiped whenever the app restarts or sleeps, so treat it as a demo and download a backup of anything worth keeping.

### Tests
```
python -m pytest
python -m bresaola.seed_from_xlsx tests/fixtures/bresaola_v5.xlsx data/bresaola.sqlite   # import the original workbook
```

## Backlog
- **Equalise step** – built (checks, lock, photos) but hidden. Not part of the current process (vacuum bag is used only for curing). Spec agreed 2026-10-09 for when it is switched on:
  - Remove wrap and netting, weigh the meat → **weight unwrapped [g]**
  - Vacuum-seal, weigh again → **weight in vacuum bag [g]**
  - Derived: wrap + net = last drying weigh-in − weight unwrapped (gives the real packaging weight, so the final loss % can be corrected); bag = in-bag − unwrapped
  - Open: weigh again when taken out of the bag at the end (final meat weight)?
