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
            try:
                monitors.append({
                    "county_fips": (r["State Code"].zfill(2) + r["County Code"].zfill(3)),
                    "pollutant": PARAMS[code],
                    "lat": float(r["Latitude"]), "lon": float(r["Longitude"]),
                    "days_over": int(float(r.get("Days Above Standard") or 0)),
                })
            except (KeyError, ValueError):
                continue
    return aggregate(monitors, counties)
