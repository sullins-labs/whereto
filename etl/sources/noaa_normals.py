"""NOAA 1991-2020 Climate Normals, station level, aggregated to counties.

The only source here that needs real spatial work. Roughly 15,000 stations,
3,144 counties, and no crosswalk between them. Inverse-distance weighting over
the three nearest stations within 60 miles, which is enough for county-scale
temperature and honest about where it isn't.

Counties with no station inside the radius — parts of the interior West — get
no value rather than a value borrowed from 200 miles away. validate.py sees
the gap; a fabricated number would have looked fine.
"""
from __future__ import annotations
import csv, io, math
from ..snapshot import fetch
from ..spine import haversine_mi

MAX_MI = 60
K = 3


def _weighted(samples: list[tuple[float, float]]) -> float | None:
    """samples: (value, distance_miles)."""
    samples = [s for s in samples if s[0] is not None]
    if not samples:
        return None
    if any(d < 0.5 for _, d in samples):
        return min(samples, key=lambda s: s[1])[0]
    num = sum(v / (d ** 2) for v, d in samples)
    den = sum(1 / (d ** 2) for _, d in samples)
    return num / den


def extract(counties: dict[str, dict], stations: list[dict] | None = None) -> dict[str, dict]:
    """stations: [{id, lat, lon, jul_high_f, jan_low_f, precip_in, sun_pct}]

    Passed in so this is testable without the network; extract() fetches when
    it is not supplied.
    """
    if stations is None:
        path = fetch("noaa_normals", filename="normals_monthly.csv")
        stations = _parse(path.read_text(errors="replace"))

    out: dict[str, dict] = {}
    for fips, c in counties.items():
        near = []
        for s in stations:
            d = haversine_mi(c["lat"], c["lon"], s["lat"], s["lon"])
            if d <= MAX_MI:
                near.append((d, s))
        if not near:
            continue                     # no fabrication; the gap is the answer
        near.sort(key=lambda t: t[0])
        near = near[:K]

        rec = {}
        for field in ("jul_high_f", "jan_low_f", "precip_in", "sun_pct"):
            v = _weighted([(s.get(field), d) for d, s in near])
            if v is not None:
                rec[{"jul_high_f": "summer_high_f", "jan_low_f": "winter_low_f",
                     "precip_in": "precip_in", "sun_pct": "sun_pct"}[field]] = round(v, 1)
        if rec:
            rec["climate_stations"] = len(near)
            rec["climate_nearest_mi"] = round(near[0][0], 1)
            out[fips] = rec
    return out


def _parse(text: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({
                "id": r["STATION"],
                "lat": float(r["LATITUDE"]), "lon": float(r["LONGITUDE"]),
                "jul_high_f": float(r["MLY-TMAX-NORMAL"]) if r.get("MLY-TMAX-NORMAL") else None,
                "jan_low_f": float(r["MLY-TMIN-NORMAL"]) if r.get("MLY-TMIN-NORMAL") else None,
                "precip_in": float(r["ANN-PRCP-NORMAL"]) if r.get("ANN-PRCP-NORMAL") else None,
                "sun_pct": None,
            })
        except (KeyError, ValueError):
            continue
    return rows
