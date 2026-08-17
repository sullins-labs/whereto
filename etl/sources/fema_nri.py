"""FEMA National Risk Index, county level.

Decomposed rather than collapsed. The single composite score is the number
most tools use, but the components are what people actually decide on: a
household weighing wildfire against hurricane wants both, not their average.
"""
from __future__ import annotations
import csv, io
from ..snapshot import fetch

# NRI column prefix -> our field. Each has a _RISKS (score) and _EALT (expected
# annual loss, dollars) variant; we take the score for comparison and the loss
# for the insurance model, because a score cannot be turned into a premium.
HAZARDS = {
    "WFIR": "wildfire",
    # Riverine flooding. The FeatureServer's own metadata calls this field
    # IFLD, but the csv export writes the RFLD alias, so read what the export
    # actually emits rather than what the layer describes.
    "RFLD": "flood_riverine",
    "CFLD": "flood_coastal",
    "HRCN": "hurricane",
    "TRND": "tornado",
    "ERQK": "earthquake",
    "HWAV": "heat_wave",
    "SWND": "strong_wind",
}


def _f(row: dict, key: str) -> float | None:
    v = (row.get(key) or "").strip()
    if v in ("", "NA", "NULL", "Not Applicable"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def extract() -> dict[str, dict]:
    # One flat csv now rather than a csv inside a zip; see config for why the
    # zip went away. utf-8-sig because the export carries a BOM.
    path = fetch("fema_nri", filename="nri_counties.csv")
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    out: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        fips = (row.get("STCOFIPS") or "").zfill(5)
        if len(fips) != 5:
            continue
        rec: dict = {
            "risk_score": _f(row, "RISK_SCORE"),
            "eal_total": _f(row, "EAL_VALT"),
            "social_vulnerability": _f(row, "SOVI_SCORE"),
            "community_resilience": _f(row, "RESL_SCORE"),
        }
        for prefix, field in HAZARDS.items():
            rec[field] = _f(row, f"{prefix}_RISKS")
            rec[f"{field}_eal"] = _f(row, f"{prefix}_EALT")
        # Riverine and coastal flood are separate hazards in NRI but one
        # concern to a household. Combined on expected loss, not on score,
        # because scores are percentile ranks and do not add.
        r, c = rec.get("flood_riverine_eal"), rec.get("flood_coastal_eal")
        rec["flood_eal"] = (r or 0) + (c or 0) if (r or c) else None
        out[fips] = rec
    return out
