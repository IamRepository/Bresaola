# Bresaola Tracker

Records home-cured bresaola batches from spice mix to slicing: calculated amounts, cure time, weigh-ins, chamber temperature/humidity and photos, then a PDF summary when the batch is closed.

**Status: v0.4.22.** Technical documentation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (how it's built), [docs/SETUPS.md](docs/SETUPS.md) (development, test, NAS), [docs/DECISIONS.md](docs/DECISIONS.md) (why), [docs/NAS.md](docs/NAS.md) (NAS runbook).

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
- **Synology NAS (Docker):** step-by-step guide in [docs/NAS.md](docs/NAS.md); `Dockerfile` + `compose.yaml` in the repo root.
- Set `BRESAOLA_MODE=persistent` (and optionally `BRESAOLA_DATA=/path/to/data`) on the PC/NAS for real use: no banner, no demo data.
- **Download backup** / **Restore from backup** in the sidebar move everything (database + photos) as one zip.

### Streamlit Community Cloud (testing only)
Deploy this repo with main file `app.py`. Data is wiped whenever the app restarts or sleeps, so treat it as a demo and download a backup of anything worth keeping.

### Tests
```
python -m pytest
python -m bresaola.seed_from_xlsx tests/fixtures/bresaola_v5.xlsx data/bresaola.sqlite   # import the original workbook
```

## Food-safety checks (v0.4.0)
Thresholds live in `bresaola/safety.py`; the app and the PDF read them from there.
- **Where it dries:** every drying chamber is a **Fridge** (about 0–4 °C) or a **Curing chamber** (about 10–15 °C). The temperature rules follow the type; existing chambers are fridges. Change it in Dry → Chamber → Type.
- **Curing salt** is a required choice for every new project (no default); changes are logged. Without it: in a fridge, an information note (below about 3 °C botulism bacteria can't grow; keep the fridge under 4 °C), turning into a warning if the fridge was warmer than 4 °C; in a curing chamber, a warning. Same in the PDF.
- **Cure length:** green when the planned days are reached (longer is fine), amber past the calculator minimum but short of the +20 % margin, red below the minimum. Locking a cure below the minimum needs an explicit confirmation, recorded in the history and the PDF.
- **Cure fridge temperature** (optional, Cure step): warning above 4 °C.
- **Weight-loss target:** 25–50 % allowed, warning outside 30–40 %. Loss is measured on the meat at the start of drying (start weight minus packaging), which is stricter than measuring from the raw weight.
- **Drying temperature and humidity**, judged on hourly averages: fridge warning above 4 °C, curing chamber warning above 15 °C (and a "slow" note below 10 °C); humidity warnings above 90 % (mould) or below 65 % (case hardening) for both. Out-of-range averages are marked ⚠ in the weigh-in table.

## Chamber temperature and humidity (Tapo T310/T315)

**Import from the Tapo app (works everywhere, including Streamlit Cloud).**
In the Tapo app: sensor → History → View All → download icon → choose interval and range → Export.
Open the e-mail, save the file (CSV, or the Excel version), and upload it in **Dry → Chamber → Import from the Tapo app**. If the sensor was out of the chamber for a while, use **Leave out a period** before importing.
The app shows how many readings, which period and the ranges before importing. Since v0.4.17 an import only
adds times that aren't stored yet; readings already there are kept unless you tick *Replace readings that are
already there*. Importing the same period again never doubles anything.

**Straight from the hub, H100 or H200 (PC or NAS on your home network only).**
The hub keeps only the last 24 hours (15-minute averages), so schedule a sync every 6 hours (docs/NAS.md, section 6).

1. `pip install -r requirements-local.txt`
2. Set these environment variables for the app and for the scheduled task:
   - `TAPO_USERNAME` / `TAPO_PASSWORD`: your Tapo account
   - `TAPO_HUB_IP`: the hub's address (Tapo app → hub → Device info), fixed in your router
   - Each batch's sensor: set its **Tapo sensor name** in the Dry step (v0.4.17). `TAPO_SENSORS`
     (`<chamber>=<sensor nickname>`) is only for older setups.
3. Test it once: `python -m bresaola.tapo_sync`
4. Schedule the same command every 6 hours (DSM Task Scheduler on the NAS, see docs/NAS.md).

**Weigh-ins and the chamber.** Each weigh-in shows that day's average chamber temperature
and humidity (all readings on that date; * = sensor reported for less than half the day; – = none), in the
weigh-in table, on the charts (dashed line at 12:00 + dot) and in the PDF.
Each weigh-in after the first also shows the average since the previous weigh-in (12:00 to 12:00), the
conditions behind that weight loss, with *Data [%]*: the share of those hours with sensor readings.
The chamber charts can show every reading (15 min) or averages per 1, 12 or 24 hours (default 1 hour), with
a shaded band from the lowest to the highest reading in each period.
**Wrong file imported?** Dry → Chamber → *Remove readings*: pick the import, optionally a date range, confirm.

With the variables set, the Dry step also shows a **Sync from hub now** button.
Credentials stay in the environment of your own machine; they are never stored in the database or the repo.

## Backlog
- **Equalise step** – built (checks, lock, photos) but hidden. Not part of the current process (vacuum bag is used only for curing). Spec agreed 2026-10-09 for when it is switched on:
  - Remove wrap and netting, weigh the meat → **weight unwrapped [g]**
  - Vacuum-seal, weigh again → **weight in vacuum bag [g]**
  - Derived: wrap + net = last drying weigh-in − weight unwrapped (gives the real packaging weight, so the final loss % can be corrected); bag = in-bag − unwrapped
  - Open: weigh again when taken out of the bag at the end (final meat weight)?
