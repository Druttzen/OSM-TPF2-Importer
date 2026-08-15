/* global L, pywebview */
const OPT_KEYS = [
  ["build_streets", "Streets"],
  ["build_tracks", "Tracks"],
  ["build_subwaytracks", "Subway / light rail"],
  ["build_tramtracks", "Tram as tracks"],
  ["build_bridges", "Bridges"],
  ["build_tunnels", "Tunnels"],
  ["build_signals", "Signals"],
  ["build_autobahn", "Motorways"],
  ["build_streets_street_types", "Street types"],
  ["build_streets_footway_types", "Footways"],
  ["build_streets_water", "Water streets"],
  ["build_streets_airport", "Airport roads"],
  ["build_buildings_residential", "Houses"],
  ["build_buildings_commercial", "Shops / offices"],
  ["build_buildings_industrial", "Industry buildings"],
  ["skip_nodes_outofbounds", "Skip out of bounds"],
  ["crash_type_not_found", "Abort if vanilla type missing"],
];

const api = () => window.pywebview.api;

let map, rect, box, sizeKey = "huge";
const logEl = () => document.getElementById("log");

function log(msg) {
  const el = logEl();
  const line = typeof msg === "string" ? msg : JSON.stringify(msg, null, 2);
  el.textContent += (el.textContent ? "\n" : "") + line;
  el.scrollTop = el.scrollHeight;
}

function boundsLatLng(b) {
  return [[b.minlat, b.minlon], [b.maxlat, b.maxlon]];
}

function hasPlace() {
  return !!(box && Number.isFinite(box.center_lat) && Number.isFinite(box.center_lon));
}

function needPlace() {
  if (hasPlace()) return true;
  log("Search a place or Shift-click the map first — there is no default city.");
  return false;
}

async function syncBoxFromForm() {
  const latEl = document.getElementById("lat");
  const lonEl = document.getElementById("lon");
  const keyEl = document.getElementById("sizeKey");
  if (!latEl || !lonEl || !keyEl) return box;
  const lat = Number(latEl.value);
  const lon = Number(lonEl.value);
  const key = keyEl.value;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return box;
  if (
    box
    && Math.abs(box.center_lat - lat) < 1e-7
    && Math.abs(box.center_lon - lon) < 1e-7
    && sizeKey === key
  ) {
    return box;
  }
  await refreshBox(lat, lon, key, false);
  return box;
}

function renderFacts(payload) {
  const b = payload && payload.box;
  const s = payload && payload.scale;
  const size = (payload && payload.size) || {};
  if (!b || !s) {
    document.getElementById("facts").innerHTML = `
      <dt>Place</dt><dd>Search a city or Shift-click the map</dd>
      <dt>TPF2</dt><dd>${size.label || sizeKey} · ${size.meters || "?"} m</dd>
    `;
    return;
  }
  const exp = size.experimental ? " (experimental in TPF2)" : "";
  document.getElementById("facts").innerHTML = `
    <dt>TPF2</dt><dd>${size.label || sizeKey} · ${size.meters || "?"} m${exp}</dd>
    <dt>Heightmap</dt><dd>${size.heightmap || "?"} × ${size.heightmap || "?"} px · 16-bit</dd>
    <dt>Ground</dt><dd>${s.real.lon_south_m} × ${s.real.lat_m} m</dd>
    <dt>Scale</dt><dd>X ${s.x} · Y ${s.y} (1.000 = exact 1:1)</dd>
    <dt>SW</dt><dd>${b.minlat.toFixed(6)}, ${b.minlon.toFixed(6)}</dd>
    <dt>NE</dt><dd>${b.maxlat.toFixed(6)}, ${b.maxlon.toFixed(6)}</dd>
  `;
  const hint = document.getElementById("hmHint");
  if (hint && size.heightmap) {
    hint.textContent = `${size.label || sizeKey} → ${size.heightmap}×${size.heightmap} px. After import, type Range min/max from the log into the map editor.`;
  }
}

function drawBox(b, fit) {
  box = b;
  const ll = boundsLatLng(b);
  if (rect) rect.setBounds(ll);
  else {
    rect = L.rectangle(ll, {
      color: "#e2c15a",
      weight: 2,
      fillColor: "#e2c15a",
      fillOpacity: 0.05,
    }).addTo(map);
  }
  document.getElementById("lat").value = b.center_lat.toFixed(6);
  document.getElementById("lon").value = b.center_lon.toFixed(6);
  if (fit) map.fitBounds(ll, { padding: [28, 28] });
}

async function refreshBox(lat, lon, key, fit) {
  sizeKey = key;
  const r = await api().compute_box(Number(lat), Number(lon), key);
  if (!r.ok) { log(r.error); return; }
  drawBox(r.box, fit);
  renderFacts(r);
}

function fmtElapsed(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  if (sec < 60) return sec + "s";
  return Math.floor(sec / 60) + "m " + String(sec % 60).padStart(2, "0") + "s";
}

function setLive(state, label, stage, percent, elapsed, detail) {
  const root = document.getElementById("liveStatus");
  if (!root) return;
  root.dataset.state = state || "idle";
  document.getElementById("liveLabel").textContent = label || "Idle";
  document.getElementById("liveStage").textContent = stage || (state === "idle" ? "No process running." : "");
  const bar = document.getElementById("liveBar");
  const pct = percent == null ? -1 : Number(percent);
  bar.classList.toggle("is-indeterminate", state === "run" && pct < 0);
  bar.style.width = (state === "run" && pct < 0) ? "" : (Math.max(0, Math.min(100, pct < 0 ? 0 : pct)) + "%");
  const bits = [];
  if (state === "run") bits.push("LIVE");
  if (state === "ok") bits.push("Done");
  if (state === "err") bits.push("Failed");
  if (pct >= 0 && state !== "idle") bits.push(Math.round(pct) + "%");
  if (elapsed != null && elapsed !== "" && state !== "idle") bits.push(fmtElapsed(elapsed));
  if (state === "idle") document.getElementById("liveMeta").textContent = "Ready";
  else document.getElementById("liveMeta").textContent = bits.join(" · ");
  const det = document.getElementById("liveDetail");
  if (det) det.textContent = detail || "";
}

async function runJob(start, label) {
  setLive("run", label, "Starting…", -1, 0, "");
  document.body.classList.add("is-busy");
  try {
    const job = await start();
    if (!job) {
      setLive("err", label, "No response from Studio.", 0, 0);
      log(label + " failed: no response");
      return job;
    }
    if (job.error && !job.job_id) {
      setLive("err", label, job.error, 0, 0);
      log(label + " failed: " + job.error);
      return job;
    }
    return await pollJob(job.job_id, label);
  } catch (err) {
    setLive("err", label, String(err), 0, 0);
    log(label + " failed: " + err);
    throw err;
  } finally {
    document.body.classList.remove("is-busy");
  }
}

async function flashStatus(label, fn) {
  const t0 = Date.now();
  setLive("run", label, "Working…", -1, 0, "");
  try {
    const r = await fn();
    const elapsed = (Date.now() - t0) / 1000;
    if (r && r.cancelled) {
      setLive("idle", label, "Cancelled.", 0, elapsed);
      return r;
    }
    if (r && r.ok === false) {
      setLive("err", label, r.error || "Failed", 0, elapsed);
      return r;
    }
    setLive("ok", label, (r && (r.stage || r.path || r.target)) || "Done.", 100, elapsed);
    return r;
  } catch (err) {
    setLive("err", label, String(err), 0, (Date.now() - t0) / 1000);
    throw err;
  }
}

async function pollJob(jobId, label) {
  log(label + " started.");
  for (;;) {
    const st = await api().job_status(jobId);
    const running = st.status === "running";
    const state = running ? "run" : (st.ok ? "ok" : "err");
    setLive(
      state,
      st.label || label,
      st.stage || st.log || (running ? "Working…" : ""),
      st.percent,
      st.elapsed,
      st.detail || "",
    );
    if (running) {
      await new Promise((res) => setTimeout(res, 400));
      continue;
    }
    if (st.ok) {
      log(label + " done" + (st.elapsed != null ? " in " + fmtElapsed(st.elapsed) : "") + ".");
      if (st.path && !st.recommended) log(st.path);
      if (st.png && st.min_m == null) log("Overlay PNG: " + st.png);
      if (st.min_m != null) {
        log(`Heightmap ${st.pixels}×${st.pixels}  Range min=${st.min_m}  max=${st.max_m}  water≈${st.water_m}`);
        log("Map editor IMPORT: paste those Range values. File: " + (st.copied || st.png));
        if (st.sources) log("Sources: " + st.sources.join(" · "));
      }
      if (st.out) {
        log("osmdata.lua: " + st.out + (st.size ? ` (${Math.round(st.size / 1e6)} MB)` : ""));
        const hint = document.getElementById("osmdataPath");
        if (hint) hint.textContent = "osmdata.lua: " + st.out;
      }
      if (st.edges != null) log(`Towns ${st.towns} · nodes ${st.nodes} · edges ${st.edges} · areas ${st.areas} · objects ${st.objects}` + (st.buildings != null ? ` · buildings ${st.buildings}` : ""));
      if (st.bytes != null && st.source) log(`Downloaded ${(st.bytes / 1e6).toFixed(1)} MB from ${st.source}`);
      if (st.target) {
        log("Installed to " + st.target);
        if (st.osmdata_source) log("osmdata source: " + st.osmdata_source);
        if (st.osmdata_copied === false) {
          log("Kept live osmdata.lua: " + (st.osmdata_note || "newer than the Studio work file"));
        } else if (st.osmdata_note) {
          log("osmdata: " + st.osmdata_note);
        }
      }
      if (st.paths) {
        renderGamePaths(st.paths);
        if (st.paths.mods_dir) log("Mods folder: " + st.paths.mods_dir);
        if (st.paths.workshop_dir) log("Workshop: " + st.paths.workshop_dir);
        if (st.paths.heightmaps) log("Heightmaps: " + st.paths.heightmaps);
      }
      if (st.recommended) {
        const miss = (st.missing || []).length;
        log(`Recommended ${st.recommended.length} Workshop packs for this map · ${miss} not installed`);
        if (st.subscribed) log(`Opened ${st.subscribed.opened || 0} Steam subscribe pages for catalog packs. Click Subscribe in Steam, then wait for downloads. Extra search hits stay in the list — subscribe those yourself if you want them.`);
        if (st.stats) {
          const s = st.stats;
          log(`osmdata: streets ${s.streets||0} · tracks ${s.tracks||0} · tram ${s.tram||0} · signals ${s.signals||0} · bridges ${s.bridges||0} · forests ${s.forests||0}`);
        }
        if (st.path) {
          const hint = document.getElementById("osmdataPath");
          if (hint) hint.textContent = "osmdata.lua: " + st.path;
        }
      }
      if (st.log_tail) log(st.log_tail);
    } else {
      log(label + " failed: " + (st.error || st.stage || JSON.stringify(st)));
    }
    return st;
  }
}

function showPanel(id) {
  document.querySelectorAll(".step").forEach((b) => b.classList.toggle("is-on", b.dataset.panel === id));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("is-on", p.id === "panel-" + id));
}

function renderModList(rows) {
  const host = document.getElementById("modList");
  host.innerHTML = "";
  for (const row of rows) {
    const div = document.createElement("div");
    div.className = "mod";
    const why = row.reason ? ` <small style="color:#9a907c">${row.reason}</small>` : "";
    div.innerHTML = `<span class="dot ${row.installed ? "on" : ""}"></span>
      <span>${row.name} <small style="color:#9a907c">${row.use || ""}</small>${why}</span>`;
    if (row.steam && row.id) {
      const b = document.createElement("button");
      b.textContent = row.installed ? "Open" : "Subscribe";
      b.className = "ghost";
      b.onclick = () => api().open_workshop(row.id);
      div.appendChild(b);
    } else {
      div.appendChild(document.createElement("span"));
    }
    host.appendChild(div);
  }
}

async function findModsForMap() {
  showPanel("mods");
  const st = await runJob(() => api().recommend_mods_from_map(true), "Mods for this map");
  if (st && st.ok && st.recommended) renderModList(st.recommended);
}

function collectOptions() {
  const o = { log_level: 1 };
  for (const [key] of OPT_KEYS) {
    const el = document.getElementById("opt-" + key);
    o[key] = !!(el && el.checked);
  }
  return o;
}

function fillOptions(opts) {
  const grid = document.getElementById("optGrid");
  grid.innerHTML = "";
  for (const [key, label] of OPT_KEYS) {
    const id = "opt-" + key;
    const wrap = document.createElement("label");
    wrap.innerHTML = `<input id="${id}" type="checkbox" ${opts[key] ? "checked" : ""}/> ${label}`;
    grid.appendChild(wrap);
  }
}

function renderGamePaths(p) {
  const host = document.getElementById("gamePaths");
  if (!host) return;
  const rows = [
    ["Game", p.game_dir],
    ["Mods", p.mods_dir],
    ["Workshop", p.workshop_dir],
    ["Heightmaps", p.heightmaps],
  ];
  host.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v || "—"}</dd>`).join("");
  if (p.game_dir) document.getElementById("gameDir").value = p.game_dir;
}

function waitApi() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", resolve, { once: true });
  });
}

async function main() {
  await waitApi();
  const boot = await api().get_bootstrap();
  box = boot.box;
  sizeKey = boot.size_key;
  document.getElementById("gameDir").value = boot.paths.game_dir || "";
  renderGamePaths(boot.paths);
  document.getElementById("osmPath").textContent = boot.paths.osm_path || "";
  document.getElementById("osmdataPath").textContent = boot.paths.osmdata_path
    ? ("osmdata.lua: " + boot.paths.osmdata_path)
    : "osmdata.lua: convert the map first";

  const sel = document.getElementById("sizeKey");
  for (const [key, info] of Object.entries(boot.map_sizes)) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = `${info.label} · ${info.meters} m${info.experimental ? " *" : ""}`;
    if (key === sizeKey) opt.selected = true;
    sel.appendChild(opt);
  }
  fillOptions(boot.options);
  const view = boot.view || { lat: 20, lon: 0, zoom: 2 };
  if (boot.place_set && boot.box) {
    renderFacts({ box: boot.box, scale: boot.scale, size: boot.map_sizes[sizeKey] });
  } else {
    box = null;
    renderFacts({ size: boot.map_sizes[sizeKey] });
  }

  map = L.map("map", { zoomControl: true }).setView(
    boot.place_set && boot.box ? [boot.box.center_lat, boot.box.center_lon] : [view.lat, view.lon],
    boot.place_set && boot.box ? 12 : (view.zoom || 2),
  );
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  if (boot.place_set && boot.box) drawBox(boot.box, true);

  map.on("click", (ev) => {
    if (!ev.originalEvent.shiftKey) return;
    refreshBox(ev.latlng.lat, ev.latlng.lng, sel.value, false);
  });

  document.querySelectorAll(".step").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".step").forEach((b) => b.classList.remove("is-on"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("is-on"));
      btn.classList.add("is-on");
      document.getElementById("panel-" + btn.dataset.panel).classList.add("is-on");
    });
  });

  sel.addEventListener("change", () => {
    if (!hasPlace()) return;
    refreshBox(document.getElementById("lat").value, document.getElementById("lon").value, sel.value, true);
  });
  document.getElementById("lat").addEventListener("change", () => syncBoxFromForm());
  document.getElementById("lon").addEventListener("change", () => syncBoxFromForm());
  document.getElementById("btnPlace").onclick = () => {
    const c = map.getCenter();
    refreshBox(c.lat, c.lng, sel.value, false);
  };
  document.getElementById("btnFit").onclick = () => {
    if (!needPlace()) return;
    map.fitBounds(boundsLatLng(box), { padding: [28, 28] });
  };
  document.getElementById("btnOsmOrg").onclick = () => {
    if (!needPlace()) return;
    api().open_osm_org(box);
  };
  document.getElementById("btnSearch").onclick = async () => {
    const q = document.getElementById("searchQ").value.trim();
    if (!q) return;
    const hits = await flashStatus("Place search", () => api().geocode(q));
    if (!hits.length) { log("No Nominatim hits."); return; }
    log(hits[0].label);
    await refreshBox(hits[0].lat, hits[0].lon, sel.value, true);
  };

  document.getElementById("btnDownload").onclick = async () => {
    await syncBoxFromForm();
    if (!needPlace()) return;
    const mode = document.getElementById("osmMode").value;
    const st = await runJob(() => api().download_osm(box, mode), "OSM download");
    if (st && st.path) document.getElementById("osmPath").textContent = st.path;
  };
  document.getElementById("btnPickOsm").onclick = async () => {
    const r = await flashStatus("Pick OSM file", () => api().pick_osm_file());
    if (r.ok) {
      document.getElementById("osmPath").textContent = r.path;
      log("Using " + r.path);
    }
  };
  document.getElementById("btnConvert").onclick = async () => {
    await syncBoxFromForm();
    if (!needPlace()) return;
    const st = await runJob(
      () => api().convert(box, sel.value, document.getElementById("osmPath").textContent),
      "Convert to osmdata.lua",
    );
    if (st && st.ok) {
      log("Next: press Find & subscribe mods for this map. Steam will open Subscribe for missing packs; skip any you do not want — vanilla types are used instead.");
    }
  };

  document.getElementById("btnScanMods").onclick = async () => {
    const data = await flashStatus("Scan Workshop mods", () => api().scan_mods());
    if (!data.ok) { log(data.error); return; }
    const rows = [...(data.catalog || []), ...(data.local_packs || []).map((p) => ({
      id: "", name: p.folder, use: p.use, installed: true, steam: false,
    }))];
    renderModList(rows);
    log(`Workshop folders: ${data.workshop_ids.length} · missing Steam deps: ${data.missing_steam.length}`);
  };
  document.getElementById("btnMapMods").onclick = findModsForMap;
  document.getElementById("btnMapMods2").onclick = findModsForMap;
  document.getElementById("btnOpenMissing").onclick = async () => {
    const r = await flashStatus("Open missing in Steam", () => api().open_missing_mods());
    log(r.ok ? `Opened ${r.opened} of ${r.total_missing} missing Workshop pages.` : r.error);
  };
  document.getElementById("btnModSearch").onclick = async () => {
    await flashStatus("Workshop search", () => api().search_workshop(document.getElementById("modQ").value));
  };

  document.getElementById("btnSat").onclick = async () => {
    await syncBoxFromForm();
    if (!needPlace()) return;
    const z = document.getElementById("satZoom").value;
    await runJob(() => api().download_overlay(box, z ? Number(z) : null), "Satellite overlay");
  };
  document.getElementById("btnHeightmap").onclick = async () => {
    await syncBoxFromForm();
    if (!needPlace()) return;
    await runJob(
      () => api().download_heightmap(
        box,
        sel.value,
        document.getElementById("hmStrip").checked,
        document.getElementById("hmCopy").checked,
      ),
      "Heightmap",
    );
  };

  document.getElementById("btnGameFolder").onclick = async () => {
    const r = await flashStatus("Pick game folder", () => api().pick_folder());
    if (r.ok) {
      const found = await api().set_paths(r.path, "");
      renderGamePaths(found);
      log(found.ok ? ("Using " + found.game_dir) : (found.error || "Folder not recognized as TPF2"));
    }
  };
  document.getElementById("btnAutoFind").onclick = async () => {
    const hint = document.getElementById("gameDir").value.trim();
    const found = await flashStatus("Auto-find TPF2 folders", () => api().discover_paths(hint));
    renderGamePaths(found);
    if (!found.ok) log(found.error || "Could not find Transport Fever 2");
    else {
      const bits = found.found || [];
      log("Found " + bits.join(", ") + ".");
      if (found.game_dir) log("Game: " + found.game_dir);
      if (found.mods_dir) log("Mods: " + found.mods_dir);
      if (found.workshop_dir) log("Workshop: " + found.workshop_dir);
      if (found.heightmaps) log("Heightmaps: " + found.heightmaps);
    }
  };
  document.getElementById("btnInstall").onclick = async () => {
    const hint = document.getElementById("gameDir").value.trim();
    await runJob(() => api().install(collectOptions(), hint), "Install into Mods");
  };
  document.getElementById("btnLaunch").onclick = async () => {
    await flashStatus("Launch TPF2", () => api().launch_game());
    log("Opening Steam: Transport Fever 2");
  };

  log("Studio ready. Yellow line is the TPF2 map square.");
  setLive("idle", "Idle", "No process running.", 0, "", "");
}

main().catch((err) => log(String(err)));
