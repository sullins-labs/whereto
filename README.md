# whereto-etl

The data pipeline behind [Wheretolive](https://sullinslabs.com/whereto/index.html), a tool for
deciding where to live, built entirely on public data at zero marginal cost.

```bash
pip install -r requirements.txt
python -m etl.build            # full run
python -m etl.build --offline  # rebuild from the archive, no network
python -m etl.build --verify   # re-hash the archive, change nothing
```

---

## Why it is shaped this way

**Nothing is parsed before it is archived.** Every fetch writes raw bytes to
`data/raw/<source>/<date>/` with a SHA-256, byte count, source URL and vintage
in an append-only manifest. This costs a few hundred megabytes and buys three
things that matter more:

1. Re-transforming never re-fetches, so rate limits stop constraining the
   transform code. BLS allows 500 calls a day even with a key; a pipeline that
   fetches per-request is dead on arrival.
2. Runs are reproducible. `--as-of 2026-07-01` rebuilds exactly what shipped
   that day, which is the only honest way to explain why a number moved.
3. Sources that vanish upstream survive here. NOAA retired its billion-dollar
   disasters series after 2024. FEMA took the National Risk Index application
   offline while leaving the download. Several thousand pages came off the
   Census site. A pipeline that re-fetches on every run loses all of that
   silently; one that archives keeps it.

**The build refuses rather than guesses.** `validate.py` blocks publication on
missing required fields, values outside plausibility envelopes, undersized
datasets and absent rings. A stale number the site already had is safer than a
wrong one it did not, so a blocked build leaves the previous data live.

**Sources are independent.** One failing degrades its fields and is reported;
it does not abort the run. A pipeline that dies because one endpoint is having
a bad afternoon is a pipeline nobody runs.

## The geography spine

The part that is easy to underestimate. Each source publishes on a different
geography: ACS is county and tract, BEA is metro only, HUD is county and
small-area ZIP, FEMA is county and tract, NOAA is weather stations, Zillow uses
proprietary region IDs, FBI is law-enforcement agencies. None of them join
without a deliberate spine.

- **Atom**: county, 5-digit FIPS. Every factor exists at this grain or can be
  honestly aggregated to it.
- **Anchor**: CBSA. What the interface calls "near Raleigh".
- **Ring**: 0 to 4, *derived, never invented*, from three published federal
  classifications: the Census CBSA delineation Central/Outlying flag, USDA ERS
  Rural-Urban Continuum Codes, and measured density from the Census Gazetteer.

When somebody asks why a county landed in ring 3, the answer is a citation
rather than a coefficient. `tests/test_spine.py` checks the derivation against
counties whose classification is well known, and it caught three real bugs:
Nassau County classified as city core, a 2,600-square-mile county called a
downtown, and an eighteen-hour drive time.

**Known weakness, stated rather than hidden.** A single county can hold a dense
downtown and open farmland. Those are flagged `heterogeneous` and the interface
widens its uncertainty. Fixing it properly means moving to census tracts, which
is the documented upgrade path.

## Statute is not data

Nobody publishes a machine-readable feed of "does this state tax Social
Security". `data/curated/*.yaml` holds that, maintained by hand, reviewed
annually, versioned like code, with an `as_of` date and a named source on every
file. A value without both is a guess wearing a number's clothing, and
validation rejects it.

Code is MIT. Data is not; see [DATA.md](DATA.md).

## Licenses are enforced, not documented

`config.py` marks each source `redistributable` or not. Zillow's research files
may be derived from but not republished; MIT's election data is non-commercial;
Open-Meteo's free tier is non-commercial. The transform stage refuses to emit a
restricted source verbatim, so the constraint is code rather than a note
somebody remembers.

## Cost

| | Service | Free tier | Usage |
|---|---|---|---|
| CI and ETL compute | GitHub Actions | unlimited on **public** repos | ~20 min/month |
| Snapshot archive | GitHub Releases | free, 2 GB per file | monthly tarball |
| Built data | Git | free | ~3 MB JSON |
| Hosting | Netlify | 100 GB/month bandwidth | one page inside sullinslabs.com |
| Data APIs | Census, BLS, BEA, HUD, FEMA, NOAA, FBI | free with key | monthly batch |

Total: **$0/month.** Not "cheap" but structurally incapable of billing. There is
no server, no database and no serverless function anywhere in the stack, so
there is no per-request meter that a traffic spike can turn into an invoice.
Scoring runs in the visitor's browser, which makes compute the visitor's cost
and keeps their income and household off the network entirely.

Bandwidth is the one allowance traffic can actually consume. Netlify's free
tier includes 100 GB a month, and a cold visit costs roughly 3 MB once the
real dataset lands, so it takes on the order of 30,000 visits a month to reach
it. That is an allowance rather than a meter: the failure mode is being asked
to upgrade, not an unexpected bill.

Two things would break it. Keep the repository **public**, because Actions
minutes are unlimited there and capped at 2,000/month on private. And the
moment the site earns money, the non-commercial tiers stop applying; those
sources sit behind swappable adapters for that reason.

## Keys

All free, all one form:

| Variable | Register at |
|---|---|
| `CENSUS_API_KEY` | api.census.gov/data/key_signup.html |
| `BLS_API_KEY` | data.bls.gov/registrationEngine |
| `BEA_API_KEY` | apps.bea.gov/API/signup |
| `HUD_API_TOKEN` | huduser.gov/portal/dataset/fmr-api.html |
| `FBI_CDE_API_KEY` | api.data.gov/signup |

## Status

Implemented: config registry, archival snapshot layer with checksummed
manifest and persisted rate limiting, geography spine with ring derivation,
validation gates, orchestrator, CI workflow, Census ACS and FEMA NRI
extractors, curated tax and services schema.

To do: the remaining extractors, all of which follow the two-file pattern in
`etl/sources/`; OSRM isochrones to replace the estimated drive times; and the
tract-level split for heterogeneous counties.
