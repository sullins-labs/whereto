"""HRSA health workforce shortage designations.

A subtlety worth stating rather than smoothing over: HPSA is a *designation*,
not a measurement. A county is designated because somebody applied for the
designation. Absence of one means no application succeeded, which is not the
same as good access — rural counties with no clinic to apply on their behalf
can look identical to well-served suburbs.

So the score is built from the provider-to-population ratio in the Area Health
Resources File, which exists for every county, and the HPSA score is used only
to sharpen it where a designation exists. Designation alone would have made
the absence of a form look like the presence of a doctor.
"""
from __future__ import annotations
import csv, io
from collections import defaultdict
from ..snapshot import fetch

# HRSA HPSA scores run 0-25, higher meaning greater shortage.
HPSA_MAX = 25.0


def build(ratios: dict[str, dict], hpsa: list[dict]) -> dict[str, dict]:
    """ratios: {fips: {primary_care_physicians, mental_health_providers, population}}
    hpsa:   [{county_fips, discipline, score, status}]
    """
    designations = defaultdict(dict)
    for h in hpsa:
        if (h.get("status") or "").lower() not in ("designated", "proposed for withdrawal"):
            continue
        f, disc = h.get("county_fips"), (h.get("discipline") or "").lower()
        if not f:
            continue
        prev = designations[f].get(disc)
        if prev is None or (h.get("score") or 0) > prev:
            designations[f][disc] = h.get("score") or 0

    out = {}
    for fips, r in ratios.items():
        pop = r.get("population") or 0
        if pop <= 0:
            continue
        pcp = r.get("primary_care_physicians") or 0
        mh = r.get("mental_health_providers") or 0
        rec = {
            "pcp_per_100k": round(pcp / pop * 100_000, 1),
            "mental_health_per_100k": round(mh / pop * 100_000, 1),
        }
        d = designations.get(fips, {})
        if d:
            rec["hpsa_primary_care"] = d.get("primary care")
            rec["hpsa_mental_health"] = d.get("mental health")
            rec["hpsa_designated"] = True
        else:
            rec["hpsa_designated"] = False
            rec["hpsa_note"] = (
                "no designation on file; this reflects whether an application was "
                "made, not necessarily whether access is adequate")
        out[fips] = rec
    return out


def extract(ratios: dict[str, dict]) -> dict[str, dict]:
    path = fetch("hrsa_hpsa", filename="hpsa_primary_care.csv")
    rows = []
    for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))):
        fips = (r.get("Common County FIPS Code") or r.get("County FIPS") or "").zfill(5)
        if len(fips) != 5:
            continue
        try:
            score = float(r.get("HPSA Score") or 0)
        except ValueError:
            score = 0.0
        rows.append({
            "county_fips": fips,
            "discipline": (r.get("HPSA Discipline Class") or "").strip(),
            "score": score,
            "status": (r.get("HPSA Status") or "").strip(),
        })
    return build(ratios, rows)
