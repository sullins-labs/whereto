"""End-to-end pipeline test on fixtures. No network.

Proves the assemble -> transform -> validate path works and that the gates
behave, which is everything except the fetching itself.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from etl.build import assemble
from etl.transform import run as transform
from etl.validate import check_dataset, report

# a spine of three counties across three rings, plus partial source coverage —
# deliberately imperfect, because a fixture where every join succeeds proves
# nothing about the joins that don't
spine = {
 "42003": dict(fips="42003", name="Allegheny", state="PA", ring=0, anchor_name="Pittsburgh",
               lat=40.47, lon=-79.98, land_sq_mi=730, population=1250000, density=1712,
               drive_min=8, drive_estimated=True, spine_notes=["heterogeneous: spans core and rural"]),
 "42019": dict(fips="42019", name="Butler", state="PA", ring=2, anchor_name="Pittsburgh",
               lat=40.91, lon=-79.91, land_sq_mi=789, population=194000, density=246,
               drive_min=62, drive_estimated=True, spine_notes=[]),
 "30051": dict(fips="30051", name="Petroleum", state="MT", ring=4, anchor_name="Lewistown",
               lat=47.10, lon=-108.25, land_sq_mi=1654, population=500, density=0.3,
               drive_min=210, drive_estimated=True, spine_notes=[]),
}
results = {
 "spine": spine,
 "acs":   {"42003": {"median_household_income": 72000, "median_gross_rent": 1100, "median_home_value": 215000},
           "42019": {"median_household_income": 81000, "median_gross_rent": 1050, "median_home_value": 288000},
           "30051": {"median_household_income": 51000, "median_gross_rent": 620,  "median_home_value": 138000}},
 "rpp":   {"42003": {"rpp": 92.4, "rpp_source": "metro"},
           "42019": {"rpp": 92.4, "rpp_source": "metro"},
           "30051": {"rpp": 88.1, "rpp_source": "state fallback"}},
 "hazard":{"42003": {"wildfire": 10, "flood": 38, "hurricane": 5, "tornado": 18, "earthquake": 6, "heat_wave": 30},
           "42019": {"wildfire": 14, "flood": 30, "hurricane": 4, "tornado": 20, "earthquake": 6, "heat_wave": 26},
           "30051": {"wildfire": 58, "flood": 20, "hurricane": 1, "tornado": 22, "earthquake": 18, "heat_wave": 34}},
 "climate":{"42003": {"summer_high_f": 82.5, "winter_low_f": 20.3},
            "42019": {"summer_high_f": 81.9, "winter_low_f": 18.8},
            "30051": {"summer_high_f": 86.0, "winter_low_f": 8.0}},
 # crime present for two, suppressed for one — the realistic case
 "crime": {"42003": {"violent_per_100k": 291.7, "property_per_100k": 2083.3, "crime_coverage": 0.96},
           "42019": {"crime_coverage": 0.41, "crime_suppressed": "coverage 41% below 80% floor"}},
 "housing":{"42003": {"home_value": 219000, "fmr_2br": 1180},
            "42019": {"home_value": 291000, "fmr_2br": 1240}},
 "air":   {"42003": {"air_days_over": 12, "air_inherited": False},
           "42019": {"air_days_over": 12, "air_inherited": True, "air_source_mi": 31.4}},
}

records = transform(assemble(results))
print(f"assembled {len(records)} records from {len(results)} sources\n")
for r in records:
    print(f"  {r['name']+', '+r['state']:<18} ring {r['ring']}  hazard {r.get('hazard_score')}"
          f"  insurance {r.get('insurance_rate',0)*100:.2f}%  rent ${r.get('rent_monthly')}")
    for c in r.get("caveats", []):
        print(f"      · {c}")

findings, stats = check_dataset(records)
print("\n" + report(findings, stats))

# a left join must never drop a row: Petroleum has no housing or crime source
assert len(records) == 3, "left join dropped a county"
pet = next(r for r in records if r["fips"] == "30051")
assert pet.get("rent_monthly") == 620, "should fall back to ACS rent"
assert "state non-metro" in " ".join(pet.get("caveats", [])), "state RPP fallback must be declared"
but = next(r for r in records if r["fips"] == "42019")
assert "violent_per_100k" not in but, "suppressed crime must not appear"
alg = next(r for r in records if r["fips"] == "42003")
assert alg["hazard_score"] < pet["hazard_score"], "rural Montana carries more wildfire risk"
assert any("spans core and rural" in c for c in alg["caveats"])
# small fixture must trip the dataset-size gate
assert stats["blocking"] > 0, "a three-county dataset must not be publishable"
print("\nall assertions passed")
