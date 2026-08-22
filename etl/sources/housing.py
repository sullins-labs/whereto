"""Zillow research indices and HUD Fair Market Rents.

The care needed here is legal rather than technical: Zillow's terms permit
deriving from the research files but not republishing them. This module used
to copy the current-month ZHVI cell straight into a published field
(home_value), which is not "deriving" anything — it is the source figure
itself, and it shipped with no attribution anywhere in the app. A 2026-08-22
licensing review ruled that not permitted. Josh's call (of three options
offered) was to drop ZHVI from published output entirely and rely on Census
ACS's median_home_value (B25077_001E), a public-domain 5-year estimate
present for every county — not to build a compliant derived index instead.
So: zillow() below still fetches and archives the file, so the snapshot
stays current if a compliant derived index is ever built, but it merges
nothing from it into the record. What actually leaves this pipeline for
home value is ACS's figure, untouched, set in census_acs.py.
"""
from __future__ import annotations
from ..snapshot import fetch


def zillow() -> dict[str, dict]:
    """Fetch and archive Zillow's ZHVI file. Merge nothing from it.

    See the module docstring for why: republishing the current-month cell,
    even a single value rather than the whole series, is still Zillow's
    figure verbatim, and the license requires attribution this app never
    carried. Nothing here is derived from the fetched file today.
    """
    fetch("zillow_zhvi", filename="county_zhvi.csv")
    return {}


def hud_fmr(year: int = 2026) -> dict[str, dict]:
    """The bulk spreadsheet, not the per-county endpoint.

    HUD's API is rate limited to 60 calls a minute; 3,144 counties would take
    52 minutes to move six megabytes. One file takes seconds.
    """
    import openpyxl
    url = f"https://www.huduser.gov/portal/datasets/fmr/fmr{year}/FY{year}_4050_FMRs.xlsx"
    path = fetch("hud_fmr", url, filename=f"fmr_{year}.xlsx")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    header, out = None, {}
    for row in ws.iter_rows(values_only=True):
        vals = ["" if v is None else str(v).strip() for v in row]
        if header is None:
            if any(v.lower().startswith("fips") for v in vals):
                header = {v.lower(): i for i, v in enumerate(vals)}
            continue
        fips_col = next((k for k in header if k.startswith("fips")), None)
        raw = vals[header[fips_col]]
        fips = raw[:5] if len(raw) >= 5 and raw[:5].isdigit() else None
        if not fips:
            continue
        rec = {}
        for beds, key in ((1, "fmr_1br"), (2, "fmr_2br"), (3, "fmr_3br")):
            col = next((k for k in header if k.endswith(f"_{beds}") or k == f"fmr_{beds}"), None)
            if col:
                try:
                    rec[key] = int(float(vals[header[col]]))
                except (ValueError, TypeError):
                    pass
        # counties split into small-area FMRs appear more than once; keep the
        # highest, which is the binding figure for anyone actually renting
        if rec:
            prior = out.get(fips)
            if not prior or rec.get("fmr_2br", 0) > prior.get("fmr_2br", 0):
                out[fips] = rec
    return out
