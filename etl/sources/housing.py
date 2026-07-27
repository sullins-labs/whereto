"""Zillow research indices and HUD Fair Market Rents.

Both are county-level and both are one file. The care needed here is legal
rather than technical: Zillow's terms permit deriving from the research files
but not republishing them. transform.py enforces that — what leaves this
pipeline is a value per county, never the series.
"""
from __future__ import annotations
import csv, io
from ..snapshot import fetch


def zillow() -> dict[str, dict]:
    path = fetch("zillow_zhvi", filename="county_zhvi.csv")
    rows = list(csv.DictReader(io.StringIO(path.read_text(errors="replace"))))
    if not rows:
        return {}

    # Month columns are ISO dates; everything else is metadata. Taking the last
    # column blindly breaks whenever Zillow appends a field, so months are
    # identified by shape.
    months = sorted(k for k in rows[0] if len(k) == 10 and k[4] == "-" and k[7] == "-")
    if not months:
        return {}
    latest, year_ago = months[-1], months[max(0, len(months) - 13)]

    out = {}
    for r in rows:
        st = (r.get("StateCodeFIPS") or "").zfill(2)
        co = (r.get("MunicipalCodeFIPS") or "").zfill(3)
        if len(st) != 2 or len(co) != 3:
            continue
        try:
            now = float(r[latest])
        except (KeyError, ValueError, TypeError):
            continue
        rec = {"home_value": round(now), "home_value_month": latest}
        try:
            then = float(r[year_ago])
            if then:
                rec["home_value_yoy_pct"] = round((now / then - 1) * 100, 1)
        except (KeyError, ValueError, TypeError):
            pass
        out[st + co] = rec
    return out


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
