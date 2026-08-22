#!/usr/bin/env python3
"""
Build the release-snapshot tarball of redistributable raw source data.

Companion to the "Archive snapshots to release" step in
.github/workflows/etl.yml. This used to be an embedded `python -c "..."`
heredoc inside that step's `run: |` block scalar. The heredoc's inline lines
were flush at column 1, which de-indented below the block scalar's
established indentation and terminated it early -- corrupting the rest of
the YAML document so badly that GitHub Actions could not parse the workflow
file at all (every run from 2026-08-20 until this fix failed instantly with
"No jobs were run"). Pulling the logic out into a standalone script removes
the trap rather than just re-indenting around it.

The set of directories archived is DERIVED AT RUNTIME from
etl.config.SOURCES[*].redistributable -- never a hardcoded list of directory
or source names. A hardcoded list is exactly how the prior licence-exposure
incident happened: snapshot-2026-08 shipped Zillow and MIT election data
because a denylist of excluded names had gone stale the moment a new
non-redistributable source was registered. Only data-licensing-reviewer sets
the `redistributable` flag; this script only ever reads it.

Usage, from the repo root:
    python scripts/archive_snapshots.py [raw_dir] [output_tarball]

    raw_dir         defaults to data/raw
    output_tarball  defaults to snapshots.tar.gz

Exit codes:
    0   archive built and re-verified successfully
    1   the derived redistributable set is empty, no redistributable
        directories were found under raw_dir, or re-opening the finished
        tarball found an entry that does not map to a declared
        redistributable source
"""
from __future__ import annotations

import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from etl.config import SOURCES  # noqa: E402  (import after sys.path fixup)


def redistributable_keys() -> set[str]:
    """Every source key marked redistributable=True in the registry.

    This is the ONLY place that set may come from. Do not special-case a
    source key here -- if a source needs including or excluding, that is a
    change to `redistributable` on the Source in etl/config.py, made by
    data-licensing-reviewer, not a change to this function.
    """
    return {key for key, s in sorted(SOURCES.items()) if s.redistributable}


def partition_raw_dirs(
    raw_dir: Path, redist: set[str]
) -> tuple[list[Path], list[str]]:
    """Split the immediate subdirectories of raw_dir into (to archive, excluded).

    A directory whose name is not a key in SOURCES at all (e.g. a stale or
    unregistered folder) is treated as excluded, the same as a known
    non-redistributable source -- absence of an explicit allow is not a
    reason to include something in a published artifact.
    """
    included: list[Path] = []
    excluded: list[str] = []
    for d in sorted(raw_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name in redist:
            included.append(d)
        else:
            excluded.append(d.name)
    return included, excluded


def build_archive(dirs: list[Path], output: Path) -> None:
    with tarfile.open(output, "w:gz") as tar:
        for d in dirs:
            tar.add(d, arcname=str(d))


def verify_archive(output: Path, redist: set[str]) -> set[str]:
    """Re-open the finished tarball and return any source names present in
    it that are not in the declared redistributable set.

    This re-derivation is deliberate belt-and-braces: a bug upstream of this
    check (in partition_raw_dirs, or a directory that changed on disk
    between being listed and being added to the tar) should stop the build,
    not ship a smaller version of the same licensing mistake.
    """
    bad: set[str] = set()
    with tarfile.open(output, "r:gz") as tar:
        for member in tar.getmembers():
            # Entries look like "data/raw/<source_key>/<file>".
            parts = member.name.split("/")
            if len(parts) < 3:
                continue
            source_name = parts[2]
            if source_name and source_name not in redist:
                bad.add(source_name)
    return bad


def main(argv: list[str]) -> int:
    raw_dir = Path(argv[1]) if len(argv) > 1 else Path("data/raw")
    output = Path(argv[2]) if len(argv) > 2 else Path("snapshots.tar.gz")

    redist = redistributable_keys()
    if not redist:
        print(
            "::error::No redistributable sources declared in "
            "etl.config.SOURCES; refusing to publish an empty snapshot",
            file=sys.stderr,
        )
        return 1

    if not raw_dir.is_dir():
        print(f"::error::{raw_dir} does not exist; nothing to archive", file=sys.stderr)
        return 1

    included, excluded = partition_raw_dirs(raw_dir, redist)

    if excluded:
        # Non-fatal: excluding a non-redistributable source is the pipeline
        # working correctly, not an error.
        print(f"Excluded non-redistributable source(s) from snapshot: {' '.join(excluded)}")

    if not included:
        print(
            f"::error::No redistributable source directories found under "
            f"{raw_dir}; refusing to publish an empty snapshot",
            file=sys.stderr,
        )
        return 1

    build_archive(included, output)

    bad = verify_archive(output, redist)
    if bad:
        print(
            "::error::Non-redistributable source(s) present in snapshot "
            f"archive: {' '.join(sorted(bad))}",
            file=sys.stderr,
        )
        return 1

    names = ", ".join(d.name for d in included)
    print(f"Wrote {output} with {len(included)} redistributable source director"
          f"{'y' if len(included) == 1 else 'ies'}: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
