"""BEA Regional Price Parities.

Published for metros and states, never for counties. Roughly 1,800 of the
3,144 counties sit inside a metro and get its RPP; the rest fall back to their
state's non-metro figure. That fallback is real and unavoidable, so every
record carries `rpp_source` saying which it got — a county in rural Nebraska
carrying a Omaha price level would be a quiet lie.
"""
from __future__ import annotations
import json
from ..snapshot import fetch


def extract(county_to_cbsa: dict[str, str | None]) -> dict[str, dict]:
    metro = json.loads(fetch(
        "bea_rpp", filename="rpp_msa.json",
        params={"method": "GetData", "datasetname": "Regional", "TableName": "MARPP",
                "LineCode": 1, "GeoFips": "MSA", "Year": "LAST5", "ResultFormat": "JSON"},
    ).read_text())
    state = json.loads(fetch(
        "bea_rpp", filename="rpp_state_nonmetro.json",
        params={"method": "GetData", "datasetname": "Regional", "TableName": "SARPP",
                "LineCode": 1, "GeoFips": "STATE", "Year": "LAST5", "ResultFormat": "JSON"},
    ).read_text())

    def latest_by_geo(payload) -> dict[str, float]:
        rows = payload.get("BEAAPI", {}).get("Results", {}).get("Data", [])
        best: dict[str, tuple[str, float]] = {}
        for r in rows:
            try:
                v = float(str(r["DataValue"]).replace(",", ""))
            except (KeyError, ValueError):
                continue
            geo, yr = r["GeoFips"], r["TimePeriod"]
            if geo not in best or yr > best[geo][0]:
                best[geo] = (yr, v)
        return {g: v for g, (_, v) in best.items()}

    by_msa, by_state = latest_by_geo(metro), latest_by_geo(state)

    out = {}
    for fips, cbsa in county_to_cbsa.items():
        if cbsa and cbsa in by_msa:
            out[fips] = {"rpp": by_msa[cbsa], "rpp_source": "metro"}
        else:
            st = fips[:2] + "000"
            if st in by_state:
                out[fips] = {"rpp": by_state[st], "rpp_source": "state fallback"}
    return out
