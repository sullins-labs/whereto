"""
Source registry.

Every external dataset the pipeline touches is declared here and nowhere else.
Extractors read from this; the licence table on the website is generated from
it; the archival manifest records against it. When a source changes its URL or
a licence changes, exactly one file needs editing.

`key` is the archive folder name and must never be reused for a different
dataset, because the archive is append-only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CURATED = ROOT / "data" / "curated"
DIST = ROOT / "data" / "dist"

# Bump when the output contract changes shape. The site checks it on load.
CONTRACT_VERSION = 1


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    url: str
    cadence: str
    licence: str
    # "public-domain" sources can be redistributed; "restricted" ones may only
    # be used to derive values, never republished as-is. transform.py enforces
    # this: a restricted source may not appear verbatim in the output.
    redistributable: bool
    needs_key: str | None = None       # env var holding the API key
    # What the API calls its key, because no two of them agree. Getting this
    # wrong is not a 401: BEA answers 200 with an empty body and BLS answers
    # 200 with a per-series "does not exist", both of which read downstream as
    # "the source had no data for you" rather than "you failed to authenticate".
    key_param: str = "key"
    key_style: str = "query"           # query | body | bearer
    daily_call_cap: int | None = None  # hard cap the fetcher will not exceed
    notes: str = ""
    params: dict = field(default_factory=dict)


SOURCES: dict[str, Source] = {}


def register(s: Source) -> Source:
    if s.key in SOURCES:
        raise ValueError(f"duplicate source key {s.key!r}; keys are permanent")
    SOURCES[s.key] = s
    return s


# ---------------------------------------------------------------- geography

register(Source(
    key="census_gazetteer",
    name="Census Gazetteer: counties",
    url="https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_counties_national.zip",
    cadence="annual", licence="Public domain", redistributable=True,
    notes="County FIPS, name, land area, internal point lat/lon. The spine.",
))

register(Source(
    key="census_cbsa_delineation",
    name="Census CBSA delineation file",
    url="https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx",
    cadence="periodic", licence="Public domain", redistributable=True,
    notes=(
        "Maps every county to its CBSA and flags it Central or Outlying. "
        "This flag is the backbone of the ring model — it is an official "
        "designation rather than something we invent."
    ),
))

register(Source(
    key="usda_rucc",
    name="USDA ERS Rural-Urban Continuum Codes",
    # ERS reorganised its media paths; the old allrfjb2 slug now 404s. Long
    # format, FIPS/State/County_Name/Attribute/Value, RUCC_2023 as an
    # Attribute row, which is the shape geo._rucc already reads.
    url="https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv",
    cadence="decennial", licence="Public domain", redistributable=True,
    notes=(
        "Nine-level county classification from 'metro, 1m+' down to 'rural, "
        "not adjacent to a metro'. Combined with the CBSA central/outlying "
        "flag and population density this produces the five rings without "
        "inventing a single multiplier."
    ),
))

# ------------------------------------------------------------- demographics

register(Source(
    key="census_acs5",
    name="Census ACS 5-year, county",
    url="https://api.census.gov/data/{vintage}/acs/acs5",
    cadence="annual", licence="Public domain", redistributable=True,
    needs_key="CENSUS_API_KEY",
    params={
        "vintage": 2024,
        "variables": {
            "B01003_001E": "population",
            "B19013_001E": "median_household_income",
            "B25077_001E": "median_home_value",
            "B25064_001E": "median_gross_rent",
            "B25041_001E": "housing_units",
            "B08303_001E": "commute_total",
            "B15003_022E": "bachelors",
            "B01002_001E": "median_age",
        },
    },
))

register(Source(
    key="bea_rpp",
    name="BEA Regional Price Parities",
    url="https://apps.bea.gov/api/data",
    cadence="annual", licence="Public domain", redistributable=True,
    needs_key="BEA_API_KEY",
    key_param="UserID",   # verified: "key" returns 200 with a zero-byte body

    params={"TableName": "MARPP", "LineCode": 1, "GeoFips": "MSA"},
    notes="Cost of living by metro, indexed to the national level = 100.",
))

register(Source(
    key="bls_laus",
    name="BLS Local Area Unemployment Statistics",
    url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
    cadence="monthly", licence="Public domain", redistributable=True,
    needs_key="BLS_API_KEY",
    key_param="registrationkey", key_style="body",   # v2 rejects GET with 405

    daily_call_cap=450,   # registered ceiling is 500/day; leave headroom
    params={"series_per_call": 50},
    notes=(
        "The tightest rate limit in the pipeline. 3,144 counties at 50 series "
        "per call is 63 calls, so a full refresh fits comfortably inside one "
        "day — but only because we batch. Never call this per-request."
    ),
))

# ------------------------------------------------------------------ housing

register(Source(
    key="hud_fmr",
    name="HUD Fair Market Rents",
    url="https://www.huduser.gov/hudapi/public/fmr/data/{fips}",
    cadence="annual", licence="Public domain", redistributable=True,
    needs_key="HUD_API_TOKEN",
    key_style="bearer",

    notes="Effective 1 October each year; published August-September.",
))

register(Source(
    key="zillow_zhvi",
    name="Zillow ZHVI, county",
    url="https://files.zillowstatic.com/research/public_csvs/zhvi/County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    cadence="monthly", licence="Attribution; no redistribution",
    redistributable=False,
    notes=(
        "Free to download and derive from, but the terms forbid republishing "
        "the files. We emit derived index values only, never the series."
    ),
))

# ------------------------------------------------------------ hazard, health

register(Source(
    key="fema_nri",
    name="FEMA National Risk Index, counties",
    # hazards.fema.gov retired the whole StaticDocuments tree: every path under
    # it, including PDFs search engines still index, 301s to a RAPT landing
    # page and then 403s. The data itself is still published by FEMA, from
    # their own ArcGIS account (FEMA_NationalRiskIndex), backing this layer:
    #   services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/
    #     National_Risk_Index_Counties/FeatureServer/0
    # That layer caps at 2,000 records against 3,232 counties, so it would
    # need paging. The Hub download below returns the whole table as one csv,
    # which is one fetch and one checksum.
    url=("https://hub.arcgis.com/api/v3/datasets/"
         "39485e8035d446a5bff03259508ae355_0/downloads/data"
         "?format=csv&spatialRefId=4326"),
    cadence="multi-year", licence="Public domain", redistributable=True,
    notes=(
        "Eighteen hazards with expected annual loss per county. FEMA retired "
        "the web application but kept the download, which is exactly why this "
        "pipeline archives rather than re-fetches."
    ),
))

register(Source(
    key="noaa_normals",
    name="NOAA NCEI 1991-2020 Climate Normals, monthly",
    # The access/ path is a directory index of ~15,600 per-station files, so
    # fetching it returned an HTML listing that the csv parser read as data.
    # archive/ carries the same release as one tarball.
    url=("https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/archive/"
         "us-climate-normals_1991-2020_v1.0.1_monthly_multivariate_by-station"
         "_c20230404.tar.gz"),
    cadence="decennial", licence="Public domain", redistributable=True,
    notes="Station-level. Aggregated to county by inverse-distance weighting.",
))

register(Source(
    key="epa_aqs",
    name="EPA AQS annual air quality by county",
    url="https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_{year}.zip",
    cadence="annual", licence="Public domain", redistributable=True,
))

register(Source(
    key="hrsa_hpsa",
    name="HRSA Health Professional Shortage Areas",
    url="https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv",
    cadence="quarterly", licence="Public domain", redistributable=True,
))

register(Source(
    key="fbi_cde",
    name="FBI Crime Data Explorer: agency offences",
    url="https://api.usa.gov/crime/fbi/cde/estimate/state/{state}/{offense}",
    cadence="annual", licence="Public domain", redistributable=True,
    needs_key="FBI_CDE_API_KEY",
    notes=(
        "Coverage is not universal and varies by agency. validate.py refuses "
        "to emit a crime figure for any county below the coverage floor rather "
        "than silently publishing a number built from partial reporting."
    ),
))

register(Source(
    key="nces_ccd",
    name="NCES Common Core of Data: district finance and enrolment",
    url="https://nces.ed.gov/ccd/Data/zip/ccd_lea_finance.zip",
    cadence="annual", licence="Public domain", redistributable=True,
))

# ------------------------------------------------------------------ politics

register(Source(
    key="mit_election",
    name="MIT Election Data and Science Lab: county presidential returns",
    url="https://dataverse.harvard.edu/api/access/datafile/:persistentId?persistentId=doi:10.7910/DVN/VOQCHQ",
    cadence="per election", licence="CC BY-NC", redistributable=False,
    notes="Non-commercial. Used to derive a local lean index, not republished.",
))

# ---------------------------------------------------- curated, no API exists
# Some of what this model needs is statute, not data. Nobody publishes a
# machine-readable feed of "does this state tax Social Security". These live
# as reviewed YAML with a source note and an as-of date per field, and they
# are treated as first-class inputs, not hardcoded constants.

CURATED_FILES = {
    "state_tax": CURATED / "state_tax.yaml",
    "state_services": CURATED / "state_services.yaml",
    "state_policy": CURATED / "state_policy.yaml",
}


def sources_needing_keys() -> dict[str, str]:
    return {s.key: s.needs_key for s in SOURCES.values() if s.needs_key}


def licence_table() -> list[dict]:
    """Feeds the licence table rendered on the site, so the page can never
    drift out of sync with what the pipeline actually pulled."""
    return [
        {
            "name": s.name,
            "cadence": s.cadence,
            "licence": s.licence,
            "redistributable": s.redistributable,
        }
        for s in SOURCES.values()
    ]
