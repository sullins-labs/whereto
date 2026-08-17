"""Quality gates.

The pipeline refuses to publish rather than publishing something wrong. Every
gate here exists because the alternative — a plausible-looking number with no
support underneath it — is worse than a gap, and much harder to notice.

Gates are either BLOCKING (build fails) or WARNING (build proceeds, note is
attached to the record and surfaced in the interface).
"""
from __future__ import annotations
from dataclasses import dataclass

BLOCKING, WARNING = "blocking", "warning"

# Below this share of a county's population covered by reporting agencies, an
# FBI crime figure is not a rate, it is an artifact of who filed paperwork.
CRIME_COVERAGE_FLOOR = 0.80

# Plausibility envelopes. Wide on purpose: these catch unit errors, sign flips
# and null sentinels leaking through, not unusual places.
BOUNDS = {
    "median_home_value":   (15_000, 6_000_000),
    "median_gross_rent":   (250, 12_000),
    "median_household_income": (10_000, 500_000),
    "rpp":                 (70, 145),
    "property_effective":  (0.0, 4.0),
    "sales_combined":      (0.0, 12.0),
    "income_top_rate":     (0.0, 14.0),
    "summer_high_f":       (45, 120),
    "winter_low_f":        (-35, 75),
    "violent_per_100k":    (0, 4_000),
    "property_per_100k":   (0, 15_000),
    "insurance_rate":      (0.001, 0.05),
    "drive_min":           (2, 240),
    # Deliberately wide at the top. Property-rich, student-poor districts are
    # real: McMullen County in Texas spends over $140,000 a pupil across 283
    # pupils, and Alpine County in California has 61 pupils in total. A tighter
    # ceiling would reject the country as it is rather than catch a mistake.
    # This is here to catch a figure in thousands or a whole-district total
    # mistaken for a per-pupil one.
    "spend_per_pupil":     (3_000, 250_000),
}

REQUIRED = [
    "fips", "name", "state", "ring", "anchor_name",
    "median_home_value", "rpp", "summer_high_f", "winter_low_f",
]


@dataclass
class Finding:
    level: str
    place: str
    field: str
    message: str


def check_record(rec: dict) -> list[Finding]:
    out: list[Finding] = []
    where = rec.get("fips", "?")

    for f in REQUIRED:
        if rec.get(f) is None:
            out.append(Finding(BLOCKING, where, f, "required field is missing"))

    for f, (lo, hi) in BOUNDS.items():
        v = rec.get(f)
        if v is None:
            continue
        if not isinstance(v, (int, float)):
            out.append(Finding(BLOCKING, where, f, f"expected a number, got {type(v).__name__}"))
        elif not (lo <= v <= hi):
            out.append(Finding(BLOCKING, where, f, f"{v} is outside {lo}-{hi}; likely a unit error or a null sentinel"))

    cov = rec.get("crime_coverage")
    if cov is not None and cov < CRIME_COVERAGE_FLOOR:
        out.append(Finding(
            WARNING, where, "violent_per_100k",
            f"reporting coverage {cov:.0%} is below the {CRIME_COVERAGE_FLOOR:.0%} floor; "
            f"crime suppressed for this county rather than published from partial returns"))

    # Internal consistency: rent and home value should not disagree wildly.
    hv, rent = rec.get("median_home_value"), rec.get("median_gross_rent")
    if hv and rent:
        ratio = hv / (rent * 12)
        if not (4 <= ratio <= 60):
            out.append(Finding(WARNING, where, "median_home_value",
                               f"price-to-rent ratio of {ratio:.0f} is implausible; check the join"))

    if rec.get("ring") in (0, 1) and (rec.get("land_sq_mi") or 0) > 400:
        out.append(Finding(WARNING, where, "ring",
                           "county spans core and rural; ring is an average over unlike places"))
    return out


def check_dataset(records: list[dict]) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    for r in records:
        findings.extend(check_record(r))

    stats = {
        "records": len(records),
        "blocking": sum(1 for f in findings if f.level == BLOCKING),
        "warnings": sum(1 for f in findings if f.level == WARNING),
    }

    # Coverage gates on the dataset as a whole. A build that quietly drops
    # half the country still produces a working website, which is precisely
    # why this has to be checked rather than eyeballed.
    if len(records) < 2_800:
        findings.append(Finding(BLOCKING, "dataset", "count",
                                f"only {len(records)} counties; expected roughly 3,144"))
    rings = {r.get("ring") for r in records}
    if not {0, 1, 2, 3, 4}.issubset(rings):
        findings.append(Finding(BLOCKING, "dataset", "ring",
                                f"not all rings present: found {sorted(x for x in rings if x is not None)}"))

    for f in ("median_home_value", "rpp", "summer_high_f"):
        filled = sum(1 for r in records if r.get(f) is not None)
        if records and filled / len(records) < 0.90:
            findings.append(Finding(BLOCKING, "dataset", f,
                                    f"only {filled/len(records):.0%} of counties have a value"))
    stats["blocking"] = sum(1 for f in findings if f.level == BLOCKING)
    return findings, stats


def report(findings: list[Finding], stats: dict) -> str:
    lines = [f"records {stats['records']}  blocking {stats['blocking']}  warnings {stats['warnings']}"]
    for level in (BLOCKING, WARNING):
        subset = [f for f in findings if f.level == level]
        if not subset:
            continue
        lines.append(f"\n{level.upper()} ({len(subset)}):")
        for f in subset[:25]:
            lines.append(f"  {f.place:<8} {f.field:<24} {f.message}")
        if len(subset) > 25:
            lines.append(f"  ... and {len(subset)-25} more")
    return "\n".join(lines)
