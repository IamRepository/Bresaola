# Bresaola Tracker

Records home-cured bresaola batches from spice mix to slicing: calculated amounts, cure time, weigh-ins, chamber temperature/humidity and photos, then a PDF summary when the batch is closed.

**Status: v0.1.0 — core only (calculations, database, workbook import, tests). No screens yet.**

## Stages
1. **Spice mix** – meat weight, EcoCure Yes/No, blend → planned grams; actual amounts editable; *Done* locks them.
2. **Cure** – equilibrium dry cure in a vacuum bag. Days = genuineideas formula `1.25 × inches²` (flat; ÷2 tubular) + 20 %, rounded up, from the exact thickness.
3. **Dry** – wrap + net; weigh-ins are gross, packaging weight (tare) stored once; target % per project.
4. **Equalise** (optional) – vacuum-sealed rest after the target weight.
5. **Close** – final notes → PDF → read-only.

## Layout
```
bresaola/blends.py          master blend table (copied onto each project at creation)
bresaola/calc.py            pure calculations
bresaola/db.py              SQLite schema and storage rules
bresaola/seed_from_xlsx.py  imports the Palermo Spicy batch from workbook v5
tests/                      pins every number to the workbook and the calculator
```

## Run
```
pip install -r requirements.txt
python -m pytest
python -m bresaola.seed_from_xlsx tests/fixtures/bresaola_v5.xlsx data/bresaola.sqlite
```
`data/` holds the database and photos and is not committed.
