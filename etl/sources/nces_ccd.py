"""NCES Common Core of Data — school districts aggregated to counties.

The interesting problem here is that school districts do not nest inside
counties. A district can straddle two or three of them; a county can contain
forty. There is no clean join, only a defensible one.

Approach: enrolment-weighted aggregation using the NCES LEA-to-county
crosswalk. A district contributes to a county in proportion to the share of
its students who live there. Averaging district-level rates unweighted would
let a 200-pupil rural district count the same as a 90,000-pupil urban one,
which is how school "rankings" end up saying things nobody recognises.

What is emitted is spending and staffing, not quality. Outcome measures exist
but are so confounded by household income that publishing them as a school
score mostly relabels affluence.
"""
from __future__ import annotations
import csv, io, zipfile
from collections import defaultdict
from ..snapshot import fetch


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    # CCD uses negative codes for missing, suppressed and not-applicable
    return None if f < 0 else f


def aggregate(districts: list[dict], crosswalk: list[dict]) -> dict[str, dict]:
    """districts: [{leaid, enrolment, total_expenditure, teachers, ...}]
    crosswalk:  [{leaid, county_fips, students_in_county}]
    """
    by_lea = {d["leaid"]: d for d in districts}
    tally = defaultdict(lambda: {"students": 0.0, "spend": 0.0, "teachers": 0.0, "districts": 0})

    for x in crosswalk:
        d = by_lea.get(x["leaid"])
        if not d:
            continue
        share_students = x.get("students_in_county") or 0
        if share_students <= 0:
            continue
        enrol = d.get("enrolment") or 0
        share = share_students / enrol if enrol else 0
        if share <= 0:
            continue
        t = tally[x["county_fips"]]
        t["students"] += share_students
        t["spend"] += (d.get("total_expenditure") or 0) * share
        t["teachers"] += (d.get("teachers") or 0) * share
        t["districts"] += 1

    out = {}
    for fips, t in tally.items():
        if t["students"] < 50:
            continue      # too few pupils for a stable per-pupil figure
        out[fips] = {
            "school_enrolment": int(t["students"]),
            "spend_per_pupil": round(t["spend"] / t["students"]) if t["students"] else None,
            "pupils_per_teacher": round(t["students"] / t["teachers"], 1) if t["teachers"] else None,
            "school_districts": t["districts"],
        }
    return out


def extract() -> dict[str, dict]:
    path = fetch("nces_ccd", filename="ccd_lea_finance.zip")
    districts, crosswalk = [], []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = z.read(name).decode("utf-8-sig", errors="replace")
            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows:
                continue
            cols = set(rows[0])
            if {"LEAID", "TOTALEXP"} <= cols:
                for r in rows:
                    districts.append({
                        "leaid": r["LEAID"],
                        "enrolment": _num(r.get("V33") or r.get("MEMBER")),
                        "total_expenditure": _num(r.get("TOTALEXP")),
                        "teachers": _num(r.get("TOTTCH") or r.get("TEACHERS")),
                    })
            elif {"LEAID", "CNTY"} <= cols:
                for r in rows:
                    crosswalk.append({
                        "leaid": r["LEAID"],
                        "county_fips": (r.get("CNTY") or "").zfill(5),
                        "students_in_county": _num(r.get("MEMBER")) or 0,
                    })
    return aggregate(districts, crosswalk)
