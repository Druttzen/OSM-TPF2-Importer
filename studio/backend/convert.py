"""Run the existing Python converter with studio bounds."""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

_CONVERTER_MODULES = (
    "osm_tpf2_converter",
    "convert_data",
    "optimize_edges",
    "cubic_spline",
    "read_osm",
    "sort_edges",
    "graph_tools",
    "coord2metric",
    "lua_remove_nil",
    "vec2",
    "osmread",
    "converter_log",
)

_CONVERT_MARKERS = (
    ("Parse OSM XML", 8),
    ("Read osm data", 12),
    ("Extracting bounding", 10),
    ("Loaded ", 22),
    ("Convert/Transform", 30),
    ("Places found", 38),
    ("Optimize Edges", 45),
    ("Split long", 50),
    ("Create Graphs", 55),
    ("Remove Nodes with high", 62),
    ("Remove unnecessary", 65),
    ("Remove short Edges", 68),
    ("Calculate Tangents", 74),
    ("Align Tangents", 78),
    ("Adjust Signals", 80),
    ("Sort Edges", 84),
    ("Write Lua", 90),
    ("Write Lua chunk", 92),
    ("Buildings kept", 86),
    ("Successfully converted", 100),
)


def percent_from_log(line: str) -> int:
    text = line or ""
    pct = -1
    for marker, value in _CONVERT_MARKERS:
        if marker in text:
            pct = value
    return pct


def _watch_log(path: Path, progress, stop: threading.Event) -> None:
    pos = 0
    last = ""
    while not stop.wait(0.35):
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                chunk = fh.read()
                pos = fh.tell()
        except OSError:
            continue
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        last = lines[-1]
        if progress:
            pct = percent_from_log(last)
            progress(last[:400], pct if pct >= 0 else None)


def run_converter(
    python_dir: Path,
    osm_file: Path,
    out_lua: Path,
    map_meters: int,
    box: dict,
    timeout: int = 7200,
    progress=None,
) -> dict:
    main_py = python_dir / "main.py"
    if not main_py.is_file():
        return {"ok": False, "error": f"Converter not found: {main_py}"}
    if not osm_file.is_file():
        return {"ok": False, "error": f"OSM file missing: {osm_file}"}

    bounds = {
        "minlat": box["minlat"],
        "minlon": box["minlon"],
        "maxlat": box["maxlat"],
        "maxlon": box["maxlon"],
    }
    log = out_lua.parent / "convert.log"
    out_lua.parent.mkdir(parents=True, exist_ok=True)
    size_mb = osm_file.stat().st_size / 1e6
    if progress:
        progress(f"Starting converter ({size_mb:.1f} MB OSM)…", 2)

    python_dir_s = str(python_dir)
    # python/ also contains a PyInstaller dump (python39.dll / *.pyd). Never prepend it.
    if python_dir_s not in sys.path:
        sys.path.append(python_dir_s)

    for name in _CONVERTER_MODULES:
        sys.modules.pop(name, None)

    stop = threading.Event()
    watcher = threading.Thread(target=_watch_log, args=(log, progress, stop), daemon=True)
    watcher.start()
    try:
        spec = importlib.util.spec_from_file_location("osm_tpf2_converter", main_py)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["osm_tpf2_converter"] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        if not hasattr(mod, "convert_osm"):
            return {"ok": False, "error": "Converter entry point missing"}
        stats = mod.convert_osm(
            str(Path(osm_file).resolve()),
            str(Path(out_lua).resolve()),
            (int(map_meters), int(map_meters)),
            bounds,
            log_file=str(log.resolve()),
        )
        tail = ""
        if log.is_file():
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        stats = stats or {}
        stats["ok"] = True
        stats["log_tail"] = tail
        stats["out"] = str(out_lua) if out_lua.is_file() else None
        stats["size"] = out_lua.stat().st_size if out_lua.is_file() else 0
        if progress:
            progress("Convert finished.", 100)
        return stats
    except Exception as exc:
        tail = ""
        if log.is_file():
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        if progress:
            progress(str(exc), None)
        return {"ok": False, "error": str(exc), "log_tail": tail}
    finally:
        stop.set()
        watcher.join(timeout=1.5)
