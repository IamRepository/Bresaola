"""Food-safety thresholds and checks, in one place (audit of 21 Oct 2026).

The numbers are general guidance for whole-muscle dried beef, not from a specific recipe.
Drying happens either in a fridge (about 0-4 °C) or in a curing chamber (about 10-15 °C); the
temperature rules differ, so every chamber has a kind: "fridge" or "chamber".
Change them here; everything in the app and the PDF reads them from this module.
"""
from __future__ import annotations

# --- weight-loss target (measured on the meat at the start of drying) -------------------
TARGET_MIN, TARGET_MAX = 25.0, 50.0        # allowed
TARGET_USUAL = (30.0, 40.0)                # usual bresaola range; outside it the app warns

# --- drying place --------------------------------------------------------------------------
KINDS = {"fridge": "Fridge", "chamber": "Curing chamber"}
TEMP_MAX = {"fridge": 4.0,       # °C: a drying fridge should stay below this; the cold is part of the protection
            "chamber": 15.0}     # °C: a curing chamber above this: spoilage risk rises
DRY_TEMP_MAX = TEMP_MAX["chamber"]
DRY_TEMP_SLOW = 10.0     # °C: curing chamber only: colder than the usual 10-15 °C is safe but slow
BOTULISM_MIN_C = 3.0     # °C: below about this, the bacteria behind botulism can't grow
RH_MAX = 90.0            # %: above this, mould risk
RH_MIN = 65.0            # %: below this, case hardening (dry crust traps moisture inside)

# --- cure ----------------------------------------------------------------------------------
CURE_FRIDGE_MAX = 4.0    # °C: the cure-time formula assumes a fridge at 1-3 °C

NO_CURE_WARNING = ("No curing salt (nitrite/nitrate). Protection rests on the salt level and on drying "
                   "properly. Most published bresaola recipes use curing salt when drying at chamber "
                   "temperatures (10-15 °C).")


def no_cure_message(kind: str | None, rows=()) -> tuple[str, str]:
    """('info' or 'warning', text) for a batch without curing salt, depending on where it dries.
    kind: 'fridge', 'chamber' or None (drying not started); rows: chamber readings during drying."""
    if kind == "chamber":
        return "warning", NO_CURE_WARNING
    if kind == "fridge":
        warm = [b for b in _hours(rows) if b["t"] is not None and b["t"] > TEMP_MAX["fridge"]]
        if warm:
            return "warning", (f"No curing salt, and the fridge was warmer than {TEMP_MAX['fridge']:g} °C for "
                               f"{_describe(warm)}. In a fridge the cold is part of the protection: keep it "
                               f"below {TEMP_MAX['fridge']:g} °C.")
        return "info", (f"No curing salt (nitrite/nitrate). Drying in a fridge: below about {BOTULISM_MIN_C:g} °C "
                        f"the bacteria behind botulism can't grow, so the 3 % salt and keeping the fridge below "
                        f"{TEMP_MAX['fridge']:g} °C are this batch's protection.")
    return "info", ("No curing salt (nitrite/nitrate). Fine for drying in a fridge kept below "
                    f"{TEMP_MAX['fridge']:g} °C; when drying in a curing chamber (10-15 °C), most published "
                    "recipes use curing salt.")


def target_problem(pct: float) -> str | None:
    """Hard limit: returns an error message, or None if allowed."""
    if not TARGET_MIN <= pct <= TARGET_MAX:
        return f"The weight-loss target must be between {TARGET_MIN:g} and {TARGET_MAX:g} %."
    return None


def target_warning(pct: float) -> str | None:
    lo, hi = TARGET_USUAL
    if pct < lo:
        return (f"A {pct:g} % target is below the usual {lo:g}-{hi:g} % for bresaola: the meat may not be "
                "dry enough to be shelf-stable.")
    if pct > hi:
        return f"A {pct:g} % target is above the usual {lo:g}-{hi:g} %: expect a hard, very dry result."
    return None


def target_message(pct: float, hint: bool = True) -> str | None:
    """One message for a stored target: outside the allowed range (set before v0.4.0) wins over 'unusual'."""
    if not TARGET_MIN <= pct <= TARGET_MAX:
        return (f"The target ({pct:g} %) is outside the allowed {TARGET_MIN:g}-{TARGET_MAX:g} % "
                "(it was set before v0.4.0)." + (" Set a new one under \"Drying start, packaging and target\"." if hint else ""))
    return target_warning(pct)


def cure_length(actual_days: int, minimum_days: float, planned_days: int) -> str:
    """'ok' (reached the planned days), 'short' (past the calculator minimum but not the +20 % margin)
    or 'below_min' (shorter than the calculator minimum: salt may not have reached the centre)."""
    if actual_days >= planned_days:
        return "ok"
    if actual_days >= minimum_days:
        return "short"
    return "below_min"


def _hours(rows):
    from . import sensors                   # here, not at the top: db imports this module
    return sensors.aggregate(list(rows), 1) if rows else []


def _describe(blocks) -> str:
    days = sorted({b["start"].date() for b in blocks})
    span = f"{days[0]:%d %b}" if len(days) == 1 else f"{days[0]:%d %b} to {days[-1]:%d %b} ({len(days)} days)"
    return f"{len(blocks)} h, {span}"


def chamber_warnings(rows, kind: str = "chamber") -> tuple[list[str], list[str]]:
    """(warnings, notes) for drying readings, judged on hourly averages so a door opening for a minute
    doesn't count. kind 'fridge': warn above 4 °C; 'chamber': warn above 15 °C, note below 10 °C."""
    hours = _hours(rows)
    if not hours:
        return [], []
    tmax = TEMP_MAX.get(kind, DRY_TEMP_MAX)
    warm = [b for b in hours if b["t"] is not None and b["t"] > tmax]
    wet = [b for b in hours if b["h"] is not None and b["h"] > RH_MAX]
    dry = [b for b in hours if b["h"] is not None and b["h"] < RH_MIN]
    warnings = []
    if warm:
        warnings.append(f"Fridge warmer than {tmax:g} °C for {_describe(warm)}: keep it colder." if kind == "fridge"
                        else f"Warmer than {tmax:g} °C for {_describe(warm)}: spoilage risk rises.")
    if wet:
        warnings.append(f"Humidity above {RH_MAX:g} % for {_describe(wet)}: mould risk.")
    if dry:
        warnings.append(f"Humidity below {RH_MIN:g} % for {_describe(dry)}: risk of case hardening "
                        "(a dry crust that traps moisture inside).")
    notes = []
    temps = [b["t"] for b in hours if b["t"] is not None]
    if kind == "chamber" and temps and sum(temps) / len(temps) < DRY_TEMP_SLOW:
        notes.append(f"Average {sum(temps) / len(temps):.1f} °C is colder than the usual 10-15 °C for a curing "
                     "chamber: safe, but drying is slow.")
    return warnings, notes


def cure_fridge_warning(temp_c: float | None) -> str | None:
    if temp_c is not None and temp_c > CURE_FRIDGE_MAX:
        return (f"Cure fridge at {temp_c:g} °C: above {CURE_FRIDGE_MAX:g} °C. The cure time assumes 1-3 °C, "
                "and a warmer fridge lets bacteria grow before the salt reaches the centre.")
    return None


def out_of_range(field: str, value: float | None, kind: str = "chamber") -> bool:
    """For averages shown in tables: temperature above the limit for this kind, humidity outside RH_MIN..RH_MAX."""
    if value is None:
        return False
    if field == "t":
        return value > TEMP_MAX.get(kind, DRY_TEMP_MAX)
    return not RH_MIN <= value <= RH_MAX
