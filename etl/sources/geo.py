"""The spine loader: Gazetteer + CBSA delineation + USDA RUCC.

Three files, three different shapes, one join. This runs before everything
else because nothing else has anywhere to land without it.
"""
from __future__ import annotations
import csv, io, zipfile
from ..snapshot import fetch
from ..spine import County, assign_rings, split_core_counties

STATE_BY_FIPS = {}   # populated from the gazetteer


def _gazetteer() -> dict[str, County]:
    path = fetch("census_gazetteer", filename="gaz_counties.zip")
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith((".txt", ".csv")))
        text = z.read(member).decode("latin-1")
    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        fips = row["GEOID"]
        out[fips] = County(
            fips=fips,
            name=row["NAME"],
            state=row["USPS"],
            lat=float(row["INTPTLAT"]),
            lon=float(row["INTPTLONG"]),
            # ALAND is square metres; 2,589,988 to the square mile. Getting this
            # wrong silently turns every density figure into nonsense, which is
            # why validate.py bounds density rather than trusting it.
            land_sq_mi=float(row["ALAND"]) / 2_589_988.0,
        )
        STATE_BY_FIPS[fips] = row["USPS"]
    return out


def _cbsa(counties: dict[str, County]) -> tuple[int, int]:
    """Census publishes this as .xlsx with a title block above the header and
    footnotes below it. Both have to be skipped by content, not by a fixed row
    offset, because the number of footnotes changes between vintages.

    Returns (fetched, kept): fetched is the number of real data rows in the
    delineation file (footnotes and the title block already excluded); kept
    is how many of those rows matched a county already in the gazetteer.
    """
    import openpyxl
    path = fetch("census_cbsa_delineation", filename="cbsa_delineation.xlsx")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    header, rows = None, []
    for row in ws.iter_rows(values_only=True):
        vals = [str(v).strip() if v is not None else "" for v in row]
        if header is None:
            if "CBSA Code" in vals and "FIPS County Code" in vals:
                header = {v: i for i, v in enumerate(vals)}
            continue
        if not vals[header["CBSA Code"]].isdigit():
            continue                      # footnote rows
        rows.append(vals)

    if header is None:
        raise RuntimeError("CBSA delineation: header row not found; layout changed")

    kept = 0
    for vals in rows:
        fips = vals[header["FIPS State Code"]].zfill(2) + vals[header["FIPS County Code"]].zfill(3)
        c = counties.get(fips)
        if not c:
            continue
        c.cbsa = vals[header["CBSA Code"]]
        c.cbsa_name = vals[header["CBSA Title"]]
        c.central = vals[header["Central/Outlying County"]].lower().startswith("central")
        kept += 1
    return len(rows), kept


def _rucc(counties: dict[str, County]) -> tuple[int, int]:
    """Returns (fetched, kept): fetched is every row read from the RUCC csv;
    kept is how many matched a county and carried a usable RUCC value."""
    path = fetch("usda_rucc", filename="rucc.csv")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    fetched, kept = 0, 0
    for row in csv.DictReader(io.StringIO(text)):
        fetched += 1
        fips = (row.get("FIPS") or row.get("FIPStxt") or "").zfill(5)
        c = counties.get(fips)
        if not c:
            continue
        attr = (row.get("Attribute") or "").strip()
        if attr in ("RUCC_2023", "RUCC_2013", ""):
            try:
                c.rucc = int(float(row.get("Value") or row.get("RUCC_2023") or 9))
                kept += 1
            except (TypeError, ValueError):
                pass
    return fetched, kept


def extract(population: dict[str, int] | None = None,
           stats: dict | None = None) -> dict[str, dict]:
    """stats, if given, is a mutable dict that this fills in with
    {source_key: (fetched, kept)} for each of the three SOURCES keys this
    extractor touches — used by build.py for per-source instrumentation.
    Optional and side-effect-only so every other caller is unaffected.
    """
    counties = _gazetteer()
    cbsa_fetched, cbsa_kept = _cbsa(counties)
    rucc_fetched, rucc_kept = _rucc(counties)
    if stats is not None:
        # The gazetteer is the spine itself: every row it parses becomes a
        # county, with no join or filter to fall short of, so fetched and
        # kept are the same number by construction, not by approximation.
        stats["census_gazetteer"] = (len(counties), len(counties))
        stats["census_cbsa_delineation"] = (cbsa_fetched, cbsa_kept)
        stats["usda_rucc"] = (rucc_fetched, rucc_kept)

    # Rings need population, which comes from ACS. Passing it in rather than
    # importing keeps the dependency one-directional.
    for fips, pop in (population or {}).items():
        if fips in counties:
            counties[fips].population = pop

    ordered = list(counties.values())
    split_core_counties(assign_rings(ordered))

    anchors = {c.fips: c for c in ordered}
    out = {}
    for c in ordered:
        anchor = anchors.get(c.anchor_fips or "")
        out[c.fips] = {
            "fips": c.fips, "name": c.name, "state": c.state,
            "lat": c.lat, "lon": c.lon, "land_sq_mi": round(c.land_sq_mi, 1),
            "population": c.population, "density": round(c.density, 1),
            "cbsa": c.cbsa, "cbsa_name": c.cbsa_name, "rucc": c.rucc,
            "ring": c.ring,
            "anchor_name": (anchor.cbsa_name or anchor.name) if anchor else c.name,
            "drive_min": c.drive_min, "drive_estimated": True,
            "spine_notes": c.notes,
        }
    return out
