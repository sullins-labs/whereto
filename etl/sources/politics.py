"""Political readings — descriptive, never evaluative.

Two distinct measures, kept apart on purpose because they answer different
questions and often disagree:

  state_lean  what the legislature has enacted — the laws that follow you into
              a rural county
  local_lean  how the county has actually voted — who your neighbours are

The interface scores both as distance from what the user asked for, so nothing
here is ranked good or bad. That neutrality has to hold in the data layer too:
the scale is a position, not a score, and it is symmetric by construction.

MIT's county returns are CC BY-NC. Derived values only; the file is never
republished.
"""
from __future__ import annotations
import csv, io
from ..snapshot import fetch


def lean_from_returns(rows: list[dict], years: tuple[int, ...] = (2020, 2024)) -> dict[str, dict]:
    """Two-party share, averaged across recent presidential cycles.

    One cycle is noisy and over-reads a single candidate; averaging two is
    steadier without smoothing away genuine movement. 0 is the most
    Republican-voting county in the country, 100 the most Democratic-voting;
    the midpoint is an even split, not a value judgement.
    """
    tally: dict[str, dict[int, dict[str, float]]] = {}
    for r in rows:
        try:
            year = int(r["year"])
            fips = str(r["county_fips"]).zfill(5)
            party = (r.get("party") or "").upper()
            votes = float(r.get("candidatevotes") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if year not in years or party not in ("DEMOCRAT", "REPUBLICAN"):
            continue
        tally.setdefault(fips, {}).setdefault(year, {"D": 0.0, "R": 0.0})
        tally[fips][year]["D" if party == "DEMOCRAT" else "R"] += votes

    out = {}
    for fips, by_year in tally.items():
        shares = []
        for _, v in by_year.items():
            total = v["D"] + v["R"]
            if total > 0:
                shares.append(v["D"] / total * 100)
        if not shares:
            continue
        lean = sum(shares) / len(shares)
        out[fips] = {
            "local_lean": round(lean, 1),
            "local_lean_cycles": len(shares),
            "local_lean_note": "two-party presidential share; a position, not a rating",
        }
    return out


def extract() -> dict[str, dict]:
    path = fetch("mit_election", filename="countypres.csv")
    rows = list(csv.DictReader(io.StringIO(path.read_text(errors="replace"))))
    return lean_from_returns(rows)
