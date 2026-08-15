import os
import re
import subprocess
from osmread import parse_file, Node, Way, Relation

osmosis_path = "osmosis\\bin\\osmosis"  # sry unix, please adjust...

_BOUNDS_TAG = re.compile(br"<bounds\b([^>]*)/?>")
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def crop_bounds(filename, bounds):
    extension = os.path.splitext(filename)[-1]
    if extension == ".pbf":
        read_comm = "--read-pbf"
    elif extension == ".osm":
        read_comm = "--read-xml"
    elif extension == ".bz2":
        read_comm = "--read-xml"
    else:
        assert 0, "Unknown OSM File Extension: " + extension
    filename_new = filename + "_crop.osm"
    print(f"Extracting bounding box area from '{filename}' via osmosis ...")
    complprocess = subprocess.run(
        [
            osmosis_path,
            read_comm,
            f"file={filename}",
            "--bounding-box",
            f"top={bounds['maxlat']}",
            f"left={bounds['minlon']}",
            f"bottom={bounds['minlat']}",
            f"right={bounds['maxlon']}",
            "completeWays=yes",
            "completeRelations=no",
            "--write-xml",
            filename_new,
        ],
        check=False,
    )
    complprocess.check_returncode()
    print(f"Saved to '{filename_new}'")
    return filename_new


def isinbounds(bounds, lat, lon):
    return bounds["minlat"] <= lat <= bounds["maxlat"] and bounds["minlon"] <= lon <= bounds["maxlon"]


def read_bounds(filename):
    """Scan the OSM XML header for <bounds> without parsing the whole file."""
    lower = str(filename).lower()
    if not (lower.endswith(".osm") or lower.endswith(".xml") or lower.endswith(".osm.xml")):
        return None
    with open(filename, "rb") as fh:
        head = fh.read(262144)
        match = _BOUNDS_TAG.search(head)
        if match is None:
            extra = fh.read(1024 * 1024 - 262144)
            match = _BOUNDS_TAG.search(head + extra)
    if match is None:
        raise AssertionError("OSM file has no <bounds> element in the first 1 MB")
    attr = match.group(1).decode("utf-8", "replace")
    parsed = dict(_ATTR.findall(attr))
    bounds = {}
    for key in ("minlat", "minlon", "maxlat", "maxlon"):
        if key not in parsed:
            raise AssertionError("OSM <bounds> missing " + key)
        bounds[key] = float(parsed[key])
    return bounds


def read(filename, bounds=None):
    print(f"Read osm data from '{filename}' ...")
    file_bounds = None
    try:
        file_bounds = read_bounds(filename)
        if file_bounds:
            print("Bounds of osm file:", file_bounds)
    except AssertionError as exc:
        print("OSM header bounds:", exc)
    use = bounds or file_bounds
    if use is None:
        raise AssertionError(
            "No map bounds: pass the Studio yellow box, or include <bounds> in the OSM file"
        )
    if bounds:
        print("Using Studio/map bounds for out-of-bounds flags:", bounds)
    assert filename.endswith(".osm") or filename.endswith(".pbf"), "File type needs to be .osm or .pbf"
    nodes = {}
    ways = {}
    relations = {}
    for entity in parse_file(filename):
        if isinstance(entity, Node):
            nodes[entity.id] = entity
            if not isinbounds(use, entity.lat, entity.lon):
                entity.tags["outofbounds"] = True
        elif isinstance(entity, Way):
            ways[entity.id] = entity
        elif isinstance(entity, Relation):
            relations[entity.id] = entity
    print(f"Loaded {len(nodes)} Nodes / {len(ways)} Ways / {len(relations)} Relations")
    return nodes, ways, relations
