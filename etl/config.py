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
    # "primary" sources may be scored on. "validation" sources exist only to
    # disagree with a primary one and are asserted out of the published file at
    # publish time, because a role recorded in a comment is not a control.
    role: str = "primary"
    # When the licence was last read from the source itself rather than assumed.
    licence_verified: str | None = None
    # Carried so the go-live checklist can catch it; CC BY-NC needs a credit.
    attribution_required: bool = False
    # Set once a live fetch has passed every gate. A source can be correctly
    # configured and still never have been exercised, and those are different
    # states worth telling apart.
    verified: bool = True


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
            # Median real estate taxes paid, owner-occupied. Divided by median
            # home value this gives an effective property tax rate per county,
            # which replaces the single hand-entered rate per state that used
            # to sit in state_tax.yaml.
            "B25103_001E": "median_real_estate_taxes",
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
    url="https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/{state}",
    cadence="annual", licence="Public domain", redistributable=True,
    needs_key="FBI_CDE_API_KEY",
    # api.data.gov calls it api_key. Sending "key" returns 403, which reads as
    # a bad key rather than a bad parameter name.
    key_param="api_key",
    verified=False,
    notes=(
        "NOT CURRENTLY OBTAINABLE AT COUNTY LEVEL. Investigated 2026-08-17; "
        "recorded here so the same dead ends are not walked twice. The bulk "
        "endpoint this pipeline used, cde/agency/download, is gone (404). "
        "cde/summarized/state/{ST}/{offense} still answers but now returns "
        "state aggregates rather than the agency rows it used to, and there is "
        "no county endpoint: cde/summarized/county/{fips} is a 404. Valid "
        "offences are violent-crime and property-crime, not 'all'. "
        "cde/agency/byStateAbbr/{ST} does work and returns every agency with "
        "its county name, and cde/summarized/agency/{ORI}/{offense} returns "
        "counts for one agency, so county figures are reachable in principle "
        "at one call per agency. Measured across PA, TX, CA, VT and WY that is "
        "roughly 43,000 agencies nationally, which against api.data.gov's "
        "1,000 requests an hour is about 43 hours of continuous calling for a "
        "single refresh, versus the 51 calls this source is budgeted. "
        "ICPSR archives county-level UCR files but behind registration, which "
        "does not fit a pipeline built on free keys and public files. "
        "Crime therefore reads 'not reported' rather than being filled from "
        "state averages, which would attach a state's rate to every county in "
        "it and be wrong in exactly the places people are comparing. "
        "Coverage was never universal anyway: validate.py refuses to emit a "
        "crime figure for any county below the coverage floor rather than "
        "publishing a number built from partial reporting."
    ),
))

register(Source(
    key="nces_ccd",
    name="NCES Common Core of Data: district finance and enrolment",
    # The School District Finance Survey (F-33). Files are named sdf{YY}_1a,
    # by fiscal year, and FY2022 is the newest published as of 2026-08-17:
    # sdf23 and sdf24 both 404. School finance runs two to three years behind,
    # so this is current rather than stale.
    url="https://nces.ed.gov/ccd/Data/zip/sdf22_1a.zip",
    cadence="annual", licence="Public domain", redistributable=True,
    notes=(
        "One tab-delimited .txt inside the zip, carrying LEAID, CONUM (the "
        "county), V33 (enrolment) and TOTALEXP together, so district finance "
        "and the county crosswalk arrive in a single fetch. No teacher count "
        "is collected here, so pupils_per_teacher is left null."
    ),
))

# ------------------------------------------------------------------ politics

register(Source(
    key="mit_election",
    name="MIT Election Data and Science Lab: county presidential returns",
    # The /datafile/ endpoint takes a *file* id; the DOI below it is the
    # *dataset*, so the previous URL was the wrong shape regardless of
    # anything else. countypres_2000-2024.tab is file 13573089 in version 20.0
    # of doi:10.7910/DVN/VOQCHQ, and format=original asks for the upload
    # rather than Dataverse's tab-separated conversion.
    #
    # UNVERIFIED, and deliberately recorded as such: as of 2026-08-16 Harvard
    # Dataverse has disabled API access during an incident ("functionality
    # such as access to our APIs, other than within a browser, is limited or
    # disabled"), answering 202 with an empty body. The file id and version
    # were read off the dataset page in a browser, so the shape is right, but
    # nothing here has been exercised against a live API. Confirm on the first
    # build after Harvard restores service.
    url="https://dataverse.harvard.edu/api/access/datafile/13573089?format=original",
    # Quarterly, not monthly: returns change once a cycle plus corrections, so
    # a monthly refetch is 200 MB of nothing and four more chances to trip an
    # outage.
    cadence="quarterly", licence="CC BY-NC", redistributable=False,
    role="primary",
    licence_verified="2026-08-17",
    attribution_required=True,
    verified=False,
    notes="Non-commercial. Used to derive a local lean index, not republished.",
))

register(Source(
    key="tonmcg_returns",
    name="tonmcg county-level presidential results (validation only)",
    # Commit-pinned. A moving branch would let the thing this is meant to
    # cross-check against change underneath the cross-check.
    url=("https://raw.githubusercontent.com/tonmcg/"
         "US_County_Level_Election_Results_08-24/"
         "8cccc82f9235dced94a76d143c59a43f4a6bf979"),
    cadence="quarterly",
    # MIT, confirmed by reading the LICENSE file in the repository rather than
    # inferring it from the GitHub badge. So redistribution is permitted, and
    # this is still validation-only: the disqualifier is provenance, not
    # licence. The data is scraped from network calls (Fox, Politico, NYT) and
    # the repository says so itself. That independence from MEDSL's
    # state-certified lineage is exactly what makes it useful as a check and
    # exactly what makes it unfit to score.
    licence="MIT", redistributable=True,
    role="validation",
    licence_verified="2026-08-17",
    notes=("Never scored. Cross-checks the two-party share county by county "
           "against MEDSL; build.py asserts no value derived from it reaches "
           "places.json."),
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
            "role": s.role,
            "licence_verified": s.licence_verified,
            "attribution_required": s.attribution_required,
            "verified": s.verified,
        }
        # Validation sources are deliberately absent from the published table:
        # listing one next to the sources the numbers came from would imply it
        # contributed to them.
        for s in SOURCES.values() if s.role == "primary"
    ]
