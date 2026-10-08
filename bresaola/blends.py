"""Master blend table, copied from the workbook sheet '1. Spice mix'.

Rates are either a fraction of meat weight ("pct") or a count per kg ("per_kg").
EcoCure and salt are handled by calc.spice_plan, not listed here.
Editing this table never changes existing projects: rates are snapshotted
onto each project when it is created.
"""

ECOCURE_RATE = 0.01          # 1 % of meat weight
ECOCURE_SALT_FRACTION = 0.5  # half of EcoCure #2 is salt
SALT_RATE = 0.03             # 3 % of meat weight, total salt incl. EcoCure's share

BLENDS = {
    "Classic Italian": [
        ("Sugar, white granulated", "pct", 0.01),
        ("Black pepper, powder", "pct", 0.004),
        ("Dried rosemary, crushed powder", "pct", 0.001),
        ("Dried thyme, crushed powder", "pct", 0.0015),
        ("Juniper berries, crushed", "per_kg", 2),
    ],
    "Spicy Calabrian": [
        ("Sugar, white granulated", "pct", 0.01),
        ("Black pepper, powder", "pct", 0.0025),
        ("Red pepper, flakes", "pct", 0.002),
        ("Fennel seed, powder", "pct", 0.005),
        ("Cayenne pepper, powder", "pct", 0.002),
        ("Calabrian pepper, powder", "pct", 0.003),
        ("Smoked paprika, powder", "pct", 0.002),
        ("Garlic, granulated", "pct", 0.004),
        ("Bay leaf, powder", "per_kg", 1),
    ],
    "Bresaola della Valtellina": [
        ("Turbinado or brown sugar", "pct", 0.005),
        ("Garlic, granulated", "pct", 0.001),
        ("Black pepper, ground", "pct", 0.002),
        ("Juniper berry, crushed", "pct", 0.001),
        ("Nutmeg", "pct", 0.00075),
        ("Cinnamon", "pct", 0.0005),
        ("Rosemary, dried and ground", "pct", 0.0005),
        ("Clove, ground", "pct", 0.00025),
        ("Bay leaf", "per_kg", 1),
    ],
}
