# Running Bresaola Tracker on the Synology NAS

Target: Synology DS1019+, DSM 7.4, Container Manager; app in `docker/bresaola`, data in
`docker/bresaola/data`; remote access through VPN Plus on the Synology router. The NAS copy is the real
one: its data stays on the NAS. Streamlit Community Cloud keeps running from `main` for trying new versions; it keeps
nothing, and the two do not share data.

## 1. Put the app on the NAS
1. On github.com (signed in), open the Bresaola repo → **Code** → **Download ZIP**.
2. DSM → **File Station** → shared folder **docker** → create a folder **bresaola**.
3. Upload the ZIP into `docker/bresaola`, right-click → **Extract** → **Extract here**.
   GitHub puts everything in a sub-folder (`Bresaola-main`): move its contents up into `docker/bresaola`,
   so that `docker/bresaola/compose.yaml` and `docker/bresaola/Dockerfile` exist. Delete the ZIP.
4. Create an empty folder `docker/bresaola/data`. The database and photos will live there.

## 2. Build and start
5. **Container Manager** → **Project** → **Create**.
   - Project name: `bresaola`
   - Path: `/docker/bresaola`
   - Source: use the existing `compose.yaml`
   - Skip the Web Station / web portal step → **Done**.
   The first build downloads Python and the packages: allow several minutes.
6. Open `http://<NAS IP>:8520`. Two things learned on this NAS:
   - **MailPlus Server reserves ports 8500–8507** (also 5230, 5252, 9526–9529, 10025, 10465, 10587, 11211,
     12340, 24245, 24246) and drops outside connections to them. Pick a port outside that list.
   - The app uses host networking (`network_mode: host`): it listens on the NAS's own address. To use another
     port, change `8520` in both the `command` and the `healthcheck` lines of `compose.yaml`.
   Check: version **v0.4.1** (or later) under "Bresaola Tracker", **no** yellow test-mode note,
   no demo project.

## 3. Bring your data over
7. In the Streamlit Cloud app: sidebar → **Data: backup and restore** → **Download backup**.
8. In the NAS app: same place → **Restore backup** → choose the zip → **Replace all data**.
   (The cloud copy may contain the demo Palermo data; alternatively start Palermo fresh on the NAS.)
9. Chamber readings: if they are not in the backup, import the Tapo file again in Dry → Chamber.
   Under **Left-out periods**, add 03/10/2026 12:15 to 09/10/2026 04:00 (the sensor was out of the fridge):
   from v0.4.9 it is remembered and applied to every later import and hub sync.

## 4. From outside home
10. Connect with **VPN Plus** (on the Synology router) and open `http://192.168.15.130:8520`, the same address as
    at home. No router port forwarding, no Tailscale needed.

## 5. Backups
11. Make sure Hyper Backup (and snapshots, if used) include the shared folder **docker**, or at least
    `docker/bresaola/data`. The in-app **Download backup** remains a quick extra copy.

## 6. Tapo hub sync (optional)
The H100 keeps only the last 24 hours, so this needs a daily task.
12. Give the H100 a fixed address in your router (DHCP reservation).
13. Create a text file `docker/bresaola/.env` (File Station → Create → text file, or upload one) with:

        TAPO_USERNAME=you@example.com
        TAPO_PASSWORD=your-tapo-password
        TAPO_HUB_IP=192.168.1.50

    Which sensor belongs to which batch is set in the app, not here (v0.4.17: one sensor per piece of
    meat): Dry step → **Sensor settings, import and remove** → **Tapo sensor name** (the name in the Tapo
    app) → **Save name**. The sync fills every batch that is drying and has a name. (Older setups with
    `TAPO_SENSORS=Fridge drawer=<name>` keep working.)

    Don't edit `compose.yaml`: updates replace it. `.env` is never replaced, never in git and not copied
    into the image. The password sits in that file on the NAS: keep the folder private.
14. Container Manager → Project → **bresaola** → **Action** → **Stop**, then **Build**, then **Start**.
    The Dry step now shows **Sync last 24 h from hub**: try it once.
15. DSM → **Control Panel** → **Task Scheduler** → **Create** → **Scheduled Task** → **User-defined script**.
    User `root`, daily at 06:15, script:

        docker exec bresaola python -m bresaola.tapo_sync

    Select the task → **Run** to test; the result is in the task's log.

## 7. Updating to a new version
16. In the app: **Download backup** first (the new version may upgrade the database when it opens it).
17. Upload the new ZIP to `docker/bresaola` → right-click → **Extract here** → **Overwrite**. The ZIP has no
    `data` folder, so the database and photos are untouched. Delete the ZIP.
18. Container Manager → Project → **bresaola** → **Action** → **Stop**, then **Build** (it starts by itself).
    The Build log must be long (`pip install`, `Successfully installed`, a few minutes). If it shows only
    "Created / Starting / Started", nothing was built: Stop → **Clean**, delete the `bresaola-tracker` image
    under **Image**, and Build again. (Before v0.4.6 the image always had the same name, so this was needed
    every time.)
19. Check the version in the sidebar. Old `bresaola-tracker:<version>` images can be deleted under **Image**.

## 8. Automatic updates from GitHub (optional, from v0.4.7)
The NAS follows the **`stable`** branch, not `main`. New versions go to `main` first (tested on Streamlit
Cloud); `stable` is moved only after the diff audit and your OK. A nightly task checks `stable` and, if
there is something new: copies the database (and `compose.yaml`) to `data/pre-update/` (last 5 kept), takes
the new files, rebuilds and restarts. It then checks that the container reports the new version and opens the
database; if not, it goes back to the previous version (whose image is kept) and won't retry that version
until `stable` changes (it fails, and e-mails you, every night until then). Log: `update.log`.
Note: going back restores the program, not the database. Database upgrades only ever add columns, which the
previous version ignores; the copy in `data/pre-update/` is there if you want the exact old state.

One-time setup:
20. Install the v0.4.7 ZIP the usual way (section 7), so `scripts/nas-update.sh` is on the NAS.
21. Task Scheduler → **Create** → **Scheduled Task** → **User-defined script**: name `bresaola-setup`,
    user **root**, untick "Enabled" (run by hand), script:

        sh /volume1/docker/bresaola/scripts/nas-update.sh setup

    Select it → **Run**. File Station now shows `docker/bresaola/deploy_key.pub`.
    (If your shared folder `docker` isn't on volume1, use the path shown in File Station →
    right-click the folder → Properties → Location.)
22. Open `deploy_key.pub` (download it, open with Notepad), copy the one line.
    github.com → the Bresaola repo → **Settings** → **Deploy keys** → **Add deploy key**:
    title `NAS`, paste the line, leave **Allow write access unticked** → **Add key**.
    Then delete `deploy_key.pub` from the NAS (the private key stays in /root/.ssh).
23. Task Scheduler → **Create** → **Scheduled Task** → **User-defined script**: name `bresaola-update`,
    user **root**, schedule daily at **04:00** (after Hyper Backup at 02:30, before a hub sync at 06:15),
    script:

        sh /volume1/docker/bresaola/scripts/nas-update.sh

    Task Settings: tick **Send run details by email** and **only when the script terminates abnormally**.
24. Select `bresaola-update` → **Run** once now. The first run turns the folder into a git checkout and
    rebuilds once. Check `docker/bresaola/update.log`: it should end with `OK: <version> is running`;
    a second **Run** says `up to date`.

If a failure was passing (no internet during the build, say): delete `docker/bresaola/update.failed` and
**Run** the task again. If the very first run fails, install the last ZIP that worked (section 7).

Stopping it: untick "Enabled" on `bresaola-update`. Going back by hand: the database copies in
`data/pre-update/` are plain SQLite files; restore one by stopping the project and copying it over
`data/bresaola.sqlite`.
