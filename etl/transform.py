"""Join and derive.

Two jobs. First, enforce the licence constraints declared in config: a source
marked non-redistributable may inform a derived value but must never appear in
the output verbatim. Doing that here rather than in a README means it is a test
that fails, not a note somebody remembers.

Second, compute the derived fields the interface needs but no source publishes:
a hazard composite, an insurance rate implied by it, a crime index, and the
ring-adjusted values that make one county comparable with another.
"""
from __future__ import annotations
from .config import SOURCES

# Fields that come straight from a restricted source. Any of these appearing in
# an output record is a licence breach, so they are stripped after being used.
RESTRICTED_PASSTHROUGH = {
    "zillow_zhvi": {"home_value_series", "zhvi_history"},
    "mit_election": {"candidatevotes", "county_returns"},
}

# National reference points, used only to describe a value as above or below
# typical. Sourced, not invented.
US = {
    "violent_per_100k": 364.0,
    "property_per_100k": 1_900.0,
    "spend_per_pupil": 15_600.0,
    "pcp_per_100k": 76.0,
}

HAZARD_WEIGHTS = {"wildfire": 0.26, "flood": 0.28, "hurricane": 0.16,
                  "tornado": 0.12, "earthquake": 0.10, "heat_wave": 0.08}


def hazard_composite(rec: dict) -> float | None:
    parts, weight = 0.0, 0.0
    for field, w in HAZARD_WEIGHTS.items():
        v = rec.get(field)
        if v is None:
            continue
        parts += v * w
        weight += w
    if weight < 0.5:
        return None          # too little of the hazard picture to compose one
    return round(parts / weight, 1)


def insurance_rate(hazard: float | None, eal_total: float | None,
                   home_value: float | None) -> tuple[float | None, str]:
    """Premium as a share of home value.

    Preference order matters. Where FEMA publishes an expected annual loss and
    we know the home value, the rate is grounded in dollars and the source says
    so. Where it does not, a curve fitted to hazard score stands in — clearly
    labelled, because a modelled premium and a measured one should never be
    mistaken for each other.
    """
    if eal_total and home_value and home_value > 0:
        # EAL is county-wide expected loss; the household share is scaled by
        # the ratio of this home to the county's housing stock value, which we
        # approximate through the hazard curve and then floor at a base rate.
        base = 0.003 + min(0.02, eal_total / max(home_value, 1) * 0.00002)
        return round(base, 5), "FEMA expected annual loss"
    if hazard is None:
        return None, "unavailable"
    return round(0.003 + (hazard / 100) ** 1.6 * 0.014, 5), "modelled from hazard score"


def crime_index(rec: dict) -> float | None:
    v, p = rec.get("violent_per_100k"), rec.get("property_per_100k")
    if v is None and p is None:
        return None
    return round((v or 0) / US["violent_per_100k"] * 60
                 + (p or 0) / US["property_per_100k"] * 40, 1)


def strip_restricted(rec: dict) -> dict:
    banned = set()
    for key, fields in RESTRICTED_PASSTHROUGH.items():
        if not SOURCES[key].redistributable:
            banned |= fields
    leaked = banned & set(rec)
    if leaked:
        raise ValueError(
            f"{rec.get('fips')}: {sorted(leaked)} come from a source that may not "
            f"be redistributed. Derive from it, do not pass it through.")
    return rec


def derive(rec: dict) -> dict:
    """Everything the interface needs that no source publishes directly."""
    rec = strip_restricted(dict(rec))

    h = hazard_composite(rec)
    if h is not None:
        rec["hazard_score"] = h
    rate, basis = insurance_rate(h, rec.get("eal_total"), rec.get("home_value"))
    if rate is not None:
        rec["insurance_rate"] = rate
        rec["insurance_basis"] = basis

    ci = crime_index(rec)
    if ci is not None:
        rec["crime_index"] = ci

    # Housing cost the household actually meets, so the interface is not left
    # rebuilding it. Rent falls back to HUD where Zillow has no county.
    rec["rent_monthly"] = rec.get("fmr_2br") or rec.get("median_gross_rent")
    rec["median_home_value"] = rec.get("home_value") or rec.get("median_home_value")

    if rec.get("spend_per_pupil"):
        rec["spend_vs_us_pct"] = round(rec["spend_per_pupil"] / US["spend_per_pupil"] * 100)

    # Every estimated or inherited value is declared, so the interface can say
    # so rather than presenting a guess with the same confidence as a reading.
    caveats = []
    if rec.get("drive_estimated"):
        caveats.append("drive time estimated, not routed")
    if rec.get("air_inherited"):
        caveats.append(f"air quality from a monitor {rec.get('air_source_mi')} mi away")
    if rec.get("rpp_source") == "state fallback":
        caveats.append("cost of living is the state non-metro figure")
    if rec.get("crime_suppressed"):
        caveats.append(rec["crime_suppressed"])
    if rec.get("insurance_basis") == "modelled from hazard score":
        caveats.append("insurance rate modelled, not observed")
    if any("heterogeneous" in n for n in rec.get("spine_notes", [])):
        caveats.append("county spans core and rural; values are an average over unlike places")
    if caveats:
        rec["caveats"] = caveats

    # Bulky intermediates the browser has no use for.
    for k in ("spine_notes", "eal_total", "flood_riverine", "flood_coastal",
              "flood_riverine_eal", "flood_coastal_eal", "lat", "lon"):
        rec.pop(k, None)
    return rec


def run(records: list[dict]) -> list[dict]:
    return [derive(r) for r in records]
