"""Pull chamber readings straight from a Tapo hub (H100, H200) on the home network.

The hub keeps only the last 24 hours (15-minute averages), so run this at least once a day,
e.g. from Windows Task Scheduler or a NAS cron job:

    python -m bresaola.tapo_sync

Settings come from environment variables, never from the database or the repo:

    TAPO_USERNAME   Tapo account e-mail
    TAPO_PASSWORD   Tapo account password
    TAPO_HUB_IP     the H100's IP address on your network, e.g. 192.168.1.50
    TAPO_SENSORS    optional, older setups only: "Fridge drawer=Bresaola sensor" (chamber name =
                    sensor nickname in the Tapo app; separate pairs with ;)

Since v0.4.17 each batch has its own readings: give the batch its Tapo sensor name in the app
(Dry step -> Sensor settings). The sync fills every batch that is drying and has one.

Needs `pip install tapo` (Python 3.11+). Not used on Streamlit Cloud, which can't reach the hub.
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from . import db, sensors, storage

SOURCE = "tapo_api"


def sensor_map(raw: str | None = None) -> dict[str, str]:
    """'Fridge drawer=Bresaola sensor; Cellar=T315 cellar' → {chamber: sensor nickname}."""
    raw = os.environ.get("TAPO_SENSORS", "") if raw is None else raw
    out = {}
    for pair in raw.split(";"):
        if "=" in pair:
            chamber, nick = (x.strip() for x in pair.split("=", 1))
            if chamber and nick:
                out[chamber] = nick
    return out


def is_configured() -> bool:
    """The hub can be reached: account and hub address are set. Which sensors feed which batch is
    stored per batch in the app (or, for older setups, in TAPO_SENSORS)."""
    return all(os.environ.get(k) for k in ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_HUB_IP"))


def to_local(t: datetime) -> datetime:
    """Hub times are UTC; store local wall-clock time like every other reading."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(db.TZ).replace(tzinfo=None, microsecond=0)


def records_to_rows(recs) -> list[tuple[datetime, float | None, float | None]]:
    fahrenheit = "fahrenheit" in str(getattr(recs, "temperature_unit", "")).lower()
    rows = []
    for r in recs.records:
        temp = float(r.temperature) if r.temperature is not None else None
        if fahrenheit and temp is not None:
            temp = (temp - 32) * 5 / 9
        rh = float(r.humidity) if r.humidity is not None else None
        rows.append((to_local(r.recorded_at), round(temp, 2) if temp is not None else None, rh))
    return sensors.merge_same_time(rows)          # the repeated October hour: average, don't overwrite


HUB_TYPES = ("Hub", "CameraHub")       # H100 / H110 report "Hub"; H200, H500 and H100 on firmware 1.7.x "CameraHub"


async def connect_hub(client, ip: str):
    """The hub's handler. Asks the hub first (discovery) which connection it uses: on the owner's hub
    (firmware 1.7.7, 29 Oct 2026) port 80 is closed and only the encrypted connection on 443 works,
    so h100(ip), which always uses port 80, timed out. Hubs that don't answer discovery: h100(ip)."""
    if hasattr(client, "discover_devices"):
        errors = []
        async for r in await client.discover_devices(ip, 5):
            try:
                res = r.get()
            except Exception as e:          # e.g. wrong password: report it, don't try again
                errors.append(e)
                continue
            if type(res).__name__ in HUB_TYPES:
                return res.handler
        if errors:
            raise errors[0]
    return await client.h100(ip)


async def fetch(nicknames: list[str], client_factory=None) -> dict[str, list]:
    """{sensor nickname: rows}. client_factory(username, password) lets tests pass a fake."""
    if client_factory is None:
        from tapo import ApiClient                  # imported here: optional dependency
        client_factory = ApiClient
    client = client_factory(os.environ["TAPO_USERNAME"], os.environ["TAPO_PASSWORD"])
    hub = await connect_hub(client, os.environ["TAPO_HUB_IP"])
    out = {}
    for nick in nicknames:              # one wrong sensor name must not stop the others
        try:
            sensor = await hub.t31x(nickname=nick)
            out[nick] = records_to_rows(await sensor.get_temperature_humidity_records())
        except Exception as e:
            out[nick] = e
    return out


@dataclass
class Result:
    chamber: str
    sensor: str
    stored: int = 0
    rejected: int = 0
    skipped: int = 0            # inside a saved left-out period or a locked drying period
    first: datetime | None = None
    last: datetime | None = None
    error: str | None = None


def norm_name(name: str) -> str:
    """Chamber names compare without capitals and extra spaces."""
    return " ".join(name.split()).casefold()


def hub_fed(chamber_row) -> bool:
    """True if the hub sync sends readings to this chamber: it has a Tapo sensor name, or (older
    setups) TAPO_SENSORS names it."""
    if chamber_row["tapo_name"]:
        return True
    return norm_name(chamber_row["name"]) in {norm_name(c) for c in sensor_map()}


def find_chamber(con, name: str) -> tuple[int | None, str | None]:
    """(chamber id, None) for the chamber called `name`, ignoring capitals and extra spaces, or
    (None, error): never a silent new chamber (audit 26 Oct, #20). Used for TAPO_SENSORS only."""
    rows = db.chambers(con)
    for r in rows:
        if norm_name(r["name"]) == norm_name(name):
            return r["id"], None
    return None, (f"no chamber called '{name}' (TAPO_SENSORS in .env). Since v0.4.17, give the batch its "
                  "Tapo sensor name in the app instead (Dry step, Sensor settings); nothing stored.")


def targets(con) -> list[tuple[str, str, int | None, str | None]]:
    """(label, sensor nickname, chamber id or None, error) for every batch that is drying (started,
    not locked, not closed) and has a Tapo sensor name; plus older TAPO_SENSORS pairs."""
    out, seen = [], set()
    for r in con.execute("""SELECT c.id, c.tapo_name, p.name FROM chamber c JOIN project p ON p.id = c.project_id
                            WHERE c.tapo_name IS NOT NULL AND p.dry_start IS NOT NULL
                              AND p.dry_locked_at IS NULL AND p.status != 'closed' ORDER BY p.name"""):
        out.append((r["name"], r["tapo_name"], r["id"], None))
        seen.add(r["id"])
    for name, nick in sensor_map().items():
        ch, err = find_chamber(con, name)
        if ch is not None and not err and not con.execute(
                """SELECT 1 FROM chamber c JOIN project p ON p.id = c.project_id WHERE c.id=?
                   AND p.dry_start IS NOT NULL AND p.dry_locked_at IS NULL AND p.status != 'closed'""",
                (ch,)).fetchone():
            # v0.4.17: readings belong to one batch; never feed a finished or unowned table
            # (full audit 28 Oct 2026, #3)
            err = (f"'{name}' is not the sensor table of a batch that is drying. Set the Tapo sensor "
                   "name in that batch's Dry step instead.")
        if ch not in seen:
            out.append((name, nick, ch, err))
            seen.add(ch)
    return out


def sync(con, client_factory=None) -> list[Result]:
    """Fetch every batch's sensor and store its readings in that batch's table. Readings already
    stored are kept (v0.4.17: data is added, never overwritten)."""
    tg = targets(con)
    results = [Result(label, nick, error=err) for label, nick, _, err in tg]
    nicks = sorted({nick for _, nick, ch, err in tg if ch is not None and not err})
    if not nicks:
        return results
    try:
        data = asyncio.run(fetch(nicks, client_factory))
    except Exception as e:                          # hub off, wrong password, sensor renamed ...
        for r in results:
            r.error = r.error or f"{type(e).__name__}: {e}"
        return results
    for r, (_, nick, ch_id, err) in zip(results, tg):
        if err or ch_id is None:
            continue
        rows = data.get(nick, [])
        if isinstance(rows, Exception):
            r.error = f"sensor '{nick}': {type(rows).__name__}: {rows}"
            continue
        with con:
            keep, n_ex, n_lk = sensors.protected(con, ch_id, rows)
            r.skipped = n_ex + n_lk
            r.stored, r.rejected = sensors.import_readings(con, ch_id, keep, SOURCE, replace=False)
        if rows:
            r.first, r.last = rows[0][0], rows[-1][0]
    return results


def main() -> int:
    if not is_configured():
        print("Set TAPO_USERNAME, TAPO_PASSWORD and TAPO_HUB_IP first (see the top of this file).")
        return 2
    con = db.connect(storage.db_path())
    ok = True
    res = sync(con)
    if not res:
        print("No batch is drying with a Tapo sensor name: nothing to sync (Dry step, Sensor settings).")
    for r in res:
        if r.error:
            ok = False
            print(f"{r.chamber} ({r.sensor}): FAILED, {r.error}")
        else:
            span = f"{r.first:%d %b %H:%M} to {r.last:%d %b %H:%M}" if r.first else "no data"
            print(f"{r.chamber} ({r.sensor}): {r.stored} readings, {span}"
                  + (f", {r.rejected} out of range" if r.rejected else "")
                  + (f", {r.skipped} skipped (left-out or finished drying period)" if r.skipped else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
