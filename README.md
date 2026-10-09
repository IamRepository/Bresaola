# Bresaola Tracker

Records home-cured bresaola batches from spice mix to slicing: calculated amounts, cure time, weigh-ins, chamber temperature/humidity and photos, then a PDF summary when the batch is closed.

**Status: v0.2.0 — Streamlit app with all stages, photos, backup/restore. PDF export not yet built.**

## Stages
1. **Spice mix** – meat weight, EcoCure Yes/No, blend → planned grams; actual amounts editable; *Done* locks them.
2. **Cure** – equilibrium dry cure in a vacuum bag. Days = genuineideas formula `1.25 × inches²` (flat; ÷2 tubular) + 20 %, rounded up, from the exact thickness.
3. **Dry** – wrap + net; weigh-ins are gross, packaging weight (tare) stored once; target % per project.
4. **Equalise** (backlog, hidden) – vacuum-sealed rest after the target weight. Switch on with `BRESAOLA_EQUALISE=1`.
5. **Close** – final notes → PDF → read-only.

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
- **Equalise step** – built (checks, lock, photos) but hidden. Not part of the current process (vacuum bag is used only for curing). When switched on: the piece is normally unwrapped before vacuum-sealing, so "weight after" must be compared without wrap and net.
