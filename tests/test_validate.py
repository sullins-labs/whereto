import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from etl.validate import check_record, check_dataset, report, BLOCKING, WARNING
from etl.validate import check_baseline_regression, _load_baseline
from etl.config import DIST

good = dict(fips="42003", name="Allegheny", state="PA", ring=0, anchor_name="Pittsburgh",
            median_home_value=215000, median_gross_rent=1100, rpp=92.4,
            summer_high_f=83.0, winter_low_f=21.0, land_sq_mi=730,
            violent_per_100k=280, crime_coverage=0.94, drive_min=8)

print("clean record ->", check_record(good) or "no findings")

# the ACS null sentinel leaking through is the classic silent failure
bad = {**good, "median_home_value": -666666666}
f = check_record(bad)
print("\nACS null sentinel ->", f[0].level, "|", f[0].message)
assert f[0].level == BLOCKING

# partial crime reporting must suppress, not publish
partial = {**good, "crime_coverage": 0.42}
f = [x for x in check_record(partial) if x.field == "violent_per_100k"]
print("partial crime reporting ->", f[0].level, "|", f[0].message[:70])
assert f[0].level == WARNING

# a county that spans core and country
het = {**good, "land_sq_mi": 2603}
f = [x for x in check_record(het) if x.field == "ring"]
print("heterogeneous county ->", f[0].level, "|", f[0].message)

# dataset-level: a build that drops the country still renders fine
findings, stats = check_dataset([good] * 50)
print("\nundersized dataset ->")
print(report(findings, stats))
assert stats["blocking"] > 0

# ---------------------------------------------------------------------------
# Baseline regression guard. Uses the real, already-committed
# data/dist/places.json as its baseline -- no network fetch, no history
# lookup, exactly the file this guard runs against for real.
# ---------------------------------------------------------------------------
raw = json.loads((DIST / "places.json").read_text(encoding="utf-8"))
base_places, base_withheld = raw["places"], raw["withheld"]
baseline = _load_baseline()
assert not baseline.get("missing"), "the repo's committed baseline must be readable"

# (a) a county present in the baseline, missing from the new build, and not
# recorded as withheld -- silently vanished, no reason on file.
dropped_fips = base_places[0]["fips"]
records_missing_county = base_places[1:]
out = check_baseline_regression(records_missing_county, base_withheld, baseline)
hit = [f for f in out if f.level == BLOCKING and f.field == "fips" and f.place == dropped_fips]
print(f"\n(a) dropped county {dropped_fips} without a withheld reason ->",
      hit[0].message if hit else "NOT CAUGHT")
assert hit, "a silently dropped county must be BLOCKING"

# (b) the BLS-empty-series case: a bad key returns HTTP 200 with an empty
# series, so unemployment_rate/labour_force go null for every county. Neither
# field is in REQUIRED or the fill-rate loop in check_dataset, so this guard
# is the only thing that catches it.
records_bls_wiped = [
    {**r, "unemployment_rate": None, "labour_force": None} for r in base_places
]
out = check_baseline_regression(records_bls_wiped, base_withheld, baseline)
hit_fields = {f.field for f in out if f.level == BLOCKING}
print("(b) BLS empty-series wipes unemployment_rate/labour_force ->", sorted(hit_fields))
assert "unemployment_rate" in hit_fields, "null-rate regression on unemployment_rate must be caught"
assert "labour_force" in hit_fields, "null-rate regression on labour_force must be caught"

# (c) baseline checked against itself: identical FIPS set, identical null
# rates -- zero regression, zero drift, nothing should fire.
out = check_baseline_regression(base_places, base_withheld, baseline)
print("(c) baseline vs itself ->", out or "no findings")
assert not out, "comparing the baseline to itself must not raise any finding"

# (d) a county published in the baseline that is withheld in this build --
# not dropped (it's still accounted for), but not free of consequence
# either. One such county WARNs; more than 25 also BLOCKs with a single
# dataset-level summary finding, since the point of a summary is that a
# human doesn't have to count 26+ per-county lines to see why it blocked.
newly_withheld_fips = base_places[10]["fips"]
withheld_plus_one = base_withheld + [{"fips": newly_withheld_fips}]
out = check_baseline_regression(base_places, withheld_plus_one, baseline)
hit = [f for f in out if f.level == WARNING and f.field == "withheld" and f.place == newly_withheld_fips]
print(f"\n(d) county {newly_withheld_fips} newly withheld (1 of them) ->",
      hit[0].message if hit else "NOT CAUGHT")
assert hit, "a county newly withheld vs. the baseline must WARN"
assert not [f for f in out if f.level == BLOCKING and f.field == "withheld"], \
    "one newly-withheld county must not trip the >25 BLOCKING summary"

many_newly_withheld = [r["fips"] for r in base_places[:26]]
withheld_plus_many = base_withheld + [{"fips": fp} for fp in many_newly_withheld]
out = check_baseline_regression(base_places, withheld_plus_many, baseline)
warns = [f for f in out if f.level == WARNING and f.field == "withheld"]
summary = [f for f in out if f.level == BLOCKING and f.field == "withheld" and f.place == "dataset"]
print(f"(d) {len(many_newly_withheld)} counties newly withheld ->",
      summary[0].message if summary else "NOT CAUGHT")
assert len(warns) == 26, "each newly-withheld county still gets its own WARNING past the threshold"
assert summary, "more than 25 newly-withheld counties must also BLOCK with a dataset-level summary"

# ---------------------------------------------------------------------------
# Wiring: check_dataset(records, withheld) must actually invoke
# check_baseline_regression() when withheld is not None. Every test above
# calls check_baseline_regression() directly, which would still pass even if
# the two-argument call site in build.py silently reverted to one argument
# and disabled this whole guard under a green suite.
# ---------------------------------------------------------------------------
from unittest.mock import patch

with patch("etl.validate.check_baseline_regression", return_value=[]) as mocked:
    check_dataset([good], withheld=[])
    assert mocked.called, "check_dataset must call check_baseline_regression when withheld is not None"
print("\n(e) check_dataset(records, withheld=[...]) calls check_baseline_regression -> called",
      mocked.call_count, "time(s)")

with patch("etl.validate.check_baseline_regression", return_value=[]) as mocked:
    check_dataset([good])
    assert not mocked.called, "check_dataset must NOT call check_baseline_regression when withheld is omitted"
print("(e) check_dataset(records) without withheld does not call check_baseline_regression -> not called")

print("\nall assertions passed")
