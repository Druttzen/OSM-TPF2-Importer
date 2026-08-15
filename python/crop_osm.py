"""Optional OSM crop helper. Pass an extract and a bbox — no city is assumed."""
import sys

import read_osm

# python crop_osm.py infile.osm minlat,minlon,maxlat,maxlon
if len(sys.argv) < 3:
    print("Usage: python crop_osm.py <file.osm|.pbf> minlat,minlon,maxlat,maxlon")
    sys.exit(1)

infile = sys.argv[1]
coords = [float(x) for x in sys.argv[2].split(",")]
if len(coords) != 4:
    print("Bounds must be minlat,minlon,maxlat,maxlon")
    sys.exit(1)
bounds = dict(zip(["minlat", "minlon", "maxlat", "maxlon"], coords))
read_osm.crop_bounds(infile, bounds)
