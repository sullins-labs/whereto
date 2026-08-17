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
    # Carried per fetch so the archive answers licence questions on its own,
    # without anyone having to line it up against whatever config.py says
    # today. role in particular is what makes a validation-only source
    # identifiable years later.
    role: str = "primary"
    licence: str = ""
    licence_verified: str | None = None
    redistributable: bool = True
    attribution_required: bool = False


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


def latest(source_key: str, on_or_before: str | None = None,
           name: str | None = None) -> Path | None:
    """Most recent archived copy of a source, optionally as of a given date.

    This is what every extractor calls. Extractors never touch the network
    directly; they ask the archive, and the archive fetches only if it must.

    `name` narrows to one archived filename. Sources that issue several calls
    need it: BLS fetches 63 batches and FBI one file per state, all under a
    single source key, so a source-wide lookup answers every one of them with
    whichever file happened to land first.
    """
    entries = [e for e in manifest() if e.source == source_key]
    if name:
        entries = [e for e in entries if Path(e.path).name == name]
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


def _redact(text: str, token: str | None) -> str:
    """Keep the key out of anything that gets printed or logged.

    requests puts the full URL, query string included, into HTTPError. A failing
    keyed source therefore prints the key straight into the build output, which
    is the one artefact most likely to be pasted into an issue or captured by
    CI. The failure still needs to name the URL, so redact rather than suppress.
    """
    return text.replace(token, "<redacted>") if token else text


def _wrong_shape(name: str, body: bytes) -> str | None:
    """Why this response is not the file we asked for, or None if it looks right.

    A 200 is not evidence of a good download. Three sources proved that on the
    first cold build: FEMA answered a zip request with an HTML landing page,
    HUD and MIT each answered with zero bytes. All three archived cleanly, with
    honest checksums over the wrong content, and surfaced much later as a
    BadZipFile or an empty parse. An archive whose whole promise is integrity
    should refuse the bytes rather than preserve them faithfully.
    """
    if not body:
        return "empty response"
    head = body[:512].lstrip()[:64].lower()
    looks_html = head.startswith(b"<!doctype html") or head.startswith(b"<html")
    if name.endswith((".zip", ".xlsx")):
        # Both are zip containers, so both must start with the local file header.
        if not body.startswith(b"PK"):
            return "HTML page, not an archive" if looks_html else "not a zip archive"
    elif name.endswith((".gz", ".tgz")):
        if not body.startswith(b"\x1f\x8b"):
            return "HTML page, not an archive" if looks_html else "not a gzip archive"
    elif name.endswith((".csv", ".json")) and looks_html:
        return "HTML page, not data"
    return None


def fetch(
    source_key: str,
    url: str | None = None,
    *,
    vintage: str | None = None,
    filename: str | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    json_body: dict | None = None,
    force: bool = False,
    max_age_days: int = 25,
    timeout: int = 120,
) -> Path:
    """Fetch and archive, or return today's archived copy if one exists.

    Set force=True to re-fetch regardless. Existing snapshots are never
    overwritten — a second fetch on the same day writes a suffixed file, so
    the archive keeps both and the manifest explains the difference.

    Pass json_body to POST it as JSON instead of issuing a GET. Only BLS needs
    this: its v2 API rejects GET outright with 405, and takes the key in the
    body rather than the query string.
    """
    src = SOURCES[source_key]
    url = url or src.url
    name = filename or url.rstrip("/").split("/")[-1].split("?")[0] or "response"

    if not force:
        # Matched on filename as well as source. Sources that issue several
        # calls write several files under one source key, and a source-wide
        # lookup hands all of them whichever file landed first.
        existing = latest(source_key, name=name)
        if existing:
            age = (datetime.now(timezone.utc) - datetime.fromtimestamp(
                existing.stat().st_mtime, timezone.utc)).days
            if age <= max_age_days:
                return existing

    LIMITER.check(src)

    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    token = None
    if src.needs_key:
        token = os.environ.get(src.needs_key)
        if not token:
            raise RuntimeError(
                f"{source_key} needs {src.needs_key} in the environment. "
                f"All of these keys are free; see README."
            )
        if src.key_style == "bearer":
            hdrs["Authorization"] = f"Bearer {token}"
        elif src.key_style == "body":
            json_body = {**(json_body or {}), src.key_param: token}
        else:
            params = {**(params or {}), src.key_param: token}

    outdir = RAW / source_key / _today()
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / name
    n = 1
    while path.exists():
        path = outdir / f"{path.stem}.{n}{path.suffix}"
        n += 1

    last_error = None
    for attempt in range(4):
        try:
            if json_body is not None:
                r = requests.post(url, json=json_body, headers=hdrs, timeout=timeout)
            else:
                r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if r.status_code == 429:
                raise requests.HTTPError("rate limited")
            r.raise_for_status()
            wrong = _wrong_shape(name, r.content)
            if wrong:
                # Checked before writing: archiving it would record a valid
                # checksum over the wrong bytes and read as a good snapshot.
                raise RuntimeError(f"{_redact(url, token)} returned {wrong}")
            path.write_bytes(r.content)
            break
        except Exception as exc:            # noqa: BLE001 - retried below
            last_error = exc
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(
            f"{source_key}: fetch failed after 4 attempts: "
            f"{_redact(str(last_error), token)}")

    LIMITER.spend(src)
    _record(Entry(
        source=source_key,
        # Redacted: requests resolves params into r.url, so a keyed source
        # would write its key into the manifest, which is the one file here
        # meant to be durable and inspectable.
        url=_redact(r.url, token),
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        vintage=vintage,
        role=src.role,
        licence=src.licence,
        licence_verified=src.licence_verified,
        redistributable=src.redistributable,
        attribution_required=src.attribution_required,
    ))
    return path
