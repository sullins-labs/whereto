"""Census ACS 5-year, county level.

The pattern every extractor in this package follows:

    fetch (via snapshot, never directly)  ->  parse  ->  return {fips: {...}}

Extractors never decide what a value means, never fill a gap and never reach
the network on their own. They hand back what the source said, with missing
values as None so validate.py can see them.
"""
from __future__ import annotations
import json
from ..config import SOURCES
from ..snapshot import fetch

# ACS uses -666666666 and friends as annotation codes for suppressed or
# unavailable estimates. Treating them as numbers produces silent nonsense:
# a county with a median home value of negative 666 million.
ACS_NULLS = {-666666666, -999999999, -888888888, -555555555, -333333333, -222222222}


def extract(vintage: int | None = None) -> dict[str, dict]:
    src = SOURCES["census_acs5"]
    vintage = vintage or src.params["vintage"]
    varmap: dict[str, str] = src.params["variables"]

    url = src.url.format(vintage=vintage)
    path = fetch(
        "census_acs5", url,
        vintage=str(vintage),
        filename=f"acs5_{vintage}_county.json",
        params={"get": "NAME," + ",".join(varmap), "for": "county:*"},
    )

    rows = json.loads(path.read_text())
    header, body = rows[0], rows[1:]
    idx = {name: i for i, name in enumerate(header)}

    out: dict[str, dict] = {}
    for r in body:
        fips = r[idx["state"]] + r[idx["county"]]
        rec: dict = {"name": r[idx["NAME"]]}
        for var, field in varmap.items():
            raw = r[idx[var]]
            try:
                v = int(raw)
            except (TypeError, ValueError):
                rec[field] = None
                continue
            rec[field] = None if v in ACS_NULLS else v

        # Effective property tax rate, per county rather than per state.
        # Property tax is levied locally, so a state figure averages away the
        # thing a household is choosing between: New Jersey counties run from
        # roughly 1.8% to 3%. Both halves come from the same table and the same
        # vintage, so the ratio is internally consistent even where the
        # underlying estimates are noisy.
        taxes, value = rec.get("median_real_estate_taxes"), rec.get("median_home_value")
        rec["property_effective"] = (
            round(taxes / value * 100, 2)
            if taxes and value and value > 0 else None
        )
        out[fips] = rec
    return out
