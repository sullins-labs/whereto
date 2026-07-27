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

## 4. Cloudflare Pages

Dashboard → Workers & Pages → Create → connect the GitHub repo.

- Build command: *(none — the site is already static)*
- Output directory: `site`
- Custom domain: `sullinslabs.com`

Nameservers move to Cloudflare; DNS, TLS and CDN are free. **Do not add
Workers, D1, KV or Functions.** Not because they cost much, but because they
are the only components in the stack that meter per request. A purely static
site has no code path that can generate an invoice, and that is a stronger
guarantee than a low bill.

## 5. Turn on the schedule

`.github/workflows/etl.yml` runs on the first of each month and can be
triggered by hand. It restores the archive from cache, verifies checksums,
builds, runs the tests, pushes snapshots to a Release, and commits
`data/dist/places.json`. Cloudflare redeploys on that commit.

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
