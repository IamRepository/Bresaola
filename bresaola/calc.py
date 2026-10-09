"""Pure calculation functions. No database, no UI.

Every rule here was confirmed with the user on 2026-10-08 and is pinned by tests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from .blends import BLENDS, ECOCURE_RATE, ECOCURE_SALT_FRACTION, SALT_RATE

# --------------------------------------------------------------------------- #
# Stage 1 – spice mix
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class IngredientLine:
    name: str
    unit: str          # "pct" -> grams, "per_kg" -> pieces
    rate: float
    planned: float     # grams, or pieces for per_kg

    @property
    def in_grams(self) -> bool:
        return self.unit == "pct"


def _ceil(x: float) -> int:
    # Guard against float noise such as 2.0000000001 -> 3
    return math.ceil(round(x, 9))


def blend_rates(blend: str) -> list[tuple[str, str, float]]:
    """Ingredient rates for a blend, as stored on a project (snapshot)."""
    if blend not in BLENDS:
        raise ValueError(f"Unknown blend: {blend!r}")
    return list(BLENDS[blend])


def spice_plan(weight_g: float, ecocure: bool,
               rates: list[tuple[str, str, float]]) -> list[IngredientLine]:
    """Planned quantities. EcoCure and salt first, then the blend's own lines.

    Salt = 3 % of weight minus the salt contained in EcoCure (50 % of it),
    so total salt is always 3 %.
    """
    if weight_g <= 0:
        raise ValueError("Meat weight must be positive")
    lines: list[IngredientLine] = []
    eco_g = weight_g * ECOCURE_RATE if ecocure else 0.0
    if ecocure:
        lines.append(IngredientLine("EcoCure #2", "pct", ECOCURE_RATE, eco_g))
    salt_g = weight_g * SALT_RATE - eco_g * ECOCURE_SALT_FRACTION
    salt_name = "Kosher salt, EcoCure #2 adjusted" if ecocure else "Kosher salt"
    lines.append(IngredientLine(salt_name, "pct", SALT_RATE, salt_g))
    for name, unit, rate in rates:
        if unit == "pct":
            qty = weight_g * rate
        elif unit == "per_kg":
            qty = _ceil(weight_g / 1000 * rate)
        else:
            raise ValueError(f"Unknown unit {unit!r} for {name}")
        lines.append(IngredientLine(name, unit, rate, qty))
    return lines


def total_grams(lines, attr: str = "planned") -> float:
    """Gram total; count items (bay leaf, juniper per kg) are excluded."""
    return sum(getattr(l, attr) for l in lines if l.unit == "pct" and getattr(l, attr) is not None)


SUGAR_WORDS = ("sugar", "turbinado")


@dataclass(frozen=True)
class MixSummary:
    salt_pct: float        # salt incl. EcoCure's salt share, % of meat weight
    ecocure_pct: float     # EcoCure, % of meat weight (0 if not used)
    sugar_pct: float
    seasoning_pct: float   # everything else weighed in grams, % of meat weight


def mix_summary(lines: list[tuple[str, str, float | None]], weight_g: float) -> MixSummary:
    """lines: (name, unit, grams). Count items (per_kg) are ignored."""
    salt = eco = sugar = other = 0.0
    for name, unit, g in lines:
        if unit != "pct" or g is None:
            continue
        n = name.lower()
        if n.startswith("ecocure"):
            eco += g
        elif n.startswith("kosher salt") or n == "salt":
            salt += g
        elif any(w in n for w in SUGAR_WORDS):
            sugar += g
        else:
            other += g
    pct = lambda x: 100 * x / weight_g
    return MixSummary(pct(salt + eco * ECOCURE_SALT_FRACTION), pct(eco), pct(sugar), pct(other))


def off_plan(lines: list[tuple[str, float, float | None]], tolerance: float = 0.10):
    """(name, planned, actual) -> [(name, relative deviation)] beyond the tolerance."""
    out = []
    for name, plan, act in lines:
        if act is None or not plan:
            continue
        dev = (act - plan) / plan
        if abs(dev) > tolerance:
            out.append((name, dev))
    return out


# --------------------------------------------------------------------------- #
# Stage 2 – cure time (genuineideas.com equilibrium brine calculator)
# --------------------------------------------------------------------------- #
# Source script javascript/update_dims.js:
#     curetime = 1.25 * inches**2   (flat)      tubular = curetime / 2
# The page says this is a minimum and to add 20 % to cure to the centre.

CURE_MARGIN = 1.2


def cure_days_minimum(thickness_cm: float, shape: str) -> float:
    if thickness_cm <= 0:
        raise ValueError("Thickness must be positive")
    shape = shape.lower()
    days = 1.25 * (thickness_cm / 2.54) ** 2
    if shape == "tubular":
        return days / 2
    if shape == "flat":
        return days
    raise ValueError("Shape must be 'flat' or 'tubular'")


def cure_days(thickness_cm: float, shape: str) -> int:
    """Calculator minimum + 20 %, rounded up to whole days."""
    return _ceil(cure_days_minimum(thickness_cm, shape) * CURE_MARGIN)


def cure_end_date(start: date, thickness_cm: float, shape: str) -> date:
    return start + timedelta(days=cure_days(thickness_cm, shape))


# --------------------------------------------------------------------------- #
# Stage 3 – drying
# --------------------------------------------------------------------------- #
# Weights on the scale include the dry-curing wrap and netting ("tare").
# Loss is calculated on meat only: gross − tare.

def target_gross_weight(start_gross_g: float, target_loss_pct: float,
                        tare_g: float = 0.0) -> float:
    meat = start_gross_g - tare_g
    if meat <= 0:
        raise ValueError("Start weight must exceed packaging weight")
    return tare_g + meat * (1 - target_loss_pct / 100)


def loss_pct(start_gross_g: float, gross_g: float, tare_g: float = 0.0) -> float:
    """Percent of meat weight lost so far."""
    return 100 * (start_gross_g - gross_g) / (start_gross_g - tare_g)


def progress_to_target(start_gross_g: float, gross_g: float,
                       target_loss_pct: float, tare_g: float = 0.0) -> float:
    """Fraction of the way from start to target weight (0 = start, 1 = done)."""
    tgt = target_gross_weight(start_gross_g, target_loss_pct, tare_g)
    return (start_gross_g - gross_g) / (start_gross_g - tgt)


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("Need readings on at least two different days")
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx


@dataclass(frozen=True)
class Eta:
    grams_per_day: float      # positive = losing weight
    days_from_start: float
    eta_date: date


def drying_eta(readings: list[tuple[date, float]], start_gross_g: float,
               target_loss_pct: float, tare_g: float = 0.0,
               last_n: int | None = None) -> Eta | None:
    """Straight-line estimate of when the target weight is reached.

    Drying normally slows, so this is an optimistic (earliest) estimate.
    `last_n` limits the fit to the most recent readings.
    Returns None if the trend is not downward.
    """
    pts = sorted(readings)
    if last_n:
        pts = pts[-last_n:]
    if len(pts) < 2:
        return None
    d0 = sorted(readings)[0][0]
    xs = [(d - d0).days for d, _ in pts]
    ys = [w for _, w in pts]
    slope, intercept = _linear_fit(xs, ys)
    if slope >= 0:
        return None
    tgt = target_gross_weight(start_gross_g, target_loss_pct, tare_g)
    days = (tgt - intercept) / slope
    return Eta(-slope, days, d0 + timedelta(days=math.ceil(days)))
