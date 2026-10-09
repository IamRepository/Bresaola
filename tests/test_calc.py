"""Pins every confirmed rule to the user's workbook and the source calculator."""
from datetime import date

import pytest

from bresaola import calc

W = 2088.0
CAL = calc.blend_rates("Spicy Calabrian")


def by_name(lines):
    return {l.name: l for l in lines}


# ---------------- stage 1: spice mix ----------------

def test_calabrian_no_ecocure_matches_sheet():
    lines = calc.spice_plan(W, False, CAL)
    m = by_name(lines)
    assert "EcoCure #2" not in m
    assert m["Kosher salt"].planned == pytest.approx(62.64)
    assert m["Fennel seed, powder"].planned == pytest.approx(10.44)
    assert m["Bay leaf, powder"].planned == 3            # ROUNDUP(2.088 * 1)
    assert calc.total_grams(lines) == pytest.approx(126.324)   # sheet D29


def test_calabrian_with_ecocure_adjusts_salt_only():
    lines = calc.spice_plan(W, True, CAL)
    m = by_name(lines)
    assert m["EcoCure #2"].planned == pytest.approx(20.88)
    assert m["Kosher salt, EcoCure #2 adjusted"].planned == pytest.approx(52.20)
    # total salt stays 3 %: 52.20 + 20.88 * 0.5 = 62.64
    assert m["Kosher salt, EcoCure #2 adjusted"].planned + 0.5 * m["EcoCure #2"].planned \
        == pytest.approx(W * 0.03)
    assert m["Sugar, white granulated"].planned == pytest.approx(20.88)
    assert calc.total_grams(lines) == pytest.approx(136.764)


def test_classic_matches_sheet():
    lines = calc.spice_plan(W, False, calc.blend_rates("Classic Italian"))
    assert calc.total_grams(lines) == pytest.approx(97.092)      # sheet D15
    assert by_name(lines)["Juniper berries, crushed"].planned == 5  # ROUNDUP(2.088*2)


def test_valtellina_built_from_intent_not_broken_sheet():
    lines = calc.spice_plan(W, False, calc.blend_rates("Bresaola della Valtellina"))
    assert calc.total_grams(lines) == pytest.approx(85.608)      # sheet D43 (values, not its formulas)
    lines_e = calc.spice_plan(W, True, calc.blend_rates("Bresaola della Valtellina"))
    m = by_name(lines_e)
    # only salt changes with EcoCure; sugar etc. stay weight × rate
    assert m["Turbinado or brown sugar"].planned == pytest.approx(10.44)
    assert m["Kosher salt, EcoCure #2 adjusted"].planned == pytest.approx(52.20)


def test_count_items_excluded_from_gram_total():
    lines = calc.spice_plan(1000, False, CAL)
    assert by_name(lines)["Bay leaf, powder"].planned == 1
    assert calc.total_grams(lines) == pytest.approx(30 + 30.5)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        calc.spice_plan(0, False, CAL)
    with pytest.raises(ValueError):
        calc.blend_rates("Nope")


# ---------------- stage 2: cure time ----------------

@pytest.mark.parametrize("cm,flat,tub", [
    # values read from the live genuineideas calculator on 2026-10-08
    (5, 4.8, 2.4), (10, 19.4, 9.7), (15, 43.6, 21.8), (17, 56.0, 28.0), (20, 77.5, 38.8),
])
def test_matches_genuineideas_calculator(cm, flat, tub):
    assert round(calc.cure_days_minimum(cm, "flat"), 1) == flat
    assert round(calc.cure_days_minimum(cm, "tubular"), 1) == tub


def test_this_batch_34_days():
    assert calc.cure_days(17, "tubular") == 34
    assert calc.cure_end_date(date(2026, 8, 15), 17, "tubular") == date(2026, 9, 18)


def test_exact_thickness_no_lookup_rounding_down():
    # the sheet's VLOOKUP gave 34 for 17.9 cm; formula gives more
    assert calc.cure_days(17.9, "tubular") == 38


def test_flat_is_twice_tubular():
    assert calc.cure_days_minimum(12, "flat") == pytest.approx(2 * calc.cure_days_minimum(12, "tubular"))


# ---------------- stage 3: drying ----------------

READ = [(date(2026, 9, 20), 2100), (date(2026, 9, 26), 2057), (date(2026, 9, 30), 2026),
        (date(2026, 10, 4), 1990), (date(2026, 10, 8), 1963)]


def test_target_weight_corrected_start():
    assert calc.target_gross_weight(2100, 35) == pytest.approx(1365.0)


def test_tare_makes_meat_loss_slightly_higher():
    # with 30 g packaging, gross target is 30 + 2070*0.65
    assert calc.target_gross_weight(2100, 35, tare_g=30) == pytest.approx(1375.5)
    assert calc.loss_pct(2100, 1365, tare_g=30) == pytest.approx(35.507, abs=1e-3)


def test_progress_today():
    assert calc.progress_to_target(2100, 1963, 35) == pytest.approx(137 / 735)
    assert calc.loss_pct(2100, 1963) == pytest.approx(6.524, abs=1e-3)


def test_eta_is_downward_and_reasonable():
    eta = calc.drying_eta(READ, 2100, 35)
    assert 7 < eta.grams_per_day < 8.5
    assert date(2026, 12, 10) < eta.eta_date < date(2027, 1, 10)


def test_eta_none_when_not_losing_weight():
    assert calc.drying_eta([(date(2026, 1, 1), 100), (date(2026, 1, 2), 101)], 100, 35) is None


# ---------------- mix summary ----------------

def _tuples(lines, attr="planned"):
    return [(l.name, l.unit, getattr(l, attr)) for l in lines]


def test_salt_pct_is_three_with_or_without_ecocure():
    for eco in (False, True):
        s = calc.mix_summary(_tuples(calc.spice_plan(W, eco, CAL)), W)
        assert s.salt_pct == pytest.approx(3.0)
        assert s.ecocure_pct == pytest.approx(1.0 if eco else 0.0)


def test_rome_classic_actuals():
    # Rome Classic as entered: 1990 g, EcoCure 19.9, salt 50
    lines = [("EcoCure #2", "pct", 19.9), ("Kosher salt, EcoCure #2 adjusted", "pct", 50),
             ("Sugar, white granulated", "pct", 19.9), ("Black pepper, powder", "pct", 9),
             ("Juniper berries, crushed", "per_kg", 4)]
    s = calc.mix_summary(lines, 1990)
    assert s.salt_pct == pytest.approx((50 + 9.95) / 19.9)     # 3.013 %
    assert s.sugar_pct == pytest.approx(1.0)
    assert s.seasoning_pct == pytest.approx(9 / 19.9)


def test_off_plan_flags_beyond_10_percent():
    flagged = calc.off_plan([("Rosemary", 1.99, 5), ("Salt", 49.75, 50), ("Thyme", 2.98, None)])
    assert [n for n, _ in flagged] == ["Rosemary"]
