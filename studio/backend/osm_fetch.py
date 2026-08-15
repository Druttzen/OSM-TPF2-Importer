"""Download OSM XML for a bounding box via Overpass, with OSM.org export fallback."""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .atomic import write_bytes

UA = "OSM-TPF2-Studio/1.0 (personal rebuild tool; contact: local user)"
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OSM_EXPORT = "https://api.openstreetmap.org/api/0.6/map?bbox={minlon},{minlat},{maxlon},{maxlat}"


def _query_filtered(box: dict) -> str:
    s, w, n, e = box["minlat"], box["minlon"], box["maxlat"], box["maxlon"]
    return f"""
[out:xml][timeout:300][bbox:{s},{w},{n},{e}];
(
  way["highway"];
  way["railway"];
  way["waterway"];
  way["landuse"];
  way["natural"];
  way["leisure"];
  way["area:highway"];
  relation["landuse"];
  relation["natural"];
  relation["type"="multipolygon"]["landuse"];
  relation["type"="multipolygon"]["natural"];
  node["place"];
  node["natural"="tree"];
  node["amenity"="fountain"];
  node["barrier"="bollard"];
  node["advertising"="column"];
  node["railway"~"^(signal|switch)$"];
  way["building"~"^(house|detached|semidetached_house|semidetached|terrace|apartments|residential|dormitory|bungalow|farm|cabin|commercial|retail|office|supermarket|kiosk|hotel|motel|shop|industrial|warehouse|factory|manufacture|hangar|barn|works)$"];
  way["building"]["shop"];
  way["building"]["office"];
  way["building"]["industrial"];
  way["building"]["residential"];
  way["building"]["building:use"~"^(residential|commercial|retail|industrial)$"];
);
(._;>;);
out meta;
""".strip()


def _query_full(box: dict) -> str:
    s, w, n, e = box["minlat"], box["minlon"], box["maxlat"], box["maxlon"]
    return f"[out:xml][timeout:240];(node({s},{w},{n},{e});<;);out meta;"


def _ensure_bounds(xml: bytes, box: dict) -> bytes:
    if b"<bounds" in xml[:12000]:
        return xml
    tag = (
        f'<bounds minlat="{box["minlat"]}" minlon="{box["minlon"]}" '
        f'maxlat="{box["maxlat"]}" maxlon="{box["maxlon"]}"/>'
    ).encode("ascii")
    match = re.search(br"<osm[^>]*>", xml)
    if not match:
        return xml
    return xml[: match.end()] + b"\n  " + tag + xml[match.end() :]


def _get(url: str, data: bytes | None, timeout: int, progress=None) -> bytes:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST" if data else "GET",
    )
    chunks: list[bytes] = []
    n = 0
    last_note = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            n += len(chunk)
            if progress and n - last_note >= 512 * 1024:
                last_note = n
                progress(n)
    return b"".join(chunks)


def download_bbox(box: dict, dest: Path, timeout: int = 300, mode: str = "filtered", progress=None) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    query = _query_full(box) if mode == "full" else _query_filtered(box)
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")

    def note(msg: str, pct=None) -> None:
        if progress:
            progress(msg, pct)

    note(f"Building Overpass query ({mode})…", 2)
    for i, endpoint in enumerate(OVERPASS_ENDPOINTS):
        host = endpoint.split("/")[2]
        note(f"Connecting to {host}…", 6 + i * 8)

        def bytes_cb(n: int, _host=host) -> None:
            note(f"{_host}: received {n / 1e6:.1f} MB…", min(82, 12 + n / 8e6 * 70))

        try:
            data = _get(endpoint, body, timeout, progress=bytes_cb)
            if len(data) < 400:
                raise RuntimeError("Empty Overpass response")
            note("Writing map.osm…", 90)
            data = _ensure_bounds(data, box)
            write_bytes(dest, data)
            note(f"Saved {len(data) / 1e6:.1f} MB from {host}", 100)
            return {
                "ok": True,
                "path": str(dest),
                "bytes": len(data),
                "source": host,
                "mode": mode,
            }
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_err = str(exc)
            note(f"{host} failed: {last_err}", 6 + i * 8)
            continue

    bbox = dict(minlon=box["minlon"], minlat=box["minlat"], maxlon=box["maxlon"], maxlat=box["maxlat"])
    area = abs(box["maxlat"] - box["minlat"]) * abs(box["maxlon"] - box["minlon"])
    if area > 0.24:
        return {
            "ok": False,
            "error": (
                last_err or "Overpass failed"
            )
            + ". Box is larger than the OSM.org export limit (0.25 deg²). "
            "Use a smaller map size, or drop a local .osm extract (Geofabrik / Global Mapper).",
        }
    try:
        note("Trying OSM.org export…", 20)

        def bytes_cb(n: int) -> None:
            note(f"OSM.org: received {n / 1e6:.1f} MB…", min(85, 20 + n / 8e6 * 65))

        data = _get(OSM_EXPORT.format(**bbox), None, min(timeout, 120), progress=bytes_cb)
        if len(data) < 400:
            raise RuntimeError("Empty OSM.org export")
        write_bytes(dest, _ensure_bounds(data, box))
        note(f"Saved {len(data) / 1e6:.1f} MB from api.openstreetmap.org", 100)
        return {"ok": True, "path": str(dest), "bytes": len(data), "source": "api.openstreetmap.org", "mode": "full"}
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        return {"ok": False, "error": last_err or str(exc)}


def geocode(query: str, limit: int = 5) -> list:
    q = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            import json
            rows = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    out = []
    for row in rows:
        out.append({
            "label": row.get("display_name"),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
        })
    return out
