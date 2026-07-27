"""Offline tests for the two extractors that do real work rather than parsing.
No network required."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from etl.sources.noaa_normals import extract as climate
from etl.sources.fbi_cde import aggregate as crime

# ---- NOAA: inverse-distance weighting, and the refusal to extrapolate ----
counties = {
  "42003": {"lat": 40.47, "lon": -79.98},   # Allegheny PA — stations nearby
  "30051": {"lat": 47.10, "lon": -108.25},  # Petroleum MT — nothing within 60 mi
}
stations = [
  {"id": "PIT",  "lat": 40.49, "lon": -80.23, "jul_high_f": 83.1, "jan_low_f": 21.4, "precip_in": 38.9, "sun_pct": 46},
  {"id": "AGC",  "lat": 40.35, "lon": -79.93, "jul_high_f": 82.4, "jan_low_f": 20.1, "precip_in": 40.2, "sun_pct": 46},
  {"id": "BTP",  "lat": 40.78, "lon": -79.95, "jul_high_f": 81.9, "jan_low_f": 18.8, "precip_in": 41.5, "sun_pct": 45},
  {"id": "FAR",  "lat": 46.90, "lon": -96.80, "jul_high_f": 82.0, "jan_low_f":  1.2, "precip_in": 22.6, "sun_pct": 58},
]
out = climate(counties, stations)
print("NOAA climate aggregation:")
for f, r in out.items():
    print(f"  {f}: {r}")
assert "42003" in out, "Allegheny should resolve from nearby stations"
assert 81 < out["42003"]["summer_high_f"] < 84
assert "30051" not in out, "Petroleum MT has no station within 60 mi — must be a gap, not a guess"
print("  Petroleum MT: no value emitted (nearest station 400+ mi) — correct")

# ---- FBI: coverage-aware suppression and partial-year annualisation ----
pops = {"42003": 1_250_000, "21015": 140_000, "13121": 1_000_000}
agencies = [
  # Allegheny: near-full coverage
  {"ori": "PA0021", "county_fips": "42003", "population_covered": 300_000, "violent": 1400, "property": 9000, "months_reported": 12},
  {"ori": "PA0022", "county_fips": "42003", "population_covered": 900_000, "violent": 2100, "property": 16000, "months_reported": 12},
  # Boone KY: one agency filed nine months — partial evidence, annualised
  {"ori": "KY0011", "county_fips": "21015", "population_covered": 130_000, "violent": 300, "property": 2100, "months_reported": 9},
  # a county where almost nobody reported
  {"ori": "GA0031", "county_fips": "13121", "population_covered": 220_000, "violent": 1900, "property": 12000, "months_reported": 12},
]
res = crime(agencies, pops)
print("\nFBI crime aggregation:")
for f, r in res.items():
    print(f"  {f}: {r}")

assert "violent_per_100k" in res["42003"], "96% coverage should publish"
assert res["21015"]["crime_coverage"] > 0.65, "nine months of 130k of 140k people"
assert "violent_per_100k" not in res["13121"], "22% coverage must suppress"
assert "crime_suppressed" in res["13121"]
print("\n  22%-coverage county suppressed rather than published — correct")
print("\nall assertions passed")
