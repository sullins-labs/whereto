"""Political readings, descriptive and never evaluative.

Two distinct measures, kept apart on purpose because they answer different
questions and often disagree:

  state_lean  what the legislature has enacted, the laws that follow you into
              a rural county
  local_lean  how the county has actually voted, who your neighbors are

The interface scores both as distance from what the user asked for, so nothing
here is ranked good or bad. That neutrality has to hold in the data layer too:
the scale is a position, not a score, and it is symmetric by construction.

Sources and their roles
-----------------------
PRIMARY, and the only thing that ever reaches a score: MIT Election Data and
Science Lab county presidential returns, from Harvard Dataverse. Cleaned,
versioned, DOI'd and licensed. CC BY-NC, so values are derived and the file is
never republished.

VALIDATION ONLY: tonmcg/US_County_Level_Election_Results_08-24, scraped from
news feeds. It exists here to disagree with MEDSL, and its value is precisely
that its lineage is independent: MEDSL derives from state-certified returns,
tonmcg from network calls. Two datasets built the same way agreeing tells you
nothing. This must never feed scoring under any circumstance, outage included,
which the publish-time assertion in build.py enforces rather than trusts.

Rejected alternatives, so this is not relitigated
-------------------------------------------------
MEDSL/county-returns on GitHub covers 2000-2016 and was last touched in 2020.
It is missing both cycles this module averages. Stale.

MEDSL/2024-elections-official is precinct level, same lineage as the Dataverse
file, and would need precinct-to-county aggregation this project would then
have to QA itself. Not a shortcut; a different project.

jaytimm/PresElectionResults is derived from tonmcg and inherits its provenance
question without answering it.

The provenance ceiling, if county-level MEDSL publication ever stops, is
aggregating the MEDSL precinct repos or OpenElections, both built from
certified sources. That is a documented future path, not a fallback to reach
for during an outage.

Integrity outranks availability. If the canonical copy is unreachable, the
honest answer is that politics is not reported, which is what need() renders.
"""
from __future__ import annotations
import csv, io
import requests
from ..snapshot import fetch, USER_AGENT

CYCLES = (2020, 2024)

# Harvard Dataverse now gates this dataset behind a mandatory guestbook
# (dataset guestbookId 458, "General guestbook": name/email/institution/
# position, no custom questions). A bare GET to /api/access/datafile/{id}
# answers 400 "You may not download this file without the required Guestbook
# response", even though the file itself is CC0 and the file id (13573089,
# still current in dataset version 20.0 as of 2026-08-17) has not changed.
# This is not the stale-id problem the 2026-08-16 outage note anticipated.
#
# The documented workaround (Dataverse API guide, "Guestbooks") is a POST to
# the same access endpoint carrying the answers, which returns a short-lived
# signed URL to GET instead. That signed URL, not the bare datafile id, is
# what actually varies run to run, so it is resolved fresh here rather than
# stored in config.py as a URL.
# Dataverse's deposit record badges this file CC0 1.0; config.py still
# classifies it CC BY-NC, redistributable=False, per MEDSL's own stated
# terms, and that is deliberate. The two badges answer different questions:
# CC0 is a Dataverse platform default on the deposit record, not a MEDSL
# statement about the data. The stricter reading costs nothing to keep,
# since this module only derives lean values and never republishes the
# file, and it would unlock nothing anyway, since Open-Meteo and the MIT
# Living Wage Calculator are already non-commercial-only. A depositor
# gating the file behind a mandatory guestbook is not treating it as
# unrestricted. Only a direct answer from MEDSL changes this, not the
# deposit badge. Decided 2026-08-17; do not flip on the CC0 badge alone.
MIT_GUESTBOOK_RESPONSE = {
    "name": "WhereToLive ETL",
    "email": "support@sullinslabs.com",
    "institution": "sullinslabs.com",
    "position": "Developer",
    "answers": [],
}


def _mit_election_signed_url() -> str:
    """Resolve the current guestbook-gated file to a one-time signed URL.

    Called on every run rather than cached: the signed URL embeds an
    ~1-hour expiry, so caching it would only reproduce the outage this
    exists to work around. fetch()'s own archive is still what prevents
    re-downloading the 10MB file on every build; this just re-earns the
    right to ask for it each time.
    """
    from ..config import SOURCES
    src = SOURCES["mit_election"]
    resp = requests.post(
        src.url,
        json={"guestbookResponse": MIT_GUESTBOOK_RESPONSE},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["data"]["signedUrl"]


# Columns each source must present. A 200 carrying the wrong shape is the
# failure mode that looks most like success, so it is checked rather than
# assumed. tonmcg 2016 predates its own schema change and is listed separately.
MEDSL_COLUMNS = {"year", "state", "county_fips", "candidate", "party",
                 "candidatevotes", "totalvotes", "mode"}
TONMCG_COLUMNS = {
    2016: {"combined_fips", "votes_dem", "votes_gop", "total_votes", "state_abbr"},
    2020: {"state_name", "county_fips", "votes_gop", "votes_dem", "total_votes"},
    2024: {"state_name", "county_fips", "votes_gop", "votes_dem", "total_votes"},
}

# Alaska does not publish presidential returns by borough. It publishes them by
# state house district, and the district identifiers are not merely different
# from borough identifiers, they overlap: district 13 is 02013 and so is
# Aleutians East Borough, district 20 is 02020 and so is Anchorage
# Municipality. A FIPS join therefore does not lose Alaska, it silently files
# one legislative district's votes under a whole anchor metro. Anchorage,
# Fairbanks-College, Juneau and Ketchikan are all anchors, so this would have
# been wrong somewhere visible. Excluded until a district-to-borough
# apportionment exists and is tested; until then need() renders "not reported".
# Connecticut retired county government for statistical purposes years ago,
# and in 2022 the Census Bureau followed by replacing the old county FIPS
# (09001-09015) with nine planning-region FIPS (09110-09190) as the current
# geography. The spine adopted the new codes, since that is what Census now
# publishes. MEDSL's presidential returns still key to the old counties,
# because that is what election administration in Connecticut is organized
# around, and the two geographies do not nest: planning regions cut across
# town lines in ways that do not reduce to a simple FIPS remap. A correct
# crosswalk exists in principle -- allocate each town's votes to its
# planning region and re-aggregate -- but that is a town-level vote
# allocation project in its own right, not a lookup table, and it is not
# something to improvise mid-build. It is a documented future path, the same
# status as the Alaska district apportionment above, not a fallback to reach
# for during a run. Until it exists and is tested, local_lean for Connecticut
# counties is simply not reported, exactly like Alaska.
EXCLUDED_STATES = {
    "02": ("Alaska", "returns are by state house district, and two district ids "
                     "collide with real borough ids (02013, 02020)"),
    "09": ("Connecticut", "abolished county government for statistical purposes; "
                          "Census replaced the old county FIPS (09001-09015) with "
                          "nine planning-region FIPS (09110-09190) in 2022, and "
                          "MEDSL's returns still key to the old counties, so no "
                          "join exists"),
    # Puerto Rico is not a Connecticut-shaped problem: there is no join to fix
    # and no crosswalk to build. Puerto Rico does not participate in United
    # States presidential elections, so county-level presidential returns for
    # its 78 municipios do not exist, in MEDSL or anywhere else, and never
    # will under this module's method. local_lean here is specifically a
    # two-party presidential vote share; that quantity has no referent for
    # Puerto Rico. Excluded permanently, not pending anything.
    "72": ("Puerto Rico", "does not vote in United States presidential elections, "
                          "so county-level presidential returns do not exist for "
                          "its municipios and never will"),
}

# Two-party share divergence between the primary and the validation source.
WARN_PP, FAIL_PP, FAIL_SHARE = 2.0, 5.0, 0.01
MIN_COUNTIES_PER_CYCLE = 3_000


class GateFailure(RuntimeError):
    """A validation gate refused the data. Blocks the build by design."""


def _fips(v) -> str:
    """Zero-pad to five. Sources disagree about whether a FIPS is a number."""
    return str(v or "").strip().split(".")[0].zfill(5)


def _check_schema(fieldnames, expected: set, source: str, where: str) -> None:
    got = {(f or "").strip() for f in (fieldnames or [])}
    missing = expected - got
    if missing:
        raise GateFailure(
            f"{source} ({where}) is missing expected columns {sorted(missing)}; "
            f"got {sorted(got)[:12]}. The shape changed, so nothing here is "
            f"trustworthy even though the fetch succeeded.")


def aggregate(rows: list[dict], cycles: tuple[int, ...] = CYCLES) -> dict:
    """Two-party votes per county per cycle, from MEDSL rows.

    MEDSL breaks 2020 and later into per-vote-mode rows (ELECTION DAY,
    ABSENTEE and so on) for some states, and in some of those states a TOTAL
    row sits alongside the modes rather than instead of them. Summing
    everything double-counts exactly those states, which inflates turnout
    without changing the two-party ratio much, so it hides well.

    Rule: within one county-cycle-party-candidate group, a TOTAL row wins
    outright; only where there is none are the modes summed.
    """
    groups: dict[tuple, dict[str, float]] = {}
    for r in rows:
        try:
            year = int(str(r["year"]).strip())
        except (KeyError, TypeError, ValueError):
            continue
        if year not in cycles:
            continue
        party = (r.get("party") or "").strip().upper()
        if party not in ("DEMOCRAT", "REPUBLICAN"):
            continue
        fips = _fips(r.get("county_fips"))
        if fips[:2] in EXCLUDED_STATES:
            continue
        try:
            votes = float(r.get("candidatevotes") or 0)
        except (TypeError, ValueError):
            continue

        key = (fips, year, party, (r.get("candidate") or "").strip().upper())
        mode = (r.get("mode") or "").strip().upper()
        g = groups.setdefault(key, {"total": 0.0, "modes": 0.0, "has_total": False})
        if mode in ("TOTAL", ""):
            g["total"] += votes
            g["has_total"] = True
        else:
            g["modes"] += votes

    by_county: dict[str, dict[int, dict[str, float]]] = {}
    for (fips, year, party, _cand), g in groups.items():
        votes = g["total"] if g["has_total"] else g["modes"]
        cycle = by_county.setdefault(fips, {}).setdefault(year, {"D": 0.0, "R": 0.0})
        cycle["D" if party == "DEMOCRAT" else "R"] += votes
    return by_county


def shares(by_county: dict) -> dict[str, dict[int, float]]:
    """Democratic share of the two-party vote, 0 to 1, per county per cycle."""
    out: dict[str, dict[int, float]] = {}
    for fips, by_year in by_county.items():
        for year, v in by_year.items():
            total = v["D"] + v["R"]
            if total > 0:
                out.setdefault(fips, {})[year] = v["D"] / total
    return out


def lean_from_returns(rows: list[dict], years: tuple[int, ...] = CYCLES) -> dict[str, dict]:
    """Two-party share averaged across recent presidential cycles.

    One cycle is noisy and over-reads a single candidate; averaging two is
    steadier without smoothing away genuine movement. 0 is the most
    Republican-voting county in the country, 100 the most Democratic-voting;
    the midpoint is an even split, not a value judgement.

    A county is only scored when every averaged cycle is present, which
    guards against a partial join anywhere quietly producing a one-cycle
    number next to a two-cycle number everywhere else, with nothing in the
    output saying so. Connecticut never reaches this check: its
    planning-region FIPS don't match MEDSL's legacy county FIPS in the first
    place, so EXCLUDED_STATES filters it out upstream in aggregate() rather
    than relying on this per-cycle guard to catch it. See EXCLUDED_STATES
    for the reasoning.
    """
    per_cycle = shares(aggregate(rows, years))
    out = {}
    for fips, by_year in per_cycle.items():
        present = [by_year[y] for y in years if y in by_year]
        if len(present) != len(years):
            continue
        out[fips] = {
            "local_lean": round(sum(present) / len(present) * 100, 1),
            "local_lean_cycles": len(present),
            "local_lean_note": "two-party presidential share; a position, not a rating",
        }
    return out


def _read(path, expected: set, source: str, where: str) -> list[dict]:
    """Read a delimited file, sniffing the separator and gating the schema.

    Dataverse stores the MEDSL file as .tab and serves tab-separated unless the
    original upload is requested. A TSV read with a comma reader yields one
    enormous column and no usable rows, which presents as "the source had no
    data" rather than as a format mismatch.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    head = text.split("\n", 1)[0]
    delim = "\t" if head.count("\t") > head.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    _check_schema(reader.fieldnames, expected, source, where)
    return list(reader)


def _tonmcg_shares(cycles: tuple[int, ...] = CYCLES) -> dict[str, dict[int, float]]:
    """Validation source. Never returned to the caller, never scored."""
    out: dict[str, dict[int, float]] = {}
    for year in cycles:
        rows = _read(fetch("tonmcg_returns",
                           url=f"{_tonmcg_base()}/{year}_US_County_Level_Presidential_Results.csv",
                           filename=f"tonmcg_{year}.csv"),
                     TONMCG_COLUMNS[year], "tonmcg", str(year))
        key = "combined_fips" if year == 2016 else "county_fips"
        for r in rows:
            fips = _fips(r.get(key))
            if fips[:2] in EXCLUDED_STATES:
                continue
            try:
                d, g = float(r["votes_dem"]), float(r["votes_gop"])
            except (KeyError, TypeError, ValueError):
                continue
            if d + g > 0:
                out.setdefault(fips, {})[year] = d / (d + g)
    return out


def _tonmcg_base() -> str:
    from ..config import SOURCES
    return SOURCES["tonmcg_returns"].url.rstrip("/")


def cross_check(primary: dict[str, dict[int, float]],
                validation: dict[str, dict[int, float]]) -> dict:
    """Compare two independently derived datasets county by county, cycle by
    cycle. Agreement is corroboration precisely because the lineages differ.
    """
    diffs = []
    for fips, by_year in primary.items():
        for year, share in by_year.items():
            other = validation.get(fips, {}).get(year)
            if other is None:
                continue
            diffs.append((abs(share - other) * 100, fips, year))
    if not diffs:
        raise GateFailure(
            "cross-source gate could not run: no county-cycle overlap between "
            "the primary and validation sources. Corroboration is part of "
            "verification, not optional, so this blocks rather than passes.")

    diffs.sort(reverse=True)
    over_warn = [d for d in diffs if d[0] > WARN_PP]
    over_fail = [d for d in diffs if d[0] > FAIL_PP]
    summary = {
        "compared": len(diffs),
        "max_divergence_pp": round(diffs[0][0], 2),
        "over_warn": len(over_warn),
        "over_fail": len(over_fail),
        "over_fail_share": round(len(over_fail) / len(diffs), 4),
    }
    if len(over_fail) / len(diffs) > FAIL_SHARE:
        worst = ", ".join(f"{f}@{y} {d:.1f}pp" for d, f, y in diffs[:10])
        raise GateFailure(
            f"cross-source gate: {len(over_fail)} of {len(diffs)} county-cycles "
            f"diverge by more than {FAIL_PP}pp "
            f"({summary['over_fail_share']:.1%} > {FAIL_SHARE:.0%}). Worst: {worst}")
    return summary


def check_coverage(per_cycle: dict[str, dict[int, float]],
                   anchors: set[str] | None,
                   cycles: tuple[int, ...] = CYCLES) -> dict:
    """Enough counties, and specifically the ones the interface is built on.

    The count catches a delimiter or schema regression that leaves the file
    parsing but nearly empty. The anchor check catches the subtler case where
    plenty of counties are present but the ones people actually search for are
    not.
    """
    stats = {}
    for year in cycles:
        n = sum(1 for by_year in per_cycle.values() if year in by_year)
        stats[year] = n
        if n < MIN_COUNTIES_PER_CYCLE:
            raise GateFailure(
                f"coverage gate: only {n} counties for {year}, expected at "
                f"least {MIN_COUNTIES_PER_CYCLE}")

    if anchors:
        scored = {f for f, by_year in per_cycle.items()
                  if all(y in by_year for y in cycles)}
        missing = sorted(a for a in anchors
                         if a[:2] not in EXCLUDED_STATES and a not in scored)
        if missing:
            raise GateFailure(
                f"coverage gate: {len(missing)} anchor counties have no "
                f"complete political reading, e.g. {missing[:8]}")
    return stats


def check_sanity(per_cycle: dict[str, dict[int, float]],
                 cycles: tuple[int, ...] = CYCLES) -> None:
    bad = [(f, y, s) for f, by_year in per_cycle.items()
           for y, s in by_year.items() if not (0.0 <= s <= 1.0)]
    if bad:
        raise GateFailure(f"sanity gate: {len(bad)} shares outside 0-1, e.g. {bad[:5]}")


def extract(anchors: set[str] | None = None) -> dict[str, dict]:
    """Fetch, gate, and return local lean. Any gate failure raises.

    Every gate here blocks rather than warns, which matches the rest of the
    pipeline: a source that cannot be trusted degrades its fields to nothing
    and the interface says so, instead of publishing a number nobody checked.
    """
    rows = _read(fetch("mit_election", url=_mit_election_signed_url(),
                       filename="countypres.csv"),
                 MEDSL_COLUMNS, "MEDSL", "county presidential returns")

    per_cycle = shares(aggregate(rows))
    check_sanity(per_cycle)
    coverage = check_coverage(per_cycle, anchors)
    summary = cross_check(per_cycle, _tonmcg_shares())

    print(f"    politics: {coverage}, cross-check {summary}")
    return lean_from_returns(rows)
