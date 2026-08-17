"""Politics extractor: aggregation shapes, schema, and the state-specific
traps that produce plausible wrong numbers rather than errors.

Run directly, like the other suites here:  python tests/test_politics.py
"""
from __future__ import annotations
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from etl.sources.politics import (            # noqa: E402
    aggregate, shares, lean_from_returns, cross_check, check_coverage,
    check_sanity, _check_schema, _fips, GateFailure,
    MEDSL_COLUMNS, EXCLUDED_STATES, CYCLES,
)


def row(fips, year, party, votes, mode="TOTAL", candidate=None):
    return {"year": year, "state": "X", "county_fips": fips,
            "candidate": candidate or ("BIDEN" if party == "DEMOCRAT" else "TRUMP"),
            "party": party, "candidatevotes": votes, "totalvotes": 0, "mode": mode}


def check(label, cond, detail=""):
    if not cond:
        raise AssertionError(f"{label}: {detail or 'failed'}")
    print(f"  ok  {label}")


# ---------------------------------------------------------------- aggregation
print("TOTAL vs vote-mode rows")

# A state that publishes only modes: they must be summed.
modes_only = [
    row("01001", 2020, "DEMOCRAT", 60, mode="ELECTION DAY"),
    row("01001", 2020, "DEMOCRAT", 40, mode="ABSENTEE"),
    row("01001", 2020, "REPUBLICAN", 300, mode="ELECTION DAY"),
    row("01001", 2020, "REPUBLICAN", 100, mode="ABSENTEE"),
]
agg = aggregate(modes_only, (2020,))
check("modes are summed when no TOTAL exists",
      agg["01001"][2020] == {"D": 100.0, "R": 400.0}, agg["01001"][2020])

# A state that publishes TOTAL *alongside* the modes. Summing everything here
# double-counts, which is the failure this rule exists for.
total_and_modes = modes_only + [
    row("01001", 2020, "DEMOCRAT", 100, mode="TOTAL"),
    row("01001", 2020, "REPUBLICAN", 400, mode="TOTAL"),
]
agg = aggregate(total_and_modes, (2020,))
check("TOTAL wins outright where it coexists with modes",
      agg["01001"][2020] == {"D": 100.0, "R": 400.0}, agg["01001"][2020])

# Two candidates of the same party (fusion tickets, write-ins) still add up.
multi = [
    row("01003", 2020, "DEMOCRAT", 70, candidate="A"),
    row("01003", 2020, "DEMOCRAT", 30, candidate="B"),
    row("01003", 2020, "REPUBLICAN", 100),
]
agg = aggregate(multi, (2020,))
check("candidates within a party are summed",
      agg["01003"][2020]["D"] == 100.0, agg["01003"][2020])


# ------------------------------------------------------------------ FIPS form
print("\nFIPS normalisation")
check("integer FIPS zero-pads", _fips(1001) == "01001", _fips(1001))
check("float-ish FIPS zero-pads", _fips("1001.0") == "01001", _fips("1001.0"))
check("string FIPS is preserved", _fips("01001") == "01001", _fips("01001"))
agg = aggregate([row(1001, 2020, "DEMOCRAT", 1), row("01001", 2020, "REPUBLICAN", 1)], (2020,))
check("int and string FIPS land on the same county", list(agg) == ["01001"], list(agg))


# --------------------------------------------------------------------- Alaska
print("\nAlaska is excluded rather than joined")
check("Alaska is declared excluded", "02" in EXCLUDED_STATES)
# 02020 is both State House District 20 and Anchorage Municipality. Joining it
# would file a legislative district's votes under an anchor metro.
ak = aggregate([row("02020", 2020, "DEMOCRAT", 500),
                row("02020", 2020, "REPUBLICAN", 500)], (2020,))
check("Alaska rows never reach the tally", ak == {}, ak)


# --------------------------------------------------- Connecticut / cycle pairs
print("\nA county is only scored when every averaged cycle is present")
# Connecticut's shape: legacy county FIPS in the older cycle, planning-region
# FIPS in the newer one, so the two never meet.
ct = (
    [row("09001", 2020, "DEMOCRAT", 60), row("09001", 2020, "REPUBLICAN", 40)] +
    [row("09110", 2024, "DEMOCRAT", 55), row("09110", 2024, "REPUBLICAN", 45)]
)
out = lean_from_returns(ct, CYCLES)
check("a county present in only one cycle is not scored", out == {}, out)

both = (
    [row("06037", 2020, "DEMOCRAT", 70), row("06037", 2020, "REPUBLICAN", 30)] +
    [row("06037", 2024, "DEMOCRAT", 60), row("06037", 2024, "REPUBLICAN", 40)]
)
out = lean_from_returns(both, CYCLES)
check("a county present in both cycles is scored", "06037" in out, out)
check("the lean is the mean of the cycle shares",
      out["06037"]["local_lean"] == 65.0, out["06037"])
check("cycle count is reported", out["06037"]["local_lean_cycles"] == 2)


# ---------------------------------------------------------------- schema gate
print("\nSchema gate")
try:
    _check_schema(sorted(MEDSL_COLUMNS), MEDSL_COLUMNS, "MEDSL", "fixture")
    print("  ok  the expected shape passes")
except GateFailure as exc:
    raise AssertionError(f"expected shape rejected: {exc}")

# A 200 carrying the wrong columns must fail loudly, not parse to nothing.
try:
    _check_schema(["year", "fips", "dem_votes"], MEDSL_COLUMNS, "MEDSL", "fixture")
    raise AssertionError("wrong schema was accepted")
except GateFailure as exc:
    check("a changed shape is rejected", "missing expected columns" in str(exc))


# -------------------------------------------------------------- coverage gate
print("\nCoverage gate")
wide = {f"{i:05d}": {2020: 0.5, 2024: 0.5} for i in range(1, 3101)}
check_coverage(wide, anchors=None)
print("  ok  a full national file passes")

try:
    check_coverage({f"{i:05d}": {2020: 0.5, 2024: 0.5} for i in range(1, 50)}, None)
    raise AssertionError("a nearly empty file was accepted")
except GateFailure as exc:
    check("too few counties is rejected", "coverage gate" in str(exc))

try:
    check_coverage(wide, anchors={"48201"})
    raise AssertionError("a missing anchor was accepted")
except GateFailure as exc:
    check("a missing anchor county is rejected", "anchor" in str(exc))

check_coverage(wide, anchors={"02020"})
print("  ok  an Alaskan anchor is not demanded, because Alaska is excluded")


# ---------------------------------------------------------------- sanity gate
print("\nSanity gate")
check_sanity({"01001": {2020: 0.0, 2024: 1.0}})
print("  ok  shares at the bounds pass")
try:
    check_sanity({"01001": {2020: 1.4}})
    raise AssertionError("an out-of-range share was accepted")
except GateFailure as exc:
    check("a share outside 0-1 is rejected", "sanity gate" in str(exc))


# ----------------------------------------------------------- cross-source gate
print("\nCross-source gate")
primary = {f"{i:05d}": {2020: 0.500} for i in range(1, 201)}
agreeing = {f"{i:05d}": {2020: 0.505} for i in range(1, 201)}
summary = cross_check(primary, agreeing)
check("close agreement passes", summary["over_fail"] == 0, summary)
check("the summary is logged either way", summary["compared"] == 200, summary)

# One bad county in 200 is 0.5%, under the 1% tolerance: warn, do not block.
one_bad = dict(agreeing, **{"00001": {2020: 0.90}})
summary = cross_check(primary, one_bad)
check("a single large divergence warns rather than blocks",
      summary["over_fail"] == 1, summary)

try:
    cross_check(primary, {f"{i:05d}": {2020: 0.90} for i in range(1, 201)})
    raise AssertionError("wholesale divergence was accepted")
except GateFailure as exc:
    check("wholesale divergence blocks", "cross-source gate" in str(exc))

# Corroboration is part of verification, so no overlap is a failure, not a pass.
try:
    cross_check(primary, {})
    raise AssertionError("an unusable validation source was accepted")
except GateFailure as exc:
    check("no overlap blocks rather than silently passing",
          "could not run" in str(exc))


# ------------------------------------------- validation source cannot publish
print("\nValidation-only sources are kept out of the published payload")
from etl.build import _assert_no_validation_sources   # noqa: E402
from etl.config import SOURCES                        # noqa: E402

validation = [s for s in SOURCES.values() if s.role == "validation"]
check("at least one source is marked validation-only", bool(validation),
      "nothing would be under test otherwise")

clean = {"sources": [{"name": "Census Gazetteer: counties"}],
         "places": [{"fips": "01001", "local_lean": 42.0}]}
_assert_no_validation_sources(clean)
print("  ok  a clean payload passes")

# The two ways it goes wrong fail differently, so both are checked.
try:
    _assert_no_validation_sources(
        {"sources": [{"name": validation[0].name}], "places": []})
    raise AssertionError("a validation source in the licence table was accepted")
except RuntimeError as exc:
    check("listing it as a source of the numbers is refused",
          "licence table" in str(exc))

try:
    _assert_no_validation_sources(
        {"sources": [], "places": [{"fips": "01001", "tonmcg_returns_lean": 0.5}]})
    raise AssertionError("a validation-derived field was accepted")
except RuntimeError as exc:
    check("a field derived from it is refused", "carries fields" in str(exc))


print("\nall assertions passed")
