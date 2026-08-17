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
import csv, io, math, tarfile
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
        path = fetch("noaa_normals", filename="normals_monthly.tar.gz")
        stations = _parse(path)

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

        rec, temp_used = {}, []
        for field in ("jul_high_f", "jan_low_f", "precip_in", "sun_pct"):
            # The three nearest stations that actually report this field, not
            # whichever of the three nearest happen to. In the 1991-2020
            # release most stations are precipitation-only, so truncating to
            # K first left the majority of counties with rainfall and no
            # temperature, which is the pair validate.py requires.
            with_field = [(s.get(field), d) for d, s in near
                          if s.get(field) is not None][:K]
            v = _weighted(with_field)
            if v is not None:
                rec[{"jul_high_f": "summer_high_f", "jan_low_f": "winter_low_f",
                     "precip_in": "precip_in", "sun_pct": "sun_pct"}[field]] = round(v, 1)
                if field == "jul_high_f":
                    temp_used = with_field
        if rec:
            # Describe the temperature reading specifically, not the radius.
            # Counting every station within 60 miles would claim 58 sources
            # for a value derived from three, and the interface reads these
            # two as its uncertainty signal.
            rec["climate_stations"] = len(temp_used) or len(near[:K])
            nearest = temp_used[0][1] if temp_used else near[0][0]
            rec["climate_nearest_mi"] = round(nearest, 1)
            out[fips] = rec
    return out


def _num(v) -> float | None:
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    # NCEI writes large negatives for missing in some products. Reading one as
    # a temperature would put a -9999 F county through the plausibility gate.
    return None if f < -900 else f


def _station(text: str) -> dict | None:
    """One station's twelve monthly rows reduced to the fields used here.

    Summer high is July's TMAX normal and winter low is January's TMIN normal,
    which is what the retired single-row layout carried directly. Annual
    precipitation is summed from the monthly normals because the monthly
    release has no annual column, and only a complete twelve months counts: a
    partial sum understates rainfall while still looking like a real number.
    """
    sid = lat = lon = None
    jul_high = jan_low = None
    precip, precip_months = 0.0, 0

    for r in csv.DictReader(io.StringIO(text)):
        if sid is None:
            sid = (r.get("STATION") or "").strip() or None
            lat, lon = _num(r.get("LATITUDE")), _num(r.get("LONGITUDE"))

        month = (r.get("month") or "").strip().lstrip("0")
        tmax = _num(r.get("MLY-TMAX-NORMAL"))
        tmin = _num(r.get("MLY-TMIN-NORMAL"))
        prcp = _num(r.get("MLY-PRCP-NORMAL"))

        if month == "7" and tmax is not None:
            jul_high = tmax
        if month == "1" and tmin is not None:
            jan_low = tmin
        if prcp is not None:
            precip += prcp
            precip_months += 1

    if sid is None or lat is None or lon is None:
        return None
    return {
        "id": sid, "lat": lat, "lon": lon,
        "jul_high_f": jul_high, "jan_low_f": jan_low,
        "precip_in": round(precip, 2) if precip_months == 12 else None,
        "sun_pct": None,
    }


def _parse(path) -> list[dict]:
    """The 1991-2020 release is one csv per station inside a tarball, where the
    layout it replaced was a single flat csv with one row per station. The
    column names did not change; only the shape did.
    """
    out = []
    with tarfile.open(path, "r:gz") as tf:
        for member in tf:
            if not member.name.endswith(".csv"):
                continue
            fh = tf.extractfile(member)
            if fh is None:
                continue
            rec = _station(fh.read().decode("utf-8", errors="replace"))
            if rec:
                out.append(rec)
    return out
