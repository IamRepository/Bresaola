# Working rules for this repo

## Audits (agreed with the owner, 26 Oct 2026)

**Default after every change set: diff audit.**
- Scope: `git diff <last audited commit>..HEAD` only.
- Code reading only (no browser, no click-through); the test suite still runs.
- Lighter model for the sweep; report High/Medium only, at most 10 findings.
- Re-check only the High findings before reporting; the rest stay "suspected".
- Record the audited commit below.

**Full audit (independent reviewer, runs the app in a browser) — recommend one when any of these apply:**
1. A new batch is about to start (Day 0) and the app changed since the last full audit.
2. Changes to food-safety logic (`bresaola/safety.py`, cure or target rules), calculations, or the database
   schema/migrations.
3. A new data source or deployment change (sensor import, hub sync, Docker/NAS setup).
4. A Streamlit upgrade (the version pin in `requirements.txt` is raised).
5. A bug reached real data on the NAS.
6. More than 2 months or about 10 releases since the last full audit.

When a trigger applies, say so and recommend a full audit; the owner decides.

**Last full audit:** 26 Oct 2026 on v0.4.2 (commit 9f51343): 21 findings, list in the project notes (claude.ai).
**Last diff audit:** 27 Oct 2026, e52f0b9..aa70801 (v0.4.7, NAS auto-update): no High; 4 Mediums fixed + re-checked
(one more Medium, the first-run recovery message, fixed after). Before that: 27 Oct 2026, 5cdad44..3be27ab (v0.4.6, compose image tag = version): no High/Medium.
Before that: 27 Oct 2026, c069c5e..93c6aef (v0.4.5, photo caption edit + delete): no High/Medium; one Low
(unlink error) fixed after. Before that: 26 Oct 2026, 2ede185..0a9a45f (v0.4.4, full-audit fixes 6-13 of the owner's list): no High/Medium;
one Low (leave-out caption count) fixed after. Before that: 6627330..2ede185 (v0.4.3): no High/Medium.
Note: v0.4.3 added a schema column (`project.dry_kind`) and v0.4.4 changed reading/averaging logic: full-audit
triggers 2, recommend one before the next batch. Still open from the full audit: owner's list 14-20.

## Releases to the NAS
- The NAS auto-updates nightly (04:00) from the **`stable`** branch (scripts/nas-update.sh), never from `main`.
- Move `stable` only after the diff audit passed and the owner said OK: `git push origin main:stable`.
  Say in the reply that it will be on the NAS the next morning.

## Other rules
- Every bug fix gets a test that fails before the fix.
- Real data lives on the NAS (`docker/bresaola/data`); Streamlit Cloud is test-only and loses data on reboot.
- NAS port 8520 with host networking: Synology MailPlus blocks 8500-8507 (see docs/NAS.md).
- Every version bump also changes the image tag in compose.yaml (tests/test_deploy.py enforces it):
  Container Manager's Build reuses an image whose name it already has.
