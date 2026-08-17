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
**`/whereto/`**. Nameservers point at Netlify, not Cloudflare. There is no
separate Cloudflare Pages project, and creating one on this domain would
collide with the live site.

Live URL: <https://sullinslabs.com/whereto/index.html>

The zero-cost argument below still holds, and for the same reason: the site
is purely static, so nothing in the stack meters per request. Netlify's free
tier does include a bandwidth allowance rather than being uncapped the way
Cloudflare Pages was, so that is the one number worth watching. At 100 GB a
month against a roughly 3 MB cold visit, it takes on the order of 30,000
visits a month to reach it, and the failure mode is being asked to upgrade
rather than an unexpected bill.

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
| Netlify | 100 GB/month bandwidth | ~2 deploys/month, built locally |
| Every data API | free with a key | 126 of 450 daily calls at the tightest point |

Two things would break it: making the repo private, and monetising the site,
at which point Open-Meteo's and MIT's non-commercial tiers stop applying. Both
sources sit behind swappable adapters for exactly that reason.
