# Setup — one evening, all free

Order matters. Each step depends on the one before it.

## 1. GitHub repository — **public**

```bash
gh repo create sullinslabs/whereto --public --source=. --push
```

Public is not cosmetic. Actions minutes are **unlimited on public repos** and
capped at 2,000/month on private. It is also the whole point of a portfolio
piece: the code being readable *is* the artifact.

Nothing secret lives in the repo. Keys go in Settings → Secrets, never in files.

## 2. Free API keys — five forms, about fifteen minutes

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

## 3. First cold build — run it locally, not in CI

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
is purely static, so nothing in the stack meters per request. Netlify serves
it on the free tier with no bandwidth cap on static assets.

### How the app reaches production now

`site/` is the source of what is served at `/whereto/`. The sullinslabs repo
holds a deployed copy at `public/whereto/`. Keep these in sync deliberately:

- `site/index.html` and `site/theme-tokens.css` are the presentation layer.
  Both are written to be portable, so they work whether the app is served
  from a domain root or from a subpath. `theme-tokens.css` is linked
  relatively, and the back link is an absolute URL to `sullinslabs.com`.
- `data/dist/places.json` is the build output this pipeline produces, and is
  the file that actually needs to flow to the deployed copy after each run.

Do not blind-copy `site/` over `public/whereto/` in either direction without
diffing first.

## 5. Turn on the schedule

`.github/workflows/etl.yml` runs on the first of each month and can be
triggered by hand. It restores the archive from cache, verifies checksums,
builds, runs the tests, pushes snapshots to a Release, and commits
`data/dist/places.json`.

Note that committing that file does **not** currently redeploy anything. The
sullinslabs site is deployed manually with `netlify deploy --prod`, so a new
`places.json` has to be copied into that repo and published there. Wiring
this up automatically is an open task.

---

## What this costs

Nothing, and structurally so.

| | Free tier | This project |
|---|---|---|
| GitHub Actions | unlimited, public repos | 7 min/month, 29 in an annual month |
| GitHub Releases | 2 GB per asset | 0.05 GB/month, split by source |
| Repository | 1 GB soft limit | ~3 MB — snapshots are never committed |
| Cloudflare Pages | 500 builds/month, uncapped bandwidth | ~2 builds/month |
| Every data API | free with a key | 126 of 450 daily calls at the tightest point |

Two things would break it: making the repo private, and monetising the site —
at which point Open-Meteo's and MIT's non-commercial tiers stop applying. Both
sources sit behind swappable adapters for exactly that reason.
