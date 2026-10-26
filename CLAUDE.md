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
**Last diff audit:** 26 Oct 2026, 6627330..2ede185 (v0.4.3, full-audit fixes 1-5): no High/Medium findings, 170 tests pass.
Note: v0.4.3 adds a schema column (`project.dry_kind`), which is full-audit trigger 2: recommend one before the next batch.

## Other rules
- Every bug fix gets a test that fails before the fix.
- Real data lives on the NAS (`docker/bresaola/data`); Streamlit Cloud is test-only and loses data on reboot.
- NAS port 8520 with host networking: Synology MailPlus blocks 8500-8507 (see docs/NAS.md).
