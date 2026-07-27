# Data sources and terms

The MIT license in this repository covers the code — the ETL
pipeline, the scoring engine, the site. It does not cover the data
those tools fetch, and it cannot: that data belongs to its
publishers and carries their terms.

Most sources are U.S. federal and public domain: Census ACS, BLS,
BEA, HUD, FEMA NRI, FBI CDE.

Two are not, and both restrict commercial use:

- **Open-Meteo** — free for non-commercial use.
- **MIT Living Wage Calculator** — non-commercial use only.

Both sit behind swappable adapters in `etl/sources/` for exactly
this reason. If this project is ever monetised, those two need
replacing with commercially-licensed equivalents before anything
ships.
