# Running Bresaola Tracker on the Synology NAS

Target: Synology DS1019+, DSM 7.4, Container Manager. Same layout as the BBQ dashboard
(`docker/<app>/data`, Tailscale for remote access). The NAS copy is the real one: its data stays on
the NAS. Streamlit Community Cloud keeps running from `main` for trying new versions; it keeps
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
6. Open `http://<NAS IP>:8503` (8501 is the BBQ dashboard and 8502 is taken too; if the start fails with
   "port is already allocated", change the first number in `compose.yaml` to a free port).
   Check: version **v0.4.1** (or later) under "Bresaola Tracker", **no** yellow test-mode note,
   no demo project.

## 3. Bring your data over
7. In the Streamlit Cloud app: sidebar → **Data: backup and restore** → **Download backup**.
8. In the NAS app: same place → **Restore backup** → choose the zip → **Replace all data**.
   (The cloud copy may contain the demo Palermo data; alternatively start Palermo fresh on the NAS.)
9. Chamber readings: if they are not in the backup, import the Tapo file again in Dry → Chamber,
   with **Leave out a period** 03/10/2026 12:15 to 09/10/2026 04:00.

## 4. From your phone (outside home)
10. Tailscale is already on the NAS for the BBQ dashboard: open `http://<NAS Tailscale name>:8503`.
    No router port forwarding.

## 5. Backups
11. Make sure Hyper Backup (and snapshots, if used) include the shared folder **docker**, or at least
    `docker/bresaola/data`. The in-app **Download backup** remains a quick extra copy.

## 6. Tapo hub sync (optional)
The H100 keeps only the last 24 hours, so this needs a daily task.
12. Give the H100 a fixed address in your router (DHCP reservation).
13. Edit `docker/bresaola/compose.yaml`: remove the `#` in front of the four `TAPO_` lines and fill them in.
    `TAPO_SENSORS` is `Fridge drawer=<the sensor's name in the Tapo app>`.
    The password then sits in that file on the NAS: keep the folder private.
14. Container Manager → Project → **bresaola** → **Action** → **Stop**, then **Build**, then **Start**.
    The Dry step now shows **Sync last 24 h from hub**: try it once.
15. DSM → **Control Panel** → **Task Scheduler** → **Create** → **Scheduled Task** → **User-defined script**.
    User `root`, daily at 06:15, script:

        docker exec bresaola python -m bresaola.tapo_sync

    Select the task → **Run** to test; the result is in the task's log.

## 7. Updating to a new version
16. Download the new ZIP (step 1), and replace all files in `docker/bresaola` **except the `data` folder**
    (and your edited `compose.yaml`, if you added Tapo settings).
17. Container Manager → Project → **bresaola** → **Action** → **Stop**, **Build**, **Start**.
    The data folder is untouched; the database is upgraded automatically when the new version opens it.
