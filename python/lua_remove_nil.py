def lua_remove_nil(d):
    if type(d) is dict:
        e = dict()
        for k, v in d.items():
            if v is not None:
                e[k] = lua_remove_nil(v)
        return e
    elif type(d) is list:
        e = []
        for v in d:
            if v is not None:
                e.append(lua_remove_nil(v))
        return e
    else:
        return d


def drop_removed_nodes(data):
    """Drop graph nodes marked removed so they are not serialized into Lua."""
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        return data
    marked_removed = {k for k, v in nodes.items() if isinstance(v, dict) and v.get("removed")}
    if not marked_removed:
        return data

    area_nodes = set()

    def collect_ring_nodes(ring):
        if isinstance(ring, list):
            for node in ring:
                if isinstance(node, list):
                    collect_ring_nodes(node)
                else:
                    area_nodes.add(node)

    areas = data.get("areas")
    if isinstance(areas, dict):
        for area_list in areas.values():
            if not isinstance(area_list, list):
                continue
            for area in area_list:
                if not isinstance(area, dict):
                    continue
                collect_ring_nodes(area.get("polygon"))
                multipolygon = area.get("multipolygon")
                if isinstance(multipolygon, dict):
                    for rings in multipolygon.values():
                        collect_ring_nodes(rings)

    removed = marked_removed - area_nodes
    data["nodes"] = {k: v for k, v in nodes.items() if k not in removed}
    paths = data.get("paths")
    if isinstance(paths, dict):
        for name, plist in list(paths.items()):
            if not isinstance(plist, list):
                continue
            cleaned = []
            for path in plist:
                if isinstance(path, list):
                    cleaned.append([n for n in path if n not in marked_removed])
                else:
                    cleaned.append(path)
            paths[name] = cleaned
    return data
