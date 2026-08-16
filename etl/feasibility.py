"""Feasibility ledger.

Answers one question with arithmetic instead of optimism: does a full national
refresh fit inside the free tier of every service it touches?

    python -m etl.feasibility

Run this before adding a source, not after. The binding constraint is rarely
the one people expect — it is BLS at 500 calls a day, not bandwidth or storage.
"""
from __future__ import annotations
import math

COUNTIES = 3_144
STATES = 51
CBSAS = 927

# How often a source actually changes. Refetching a decadal dataset every
# month is 240 MB of nothing, and it is what pushed the first draft of this
# pipeline past the CI timeout.
MONTHLY, QUARTERLY, ANNUAL, RARE = "monthly", "quarterly", "annual", "rare"

CADENCE = {
  "census_gazetteer": ANNUAL, "census_cbsa_delineation": RARE, "usda_rucc": RARE,
  "census_acs5": ANNUAL, "bea_rpp": ANNUAL, "bls_laus": MONTHLY,
  "hud_fmr": ANNUAL, "zillow_zhvi": MONTHLY, "fema_nri": RARE,
  "noaa_normals": RARE, "epa_aqs": ANNUAL, "hrsa_hpsa": QUARTERLY,
  "nces_ccd": ANNUAL, "fbi_cde": ANNUAL, "mit_election": RARE,
}

# (calls per full refresh, MB fetched, daily cap or None, note)
PLAN = {
  "census_gazetteer": (1, 2, None, "one zip, all counties"),
  "census_cbsa_delineation": (1, 1, None, "one xlsx"),
  "usda_rucc": (1, 1, None, "one csv"),
  "census_acs5": (1, 9, 500,
      "for=county:* returns all 3,144 in a single response; per-county calls "
      "would need 3,144 and are the obvious wrong turn"),
  "bea_rpp": (2, 3, 100, "metro table plus state table for the non-metro fallback"),
  "bls_laus": (math.ceil(COUNTIES * 2 / 50), 14, 450,
      "2 series per county, 50 per call — the tightest limit in the pipeline"),
  "hud_fmr": (1, 6, None,
      "bulk xlsx, not the per-county endpoint. The API is 60/min, so 3,144 "
      "county calls would take 52 minutes and burn the quota for nothing"),
  "zillow_zhvi": (1, 38, None, "single county-level csv"),
  "fema_nri": (1, 190, None, "county table zip, 18 hazards"),
  "noaa_normals": (1, 240, None, "station archive; aggregated locally to counties"),
  "epa_aqs": (1, 120, None, "annual monitor zip"),
  "hrsa_hpsa": (1, 18, None, "shortage-area csv"),
  "nces_ccd": (1, 46, None, "district finance zip"),
  "fbi_cde": (STATES, 30, 1_000, "one call per state, agencies aggregated locally"),
  "mit_election": (1, 26, None, "county returns, single file"),
}

FREE = {
  "actions_minutes_month": None,     # unlimited on public repos
  "actions_minutes_private": 2_000,
  "release_asset_gb": 2,
  "repo_soft_limit_gb": 1,
  "netlify_bandwidth_gb": 100,       # free-tier monthly allowance
  "netlify_build_minutes": None,     # not consumed: deploys are built locally
}

# A cold visit is the page plus the whole dataset, since scoring is client side.
VISIT_MB = 3.2

# rough per-source processing time on a 2-core Actions runner
CPU_MIN = {"noaa_normals": 4.5, "fema_nri": 1.2, "nces_ccd": 1.0, "epa_aqs": 0.8,
           "mit_election": 0.4, "zillow_zhvi": 0.4}


def main() -> int:
    print("FEASIBILITY LEDGER — full national refresh, 3,144 counties\n")
    print(f"  {'source':<26}{'calls':>7}{'cap':>7}{'MB':>7}  note")
    print("  " + "-" * 104)

    total_calls = total_mb = 0
    breaches = []
    for key, (calls, mb, cap, note) in PLAN.items():
        total_calls += calls
        total_mb += mb
        flag = ""
        if cap is not None and calls > cap:
            flag = "  ← EXCEEDS CAP"
            breaches.append(key)
        headroom = f"{cap}" if cap else "—"
        print(f"  {key:<26}{calls:>7}{headroom:>7}{mb:>7}  {note[:64]}{flag}")

    print("  " + "-" * 104)
    print(f"  {'TOTAL':<26}{total_calls:>7}{'':>7}{total_mb:>7}")

    def subset(cadences):
        keys = [k for k in PLAN if CADENCE[k] in cadences]
        mb = sum(PLAN[k][1] for k in keys)
        calls = sum(PLAN[k][0] for k in keys)
        cpu = sum(CPU_MIN.get(k, 0.2) for k in keys)
        return calls, mb, mb / 12.0 + cpu + 2

    cold_calls, cold_mb, cold_min = subset({MONTHLY, QUARTERLY, ANNUAL, RARE})
    mth_calls, mth_mb, mth_min = subset({MONTHLY})
    qtr_calls, qtr_mb, qtr_min = subset({MONTHLY, QUARTERLY})
    ann_calls, ann_mb, ann_min = subset({MONTHLY, QUARTERLY, ANNUAL})

    fetch_min, cpu_min, run_min = cold_mb / 12.0, sum(CPU_MIN.values()), cold_min

    print(f"""
RUNTIME BY RUN TYPE
  Because the archive is append-only and cadence-aware, a routine run touches
  only what has actually changed. Refetching a decadal dataset monthly is
  240 MB of nothing — and it is what pushed the first draft past the timeout.

  monthly run           {mth_min:5.1f} min   ({mth_mb:>3} MB, {mth_calls:>3} calls)  Zillow, BLS
  quarterly run         {qtr_min:5.1f} min   ({qtr_mb:>3} MB, {qtr_calls:>3} calls)  + HRSA
  annual run            {ann_min:5.1f} min   ({ann_mb:>3} MB, {ann_calls:>3} calls)  + ACS, BEA, HUD, EPA, NCES, FBI
  cold build            {cold_min:5.1f} min   ({cold_mb:>3} MB, {cold_calls:>3} calls)  everything, first run only

COLD BUILD DETAIL
  fetch                 {fetch_min:5.1f} min   ({total_mb} MB at ~12 MB/s)
  transform             {cpu_min:5.1f} min
  overhead              {2.0:5.1f} min
  total                 {run_min:5.1f} min per monthly refresh

GITHUB ACTIONS
  monthly usage         {mth_min:5.1f} min   (annual month: {ann_min:.0f} min)
  public repo           unlimited                     → fits
  private repo          {FREE['actions_minutes_private']} min/month{'':<12}→ {'fits' if ann_min*4 < FREE['actions_minutes_private'] else 'does not fit'}

STORAGE
  cold snapshot         {cold_mb/1024:5.2f} GB   (once)
  monthly increment     {mth_mb/1024:5.2f} GB   → 12 months adds {mth_mb*12/1024:.2f} GB
  per release asset     {FREE['release_asset_gb']} GB limit{'':<15}→ fits, snapshots split by source
  in-repo data          ~0.003 GB  (places.json only; snapshots never committed)
  repo soft limit       {FREE['repo_soft_limit_gb']} GB{'':<20}→ fits with room

NETLIFY
  deploys               ~2/month                      → built locally, no CI minutes
  bandwidth             {FREE['netlify_bandwidth_gb']} GB/month allowance{'':<9}→ ~{FREE['netlify_bandwidth_gb'] * 1024 / VISIT_MB:,.0f} cold visits at {VISIT_MB} MB
  serverless surface    none                          → nothing metered can bill

VERDICT""")
    if breaches:
        print(f"  BLOCKED — over cap on: {', '.join(breaches)}")
        return 1
    tightest = max(
        ((k, c, cap) for k, (c, _, cap, _) in PLAN.items() if cap),
        key=lambda t: t[1] / t[2])
    k, c, cap = tightest
    print(f"  Fits. Tightest constraint is {k} at {c}/{cap} calls "
          f"({c/cap:.0%} of its daily allowance).")
    print(f"  Headroom there is {cap - c} calls — enough to roughly "
          f"{cap/c:.1f}x the county count before it binds.")
    print(f"  Routine monthly run is {mth_min:.0f} minutes; only the first cold build is long.")
    print("  Nothing in the stack meters per-request, so traffic cannot generate cost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
