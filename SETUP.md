# Setup: one evening, all free

Order matters. Each step depends on the one before it.

## 1. GitHub repository: **public**

```bash
gh repo create sullins-labs/whereto --public --source=. --push
```

Public is not cosmetic. Actions minutes are **unlimited on public repos** and
capped at 2,000/month on private. It is also the whole point of a portfolio
piece: the code being readable *is* the artifact.

Nothing secret lives in the repo. Keys go in Settings → Secrets, never in files.

## 2. Free API keys: five forms, about fifteen minutes

| Secret name | Register |
|---|---|
| `CENSUS_API_KEY` | api.census.gov/data/key_signup.html |
| `BEA_API_KEY` | apps.bea.gov/API/signup |
| `BLS_API_KEY` | data.bls.gov/registrationEngine |
| `HUD_API_TOKEN` | huduser.gov/portal/dataset/fmr-api.html |
| `FBI_CDE_API_KEY` | api.data.gov/signup |

```bash
gh secret set CENSUS_API_KEY --body "..."
```

Register for BLS specifically. Unregistered is 25 calls a day against the 126
this pipeline needs; registered is 500.

## 3. First cold build: run it locally, not in CI

```bash
pip install -r requirements.txt
python -m etl.feasibility        # confirm it still fits before spending an hour
python -m etl.build              # ~70 min, 744 MB
python -m etl.build --verify     # re-hash what just landed
```

Locally first because the cold build is the run most likely to surface a
source that has moved, and watching it is faster than reading CI logs. After
that, routine runs are about seven minutes and belong in Actions.

## 4. Hosting (superseded, read this before following anything below)

**This step no longer applies.** It described standing up a separate
Cloudflare Pages deployment on the `sullinslabs.com` apex domain. That is not
what happened.

As of August 2026, `sullinslabs.com` is a single Astro site deployed on
**Netlify**, and this app ships as static files inside it at
**`/whereto/`**. The domain is registered and DNS-hosted at **Porkbun**
(nameservers salvador/curitiba/maceio/fortaleza.ns.porkbun.com), with MX
records pointed at Fastmail. Netlify is only the site host, not the
nameserver. There is no separate Cloudflare Pages project, and creating one
on this domain would collide with the live site.

Live URL: <https://sullinslabs.com/whereto/index.html>

The zero-cost argument below still holds in that nothing in the stack meters
per request the way a server would. But Netlify's free tier is metered by a
**monthly credit allowance**, not the bandwidth-only model this doc used to
describe, and the failure mode is worse than "asked to upgrade." See "What
this costs" below.

### How the app reaches production now

**This repo is authoritative for the whole app.** That includes the markup,
the scoring code, the Sullins Labs theming and the built data. The sullinslabs
repo holds a deployed copy at `public/whereto/` which is generated, never
hand-edited. Anything edited there is lost on the next sync.

That boundary exists because the two copies had already diverged once: the
deployed copy grew the theme toggle, the back link and `theme-tokens.css`
while `site/` did not. Those changes now live here, where the pipeline that
keeps changing the app can also change its markup.

Three files cross the boundary, and only in this direction:

| From this repo | To `public/whereto/` | Changes when |
|---|---|---|
| `site/index.html` | `index.html` | the app changes |
| `site/theme-tokens.css` | `theme-tokens.css` | the theming changes |
| `data/dist/places.json` | `data/places.json` | every ETL run |

Both presentation files are written to be portable, so they work served from
a domain root or from a subpath: `theme-tokens.css` is linked relatively and
the back link is an absolute URL to `sullinslabs.com`.

```bash
sh scripts/sync-to-sullinslabs.sh            # dry run, shows what differs
sh scripts/sync-to-sullinslabs.sh --apply    # copy
```

The script refuses to run in the other direction, normalizes line endings to
LF to match what is committed in the sullinslabs repo, and reports the files
that actually differ so a routine data-only run does not touch the markup.
Publishing stays a separate, deliberate step.

## 5. Turn on the schedule

`.github/workflows/etl.yml` runs on the first of each month and can be
triggered by hand. It restores the archive from cache, verifies checksums,
builds, runs the tests, pushes snapshots to a Release, and commits
`data/dist/places.json`.

Note that committing that file does **not** currently redeploy anything. The
sullinslabs site is deployed manually, so publishing a fresh dataset is two
more steps after the workflow finishes:

```bash
sh scripts/sync-to-sullinslabs.sh --apply
cd ../sullinslabs && netlify deploy --prod
```

Wiring that up automatically is an open task.

---

## What this costs

Nothing, and structurally so.

| | Free tier | This project |
|---|---|---|
| GitHub Actions | unlimited, public repos | 7 min/month, 29 in an annual month |
| GitHub Releases | 2 GB per asset | 0.05 GB/month, split by source |
| Repository | 1 GB soft limit | ~3 MB, snapshots are never committed |
| Netlify | monthly credit allowance | ~2 deploys/month, built locally |
| Every data API | free with a key | 126 of 450 daily calls at the tightest point |

Netlify's free tier used to be described here purely in terms of bandwidth.
It no longer works that way: Netlify meters usage (builds, deploys, requests)
against a **credit allowance that resets on a monthly cycle**. On 2026-08-18
the account ran out of credit for the cycle after three production deploys
in a single day — normal cadence is roughly monthly, not daily. The result
was not a bill. It was **production deploys pausing entirely** until the
cycle reset (2026-08-25), plus a warning that if *operational* credits are
also exhausted, **published sites get suspended**, which is a step worse
than a paused deploy. The practical rule: batch related changes into one
production deploy instead of deploying per change.

Two things would break the rest of it: making the repo private, and
monetising the site, at which point Open-Meteo's and MIT's non-commercial
tiers stop applying. Both sources sit behind swappable adapters for exactly
that reason.
