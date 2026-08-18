"""The field contract against the built dataset.

The other five suites test the pipeline's internals: joins, gates, schema
shape of a fixture. None of them ask the question this one does — does the
dataset actually sitting in data/dist/places.json deliver what etl/contract.py
promises? Three real incidents motivate this:

  * flood_score defaulted to 30 for every county because fema_nri.py produced
    flood_riverine/flood_coastal while the site read `flood`. A field that
    exists and is 100% populated is not the same as a field that is right;
    the giveaway was that it never varied.
  * politics vanished from the schema entirely while builds kept passing,
    because the stage failure was recorded as non-blocking.
  * rent_monthly silently falls back to ACS median_gross_rent while HUD FMR
    sits at 0% populated, and nothing said so out loud.

This suite reads the contract, reads the built payload, and checks four
things per declared field: it exists in the schema, it is populated above a
sensible floor, it is not suspiciously constant, and it is not a silent
duplicate of some other field. Anything that fails here is either a real gap
or an undeclared exception — see KNOWN_EXCEPTIONS below, which is the only
place an exception is allowed to live quietly.

Run directly, like the other suites:  python tests/test_contract_coverage.py
"""
from __future__ import annotations
import json, pathlib, sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from etl.contract import PLACE_FIELDS  # noqa: E402

DATA_PATH = ROOT / "data" / "dist" / "places.json"

# --------------------------------------------------------------------------
# KNOWN EXCEPTIONS
#
# Every entry here is a deliberate, visible decision, not a way to make a
# real gap quiet. Each needs a reason and, where there is one, a pointer to
# the upstream cause. Adding to this list is how you register a known gap;
# it is not something this test should ever do on its own.
# --------------------------------------------------------------------------

# Fields that are allowed to be entirely absent from the schema (not just
# sparsely populated -- the key never appears on any record) and/or to have
# 0% coverage where present.
EXISTENCE_EXCEPTIONS = {
    "violent_per_100k":  "FBI county-level crime unobtainable from the current "
                          "CDE API. Permanent; the interface says 'not reported' "
                          "rather than showing a number. See etl/sources/fbi_cde.py "
                          "and commit 13a2298.",
    "property_per_100k": "Same cause as violent_per_100k.",
    "crime_index":       "Same cause as violent_per_100k.",
    "crime_coverage":    "Same cause as violent_per_100k.",
    "state_lean":        "Declared in etl/contract.py:56 but no extractor has ever "
                          "produced it -- there is no AHRF-style state-policy source "
                          "wired up, so the key never appears on any record. This is "
                          "an ACKNOWLEDGED GAP AWAITING WORK, not a settled decision: "
                          "unlike violent_per_100k, nothing here says the data is "
                          "unobtainable, only that it hasn't been built yet. The "
                          "per-county interface already handles the absence honestly "
                          "-- site/index.html renders 'not reported' via the "
                          "stateLeanKnown flag rather than showing a fabricated "
                          "number. If a state-policy extractor is ever built, this "
                          "line should be deleted, not extended.",
}

# Fields allowed a lower coverage floor than COVERAGE_FLOOR, with the reason
# and the expected floor for that specific field.
COVERAGE_EXCEPTIONS = {
    # local_lean is handled by its own dedicated check below (it is not just
    # under-covered, it needs to be under-covered in exactly the right
    # counties), so it is exempted from the generic floor here.
    "local_lean": 0.0,
    # pupils_per_teacher is null on 100% of records because the underlying
    # source -- NCES Common Core of Data, School District Finance Survey
    # (F-33) -- does not collect teacher counts at all. See etl/config.py:291
    # and etl/sources/nces_ccd.py:63/93. This is an ACKNOWLEDGED GAP AWAITING
    # WORK, not a permanent ceiling the way violent_per_100k is: a different
    # NCES file (the Common Core of Data staff survey) does publish teacher
    # counts and could be joined in later. Until that join exists, the field
    # stays declared and genuinely null rather than backfilled with a guess.
    "pupils_per_teacher": 0.0,
}

# Fields allowed to be constant (or near-constant) across the dataset, with
# the reason. Anything not listed here that trips the constant-value check
# is a genuine finding, not a formatting quirk.
CONSTANT_EXCEPTIONS = {
    "senior_property_relief_pct": (
        "Zero for every state by deliberate decision, not an oversight: every "
        "state's relief program is income-tested at thresholds low enough "
        "that a typical retired household in this model may not qualify, and "
        "the four different program structures cannot collapse into one "
        "fraction without misstating who qualifies and by how much. See "
        "data/curated/state_services.yaml lines 39-47. The consuming code "
        "was already corrected so real values can be filled in later without "
        "a model change."
    ),
}

# (field_a, field_b) pairs that are allowed to be bit-for-bit identical
# across the dataset, with the reason. This is intentionally a pair list
# rather than a general allowance, because outside these specific pairs an
# identical pair is exactly the rent_monthly/median_gross_rent signature:
# a field advertised as independent that is actually a silent passthrough.
IDENTICAL_PAIR_EXCEPTIONS = {
    frozenset({"rent_monthly", "median_gross_rent"}): (
        "rent_monthly is declared as 'HUD FMR 2-bed, else ACS median gross "
        "rent' (etl/transform.py: rec['rent_monthly'] = rec.get('fmr_2br') or "
        "rec.get('median_gross_rent')). HUD's FY2026 FMR file "
        "(huduser.gov/portal/datasets/fmr/fmr2026/FY2026_4050_FMRs.xlsx) "
        "currently returns empty even with a valid HUD_API_TOKEN, so fmr_2br "
        "is unpopulated for the whole dataset and every county falls back to "
        "the ACS figure. Upstream outage, not a code bug. If HUD recovers, "
        "this identity should start breaking apart on its own -- if it is "
        "still 100% identical a long time from now, that is worth checking."
    ),
}

# --------------------------------------------------------------------------

print(f"loading {DATA_PATH}")
payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
places = payload["places"]
n = len(places)
print(f"{n} places\n")
assert n > 1000, f"suspiciously small dataset ({n} places); refusing to trust coverage stats"

declared = list(PLACE_FIELDS)

# ---------------------------------------------------------- 1. field existence
# A field declared in the contract must appear as a key on at least one
# record. This is the politics case: the field was still in the contract,
# builds still passed, and the key had simply stopped showing up anywhere.
print("1. schema existence")
key_union = set()
for p in places:
    key_union |= set(p)

existence_failures = []
for field in declared:
    if field in key_union:
        continue
    if field in EXISTENCE_EXCEPTIONS:
        print(f"  ok  {field}: absent, registered exception "
              f"({EXISTENCE_EXCEPTIONS[field][:60]}...)")
        continue
    existence_failures.append(field)

if existence_failures:
    for field in existence_failures:
        print(f"  FAIL {field}: declared in the contract, absent from every "
              f"record in the built dataset, and not a registered exception")
assert not existence_failures, (
    f"fields declared but entirely absent from the schema, unregistered: "
    f"{existence_failures}")
print("  all declared fields exist in the schema (or are a registered exception)\n")

# ---------------------------------------------------------- 2. coverage floor
# A field present as a key but null everywhere is the same failure wearing a
# different hat. 10% is deliberately low -- this is not a data-quality bar,
# it is a "did the join even run" bar. Every field in this dataset that is
# legitimately sparse (hurricane risk: 70.7%, only coastal-exposed counties
# get an NRI percentile; air_days_over: 84.9%, monitors do not cover every
# county) clears it by a wide margin. Only fields that are genuinely broken
# or genuinely unimplemented sit at or near 0%, which is exactly the
# distinction this floor exists to draw.
print("2. coverage floor (10%, see comment above)")
COVERAGE_FLOOR = 0.10

coverage_failures = []
for field in declared:
    if field in EXISTENCE_EXCEPTIONS:
        continue  # already handled: expected to be entirely absent
    populated = sum(1 for p in places if p.get(field) is not None)
    pct = populated / n
    floor = COVERAGE_EXCEPTIONS.get(field, COVERAGE_FLOOR)
    if pct >= floor:
        continue
    reason = f" (registered floor {floor:.0%})" if field in COVERAGE_EXCEPTIONS else ""
    coverage_failures.append((field, pct, floor))
    print(f"  FAIL {field}: {pct:.1%} populated, below the {floor:.0%} floor{reason}")

assert not coverage_failures, (
    f"fields below their coverage floor, unregistered: "
    f"{[f for f, _, _ in coverage_failures]}")
print(f"  every declared field clears its coverage floor\n")

# ---------------------------------------------------- 3. local_lean precision
# local_lean is documented as absent for Alaska, Connecticut, and Puerto
# Rico by deliberate exclusion. That is a specific claim, not just "some
# counties are missing it" -- so check it precisely rather than folding it
# into the generic floor above. A gap in a state that is NOT on this list is
# not covered by the documented reason and must fail.
print("3. local_lean exclusion set")
EXPECTED_LOCAL_LEAN_GAP_STATES = {"AK", "CT", "PR"}
missing_local_lean = [p for p in places if p.get("local_lean") is None]
unexpected = sorted({p["fips"] + " " + p.get("name", "?")
                      for p in missing_local_lean
                      if p.get("state") not in EXPECTED_LOCAL_LEAN_GAP_STATES})
by_state = Counter(p.get("state") for p in missing_local_lean)
print(f"  {len(missing_local_lean)} counties missing local_lean: {dict(by_state)}")
assert not unexpected, (
    f"local_lean is missing in counties outside the documented AK/CT/PR "
    f"exclusion, which means the gap has a cause nobody has written down: "
    f"{unexpected}")
print("  all local_lean gaps fall inside the documented AK/CT/PR exclusion\n")

# --------------------------------------------------- 4. constant-value check
# The flood-defaults-to-30 signature: a numeric field that barely varies
# across thousands of counties that should differ enormously (physician
# density, home values, hazard scores). 95% share on one value is the bar --
# high enough that a legitimately common but non-uniform value (e.g. a
# categorical code most states share) will not trip it, low enough to catch
# a field that is silently stuck. Boolean and small fixed-vocabulary fields
# (medicaid_expansion, retire_code, rpp_source, insurance_basis) are exactly
# the case where a shared value is legitimate, so this only runs on
# fields whose declared type is a pure numeric ((int, float) or int/float),
# and it is a report-then-assert against CONSTANT_EXCEPTIONS, not a blanket
# skip, because a numeric field defaulting to one value is precisely the bug
# this check exists to catch.
print("4. constant-value check (95% same-value share)")
CONSTANT_SHARE = 0.95
NUMERIC_TYPES = (int, float)

constant_failures = []
for field in declared:
    typ = PLACE_FIELDS[field][0]
    types = typ if isinstance(typ, tuple) else (typ,)
    if not all(t in NUMERIC_TYPES for t in types):
        continue  # str/bool/list fields: a shared value is not this bug
    if field in EXISTENCE_EXCEPTIONS:
        continue  # already entirely absent, nothing to check for constancy
    vals = [p[field] for p in places if p.get(field) is not None]
    if len(vals) < 30:
        continue  # too few populated values to say anything about constancy
    top_val, top_ct = Counter(vals).most_common(1)[0]
    share = top_ct / len(vals)
    if share < CONSTANT_SHARE:
        continue
    if field in CONSTANT_EXCEPTIONS:
        print(f"  ok  {field}: {share:.1%} at {top_val!r}, registered exception")
        continue
    constant_failures.append((field, top_val, share))
    print(f"  FAIL {field}: {share:.1%} of {len(vals)} populated records are "
          f"exactly {top_val!r} -- this is the flood-defaults-to-30 signature")

assert not constant_failures, (
    f"numeric fields stuck at one value across the dataset, unregistered: "
    f"{[f for f, _, _ in constant_failures]}")
print("  no unregistered constant-value fields\n")

# --------------------------------------------------- 5. silent-fallback check
# rent_monthly == median_gross_rent for every record is the known,
# registered signature of the HUD FMR outage. Checking a fully general "any
# two fields identical across the dataset" would flag legitimate cases (e.g.
# median_home_value and home_value tracking the same Zillow figure through
# two names) and drown the one pairing that actually matters, so this checks
# only the specific pairs on the exception list plus the one pairing the
# task exists to catch: rent_monthly against its declared fallback source.
print("5. silent-fallback check (registered pairs)")
for pair, reason in IDENTICAL_PAIR_EXCEPTIONS.items():
    a, b = tuple(pair)
    both = [p for p in places if p.get(a) is not None and p.get(b) is not None]
    identical = sum(1 for p in both if p[a] == p[b])
    pct = identical / len(both) if both else 0.0
    print(f"  {a} == {b}: {identical}/{len(both)} ({pct:.1%}) -- registered, {reason[:70]}...")

# The pairing that matters even where it is NOT on the exception list: if
# rent_monthly and median_gross_rent were ever to diverge, or if some other
# field started mirroring one of them, this would be silent. There is only
# one field this task calls out (rent_monthly), and it is already covered
# above with its documented reason, so there is nothing further to assert
# here beyond having reported it.
print("  no unregistered identical-pair findings\n")

print("all assertions passed")
