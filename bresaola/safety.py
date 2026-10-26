"""Food-safety thresholds and checks, in one place (audit of 21 Oct 2026).

The numbers are general guidance for whole-muscle air-dried beef, not from a specific recipe.
Change them here; everything in the app and the PDF reads them from this module.
"""
from __future__ import annotations

# --- weight-loss target (measured on the meat at the start of drying) -------------------
TARGET_MIN, TARGET_MAX = 25.0, 50.0        # allowed
TARGET_USUAL = (30.0, 40.0)                # usual bresaola range; outside it the app warns

# --- drying chamber ------------------------------------------------------------------------
DRY_TEMP_MAX = 15.0      # °C: warmer than this, spoilage risk rises
DRY_TEMP_SLOW = 10.0     # °C: colder than the usual 10-15 °C range: safe, but drying is slow
RH_MAX = 90.0            # %: above this, mould risk
RH_MIN = 65.0            # %: below this, case hardening (dry crust traps moisture inside)

# --- cure ----------------------------------------------------------------------------------
CURE_FRIDGE_MAX = 4.0    # °C: the cure-time formula assumes a fridge at 1-3 °C

NO_CURE_WARNING = ("No curing salt (nitrite/nitrate). Protection rests on the salt level and on drying "
                   "properly. Most published bresaola recipes use curing salt for long air-drying.")


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


def cure_length(actual_days: int, minimum_days: float, planned_days: int) -> str:
    """'ok' (reached the planned days), 'short' (past the calculator minimum but not the +20 % margin)
    or 'below_min' (shorter than the calculator minimum: salt may not have reached the centre)."""
    if actual_days >= planned_days:
        return "ok"
    if actual_days >= minimum_days:
        return "short"
    return "below_min"


def chamber_warnings(rows) -> tuple[list[str], list[str]]:
    """(warnings, notes) for drying-chamber readings, judged on hourly averages so a door opening
    for a minute doesn't count. rows: chamber_reading rows (ts, temp_c, rh_pct)."""
    from . import sensors                   # here, not at the top: db imports this module
    hours = sensors.aggregate(rows, 1)
    if not hours:
        return [], []

    def describe(blocks):
        days = sorted({b["start"].date() for b in blocks})
        span = f"{days[0]:%d %b}" if len(days) == 1 else f"{days[0]:%d %b} to {days[-1]:%d %b} ({len(days)} days)"
        return f"{len(blocks)} h, {span}"

    warm = [b for b in hours if b["t"] is not None and b["t"] > DRY_TEMP_MAX]
    wet = [b for b in hours if b["h"] is not None and b["h"] > RH_MAX]
    dry = [b for b in hours if b["h"] is not None and b["h"] < RH_MIN]
    warnings = []
    if warm:
        warnings.append(f"Warmer than {DRY_TEMP_MAX:g} °C for {describe(warm)}: spoilage risk rises.")
    if wet:
        warnings.append(f"Humidity above {RH_MAX:g} % for {describe(wet)}: mould risk.")
    if dry:
        warnings.append(f"Humidity below {RH_MIN:g} % for {describe(dry)}: risk of case hardening "
                        "(a dry crust that traps moisture inside).")
    temps = [b["t"] for b in hours if b["t"] is not None]
    notes = []
    if temps and sum(temps) / len(temps) < DRY_TEMP_SLOW:
        notes.append(f"Average {sum(temps) / len(temps):.1f} °C is colder than the usual 10-15 °C drying range: "
                     "safe, but drying is slow.")
    return warnings, notes


def cure_fridge_warning(temp_c: float | None) -> str | None:
    if temp_c is not None and temp_c > CURE_FRIDGE_MAX:
        return (f"Cure fridge at {temp_c:g} °C: above {CURE_FRIDGE_MAX:g} °C. The cure time assumes 1-3 °C, "
                "and a warmer fridge lets bacteria grow before the salt reaches the centre.")
    return None


def out_of_range(field: str, value: float | None) -> bool:
    """For averages shown in tables: temperature above DRY_TEMP_MAX, humidity outside RH_MIN..RH_MAX."""
    if value is None:
        return False
    if field == "t":
        return value > DRY_TEMP_MAX
    return not RH_MIN <= value <= RH_MAX
