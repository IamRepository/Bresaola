"""Pull chamber readings straight from a Tapo H100 hub on the home network.

The hub keeps only the last 24 hours (15-minute averages), so run this at least once a day,
e.g. from Windows Task Scheduler or a NAS cron job:

    python -m bresaola.tapo_sync

Settings come from environment variables, never from the database or the repo:

    TAPO_USERNAME   Tapo account e-mail
    TAPO_PASSWORD   Tapo account password
    TAPO_HUB_IP     the H100's IP address on your network, e.g. 192.168.1.50
    TAPO_SENSORS    which sensor feeds which chamber: "Fridge drawer=Bresaola sensor"
                    (chamber name = sensor nickname in the Tapo app; separate pairs with ;)

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
    return all(os.environ.get(k) for k in ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_HUB_IP")) and bool(sensor_map())


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


async def fetch(nicknames: list[str], client_factory=None) -> dict[str, list]:
    """{sensor nickname: rows}. client_factory(username, password) lets tests pass a fake."""
    if client_factory is None:
        from tapo import ApiClient                  # imported here: optional dependency
        client_factory = ApiClient
    client = client_factory(os.environ["TAPO_USERNAME"], os.environ["TAPO_PASSWORD"])
    hub = await client.h100(os.environ["TAPO_HUB_IP"])
    out = {}
    for nick in nicknames:
        sensor = await hub.t31x(nickname=nick)
        out[nick] = records_to_rows(await sensor.get_temperature_humidity_records())
    return out


@dataclass
class Result:
    chamber: str
    sensor: str
    stored: int = 0
    rejected: int = 0
    first: datetime | None = None
    last: datetime | None = None
    error: str | None = None


def sync(con, client_factory=None) -> list[Result]:
    """Fetch every configured sensor and store its readings under its chamber."""
    pairs = sensor_map()
    results = [Result(ch, nick) for ch, nick in pairs.items()]
    try:
        data = asyncio.run(fetch(list(pairs.values()), client_factory))
    except Exception as e:                          # hub off, wrong password, sensor renamed ...
        for r in results:
            r.error = f"{type(e).__name__}: {e}"
        return results
    for r in results:
        rows = data.get(r.sensor, [])
        with con:
            ch_id = db.get_or_create_chamber(con, r.chamber, f"Tapo T31x '{r.sensor}' via H100")
            r.stored, r.rejected = sensors.import_readings(con, ch_id, rows, SOURCE)
        if rows:
            r.first, r.last = rows[0][0], rows[-1][0]
    return results


def main() -> int:
    if not is_configured():
        print("Set TAPO_USERNAME, TAPO_PASSWORD, TAPO_HUB_IP and TAPO_SENSORS first (see the top of this file).")
        return 2
    con = db.connect(storage.db_path())
    ok = True
    for r in sync(con):
        if r.error:
            ok = False
            print(f"{r.chamber} ({r.sensor}): FAILED, {r.error}")
        else:
            span = f"{r.first:%d %b %H:%M} to {r.last:%d %b %H:%M}" if r.first else "no data"
            print(f"{r.chamber} ({r.sensor}): {r.stored} readings, {span}"
                  + (f", {r.rejected} out of range" if r.rejected else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
