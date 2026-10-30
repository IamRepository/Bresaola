# Bresaola Tracker: design decisions

Status: **draft 1, 30 Oct 2026** (v0.4.22). Each entry records a decision that shapes the system: the
situation, what was decided and why, the alternatives turned down, and what follows from it. Dates are when
the decision was made or confirmed; sources are the git history, `CLAUDE.md` and the project notes.

Alternatives are the ones discussed at the time; those marked *(in hindsight)* weren't discussed then and
are listed to make the trade-off visible.

A decision that is reversed stays here, marked *superseded*, with a link to the one that replaces it.
New entries go at the end with the next number.

| # | Date | Decision | Status |
|---|---|---|---|
| D-01 | 2026-10-08 | One SQLite file and a photo folder; single user, no login | active |
| D-02 | 2026-10-08 | Blend rates are copied onto each batch | active |
| D-03 | 2026-10-08 | Cure time = calculator minimum + 20 %, rounded up | active |
| D-04 | 2026-10-08 | Weight loss on the meat from the start of drying | active |
| D-05 | 2026-10-09 | Stages lock; unlocking is explicit, logged and in reverse order | active |
| D-06 | 2026-10-26 | Food-safety limits in one module; the drying place selects them | active |
| D-07 | 2026-10-26 | Diff audit after every change set, full audit on triggers | active |
| D-08 | 2026-10-26 | NAS: Docker host networking on port 8520 | active |
| D-09 | 2026-10-27 | Image tag = app version | active |
| D-10 | 2026-10-27 | NAS updates itself from `stable`, with health check and rollback | active |
| D-11 | 2026-10-28 | One sensor table per batch | active |
| D-12 | 2026-10-28 | Sensor readings are only added, never silently replaced | active |
| D-13 | 2026-10-28 | Widget keys carry the database value (stale tabs) | active |
| D-14 | 2026-10-29 | Hub connection through discovery; never a second login | active |
| D-15 | 2026-10-29 | Hub sync every 6 hours; warn on the age of the newest reading | active |
| D-16 | 2026-10-29 | One sensor chart with two y-axes and a period slider | active (supersedes the v0.4.21 zoom strip) |
| D-17 | 2026-10-30 | Documentation lives in the repo and changes with the code | active |

---

### D-01: One SQLite file and a photo folder; single user, no login

- **Situation.** The record started as one Excel workbook per piece of meat, with every value carried between
  sheets by hand. The app runs for one person, at home, on a NAS.
- **Decision.** One SQLite file (`bresaola.sqlite`) plus a `photos/` folder, both in one data folder
  (`BRESAOLA_DATA`). Streamlit for the UI. No user accounts; access is limited to the home network and the
  VPN. A *test mode* (anything but `BRESAOLA_MODE=persistent`) shows a banner and seeds demo data, so a
  public demo can never be mistaken for the real record.
- **Why.** No database server to run, back up or upgrade; backup is copying one folder (or the in-app zip).
  Streamlit gives a phone-friendly UI with little code.
- **Alternatives.** Keeping the spreadsheet (no checks, no history). *(In hindsight:)* PostgreSQL (one more
  service for one user); a desktop app (no phone access).
- **Consequences.** Two processes (app and hub sync) share one file: writes must stay short (ARCHITECTURE
  5.4). No access control inside the app.
- **Where.** `bresaola/db.py`, `bresaola/storage.py`.

### D-02: Blend rates are copied onto each batch

- **Decision.** When a batch is created, its blend's rates are copied into `ingredient_line`. The blend table
  in `blends.py` is only read at creation.
- **Why.** Editing a recipe later must not change the record of a batch already made (confirmed 2026-10-08).
- **Alternatives.** *(In hindsight:)* referencing the blend by name and computing on the fly (history would
  change with the recipe).
- **Consequences.** A blend renamed or removed in code still shows correctly on old batches, as "(saved
  recipe)". Editing blends in the app is in the backlog and won't need a migration.

### D-03: Cure time = calculator minimum + 20 %, rounded up

- **Situation.** The owner cures in a vacuum bag with salt and spices dosed by weight (equilibrium dry
  cure). The genuineideas.com equilibrium-brine calculator gives a minimum for wet brine; its own page
  advises adding 20 % to reach the centre.
- **Decision.** `t_plan = ⌈1.2 · 1.25 · (d/2.54)²⌉` days, halved before the margin for a tubular piece
  (ARCHITECTURE 6.2). The formula was checked against the calculator in a browser on 2026-10-08 for 5 to
  20 cm; it matches the workbook.
- **Why.** In an equilibrium cure the meat can't get saltier than the dose, so erring long costs nothing,
  while too short leaves the centre unsalted.
- **Consequences.** Locking a cure below the calculator minimum needs a confirmation and is logged (D-06).

### D-04: Weight loss on the meat from the start of drying

- **Decision.** Loss = (G₀ − G) / (G₀ − T): gross weights minus the tare (wrap + net), measured from the start
  of drying, not from the raw weight. Confirmed in the food-safety review of 21 Oct 2026.
- **Why.** The meat already loses weight in the bag. Measuring from the raw weight would reach the target
  earlier while the meat is wetter. The stricter basis is the safe side.
- **Alternatives.** Loss from the raw (green) weight, as some recipes quote.
- **Consequences.** The tare is stored once per batch. The owner chose tare 0: grams stay exact, the loss %
  is understated by about 0.5 percentage points, again the safe side.

### D-05: Stages lock; unlocking is explicit, logged and in reverse order

- **Decision.** Day 0, Cure and Dry each lock when done; their inputs are then read-only. Unlocking needs a
  reason and goes in reverse order (Dry → Cure → Day 0). Notes and photos stay editable until the batch is
  closed; a closed batch is entirely read-only. Every lock, unlock and safety-relevant change is written to
  `project_event`.
- **Why.** The record is only trustworthy if a finished stage can't change unnoticed.
- **Where.** `db._require_unlocked`, `lock_*`, `unlock_*`, `log`.

### D-06: Food-safety limits in one module; the drying place selects them

- **Situation.** A review of the app's safety logic on 21 Oct 2026 found the limits scattered and some checks
  missing.
- **Decision.** All limits and the messages built from them in `bresaola/safety.py`. Each drying place has a
  kind, `fridge` (warn above 4 °C) or `chamber` (warn above 15 °C, note below 10 °C), and the kind is frozen
  at the end of drying. Curing salt is a required choice per batch, with no default. Target 25–50 % allowed,
  warning outside 30–40 %. Temperature and humidity are judged on hourly averages.
- **Why.** One place to change and review; the app and the PDF can't disagree. The same batch without curing
  salt is reasonable in a cold fridge and questionable in a curing chamber, so the rules must follow the
  place. Hourly averages keep a door opening from raising an alarm.
- **Consequences.** A change to `safety.py` is a full-audit trigger (D-07). Details: ARCHITECTURE section 7.

### D-07: Diff audit after every change set, full audit on triggers

- **Decision.** After every change set an independent reviewer reads the diff and runs the tests; High and
  Medium findings are fixed with tests before release. A full audit (reviewer runs the app in a browser) is
  recommended on six triggers, and the owner decides (`CLAUDE.md`). Every audit is recorded with its findings
  and token cost.
- **Why.** The author checking their own work misses the same things twice. The full audits found real
  defects that tests had missed, for example a stale browser tab writing old values back (D-13).
- **Alternatives.** A full audit on every release: about 240k tokens each, about 2 % of the owner's usage.
- **Consequences.** Releases take one review round longer. Very small changes (one string, a few lines) may
  be reviewed directly; that's recorded too.

### D-08: NAS: Docker host networking on port 8520

- **Situation.** Docker port forwarding didn't work on the Synology; on host networking, port 8503 was
  unreachable from other machines.
- **Decision.** `network_mode: host`, Streamlit on port 8520.
- **Why.** Synology MailPlus Server reserves ports 8500–8507 (and others) and drops outside connections to
  them; 8520 is outside that list. Host networking also lets the container reach the hub on the LAN for
  discovery (D-14).
- **Consequences.** The port is in `compose.yaml` twice (command and health check) and in the update script's
  health check (`PORT`).

### D-09: Image tag = app version

- **Situation.** After an update, Container Manager kept running the old version: its *Build* reused an image
  whose name it already had (found 27 Oct 2026).
- **Decision.** `compose.yaml` names the image `bresaola-tracker:<version>`, equal to
  `bresaola/__init__.py`. `tests/test_deploy.py` fails if they differ.
- **Consequences.** Every version bump changes two files. Old images are pruned by the update script, which
  keeps the current and the previous one for a rollback.

### D-10: NAS updates itself from `stable`, with health check and rollback

- **Decision.** A DSM task runs `scripts/nas-update.sh` at 04:00. If `stable` has moved, the script copies
  the database to `data/pre-update/` (last 5 kept), checks out the commit, rebuilds and restarts, then checks
  that the web server answers and that the container reports the new version and can open the database.
  If the check fails, it goes back to the previous commit and image and marks the bad commit (`update.failed`),
  so it isn't retried every night. Git access is a read-only deploy key.
- **Why.** No manual ZIP uploads; `main` can move freely without reaching the real data; a failed update
  undoes itself.
- **Alternatives.** Following `main` (untested changes on real data); manual ZIP uploads (the method until
  v0.4.6, which is how the stale-image problem of D-09 was found).
- **Consequences.** `stable` only moves after the diff audit and the owner's OK. A rollback restores the
  program, not the database; migrations only add columns, which older versions ignore.

### D-11: One sensor table per batch

- **Situation.** Until v0.4.17 sensor readings belonged to a physical *chamber* shared by batches. The owner
  uses one sensor per piece of meat, possibly in different drawers, and "switching fridge" isn't something
  he wants in the app.
- **Decision.** Each batch owns its `chamber` row (`chamber.project_id`). A batch's sensor name
  (`chamber.tapo_name`) tells the hub sync which sensor feeds it. Two batches may name the same physical
  sensor; each still gets its own copy of the readings.
- **Why.** A batch's record is self-contained: deleting one batch removes only its readings; a left-out
  period or an import for one batch can't touch another.
- **Migration.** `_split_shared_chambers` (in `connect()`): makes a timestamped copy of the database file
  first, gives each batch on a shared chamber its own copy of the readings and left-out periods (the batch
  drying now keeps the original), runs under a write lock, and is skipped if the copy fails.
- **Consequences.** Shared-sensor setups store the same readings once per batch (a few hundred kB). The
  table is still named `chamber` for historical reasons.

### D-12: Sensor readings are only added, never silently replaced

- **Decision.** Imports and the hub sync insert with `INSERT OR IGNORE`: a time already stored keeps its
  value. Replacing is opt-in, by a box the owner ticks on an upload. Left-out periods are stored and applied
  to every later import and sync. Readings inside a locked drying period are never added or removed. The
  same time from different sources is stored once per source and shown once (export > hub > manual).
- **Why.** Uploading the same or a longer export again must be harmless, and a finished batch's PDF must stay
  reproducible. Tapo's cloud history occasionally re-rounds old values by 0.1 °C; ignoring those keeps the
  record stable.
- **Consequences.** To correct wrong data, the owner removes it explicitly (*Remove readings*) or ticks
  *Replace*.

### D-13: Widget keys carry the database value (stale tabs)

- **Situation.** A browser tab left open on the phone held its own widget values. On its next rerun it sent
  them back and overwrote newer values entered elsewhere. The v0.4.9 fix reset only the server's copy; the
  full audit of 28 Oct 2026 showed the browser still sent the stale value.
- **Decision.** Widgets that show a database value get a key that includes a hash of that value
  (`fresh(key, value)` in `app.py`). When the value changes elsewhere, the key changes, the old widget is
  gone, and its value can't be sent back.
- **Verification.** Reproduced in two real browser tabs with Playwright: old code 2000 g (wrong), new code
  2500 g (right).
- **Consequences.** Unsaved typing in a field is lost only if the same value is changed in another tab at
  the same time.

### D-14: Hub connection through discovery; never a second login

- **Situation.** The sync used `ApiClient.h100(ip)`, which always connects on port 80. The owner's hub turned
  out to be an **H200** on firmware 1.7.7: port 80 closed, port 443 open. Found on 29 Oct 2026 with a series
  of one-off DSM tasks (port check, then a library discovery test). The hub reports itself as a camera hub
  (`CameraHub`) and accepts only the encrypted connection.
- **Decision.** `tapo_sync.connect_hub` asks the hub first (`discover_devices`) and uses the connection the
  hub announces, for a `Hub` or a `CameraHub`. A login error stops at once, with no second attempt: a TPAP hub
  locks itself after repeated wrong passwords. Any other discovery trouble falls back to `h100(ip)` for older
  hubs.
- **Alternatives.** *(In hindsight:)* hard-coding `h200(ip)` (would break an H100 setup); retrying on any
  error (lockout risk).
- **Consequences.** Works with the H200 and should keep working with the H100. The `tapo` library is pinned
  `<0.13`; a firmware change may need a newer library, tested against the real hub before the pin is raised.

### D-15: Hub sync every 6 hours; warn on the age of the newest reading

- **Situation.** The hub holds only the last 24 hours, and loses them on a restart (seen twice on
  29 Oct 2026).
- **Decision.** One DSM task, `tapo_to_nas`, at 00:00, 06:00, 12:00 and 18:00, e-mailing only on failure.
  Every attempt is logged per batch in `meta`. The app shows "Last loaded from the hub", warns when the last
  attempt failed, and warns when the **newest reading from the hub** is more than 12 hours old while the
  batch is drying, or when there is none yet.
- **Why.** Three runs can fail in a row before a reading is lost. Judging by the newest reading, not by the
  time of the last sync, also catches a sync that runs but gets nothing (sensor out of range, flat battery).
- **Consequences.** With the current radio link, the 12-hour warning appears on some days. That's a true
  report: no readings exist for that time.

### D-16: One sensor chart with two y-axes and a period slider

- **Situation.** v0.4.21 stacked temperature and humidity with a drag-to-zoom strip below; the owner didn't
  like the strip and asked for both quantities in one chart.
- **Decision.** One chart: temperature on the left axis (red title and labels, matching the red line),
  humidity on the right (green). The lowest-to-highest band for temperature only. A dashed line at the
  drying place's temperature limit, always in view. Below the chart, a slider with two handles sets the
  period, with *Last 24 h*, *Last 7 days* and *All*. Only the chosen period is drawn, so both y-axes fit it.
- **Why.** Temperature and humidity move together (a door opening shows as temperature up, humidity down),
  so one time axis helps. Two axes can mislead, so each axis carries its line's colour and a caption explains
  them. A slider works on a phone; dragging inside a chart doesn't. No manual y-axis control: it could hide a
  peak above the limit.
- **Alternatives.** The zoom strip (v0.4.21); zooming with the mouse wheel (no phone support, no y fit).
- **Consequences.** A period without readings shows a message instead of an empty chart. A period that ends
  at the newest reading keeps following new readings.

### D-17: Documentation lives in the repo and changes with the code

- **Decision.** Technical documentation is Markdown under `docs/` (diagrams in Mermaid, formulas in LaTeX,
  both rendered by GitHub). A change to how the system works updates the documentation in the same change set,
  and the diff audit checks the documentation against the code (`CLAUDE.md`).
- **Why.** Documentation kept elsewhere falls behind with the first release. In the repo it's versioned,
  reviewed and diffed with the code.
- **Alternatives.** A separate document or wiki.
