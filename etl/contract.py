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
    "drive_min":       (int,   True,  "to the anchor center"),

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
    "insurance_basis": (str,   False, "FEMA expected annual loss | modeled from hazard score"),

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
    "median_real_estate_taxes": ((int, float), False,
                                 "ACS median paid, owner-occupied; the numerator "
                                 "of property_effective, published so the rate "
                                 "can be checked rather than taken on trust"),
    "property_effective":  ((int, float), False,
                            "taxes paid over home value, per county, from ACS"),
    "retire_code":         (int,  False, "0 none | 1 exempts all | 2 exempts SS | 3 taxes part of SS"),
    "prek_coverage_pct":   ((int, float), False, ""),
    "tuition_instate":     ((int, float), False, ""),
    "grant_aid_per_student": ((int, float), False, ""),
    "medicaid_expansion":  (bool, False, ""),
    "paid_family_leave":   (bool, False, ""),
    "senior_property_relief_pct": ((int, float), False,
                                   "share of the county property tax bill a "
                                   "qualifying senior household avoids, 0 to 1"),

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


# Keys the site reads off the payload itself rather than off a place. Losing
# one of these does not show up as a missing value; it throws on boot.
ENVELOPE_KEYS = ["contract_version", "built_at", "place_count", "sources",
                 "stage_failures", "warnings", "places"]


def check_envelope(payload: dict) -> list[str]:
    """Verify the wrapper, not the contents. validate.py checks every place
    and would pass a payload with all 3,135 of them and no place_count."""
    problems = [f"missing envelope key: {k}"
                for k in ENVELOPE_KEYS if k not in payload]
    if payload.get("contract_version") != VERSION:
        problems.append(
            f"contract_version is {payload.get('contract_version')!r}, expected {VERSION}")
    if payload.get("place_count") != len(payload.get("places") or []):
        problems.append(
            f"place_count {payload.get('place_count')!r} does not match "
            f"{len(payload.get('places') or [])} places")
    return problems


def envelope(places: list[dict], sources: list[dict], built_at: str,
             warnings: list | None = None, failures: dict | None = None,
             withheld: list | None = None) -> dict:
    """The published payload. Build it here and nowhere else.

    This existed and was never called: build.py assembled the same dict by
    hand and the two drifted, losing place_count. The site reads that key on
    boot, so the first real dataset rendered zero places and threw before it
    got as far as the table. Nothing caught it, because every gate in this
    pipeline checks the places and none of them check the envelope around them.
    """
    return {
        "contract_version": VERSION,
        "built_at": built_at,
        "place_count": len(places),
        "sources": sources,
        "stage_failures": failures or {},
        "warnings": warnings or [],
        "withheld": withheld or [],
        "places": places,
    }
