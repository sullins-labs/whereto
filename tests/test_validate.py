import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from etl.validate import check_record, check_dataset, report, BLOCKING, WARNING

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
print("\nall assertions passed")
