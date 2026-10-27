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

**Last full audit:** 27 Oct 2026 on v0.4.8 (commit b00fd60): 10 findings (2 High), 1-8 + 10 fixed in v0.4.9, 9 accepted
(DST hour split across two hub syncs). Cost: 254k tokens, about 2 % of the owner's usage. Before that: 26 Oct 2026 on v0.4.2.
**Last diff audit:** 27 Oct 2026, 6de43a5..77beff4 (v0.4.11, backlog: recent-pace finish, left-aligned table, small fixes): no High/Medium (86k tokens).
Before that: 27 Oct 2026, df1cad4..1adcdd3 (v0.4.10, chart time axes): no High/Medium (75k tokens).
Before that: 27 Oct 2026, b00fd60..b8b35d3 (v0.4.9, full-audit fixes): no High/Medium (107k tokens).
Before that: 27 Oct 2026, aa70801..712636b (v0.4.8, full-audit items 14-19 + script follow-up): no High;
3 Mediums (hub sync with 2 sensors on a fresh DB, unescaped names in errors, old docker-compose without
--quiet) + 1 Low fixed after, with tests. Still open from the full audit: none (owner's 21 = audit #4 old-DB
migration, doesn't affect the NAS data). Before that: 27 Oct 2026, e52f0b9..aa70801 (v0.4.7, NAS auto-update): no High; 4 Mediums fixed + re-checked
(one more Medium, the first-run recovery message, fixed after). Before that: 27 Oct 2026, 5cdad44..3be27ab (v0.4.6, compose image tag = version): no High/Medium.
Before that: 27 Oct 2026, c069c5e..93c6aef (v0.4.5, photo caption edit + delete): no High/Medium; one Low
(unlink error) fixed after. Before that: 26 Oct 2026, 2ede185..0a9a45f (v0.4.4, full-audit fixes 6-13 of the owner's list): no High/Medium;
one Low (leave-out caption count) fixed after. Before that: 6627330..2ede185 (v0.4.3): no High/Medium.
Note: v0.4.9 adds table `chamber_exclusion` (left-out periods); reviewed by the diff audit only.

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
