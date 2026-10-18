# Bresaola Tracker

Records home-cured bresaola batches from spice mix to slicing: calculated amounts, cure time, weigh-ins, chamber temperature/humidity and photos, then a PDF summary when the batch is closed.

**Status: v0.3.9 — journey layout, PDF batch summary, Tapo sensor import.**

## Steps (journey rail at the top; a next-action card says what to do today)
1. **Day 0: spice and bag** – meat weight, EcoCure on/off, blend → planned grams, actual amounts; measure the piece and seal the bag (cure time shown live). *Done* locks day 0 and starts the cure.
2. **Cure** – equilibrium dry cure in a vacuum bag. Days = genuineideas formula `1.25 × inches²` (flat; ÷2 tubular) + 20 %, rounded up. Enter the out-of-bag date; *Done* locks it and opens drying.
3. **Dry** – weigh-in first; weights are gross (wrap + net), tare stored once; target % per project; progress, chart, ETA. *Done* locks drying.
4. **Finish** – result summary, PDF summary download ("so far" before closing, final after), close the batch (read-only), all photos by step, history.

Rename, change the start date (day 0) or delete a project from the "Edit or delete" menu under the project list. "Dark mode" (under New project) switches light/dark; the choice is saved in the browser and the page reloads. Under each step, a status line shows DONE / NOW / NEXT; the "Weigh today" reminder appears only when the last weigh-in is 7 or more days old.

Date and lock rules (v0.3.5): no dates in the future; into the bag ≥ start date; out of the bag ≥ into the bag and ≤ drying start; drying end ≥ drying start and ≥ last weigh-in. The cure can only be locked after day 0, and steps unlock in reverse order (drying → cure → day 0). Unlocking drying clears its end date.

Every step has the same blocks: work → journal (notes + photos, allowed after locking) → Done / unlock with a reason.
Equalise (vacuum-sealed rest after drying) is in the backlog: database code and tests exist, no screen.

## Layout
```
bresaola/report.py          PDF batch summary (reportlab, bundled DejaVu fonts in bresaola/fonts)
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

## Chamber temperature and humidity (Tapo T310/T315)

**Import from the Tapo app (works everywhere, including Streamlit Cloud).**
In the Tapo app: sensor → History → View All → download icon → choose interval and range → Export.
Open the e-mail, save the file, and upload it in **Dry → Chamber → Import from the Tapo app**.
The app shows how many readings, which period and the ranges before importing. Importing an
overlapping period again replaces those readings; it never doubles them.

**Straight from the H100 hub (PC or NAS on your home network only).**
The hub keeps only the last 24 hours (15-minute averages), so schedule a sync at least once a day.

1. `pip install -r requirements-local.txt`
2. Set these environment variables for the app and for the scheduled task:
   - `TAPO_USERNAME` / `TAPO_PASSWORD`: your Tapo account
   - `TAPO_HUB_IP`: the H100's address (Tapo app → hub → Device info), best fixed in your router
   - `TAPO_SENSORS`: `Fridge drawer=<sensor nickname in the Tapo app>` (more pairs separated by `;`)
3. Test it once: `python -m bresaola.tapo_sync`
4. Schedule the same command daily (Windows Task Scheduler, or cron on the NAS, e.g. `15 6 * * *`).

With the variables set, the Dry step also shows a **Sync last 24 h from hub** button.
Credentials stay in the environment of your own machine; they are never stored in the database or the repo.

## Backlog
- **Equalise step** – built (checks, lock, photos) but hidden. Not part of the current process (vacuum bag is used only for curing). Spec agreed 2026-10-09 for when it is switched on:
  - Remove wrap and netting, weigh the meat → **weight unwrapped [g]**
  - Vacuum-seal, weigh again → **weight in vacuum bag [g]**
  - Derived: wrap + net = last drying weigh-in − weight unwrapped (gives the real packaging weight, so the final loss % can be corrected); bag = in-bag − unwrapped
  - Open: weigh again when taken out of the bag at the end (final meat weight)?
