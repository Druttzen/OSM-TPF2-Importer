"""pywebview JS bridge for OSM-TPF2 Studio."""
from __future__ import annotations

import threading
import time
import uuid
import webbrowser
from pathlib import Path

import webview

from . import bounds as B
from . import convert as C
from . import heightmap as H
from . import install as I
from . import mods as M
from . import osm_fetch as O
from . import overlay as V
from . import paths as P


class StudioApi:
    window = None

    def __init__(self, repo_root: Path):
        self.repo = Path(repo_root)
        self.work = self.repo / "studio" / "work"
        self.work.mkdir(parents=True, exist_ok=True)
        saved = P.load_settings(self.work)
        found = P.discover(self.repo, hint_game=saved.get("game_dir") or "")
        self.state = dict(found)
        for k in (
            "size_key", "center_lat", "center_lon", "options", "osm_path", "osmdata_path",
            "heightmaps", "game_dir", "mods_dir", "workshop_dir", "steam_library", "steam_dir",
        ):
            if saved.get(k):
                self.state[k] = saved[k]
        if found.get("ok"):
            self._apply_discovered(found, keep_heightmaps=True)
        self.state.setdefault("size_key", "huge")
        lat, lon = self.state.get("center_lat"), self.state.get("center_lon")
        if lat is None or lon is None or B.is_legacy_center(lat, lon):
            self.state.pop("center_lat", None)
            self.state.pop("center_lon", None)
            self.state["place_set"] = False
        else:
            self.state["place_set"] = True
        self.state.setdefault("options", dict(I.DEFAULT_OPTIONS))
        self.state.setdefault("osm_path", str(self.work / "map.osm"))
        self.state.setdefault("osmdata_path", str(self.work / "osmdata.lua"))
        if not self.state.get("place_set") and saved.get("center_lat") is not None:
            self._persist()
        self.jobs: dict[str, dict] = {}
        self._active: str | None = None

    def _persist(self) -> None:
        P.save_settings(self.work, {
            "game_dir": self.state.get("game_dir"),
            "steam_library": self.state.get("steam_library"),
            "steam_dir": self.state.get("steam_dir"),
            "workshop_dir": self.state.get("workshop_dir"),
            "heightmaps": self.state.get("heightmaps"),
            "size_key": self.state.get("size_key"),
            "center_lat": self.state.get("center_lat") if self.state.get("place_set") else None,
            "center_lon": self.state.get("center_lon") if self.state.get("place_set") else None,
            "place_set": bool(self.state.get("place_set")),
            "options": self.state.get("options"),
            "osm_path": self.state.get("osm_path"),
            "osmdata_path": self.state.get("osmdata_path"),
        })

    def _job(self, fn, kind: str = "", label: str = "") -> dict:
        if self._active:
            running = self.jobs.get(self._active)
            if running and running.get("status") == "running":
                return {
                    "ok": False,
                    "error": f"Busy: {running.get('label') or 'another job'} is still running. Wait until it finishes.",
                }
        jid = uuid.uuid4().hex[:12]
        started = time.time()
        rec = {
            "id": jid,
            "status": "running",
            "ok": None,
            "log": "Starting…",
            "kind": kind,
            "label": label or kind or "Job",
            "stage": "Starting…",
            "percent": -1,
            "started": started,
            "elapsed": 0,
            "detail": "",
        }
        self.jobs[jid] = rec
        self._active = jid

        def progress(msg: str, percent=None) -> None:
            rec["stage"] = str(msg)[:400]
            rec["log"] = rec["stage"]
            if percent is not None:
                rec["percent"] = max(-1, min(100, float(percent)))
            rec["elapsed"] = round(time.time() - started, 1)
            prev = rec.get("detail") or ""
            line = rec["stage"]
            if not prev.endswith(line):
                rec["detail"] = (prev + "\n" + line).strip()[-2500:]

        def wrap():
            try:
                result = fn(progress)
                result = result or {}
                kind, label, started_at = rec["kind"], rec["label"], rec["started"]
                rec.update(result)
                rec["kind"] = kind
                rec["label"] = label
                rec["started"] = started_at
                rec["elapsed"] = round(time.time() - started_at, 1)
                if result.get("ok"):
                    rec["status"] = "done"
                    rec["percent"] = 100
                    if not rec.get("stage") or rec["stage"] == "Starting…":
                        rec["stage"] = "Done."
                    rec["log"] = rec["stage"]
                else:
                    rec["status"] = "error"
                    rec["stage"] = result.get("error") or rec.get("stage") or "Failed"
                    rec["log"] = rec["stage"]
            except Exception as exc:
                rec.update({
                    "ok": False,
                    "error": str(exc),
                    "status": "error",
                    "stage": str(exc),
                    "log": str(exc),
                    "elapsed": round(time.time() - started, 1),
                })
            finally:
                if self._active == jid:
                    self._active = None

        threading.Thread(target=wrap, daemon=True).start()
        return {"job_id": jid, "ok": True}

    def get_bootstrap(self) -> dict:
        size_key = self.state.get("size_key", "huge")
        meters = B.MAP_SIZES[size_key]["meters"]
        place_set = bool(self.state.get("place_set") and self.state.get("center_lat") is not None)
        box = None
        scale = None
        osm_url = "https://www.openstreetmap.org/"
        if place_set:
            box = B.box_from_center(self.state["center_lat"], self.state["center_lon"], meters)
            scale = B.scale_factors(box, meters)
            osm_url = B.osm_export_url(box)
        lua = self._osmdata_file()
        return {
            "paths": {
                "repo": self.state.get("repo"),
                "game_dir": self.state.get("game_dir"),
                "mods_dir": self.state.get("mods_dir"),
                "steam_library": self.state.get("steam_library"),
                "steam_dir": self.state.get("steam_dir"),
                "work_dir": str(self.work),
                "osm_path": self.state.get("osm_path"),
                "osmdata_path": str(lua) if lua else "",
                "workshop_dir": self.state.get("workshop_dir"),
                "heightmaps": self.state.get("heightmaps"),
                "exe": self.state.get("exe"),
            },
            "map_sizes": B.MAP_SIZES,
            "size_key": size_key,
            "place_set": place_set,
            "view": dict(B.DEFAULT_VIEW),
            "box": box,
            "scale": scale,
            "options": self.state.get("options") or dict(I.DEFAULT_OPTIONS),
            "osm_url": osm_url,
        }

    def _apply_discovered(self, found: dict, keep_heightmaps: bool = True) -> dict:
        for key in (
            "game_dir", "mods_dir", "steam_library", "steam_dir",
            "workshop_dir", "heightmaps", "exe",
        ):
            if key == "heightmaps" and keep_heightmaps:
                existing = self.state.get("heightmaps")
                if existing:
                    p = Path(existing)
                    if p.is_dir() or (p.parent.is_dir() and "heightmaps" in str(p).replace("\\", "/")):
                        continue
            if found.get(key):
                self.state[key] = found[key]
        self._persist()
        return found

    def _ensure_paths(self, hint: str = "", keep_heightmaps: bool = True) -> dict:
        found = P.discover(self.repo, hint_game=hint or self.state.get("game_dir") or "")
        if found.get("ok"):
            self._apply_discovered(found, keep_heightmaps=keep_heightmaps)
        return found

    def discover_paths(self, game_dir: str = "") -> dict:
        return self._ensure_paths(game_dir, keep_heightmaps=True)

    def set_paths(self, game_dir: str, steam_library: str = "") -> dict:
        found = self._ensure_paths(game_dir)
        if steam_library:
            self.state["steam_library"] = steam_library
            self._persist()
            found["steam_library"] = steam_library
        found["ok"] = bool(self.state.get("game_dir"))
        if not found.get("ok") and game_dir:
            found["error"] = f"Not a Transport Fever 2 folder: {game_dir}"
        return found

    def compute_box(self, lat: float, lon: float, size_key: str) -> dict:
        if size_key not in B.MAP_SIZES:
            return {"ok": False, "error": f"Unknown size {size_key}"}
        self.state["center_lat"] = float(lat)
        self.state["center_lon"] = float(lon)
        self.state["place_set"] = True
        self.state["size_key"] = size_key
        meters = B.MAP_SIZES[size_key]["meters"]
        box = B.box_from_center(float(lat), float(lon), meters)
        self._persist()
        return {
            "ok": True,
            "box": box,
            "scale": B.scale_factors(box, meters),
            "size": B.MAP_SIZES[size_key],
            "osm_url": B.osm_export_url(box),
            "area_deg2": B.bbox_area_deg2(box),
        }

    def geocode(self, query: str) -> list:
        return O.geocode(query)

    def pick_folder(self) -> dict:
        result = self._dialog(folder=True)
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0]
        return {"ok": True, "path": path}

    def pick_osm_file(self) -> dict:
        result = self._dialog(folder=False, file_types=("OSM XML (*.osm)", "All files (*.*)"))
        if not result:
            return {"ok": False, "cancelled": True}
        self.state["osm_path"] = result[0]
        self._persist()
        return {"ok": True, "path": result[0]}

    def _dialog(self, folder=False, file_types=None):
        if not self.window:
            return None
        file_types = file_types or tuple()
        if hasattr(webview, "FileDialog"):
            kind = webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN
            kwargs = {"directory": str(self.work)}
            if not folder:
                kwargs["file_types"] = file_types
            return self.window.create_file_dialog(kind, **kwargs)
        kind = webview.FOLDER_DIALOG if folder else webview.OPEN_DIALOG
        if folder:
            return self.window.create_file_dialog(kind)
        return self.window.create_file_dialog(kind, file_types=file_types)

    def download_osm(self, box: dict, mode: str = "filtered") -> dict:
        dest = Path(self.state.get("osm_path") or (self.work / "map.osm"))

        def job(progress):
            result = O.download_bbox(box, dest, mode=mode, progress=progress)
            if result.get("ok"):
                self.state["osm_path"] = result["path"]
                self._persist()
            return result

        return self._job(job, kind="osm", label="OSM download")

    def convert(self, box: dict, size_key: str, osm_path: str = "") -> dict:
        osm = Path(osm_path or self.state.get("osm_path") or (self.work / "map.osm"))
        out = Path(self.state.get("osmdata_path") or (self.work / "osmdata.lua"))
        meters = B.MAP_SIZES.get(size_key, B.MAP_SIZES["huge"])["meters"]

        def job(progress):
            result = C.run_converter(self.repo / "python", osm, out, meters, box, progress=progress)
            if result.get("ok"):
                self.state["osmdata_path"] = result.get("out") or str(out)
                self._persist()
            return result

        return self._job(job, kind="convert", label="Convert to osmdata.lua")

    def job_status(self, job_id: str) -> dict:
        rec = self.jobs.get(job_id)
        if not rec:
            return {"status": "unknown", "error": "No such job", "ok": False}
        st = dict(rec)
        started = st.get("started") or time.time()
        if st.get("status") == "running":
            st["elapsed"] = round(time.time() - started, 1)
            kind = st.get("kind")
            if kind == "heightmap":
                prog = self.work / "heightmap" / "progress.txt"
                if prog.is_file():
                    msg = prog.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    if msg:
                        st["stage"] = msg[-1][-400:]
                        st["log"] = st["stage"]
            elif kind == "mods":
                prog = self.work / "mods" / "progress.txt"
                if prog.is_file():
                    msg = prog.read_text(encoding="utf-8", errors="replace").strip()
                    if msg:
                        st["stage"] = msg[-400:]
                        st["log"] = st["stage"]
            elif kind == "convert":
                log = self.work / "convert.log"
                if not log.is_file():
                    log = self.repo / "python" / "log.txt"
                if log.is_file():
                    with log.open("rb") as fh:
                        fh.seek(0, 2)
                        size = fh.tell()
                        fh.seek(max(0, size - 8000))
                        chunk = fh.read().decode("utf-8", "replace")
                    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
                    if lines:
                        st["stage"] = lines[-1][-400:]
                        st["log"] = st["stage"]
                        st["detail"] = "\n".join(lines[-12:])
                        parsed = C.percent_from_log(lines[-1])
                        if parsed >= 0:
                            prev = st.get("percent")
                            st["percent"] = parsed if prev is None or prev < 0 else max(prev, parsed)
        return st

    def converter_log_tail(self) -> str:
        for log in (self.work / "convert.log", self.repo / "python" / "log.txt"):
            if not log.is_file():
                continue
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-50:])
        return ""

    def scan_mods(self) -> dict:
        found = self._ensure_paths()
        game = self.state.get("game_dir")
        if not game:
            return {"ok": False, "error": found.get("error") or "Could not find Transport Fever 2."}
        data = M.scan(game, self.state.get("steam_library") or None)
        data["ok"] = True
        data["paths"] = {
            "game_dir": game,
            "mods_dir": self.state.get("mods_dir"),
            "workshop_dir": self.state.get("workshop_dir"),
        }
        return data

    def open_workshop(self, file_id: str) -> dict:
        M.open_workshop(str(file_id))
        return {"ok": True}

    def open_missing_mods(self) -> dict:
        found = self._ensure_paths()
        game = self.state.get("game_dir")
        if not game:
            return {"ok": False, "error": found.get("error") or "Could not find Transport Fever 2."}
        return {"ok": True, **M.open_missing(game, self.state.get("steam_library") or None)}

    def search_workshop(self, query: str) -> dict:
        M.search_workshop(query or "street")
        return {"ok": True}

    def _work_osmdata(self) -> Path | None:
        for candidate in (self.state.get("osmdata_path"), self.work / "osmdata.lua"):
            if candidate:
                p = Path(candidate)
                if p.is_file():
                    return p
        return None

    def _osmdata_file(self) -> Path | None:
        game = Path(self.state.get("game_dir") or "")
        mods = Path(self.state.get("mods_dir") or "") if self.state.get("mods_dir") else (game / "mods" if game else None)
        live = None
        if mods:
            live = mods / "osm_importer_1" / "res" / "scripts" / "osm_importer" / "osmdata.lua"
        for candidate in (
            self.state.get("osmdata_path"),
            self.work / "osmdata.lua",
            live,
        ):
            if candidate:
                p = Path(candidate)
                if p.is_file():
                    return p
        return None

    def recommend_mods_from_map(self, subscribe: bool = True) -> dict:
        self._ensure_paths()
        lua = self._osmdata_file()
        if not lua:
            return {
                "ok": False,
                "error": "Convert OSM to osmdata.lua first, then press Find & subscribe mods for this map.",
            }
        dest = self.work / "mods"
        dest.mkdir(parents=True, exist_ok=True)

        def job(progress):
            (dest / "progress.txt").write_text("Starting…", encoding="utf-8")

            def both(msg: str, percent=None) -> None:
                (dest / "progress.txt").write_text(msg, encoding="utf-8")
                progress(msg, percent)

            result = M.recommend_for_map(
                lua,
                self.state.get("game_dir") or "",
                self.state.get("steam_library") or None,
                search_workshop_web=True,
                progress=both,
                lat=self.state.get("center_lat") if self.state.get("place_set") else None,
                lon=self.state.get("center_lon") if self.state.get("place_set") else None,
            )
            missing = result.get("missing") or []
            catalog_missing = [row for row in missing if row.get("source") != "workshop-search"]
            opened = {"opened": 0, "ids": []}
            if subscribe and catalog_missing:
                both(
                    f"Opening Steam subscribe for {min(12, len(catalog_missing))} missing catalog packs…",
                    92,
                )
                opened = M.subscribe_ids([row["id"] for row in catalog_missing], limit=12)
            result["subscribed"] = opened
            result["catalog_missing"] = catalog_missing
            result["path"] = str(lua)
            both("Done.", 100)
            return result

        return self._job(job, kind="mods", label="Mods for this map")

    def download_overlay(self, box: dict, zoom: int | None = None) -> dict:
        dest = self.work / "overlay"

        def job(progress):
            z = int(zoom) if zoom else None
            return V.download_overlay(box, dest, zoom=z, progress=progress)

        return self._job(job, kind="overlay", label="Satellite overlay")

    def download_heightmap(self, box: dict, size_key: str, strip_vegetation: bool = True, copy_to_game: bool = True) -> dict:
        dest = self.work / "heightmap"
        pixels = B.MAP_SIZES.get(size_key, B.MAP_SIZES["huge"])["heightmap"]
        def job(progress):
            progress("Finding TPF2 folders…", 1)
            found = self._ensure_paths()
            hm = found.get("heightmaps") or self.state.get("heightmaps") or ""
            if copy_to_game and hm:
                progress(f"Heightmaps: {hm}", 3)
            return H.generate_heightmap(
                box,
                int(pixels),
                dest,
                heightmaps_dir=Path(hm) if (copy_to_game and hm) else None,
                strip_vegetation=bool(strip_vegetation),
                copy_to_game=bool(copy_to_game and hm),
                progress=progress,
            )

        return self._job(job, kind="heightmap", label="Heightmap")

    def install(self, options: dict | None = None, game_dir: str = "") -> dict:
        if options:
            self.state["options"] = options
            self._persist()
        found = self._ensure_paths(game_dir)
        if not found.get("ok") or not self.state.get("mods_dir"):
            return {
                "ok": False,
                "error": found.get("error") or "Could not find Transport Fever 2 mods folder.",
            }
        mods = Path(self.state["mods_dir"])
        lua = self._work_osmdata()

        def job(progress):
            progress(f"Game: {self.state.get('game_dir')}", 2)
            progress(f"Mods: {mods}", 4)
            if self.state.get("workshop_dir"):
                progress(f"Workshop: {self.state.get('workshop_dir')}", 5)
            result = I.install_mod(
                self.repo,
                mods,
                lua,
                self.state.get("options") or {},
                progress=progress,
            )
            result["paths"] = {
                "game_dir": self.state.get("game_dir"),
                "mods_dir": str(mods),
                "workshop_dir": self.state.get("workshop_dir") or "",
                "heightmaps": self.state.get("heightmaps") or "",
                "target": result.get("target") or "",
            }
            return result

        return self._job(job, kind="install", label="Install into Mods")

    def save_options(self, options: dict) -> dict:
        self.state["options"] = options
        self._persist()
        return {"ok": True}

    def launch_game(self) -> dict:
        webbrowser.open("steam://rungameid/1066780")
        return {"ok": True}

    def open_osm_org(self, box: dict) -> dict:
        webbrowser.open(B.osm_export_url(box))
        return {"ok": True}

    def open_path(self, path: str) -> dict:
        p = Path(path)
        if p.is_file():
            webbrowser.open(p.parent.as_uri())
        elif p.is_dir():
            webbrowser.open(p.as_uri())
        else:
            return {"ok": False, "error": "Path not found"}
        return {"ok": True}
