"""Curated statute inputs.

Loads the reviewed YAML and enforces its own provenance rules: a file without
`meta.as_of` and `meta.sources` is rejected, and a stale one warns. Hand-
maintained data that nobody has to justify is how a model drifts.
"""
from __future__ import annotations
from datetime import date
import yaml
from ..config import CURATED_FILES

MAX_AGE_DAYS = 400


def load(name: str) -> dict:
    path = CURATED_FILES[name]
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; curated inputs are required, not optional")
    doc = yaml.safe_load(path.read_text())
    meta = doc.get("meta") or {}
    if not meta.get("as_of") or not meta.get("sources"):
        raise ValueError(f"{path}: every curated file needs meta.as_of and meta.sources")
    age = (date.today() - meta["as_of"]).days if isinstance(meta["as_of"], date) else 0
    if age > MAX_AGE_DAYS:
        doc["_stale"] = f"{name} last reviewed {age} days ago; tax law has moved since"
    return doc


def extract(county_state: dict[str, str]) -> dict[str, dict]:
    tax = load("state_tax")["states"]
    svc = load("state_services")["states"]
    out = {}
    for fips, st in county_state.items():
        rec = {}
        if st in tax:
            t = tax[st]
            rec.update({
                "income_top_rate": t["income_top_rate"],
                "sales_combined": t["sales_combined"],
                # property_effective is no longer read here. It is measured per
                # county from ACS, because it was never statute; it is what
                # households in a place actually paid.
                "retire_code": t["retire_code"],
            })
        if st in svc:
            s = svc[st]
            rec.update({
                "prek_coverage_pct": s["prek_coverage_pct"],
                "tuition_instate": s["tuition_instate"],
                "grant_aid_per_student": s["grant_aid_per_student"],
                "medicaid_expansion": s["medicaid_expansion"],
                "paid_family_leave": s["paid_family_leave"],
                # Renamed with its units, because the meaning changed from an
                # index out of 100 to a share of the local property tax bill.
                # An old reader meeting a new file now sees a missing field and
                # credits nothing, rather than reading 0.25 as an index and
                # quietly under-crediting by a factor of a hundred.
                "senior_property_relief_pct": s["senior_property_relief_pct"],
            })
        if rec:
            out[fips] = rec
    return out
