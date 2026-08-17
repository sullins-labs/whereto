"""Exercise a source against its live endpoint and report whether it earned
its `verified` flag.

    python -m etl.verify politics

A source can be correctly configured and never once have been run. Those are
different states, and the difference matters most exactly when a source is
unreachable for reasons that have nothing to do with the configuration, which
is where the politics source sits: the URL was corrected from a dataset DOI to
a file id while Harvard Dataverse had API access disabled, so the fix is
reasoned rather than observed.

This does not edit config.py. Flipping `verified` is a deliberate edit made by
a person who has read the output below, because a flag a script can set is a
flag that records nothing.
"""
from __future__ import annotations
import sys

from .config import SOURCES


def politics() -> int:
    from .sources import politics as pol
    from .sources import geo

    print("Verifying the politics source against live endpoints.\n")
    src = SOURCES["mit_election"]
    print(f"  primary:    {src.name}")
    print(f"              {src.url}")
    print(f"  validation: {SOURCES['tonmcg_returns'].name}")
    print(f"  currently marked verified={src.verified}\n")

    try:
        anchors = {f for f, r in geo.extract().items() if r.get("ring") == 0}
        print(f"  anchor counties to satisfy: {len(anchors)}")
    except Exception as exc:                     # noqa: BLE001
        print(f"  could not build the spine for anchors ({exc}); "
              f"running the coverage gate without them")
        anchors = None

    try:
        out = pol.extract(anchors=anchors)
    except pol.GateFailure as exc:
        print(f"\nFAILED a validation gate:\n  {exc}\n")
        print("Leave verified=False. The data is not trustworthy yet.")
        return 1
    except Exception as exc:                     # noqa: BLE001
        print(f"\nCould not fetch:\n  {type(exc).__name__}: {exc}\n")
        print("Leave verified=False. Nothing was exercised, so nothing is proven.")
        return 1

    print(f"\n  scored counties: {len(out)}")
    sample = sorted(out)[:3]
    for f in sample:
        print(f"    {f}: lean {out[f]['local_lean']} "
              f"over {out[f]['local_lean_cycles']} cycles")

    print("\nAll gates passed against live endpoints.")
    if not src.verified:
        print("This source has earned its flag. In etl/config.py, on the")
        print("mit_election entry, change:")
        print("    verified=False,   ->   verified=True,")
        print("and delete the UNVERIFIED note above the url, which is now stale.")
    return 0


TARGETS = {"politics": politics}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1 or argv[0] not in TARGETS:
        print(f"usage: python -m etl.verify {{{'|'.join(TARGETS)}}}")
        return 2
    return TARGETS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
