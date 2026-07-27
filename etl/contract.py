"""The output contract.

The single definition of what the pipeline emits and what the browser expects.
Both sides import their understanding of the shape from here — the ETL to
validate before writing, the site to check `contract_version` before trusting
what it loaded. A silent shape change is how a site starts rendering nulls
that look like real zeroes.
"""
from __future__ import annotations

VERSION = 1

# field -> (type, required, description)
PLACE_FIELDS: dict[str, tuple[type | tuple, bool, str]] = {
    "fips":            (str,   True,  "5-digit county FIPS, the primary key"),
    "name":            (str,   True,  "county name"),
    "state":           (str,   True,  "two-letter postal code"),
    "ring":            (int,   True,  "0 core .. 4 rural, derived in spine.py"),
    "anchor_name":     (str,   True,  "the metro this ring is measured against"),
    "population":      (int,   True,  ""),
    "density":         ((int, float), False, "people per square mile"),
    "land_sq_mi":      ((int, float), False, ""),
    "drive_min":       (int,   True,  "to the anchor centre"),

    "median_home_value": ((int, float), True,  ""),
    "rent_monthly":      ((int, float), False, "HUD FMR 2-bed, else ACS median gross rent"),
    "median_household_income": ((int, float), False, ""),
    "rpp":               ((int, float), True,  "cost of living, US = 100"),
    "rpp_source":        (str,   False, "metro | state fallback"),

    "summer_high_f":   ((int, float), True,  "July mean daily maximum"),
    "winter_low_f":    ((int, float), True,  "January mean daily minimum"),
    "precip_in":       ((int, float), False, ""),

    "hazard_score":    ((int, float), False, "composite, 0-100"),
    "wildfire":        ((int, float), False, ""),
    "flood":           ((int, float), False, ""),
    "hurricane":       ((int, float), False, ""),
    "tornado":         ((int, float), False, ""),
    "earthquake":      ((int, float), False, ""),
    "heat_wave":       ((int, float), False, ""),
    "insurance_rate":  ((int, float), False, "share of home value per year"),
    "insurance_basis": (str,   False, "FEMA expected annual loss | modelled from hazard score"),

    "violent_per_100k":  ((int, float), False, "absent where reporting coverage is too low"),
    "property_per_100k": ((int, float), False, ""),
    "crime_index":       ((int, float), False, ""),
    "crime_coverage":    ((int, float), False, "0-1 share of population whose agencies reported"),

    "spend_per_pupil":   ((int, float), False, ""),
    "pupils_per_teacher": ((int, float), False, ""),
    "pcp_per_100k":      ((int, float), False, "primary care physicians"),
    "air_days_over":     ((int, float), False, "days above the national standard"),

    "local_lean":      ((int, float), False, "two-party presidential share, a position not a rating"),
    "state_lean":      ((int, float), False, "enacted-policy position"),

    "income_top_rate":     ((int, float), False, ""),
    "sales_combined":      ((int, float), False, ""),
    "property_effective":  ((int, float), False, ""),
    "retire_code":         (int,  False, "0 none | 1 exempts all | 2 exempts SS | 3 taxes part of SS"),
    "prek_coverage_pct":   ((int, float), False, ""),
    "tuition_instate":     ((int, float), False, ""),
    "grant_aid_per_student": ((int, float), False, ""),
    "medicaid_expansion":  (bool, False, ""),
    "paid_family_leave":   (bool, False, ""),
    "senior_property_relief": ((int, float), False, ""),

    "caveats":         (list,  False, "what this record does not know, shown in the interface"),
}

REQUIRED = [k for k, (_, req, _) in PLACE_FIELDS.items() if req]


def check(rec: dict) -> list[str]:
    problems = []
    for field, (typ, required, _) in PLACE_FIELDS.items():
        if field not in rec or rec[field] is None:
            if required:
                problems.append(f"{field}: required, missing")
            continue
        if not isinstance(rec[field], typ):
            problems.append(f"{field}: expected {typ}, got {type(rec[field]).__name__}")
    unknown = set(rec) - set(PLACE_FIELDS)
    if unknown:
        problems.append(f"unexpected fields: {sorted(unknown)}")
    return problems


def envelope(places: list[dict], sources: list[dict], built_at: str,
             warnings: list | None = None, failures: dict | None = None) -> dict:
    return {
        "contract_version": VERSION,
        "built_at": built_at,
        "place_count": len(places),
        "sources": sources,
        "stage_failures": failures or {},
        "warnings": warnings or [],
        "places": places,
    }
