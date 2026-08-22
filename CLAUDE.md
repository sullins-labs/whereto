# CLAUDE.md — whereto (Wheretolive)

This file is inherited by any agent working in this repo. Read it before
touching code, data, or CI here.

## What this is

Wheretolive (product name as of 2026-08-17; repo/GitHub name stays `whereto`)
is a free tool for deciding where to live, built entirely on public federal
data at zero marginal cost. It is a static-data pipeline (Python ETL, this
repo, `etl/`) plus a static HTML/JS scoring site (`site/index.html`) — no
server, no database, no serverless function. Scoring runs client-side, in the
visitor's browser.

Full architecture and rationale: `README.md`. Data licensing: `DATA.md`.
Setup and deploy mechanics: `SETUP.md`.

**This repo deploys inside sullinslabs.com — a cross-program coupling.**
This app is not its own site. It ships as static files at
`https://sullinslabs.com/whereto/` inside the separate `sullinslabs` repo's
Astro site. `whereto` is authoritative for the app (markup, scoring code,
theming, built data); the `sullinslabs` repo holds a **generated, never
hand-edited** copy at `public/whereto/`. Changes to sullinslabs.com's site
structure (routing, layout, shared CSS) can break this app, and changes here
that assume a domain root instead of a subpath can break there. Coordinate
with the sullinslabs program before changing anything that crosses that
boundary (URLs, relative paths, shared theming assumptions).

Publishing is manual and three steps, none of which are triggered by a
commit landing in this repo:
1. `python -m etl.build` (locally, or via the monthly CI cron)
2. `sh scripts/sync-to-sullinslabs.sh --apply` — one-way sync into the
   sullinslabs repo; refuses to run the other direction
3. `cd ../sullinslabs && netlify deploy --prod`

Committing `data/dist/places.json` here does **not** redeploy the live site.
**Do not run step 3 (or any `netlify deploy`) without explicit authorization
— Netlify credits are a shared, exhaustible resource (see below).**

## The ETL cron — read this before touching etl/ or .github/workflows/etl.yml

`.github/workflows/etl.yml` ("Refresh data") runs monthly on
`0 9 1 * *` (00:09 UTC, 1st of month) plus `workflow_dispatch`. **The next
scheduled run is 2026-09-01, and it is the first run since the
redistributable-source license filter (below) was added** — that filter has
only ever been exercised by hand, never by the cron itself. Treat that run
as unverified in production until it's been watched.

The job: restores the `data/raw` archive from cache, verifies checksums,
builds (`python -m etl.build`, using five API-key secrets — see below), runs
the full test suite, archives redistributable-only source snapshots to a
GitHub Release, and commits `data/dist/places.json` back to `main` as the
`etl` bot user. It does not sync to sullinslabs or deploy — see "Publishing"
above.

Five secrets, all free-tier API keys, live in GitHub Settings → Secrets
(never in files): `CENSUS_API_KEY`, `BLS_API_KEY`, `BEA_API_KEY`,
`HUD_API_TOKEN`, `FBI_CDE_API_KEY`. Register instructions are in `SETUP.md`.

## Licensing is load-bearing, not a note somebody remembers

Every source is registered in `etl/config.py`'s `SOURCES` dict with a
`redistributable: bool` flag. The snapshot-archive step in
`.github/workflows/etl.yml` derives its allowlist of directories to tar and
publish **from that flag at run time**, and fails the build loudly
(`::error::` + `exit 1`) if a non-redistributable source's raw directory
ends up in the built tarball anyway. This is a fail-loud guard, not
documentation — treat it as the actual enforcement mechanism.

**Zillow ZHVI (`zillow_zhvi`) and MIT election data (`mit_election`) must
never appear in a published release asset.** `mit_election` is CC BY-NC,
non-commercial and non-redistributable by explicit project decision (not
just the source's default badge — see `etl/config.py` comments near
`mit_election` and program memory for the CC0-vs-CC-BY-NC reasoning).
Open-Meteo and the MIT Living Wage Calculator are similarly non-commercial-
only; they don't appear in raw form in `data/raw` snapshots at all today,
but if that ever changes, they need the same `redistributable=False`
treatment.

**On 2026-08-20 this guard did not yet exist** and a wholesale tar of
`data/raw` was published as a public release asset, leaking Zillow and MIT
election data. It was caught, the asset deleted, and the workflow rewritten
to the config-driven, fail-loud form described above (commit `0774467`). If
you touch the "Archive snapshots to release" step in `etl.yml`, do not
reintroduce a hardcoded directory list — derive from `SOURCES[*].redistributable`
or the guard is worthless the next time a source is added.

## Never commit

- `data/raw/` — gitignored; this is the archived-bytes layer, hundreds of MB,
  and some of it (Zillow, MIT election) must never leave this machine or CI's
  ephemeral runner except as an allowlisted, config-driven release asset (see
  above).
- `.env`, any file containing an API key — gitignored. Keys are GitHub Actions
  secrets only. If you ever see a bare key string in a diff, stop and report
  it rather than committing.
- Anything under `.venv/`.

## git add: explicit paths only

Never `git add .` or `git add -A` in this repo. Josh commits and pushes to
this repo directly and live, sometimes while an agent is mid-task in the
same working tree — a broad `git add` can sweep up someone else's in-flight,
unrelated, or half-finished changes. Stage only the exact files a task
authorized, by name. Run `git status` immediately before staging (not
earlier in the session — the tree can have changed) and `git show --stat
HEAD` after committing to confirm exactly what landed.

All commits in this repo use `user.email = support@sullinslabs.com`, set as
a **repo-local** override (`git config user.email support@sullinslabs.com`),
not the global config. Never author a commit with
`sullinslabs@gmail.com`, `josh@sullinslabs.com`, or any
`@users.noreply.github.com` address — these are deprecated. Two pre-existing
commits (`bd3d9bd`, `4c29c12`) already carry a deprecated noreply address;
that is known, reported, and intentionally not rewritten — don't "fix" it
without explicit authorization, published history stays as it is.

## Project-specific traps

- **HUD rent data is broken upstream, not an auth problem.** `huduser.gov`
  returns empty for `FY2026_4050_FMRs.xlsx` even with `HUD_API_TOKEN`
  correctly present. `fmr_*` fields are 0% populated; `rent_monthly` is
  currently 100% ACS fallback. If you touch rent-related UI or copy, make
  sure it doesn't credit HUD for figures that are actually all-ACS —
  that's quiet, user-facing data degradation, not a cosmetic bug.
- **Crime data cannot be restored.** This is a permanent upstream condition
  (FBI CDE bulk agency download withdrawn, no county endpoint, per-agency
  calls infeasible against the API quota), not a bug to fix. The `fbi_cde`
  extractor refuses immediately by design; the site reports "not reported."
  Don't propose "just fix the crime extractor" without first re-verifying
  upstream has changed.
- **Two contract fields are declared but never built:** `state_lean`
  (declared in `etl/contract.py`, no extractor has ever populated it) and
  `pcp_per_100k` (needs an AHRF extractor that doesn't exist; 0% coverage).
  Both are tracked as known, registered gaps in
  `tests/test_contract_coverage.py` — that test file is the source of truth
  for what's a known gap vs. a regression. Check it before treating either
  field's absence as a new bug.
- **Raw-score curves for STATIC factors don't affect output.** `percentiles()`
  only cares about rank order, not the underlying curve shape, so tuning a
  static factor's raw-score curve is wasted effort unless it changes
  relative ordering. Don't spend time "improving" a curve without confirming
  it actually reorders anything.
- **Netlify credits are a shared, exhaustible resource**, not unlimited CI
  minutes. The account exhausted its monthly credit on 2026-08-18 after
  three production deploys in one day; deploys paused until the next cycle
  reset, with a warning that exhausting *operational* credit too gets a
  published site suspended (worse than paused). Batch changes into one
  deploy. Never run `netlify deploy --prod` for a one-line tweak, and never
  run it without explicit authorization — it's a production action against
  a shared budget, not a local build step.
- **Two Pythons on this machine.** A bare system `python` lacks
  `requests`/`pandas`/etc.; use `.venv/Scripts/python.exe` (or an activated
  `.venv`) for anything in this repo. The test suite is 5-6 files run
  individually (`python tests/test_spine.py`, etc. — see `.github/workflows/etl.yml`
  for the current list), not a single pytest command; there's no pytest
  dependency here at all.
- **The geography spine and ring derivation are the easiest part to break
  silently.** `tests/test_spine.py` checks ring assignment against counties
  whose classification is well known (it has caught real bugs before). Don't
  change `etl/spine.py` without running that test.

## What this file is not

Not a build/setup guide (`SETUP.md`), not a licensing reference (`DATA.md`),
not an architecture deep-dive (`README.md`). Read those for the "how" and
"why" of the pipeline design; this file exists so the traps above don't get
rediscovered the hard way.
