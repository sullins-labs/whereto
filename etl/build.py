"""Orchestrator.

    python -m etl.build                     full run, fetching what is stale
    python -m etl.build --offline           rebuild from the archive only
    python -m etl.build --as-of 2026-07-01  reproduce that day's output exactly
    python -m etl.build --verify            re-hash the archive, change nothing

Sources are independent. One failing does not abort the run — it degrades the
affected fields and is reported. A pipeline that dies because the FBI endpoint
is having a bad afternoon is a pipeline nobody runs.
"""
from __future__ import annotations
import argparse, json, sys, traceback
from datetime import datetime, timezone

from . import snapshot
from .config import DIST, CONTRACT_VERSION, licence_table
from .validate import check_dataset, report, BLOCKING

# Order is a dependency graph, not a preference. ACS runs first because the
# spine needs population to compute density, and density decides the ring.
# Everything after the spine is independent and could run in parallel; it does
# not, because 70 minutes once a month is not worth the concurrency bugs.
# (key, description, stages it needs to have succeeded first)
STAGES = [
    ("acs",       "population, income, housing",           ()),
    ("spine",     "geography, rings and crosswalks",       ("acs",)),
    ("rpp",       "cost of living",                        ("spine",)),
    ("labour",    "unemployment and labour force",         ("spine",)),
    ("housing",   "home values and fair market rents",     ()),
    ("hazard",    "wildfire, flood, wind, quake",          ()),
    ("climate",   "temperature normals",                   ("spine",)),
    ("air",       "particulates and ozone",                ("spine",)),
    ("crime",     "violent and property offences",         ("spine",)),
    ("health",    "shortage areas and provider ratios",    ("spine",)),
    ("schools",   "district finance and enrolment",        ()),
    ("politics",  "local voting lean",                     ()),
    ("curated",   "tax and services statute",              ("spine",)),
]


def _stages(offline: bool, as_of: str | None):
    """Bound the extractors into callables the orchestrator can run uniformly.

    Each returns {fips: {...}}. State accumulates in `ctx` because later
    stages legitimately need earlier output — the spine needs population, BEA
    needs the county-to-CBSA map, climate needs coordinates.
    """
    from .sources import census_acs, geo, bea_rpp, bls_laus, housing as housing_src
    from .sources import fema_nri, noaa_normals, epa_aqs, hrsa_health, nces_ccd
    from .sources import politics, curated, fbi_cde
    ctx: dict = {}

    def acs(**_):
        ctx["acs"] = census_acs.extract()
        return ctx["acs"]

    def spine(**_):
        pop = {f: r.get("population") or 0 for f, r in ctx.get("acs", {}).items()}
        ctx["spine"] = geo.extract(population=pop)
        return ctx["spine"]

    def rpp(**_):
        return bea_rpp.extract({f: r.get("cbsa") for f, r in ctx["spine"].items()})

    def labour(**_):
        return bls_laus.extract(sorted(ctx["spine"]))

    def housing(**_):
        merged: dict[str, dict] = {}
        for table in (housing_src.zillow(), housing_src.hud_fmr()):
            for f, v in table.items():
                merged.setdefault(f, {}).update(v)
        return merged

    def climate(**_):
        return noaa_normals.extract(ctx["spine"])

    def air(**_):
        return epa_aqs.extract(ctx["spine"])

    def health(**_):
        ratios = {f: {"population": r.get("population") or 0,
                      "primary_care_physicians": 0, "mental_health_providers": 0}
                  for f, r in ctx["spine"].items()}
        return hrsa_health.extract(ratios)

    def curated_stage(**_):
        return curated.extract({f: r["state"] for f, r in ctx["spine"].items()})

    return {
        "acs": acs, "spine": spine, "rpp": rpp, "labour": labour,
        "housing": housing, "hazard": lambda **_: fema_nri.extract(),
        "climate": climate, "air": air,
        "crime": lambda **_: fbi_cde.extract(
            {f: r.get("population") or 0 for f, r in ctx["spine"].items()}),
        "health": health,
        "schools": lambda **_: nces_ccd.extract(),
        "politics": lambda **_: politics.extract(),
        "curated": curated_stage,
    }, ctx


def run(offline: bool = False, as_of: str | None = None) -> int:
    started = datetime.now(timezone.utc)
    results, failures = {}, {}
    fns, ctx = _stages(offline, as_of)

    for key, desc, needs in STAGES:
        missing = [n for n in needs if n not in results]
        if missing:
            # Say what actually went wrong. A downstream KeyError tells you
            # nothing about which upstream stage to go and fix.
            failures[key] = f"skipped: depends on {', '.join(missing)}, which did not complete"
            print(f"  – {key:<10} {desc} — {failures[key]}")
            continue
        try:
            fn = fns.get(key)
            if fn is None:
                print(f"  ○ {key:<10} {desc} — not wired")
                continue
            results[key] = fn(offline=offline, as_of=as_of)
            print(f"  ● {key:<10} {desc} — {len(results[key])} records")
        except Exception as exc:                     # noqa: BLE001
            failures[key] = f"{type(exc).__name__}: {exc}"
            print(f"  ✕ {key:<10} {desc} — {failures[key]}")
            if "--traceback" in sys.argv:
                traceback.print_exc()

    from .transform import run as transform_run
    records = transform_run(assemble(results))
    findings, stats = check_dataset(records)
    print("\n" + report(findings, stats))

    if stats["blocking"]:
        print("\nBlocked. Nothing written — the previous build stays live.")
        print("A stale number the site already had is safer than a wrong one it did not.")
        return 1

    DIST.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "built_at": started.isoformat(timespec="seconds"),
        "sources": licence_table(),
        "stage_failures": failures,
        "warnings": [f.__dict__ for f in findings],
        "places": records,
    }
    out = DIST / "places.json"
    out.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"\nWrote {out} — {len(records)} places, {out.stat().st_size/1024:.0f} kB")
    if failures:
        print(f"Degraded: {', '.join(failures)} — affected fields are marked in the output.")
    return 0


def assemble(results: dict) -> list[dict]:  # noqa: D401
    """Join every source onto the spine.

    Left join, always. A source that lacks a county leaves a null, never drops
    the row — otherwise a gap in one dataset silently deletes places from the
    map, which is the failure mode nobody notices because the site still works.
    """
    spine = results.get("spine") or {}
    records = []
    for fips, base in spine.items():
        rec = dict(base)
        for key, table in results.items():
            if key == "spine":
                continue
            rec.update(table.get(fips, {}))
        records.append(rec)
    return records


def main() -> int:
    ap = argparse.ArgumentParser(prog="etl.build")
    ap.add_argument("--offline", action="store_true", help="rebuild from the archive, no network")
    ap.add_argument("--as-of", help="reproduce the output as of a date, YYYY-MM-DD")
    ap.add_argument("--verify", action="store_true", help="re-hash the archive and exit")
    ap.add_argument("--traceback", action="store_true")
    a = ap.parse_args()

    if a.verify:
        problems = snapshot.verify()
        print("archive intact" if not problems else "\n".join(problems))
        return 1 if problems else 0

    print(f"whereto-etl · contract v{CONTRACT_VERSION}"
          f"{' · offline' if a.offline else ''}{' · as of ' + a.as_of if a.as_of else ''}\n")
    return run(offline=a.offline, as_of=a.as_of)


if __name__ == "__main__":
    raise SystemExit(main())
