"""Initial data required by Prusa's published filament-usage tracker.

This checks missing inputs only; it does not certify hardware compatibility or
fill a missing measurement. Prusa's AmountsInfo prefers actual values, then
nominal values, and its tracker requires both full weight and full length.
"""
import math


def missing_prusa_tracking_data(main):
    if main.get("material_class") != "FFF":
        return []
    missing = []
    for label, actual, nominal in (
        ("initial_weight", "actual_netto_full_weight", "nominal_netto_full_weight"),
        ("initial_length", "actual_full_length", "nominal_full_length"),
    ):
        value = main.get(actual, main.get(nominal))
        if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
            missing.append(label)
    return missing
