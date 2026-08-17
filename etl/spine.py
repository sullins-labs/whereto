"""
The geography spine.

This is the part of the pipeline that everything else depends on and that is
easy to underestimate. Each source publishes on a different geography: ACS is
county and tract, BEA is metro only, HUD is county and small-area ZIP, FEMA is
county and tract, NOAA is weather stations, Zillow uses proprietary region IDs,
FBI is law-enforcement agencies. None of them join without a deliberate spine.

Design:

  atom    = county (5-digit FIPS). Every metric in the model exists at county
            level or can be honestly aggregated to it. Tract would be better
            for rings and is the documented upgrade path, but 85,000 tracts
            multiplies both the build and the failure modes, and most of the
            factors here do not exist below county anyway.

  anchor  = CBSA. What the interface calls "near Raleigh".

  ring    = 0..4, derived, never invented.

The ring derivation is the one judgement call worth defending. It is built
from three published federal classifications rather than from multipliers:

  * Census CBSA delineation flags each county Central or Outlying.
  * USDA ERS Rural-Urban Continuum Codes place each county on a nine-level
    scale from "metro of 1m+" to "rural, not adjacent to a metro".
  * Census Gazetteer gives land area, so density is measurable rather than
    assumed.

Combined, those give a defensible five-level ring. When someone asks why a
county landed in ring 3, the answer is a citation, not a coefficient.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

EARTH_MI = 3958.8

# USDA Rural-Urban Continuum Codes, 2023 vintage.
#  1 metro 1m+ | 2 metro 250k-1m | 3 metro <250k
#  4 urban 20k+ adjacent to metro | 5 urban 20k+ not adjacent
#  6 urban 2.5-20k adjacent       | 7 urban 2.5-20k not adjacent
#  8 rural adjacent to metro      | 9 rural not adjacent
RUCC_METRO = {1, 2, 3}
RUCC_RURAL = {8, 9}

RING_NAMES = {
    0: "city core",
    1: "inner suburbs",
    2: "outer suburbs",
    3: "small towns",
    4: "rural",
}


@dataclass
class County:
    fips: str
    name: str
    state: str
    lat: float
    lon: float
    land_sq_mi: float
    population: int = 0
    cbsa: str | None = None
    cbsa_name: str | None = None
    central: bool = False       # Census "Central/Outlying" flag
    rucc: int = 9
    ring: int | None = None
    anchor_fips: str | None = None
    drive_min: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def density(self) -> float:
        return self.population / self.land_sq_mi if self.land_sq_mi > 0 else 0.0


def haversine_mi(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MI * math.asin(math.sqrt(h))


MAX_SENSIBLE_DRIVE_MIN = 240


def straight_line_to_drive_minutes(miles: float, ring_hint: int) -> tuple[int, bool]:
    """Crude but honest stand-in for a routed isochrone.

    A real build should call OSRM against an OpenStreetMap extract and take the
    actual drive time; that is a container and an hour of setup, and it is the
    single highest-value upgrade to this pipeline. Until then: a circuity
    factor of 1.28 (the usual road-network detour ratio) and an effective speed
    that rises with distance, because a long trip is mostly highway while a
    short one is mostly junctions. A flat per-ring speed gets this badly wrong
    — it turned a 20-mile suburban commute into 86 minutes.

    Returns (minutes, capped). Everything produced here is tagged
    `drive_estimated` in the output so the interface can say so.
    """
    circuity = 1.28
    mph = min(58.0, max(14.0, 14 + 0.55 * miles + ring_hint * 3.5))
    minutes = max(4, round(miles * circuity / mph * 60))
    if minutes > MAX_SENSIBLE_DRIVE_MIN:
        return MAX_SENSIBLE_DRIVE_MIN, True
    return minutes, False


def assign_rings(counties: list[County]) -> list[County]:
    """Place every county on the 0-4 ring scale.

    Order matters: the CBSA flag decides metro membership, RUCC decides how
    rural, and density only breaks ties inside the metro. Density alone would
    put Manhattan and a dense small city in the same ring, which is wrong —
    the ring is about position relative to a center, not about crowding.
    """
    by_cbsa: dict[str, list[County]] = {}
    for c in counties:
        if c.cbsa:
            by_cbsa.setdefault(c.cbsa, []).append(c)

    # Anchor of each CBSA: the central county with the largest population.
    anchors: dict[str, County] = {}
    for cbsa, members in by_cbsa.items():
        central = [m for m in members if m.central] or members
        anchors[cbsa] = max(central, key=lambda m: m.population)

    for c in counties:
        if not c.cbsa:
            # Outside any CBSA. RUCC alone decides.
            c.ring = 4 if c.rucc in RUCC_RURAL else 3
            c.notes.append("no CBSA; ring from RUCC alone")
            nearest = _nearest_anchor(c, anchors)
            if nearest:
                miles = haversine_mi(c.lat, c.lon, nearest.lat, nearest.lon)
                c.anchor_fips = nearest.fips
                c.cbsa_name = nearest.cbsa_name
                c.drive_min, capped = straight_line_to_drive_minutes(miles, c.ring)
                if miles > 120:
                    # Genuinely remote. Naming an anchor three hours away is
                    # worse than admitting there isn't one nearby.
                    c.notes.append(f"remote: nearest anchor is {miles:.0f} mi away")
            continue

        anchor = anchors[c.cbsa]
        c.anchor_fips = anchor.fips
        miles = haversine_mi(c.lat, c.lon, anchor.lat, anchor.lon)

        # Ring 0 needs proximity as well as density. Nassau County is dense
        # and officially central, but it is twenty miles out on Long Island
        # and is nobody's idea of the city core.
        if c is anchor:
            ring = 0
        elif c.central and c.density >= 2000 and miles <= 15:
            ring = 0
        elif c.central:
            ring = 1
        elif c.rucc in RUCC_METRO and c.density >= 400:
            ring = 1 if miles < 25 else 2
        elif c.rucc in RUCC_METRO:
            ring = 2 if miles < 45 else 3
        elif c.rucc in RUCC_RURAL:
            ring = 4
        else:
            ring = 3

        c.ring = ring
        c.drive_min, capped = straight_line_to_drive_minutes(miles, ring)
        if capped:
            c.notes.append("drive time capped; anchor is implausibly distant")
        c.notes.append(
            f"ring {ring}: {'central' if c.central else 'outlying'}, "
            f"RUCC {c.rucc}, {c.density:,.0f}/sq mi, {miles:.0f} mi from anchor"
        )

    return counties


def _nearest_anchor(c: County, anchors: dict[str, County]) -> County | None:
    if not anchors:
        return None
    return min(anchors.values(), key=lambda a: haversine_mi(c.lat, c.lon, a.lat, a.lon))


def split_core_counties(counties: list[County]) -> list[County]:
    """Flag counties that genuinely span more than one ring.

    A single county can hold a dense downtown and open farmland — Marion County
    Indiana, or any consolidated city-county. Aggregating those into one number
    is the biggest honest weakness of a county-grained model, so rather than
    hide it we mark it, and the interface widens its uncertainty accordingly.
    Resolving it properly means moving to tracts.
    """
    for c in counties:
        # A large county at the center of a metro necessarily contains both
        # downtown and open country. Density does not detect this — Gallatin
        # County holds Bozeman and 2,600 square miles of mountain.
        if c.ring is not None and c.ring <= 1 and c.land_sq_mi > 400:
            c.notes.append("heterogeneous: county spans core and rural; tract-level recommended")
    return counties


def summarize(counties: list[County]) -> dict:
    out: dict = {"total": len(counties), "by_ring": {}, "unassigned": 0, "heterogeneous": 0}
    for c in counties:
        if c.ring is None:
            out["unassigned"] += 1
            continue
        k = f"{c.ring} {RING_NAMES[c.ring]}"
        out["by_ring"][k] = out["by_ring"].get(k, 0) + 1
        if any("heterogeneous" in n for n in c.notes):
            out["heterogeneous"] += 1
    return out
