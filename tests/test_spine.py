"""Offline test of the ring derivation, using counties whose real-world
classification is well known. No network required."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from etl.spine import County, assign_rings, split_core_counties, summarize, RING_NAMES

def c(fips,name,st,lat,lon,area,pop,cbsa,cbsa_name,central,rucc):
    return County(fips=fips,name=name,state=st,lat=lat,lon=lon,land_sq_mi=area,
                  population=pop,cbsa=cbsa,cbsa_name=cbsa_name,central=central,rucc=rucc)

COUNTIES = [
    c("42003","Allegheny","PA",40.47,-79.98,730,1250000,"38300","Pittsburgh",True,1),
    c("42007","Beaver","PA",40.68,-80.35,435,166000,"38300","Pittsburgh",False,1),
    c("42019","Butler","PA",40.91,-79.91,789,194000,"38300","Pittsburgh",False,1),
    c("42125","Washington","PA",40.19,-80.25,857,210000,"38300","Pittsburgh",False,1),
    c("42073","Lawrence","PA",40.99,-80.33,358,86000,"38300","Pittsburgh",False,1),
    c("36061","New York","NY",40.78,-73.97,22.8,1600000,"35620","New York",True,1),
    c("36059","Nassau","NY",40.74,-73.59,285,1390000,"35620","New York",True,1),
    c("36103","Suffolk","NY",40.94,-72.69,912,1520000,"35620","New York",False,1),
    c("30031","Gallatin","MT",45.55,-111.17,2603,125000,"14580","Bozeman",True,3),
    c("30051","Petroleum","MT",47.10,-108.25,1654,500,None,None,False,9),
    c("31183","Wheeler","NE",41.91,-98.52,575,700,None,None,False,9),
    c("42053","Forest","PA",41.51,-79.23,427,6000,None,None,False,8),
]

rings = {x.fips: x for x in split_core_counties(assign_rings(COUNTIES))}

print("ring assignment:")
for x in COUNTIES:
    print(f"  {x.name+', '+x.state:<22} ring {x.ring} {RING_NAMES[x.ring]:<15} "
          f"drive {str(x.drive_min)+'m':<6} {x.notes[0][:60]}")
print("\nsummary:", summarize(COUNTIES))

assert rings["42003"].ring == 0, "Allegheny (Pittsburgh) should be core"
assert rings["36061"].ring == 0, "Manhattan should be core"
assert rings["30051"].ring == 4, "Petroleum County MT should be rural"
assert rings["31183"].ring == 4, "Wheeler County NE should be rural"
assert rings["42003"].drive_min < rings["42073"].drive_min, "core closer than fringe"
assert rings["36103"].ring >= 1, "Suffolk is outlying, not core"
assert any("heterogeneous" in n for n in rings["42003"].notes), "Allegheny spans rings"
print("\nall assertions passed")
