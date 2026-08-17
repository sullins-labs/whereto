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
    path = fetch("nces_ccd", filename="sdf_lea_finance.zip")
    districts, crosswalk = [], []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            # The F-33 release ships one tab-delimited .txt, not a .csv. Looking
            # only for .csv found nothing in a zip that opened perfectly well.
            if not name.lower().endswith((".csv", ".txt")):
                continue
            text = z.read(name).decode("utf-8-sig", errors="replace")
            head = text.split("\n", 1)[0]
            delim = "\t" if head.count("\t") > head.count(",") else ","
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
            if not rows:
                continue
            cols = set(rows[0])

            if {"LEAID", "TOTALEXP"} <= cols:
                for r in rows:
                    districts.append({
                        "leaid": r["LEAID"],
                        "enrolment": _num(r.get("V33") or r.get("MEMBER")),
                        "total_expenditure": _num(r.get("TOTALEXP")),
                        # F-33 is a finance collection and carries no teacher
                        # count, so pupils_per_teacher stays null rather than
                        # being invented from a ratio somewhere else.
                        "teachers": _num(r.get("TOTTCH") or r.get("TEACHERS")),
                    })

            # The county code is CONUM here and CNTY in the LEA universe file.
            # Both name the same thing, and in this release it travels in the
            # same file as the finance columns, so one fetch covers both halves.
            county_col = "CONUM" if "CONUM" in cols else "CNTY" if "CNTY" in cols else None
            if county_col and "LEAID" in cols:
                for r in rows:
                    enrol = _num(r.get("V33") or r.get("MEMBER")) or 0
                    crosswalk.append({
                        "leaid": r["LEAID"],
                        "county_fips": (r.get(county_col) or "").strip().zfill(5),
                        # A district sits in one county here, so its whole roll
                        # counts toward that county and the share works out to 1.
                        "students_in_county": enrol,
                    })
    return aggregate(districts, crosswalk)
