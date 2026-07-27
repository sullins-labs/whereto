"""
Archival fetch layer.

One rule: nothing in this pipeline parses a byte it has not first written to
disk. Every fetch lands in data/raw/<source>/<fetch-date>/ alongside a manifest
entry recording the URL, the SHA-256, the byte count and the vintage.

That costs a few megabytes and buys three things:

  1. Re-transforming never re-fetches. Rate limits stop being a design
     constraint on the transform code.
  2. Runs are reproducible. `build.py --from-snapshot 2026-07-01` rebuilds
     exactly what shipped that day, which is the only honest way to explain
     why a number changed.
  3. Sources that vanish upstream survive here. NOAA retired its billion-dollar
     disasters series after 2024; FEMA took the National Risk Index application
     offline; several thousand pages came off the Census site. A pipeline that
     re-fetches on every run silently loses all of that. One that archives
     keeps it.

The archive is append-only. Nothing in this module deletes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from .config import RAW, SOURCES, Source

USER_AGENT = "whereto-etl/0.1 (+https://sullinslabs.com; public data, cached)"
MANIFEST = RAW / "manifest.jsonl"


@dataclass
class Entry:
    source: str
    url: str
    path: str
    sha256: str
    bytes: int
    fetched_at: str
    vintage: str | None = None
    note: str = ""


class RateLimiter:
    """Counts calls per source per day against the cap declared in config.

    The counter is persisted, so a re-run on the same day does not get a fresh
    budget — which matters because BLS caps at 500 a day per key and there is
    no way to ask how many are left.
    """

    def __init__(self, path: Path):
        self.path = path
        self.day = date.today().isoformat()
        self.counts: dict[str, int] = {}
        if path.exists():
            saved = json.loads(path.read_text())
            if saved.get("day") == self.day:
                self.counts = saved.get("counts", {})

    def check(self, src: Source, n: int = 1) -> None:
        if src.daily_call_cap is None:
            return
        used = self.counts.get(src.key, 0)
        if used + n > src.daily_call_cap:
            raise RuntimeError(
                f"{src.key}: would use {used + n} calls today, cap is "
                f"{src.daily_call_cap}. Run again tomorrow or narrow the scope "
                f"— do not raise the cap to get past this."
            )

    def spend(self, src: Source, n: int = 1) -> None:
        if src.daily_call_cap is None:
            return
        self.counts[src.key] = self.counts.get(src.key, 0) + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"day": self.day, "counts": self.counts}))


LIMITER = RateLimiter(RAW / ".ratelimit.json")


def _today() -> str:
    return date.today().isoformat()


def _record(entry: Entry) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(asdict(entry)) + "\n")


def manifest() -> list[Entry]:
    if not MANIFEST.exists():
        return []
    return [Entry(**json.loads(l)) for l in MANIFEST.read_text().splitlines() if l.strip()]


def latest(source_key: str, on_or_before: str | None = None) -> Path | None:
    """Most recent archived copy of a source, optionally as of a given date.

    This is what every extractor calls. Extractors never touch the network
    directly; they ask the archive, and the archive fetches only if it must.
    """
    entries = [e for e in manifest() if e.source == source_key]
    if on_or_before:
        entries = [e for e in entries if e.fetched_at[:10] <= on_or_before]
    if not entries:
        return None
    newest = max(entries, key=lambda e: e.fetched_at)
    p = Path(newest.path)
    return p if p.exists() else None


def verify() -> list[str]:
    """Re-hash every archived file against the manifest. Silent corruption in
    an append-only archive is worse than a missing file, because it is
    invisible until a number looks wrong months later."""
    problems = []
    for e in manifest():
        p = Path(e.path)
        if not p.exists():
            problems.append(f"missing: {e.path}")
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != e.sha256:
            problems.append(f"checksum changed: {e.path}")
    return problems


def fetch(
    source_key: str,
    url: str | None = None,
    *,
    vintage: str | None = None,
    filename: str | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    force: bool = False,
    max_age_days: int = 25,
    timeout: int = 120,
) -> Path:
    """Fetch and archive, or return today's archived copy if one exists.

    Set force=True to re-fetch regardless. Existing snapshots are never
    overwritten — a second fetch on the same day writes a suffixed file, so
    the archive keeps both and the manifest explains the difference.
    """
    src = SOURCES[source_key]
    url = url or src.url

    if not force:
        existing = latest(source_key)
        if existing:
            age = (datetime.now(timezone.utc) - datetime.fromtimestamp(
                existing.stat().st_mtime, timezone.utc)).days
            if age <= max_age_days:
                return existing

    LIMITER.check(src)

    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    if src.needs_key:
        token = os.environ.get(src.needs_key)
        if not token:
            raise RuntimeError(
                f"{source_key} needs {src.needs_key} in the environment. "
                f"All of these keys are free; see README."
            )
        if source_key == "hud_fmr":
            hdrs["Authorization"] = f"Bearer {token}"
        else:
            params = {**(params or {}), "key": token}

    outdir = RAW / source_key / _today()
    outdir.mkdir(parents=True, exist_ok=True)
    name = filename or url.rstrip("/").split("/")[-1].split("?")[0] or "response"
    path = outdir / name
    n = 1
    while path.exists():
        path = outdir / f"{path.stem}.{n}{path.suffix}"
        n += 1

    last_error = None
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if r.status_code == 429:
                raise requests.HTTPError("rate limited")
            r.raise_for_status()
            path.write_bytes(r.content)
            break
        except Exception as exc:            # noqa: BLE001 - retried below
            last_error = exc
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"{source_key}: fetch failed after 4 attempts: {last_error}")

    LIMITER.spend(src)
    _record(Entry(
        source=source_key,
        url=r.url,
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        vintage=vintage,
    ))
    return path
