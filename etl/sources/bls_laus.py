"""BLS Local Area Unemployment Statistics, county level.

The tightest rate limit in the pipeline: 500 calls a day with a registered
key, 50 series per call. 3,144 counties is 63 calls, which fits comfortably —
but only because the series are batched. Anything that calls this per county
per request needs 3,144 calls and dies on day one.

Series ID: LAU + area type CN + 5-digit FIPS + 8 zeros + measure code, which
is 20 characters. Getting this to 19 does not error: BLS answers
REQUEST_SUCCEEDED with "Series does not exist" per series, and an extractor
that only reads Results.series sees an empty list rather than a failure.
Measure 03 is the unemployment rate; 06 is labour force.
"""
from __future__ import annotations
import json, math
from ..config import SOURCES
from ..snapshot import fetch

BATCH = 50
MEASURES = {"03": "unemployment_rate", "06": "labour_force"}


def series_id(fips: str, measure: str) -> str:
    sid = f"LAUCN{fips}00000000{measure}"
    # A malformed id is reported per-series inside a successful response, so
    # assert the width here rather than discovering it as missing data.
    assert len(sid) == 20, f"BLS series id must be 20 chars, got {len(sid)}: {sid}"
    return sid


def plan(fips_list: list[str]) -> int:
    """Calls required. Called by feasibility.py before anything is fetched."""
    return math.ceil(len(fips_list) * len(MEASURES) / BATCH)


def extract(fips_list: list[str], year: int = 2025) -> dict[str, dict]:
    src = SOURCES["bls_laus"]
    needed = plan(fips_list)
    if src.daily_call_cap and needed > src.daily_call_cap:
        raise RuntimeError(
            f"BLS: {needed} calls needed, {src.daily_call_cap} allowed per day. "
            f"Split the run across days rather than raising the cap.")

    ids = [series_id(f, m) for f in fips_list for m in MEASURES]
    out: dict[str, dict] = {}

    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        path = fetch(
            "bls_laus",
            filename=f"laus_{year}_{i//BATCH:03d}.json",
            # BLS v2 is POST-with-JSON-body, unlike everything else here, and
            # rejects GET with a 405. snapshot.fetch takes json_body for this
            # so the batch still goes through the same archival path.
            json_body={
                "seriesid": chunk,
                "startyear": str(year),
                "endyear": str(year),
            },
            headers={"Content-Type": "application/json"},
        )
        payload = json.loads(path.read_text())
        for s in payload.get("Results", {}).get("series", []):
            sid = s["seriesID"]
            fips, measure = sid[5:10], sid[-2:]
            data = [d for d in s.get("data", []) if d.get("period", "").startswith("M")]
            if not data:
                continue
            latest = data[0]
            try:
                value = float(latest["value"])
            except (KeyError, ValueError):
                continue
            rec = out.setdefault(fips, {})
            rec[MEASURES[measure]] = value
            rec["labour_vintage"] = f"{latest['year']}-{latest['period'][1:]}"
    return out
