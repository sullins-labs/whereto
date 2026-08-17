"""FBI Crime Data Explorer, agency offenses aggregated to counties.

The hard part is not fetching, it is knowing when to refuse. Reporting is
voluntary and coverage varies enormously by agency and by year. A county where
agencies covering 40% of the population filed returns does not have a crime
rate — it has an artifact.

So this returns coverage alongside the numbers, and validate.py suppresses any
county below the floor. Publishing a confident-looking rate built on partial
returns is the single easiest way for a tool like this to mislead people.
"""
from __future__ import annotations
import csv, io
from collections import defaultdict
from ..snapshot import fetch

COVERAGE_FLOOR = 0.80


def aggregate(agencies: list[dict], county_pop: dict[str, int]) -> dict[str, dict]:
    """agencies: [{ori, county_fips, population_covered, violent, property, months_reported}]

    Agencies reporting fewer than twelve months are counted toward coverage
    pro rata, not excluded — a department that filed nine months of data is
    partial evidence, not no evidence, and dropping it overstates coverage.
    """
    tally = defaultdict(lambda: {"pop": 0, "violent": 0, "property": 0, "weighted_pop": 0})
    for a in agencies:
        fips = a.get("county_fips")
        if not fips:
            continue
        months = min(12, max(0, a.get("months_reported", 12)))
        if months == 0:
            continue
        share = months / 12
        t = tally[fips]
        t["pop"] += a.get("population_covered", 0)
        t["weighted_pop"] += a.get("population_covered", 0) * share
        # annualise partial-year returns before summing
        t["violent"] += (a.get("violent", 0) or 0) / share
        t["property"] += (a.get("property", 0) or 0) / share

    out = {}
    for fips, t in tally.items():
        total = county_pop.get(fips, 0)
        if not total:
            continue
        coverage = min(1.0, t["weighted_pop"] / total)
        rec = {"crime_coverage": round(coverage, 3),
               "crime_pop_covered": int(t["weighted_pop"])}
        if coverage >= COVERAGE_FLOOR:
            # rates use covered population, not county population — dividing
            # offenses from 60% of a county by 100% of its people halves the rate
            base = max(1, t["pop"])
            rec["violent_per_100k"] = round(t["violent"] / base * 100_000, 1)
            rec["property_per_100k"] = round(t["property"] / base * 100_000, 1)
        else:
            rec["crime_suppressed"] = f"coverage {coverage:.0%} below {COVERAGE_FLOOR:.0%} floor"
        out[fips] = rec
    return out


# ---------------------------------------------------------------- crosswalk

def ori_to_county(rows: list[dict]) -> dict[str, str]:
    """ORI (agency identifier) to county FIPS.

    Two wrinkles worth knowing about. State police and highway patrol agencies
    have an ORI but no meaningful county — their offenses are spread across a
    state and assigning them anywhere is arbitrary, so they are dropped rather
    than dumped into the capital's county. And a handful of agencies serve more
    than one county; they are attributed to the one holding the largest share
    of their covered population, which the reference file provides.
    """
    out: dict[str, str] = {}
    best_share: dict[str, float] = {}
    for r in rows:
        ori = (r.get("ORI9") or r.get("ORI") or "").strip()
        if not ori:
            continue
        agency_type = (r.get("AGENCY_TYPE_NAME") or r.get("agency_type") or "").lower()
        if any(k in agency_type for k in ("state police", "highway patrol", "state agency")):
            continue
        fips = ((r.get("FIPS_ST") or "").zfill(2) + (r.get("FIPS_COUNTY") or "").zfill(3))
        if len(fips) != 5 or not fips.isdigit():
            continue
        try:
            share = float(r.get("POPULATION") or r.get("population") or 0)
        except ValueError:
            share = 0.0
        if ori not in out or share > best_share.get(ori, -1):
            out[ori] = fips
            best_share[ori] = share
    return out


def extract(county_pop: dict[str, int], year: int = 2025) -> dict[str, dict]:
    """Fetch agency returns state by state, map to counties, aggregate.

    One call per state rather than one per agency: there are roughly 18,000
    agencies and 51 states, and the per-agency pattern would blow the daily
    quota before finishing the alphabet.
    """
    # Fails immediately rather than retrying four times against an endpoint
    # already proven gone. The investigation is written up on the fbi_cde entry
    # in config.py; the short version is that the bulk agency download was
    # withdrawn, summarized/state now returns state aggregates instead of
    # agency rows, and county figures would cost one call per agency against
    # roughly 43,000 agencies.
    raise RuntimeError(
        "FBI county-level crime is not obtainable from the current CDE API. "
        "See the notes on the fbi_cde source in config.py before spending an "
        "afternoon on it. Crime reads 'not reported' in the interface, which "
        "is accurate."
    )

    xw_path = fetch(                                        # noqa: F821 - unreachable
        "fbi_cde",
        "https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/{state}",
        filename="agency_reference.csv",
    )
    crosswalk = ori_to_county(list(csv.DictReader(
        io.StringIO(xw_path.read_text(encoding="utf-8-sig", errors="replace")))))

    agencies: list[dict] = []
    states = sorted({f[:2] for f in county_pop})
    for st in states:
        path = fetch(
            "fbi_cde",
            f"https://api.usa.gov/crime/fbi/cde/summarized/state/{st}/all",
            filename=f"cde_{st}_{year}.csv",
            params={"from": f"01-{year}", "to": f"12-{year}"},
        )
        for r in csv.DictReader(io.StringIO(path.read_text(errors="replace"))):
            ori = (r.get("ori") or "").strip()
            fips = crosswalk.get(ori)
            if not fips:
                continue
            def n(k):
                try:
                    return float(r.get(k) or 0)
                except ValueError:
                    return 0.0
            agencies.append({
                "ori": ori,
                "county_fips": fips,
                "population_covered": int(n("population")),
                "violent": n("violent_crime"),
                "property": n("property_crime"),
                "months_reported": int(n("months_reported") or 12),
            })
    return aggregate(agencies, county_pop)
