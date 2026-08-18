"""EPA AQS annual air quality, monitors aggregated to counties.

Two pollutants matter for a livability read: PM2.5, which tracks wildfire
smoke and traffic, and ozone, which tracks heat and traffic. They are reported
in different units against different standards, so they are combined on days
exceeding the national standard rather than on concentration.

Monitors are sparse — roughly a thousand counties have one. Unlike temperature,
air quality is genuinely regional, so a county without a monitor inherits from
the nearest within 50 miles and is flagged `air_inherited`. Beyond that it gets
nothing.
"""
from __future__ import annotations
import csv, io, zipfile
from collections import defaultdict
from ..snapshot import fetch
from ..spine import haversine_mi

INHERIT_MI = 50
PARAMS = {"88101": "pm25", "44201": "ozone"}
# Current primary (health-based) NAAQS vintage for each pollutant's health-relevant
# averaging time. EPA AQS repeats one row per monitor per pollutant-standard vintage
# (e.g. "PM25 24-hour 2006/2012/2024" all carry the same 35 ug/m3 24-hour threshold,
# just re-issued alongside later rulemakings); using the wrong vintage, or none, either
# undercounts or silently sums duplicate rows for the same days. Annual PM2.5 standards
# are excluded here because their "exceedance count" is a design-value/year concept, not
# a day count, so it isn't comparable to ozone's day-based exceedance count.
STANDARDS = {"88101": "PM25 24-hour 2024", "44201": "Ozone 8-hour 2015"}


def aggregate(monitors: list[dict], counties: dict[str, dict]) -> dict[str, dict]:
    direct = defaultdict(lambda: {"pm25_days": [], "ozone_days": [], "lat": None, "lon": None})
    for m in monitors:
        f = m.get("county_fips")
        if not f:
            continue
        d = direct[f]
        d["lat"], d["lon"] = m.get("lat"), m.get("lon")
        if m["pollutant"] == "pm25" and m.get("days_over") is not None:
            d["pm25_days"].append(m["days_over"])
        elif m["pollutant"] == "ozone" and m.get("days_over") is not None:
            d["ozone_days"].append(m["days_over"])

    measured = {}
    for f, d in direct.items():
        pm = max(d["pm25_days"]) if d["pm25_days"] else None
        oz = max(d["ozone_days"]) if d["ozone_days"] else None
        if pm is None and oz is None:
            continue
        # worst monitor in the county, not the average — a household breathes
        # the air where it lives, not the county mean
        measured[f] = {"pm25_days_over": pm, "ozone_days_over": oz,
                       "air_days_over": (pm or 0) + (oz or 0),
                       "lat": d["lat"], "lon": d["lon"]}

    out = {}
    for fips, c in counties.items():
        if fips in measured:
            m = dict(measured[fips]); m.pop("lat", None); m.pop("lon", None)
            m["air_inherited"] = False
            out[fips] = m
            continue
        best, best_d = None, 1e9
        for mf, m in measured.items():
            if m["lat"] is None:
                continue
            d = haversine_mi(c["lat"], c["lon"], m["lat"], m["lon"])
            if d < best_d:
                best, best_d = m, d
        if best and best_d <= INHERIT_MI:
            out[fips] = {"pm25_days_over": best["pm25_days_over"],
                         "ozone_days_over": best["ozone_days_over"],
                         "air_days_over": best["air_days_over"],
                         "air_inherited": True,
                         "air_source_mi": round(best_d, 1)}
    return out


def extract(counties: dict[str, dict], year: int = 2025) -> dict[str, dict]:
    src_url = f"https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_{year}.zip"
    path = fetch("epa_aqs", src_url, filename=f"aqs_annual_{year}.zip")
    monitors = []
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        for r in csv.DictReader(io.StringIO(z.read(member).decode("utf-8-sig", errors="replace"))):
            code = (r.get("Parameter Code") or "").strip()
            if code not in PARAMS:
                continue
            if (r.get("Pollutant Standard") or "").strip() != STANDARDS[code]:
                continue
            # Primary standards protect public health; secondary protect welfare
            # (visibility, crops). This module's stated purpose is a health read.
            pec = (r.get("Primary Exceedance Count") or "").strip()
            if pec == "":
                continue
            try:
                monitors.append({
                    "county_fips": (r["State Code"].zfill(2) + r["County Code"].zfill(3)),
                    "pollutant": PARAMS[code],
                    "lat": float(r["Latitude"]), "lon": float(r["Longitude"]),
                    "days_over": int(float(pec)),
                })
            except (KeyError, ValueError):
                continue
    return aggregate(monitors, counties)
