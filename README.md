# San Francisco 1:1 — Godot 4.7

Explorable, geographically accurate 1:1 recreation of San Francisco (city
proper, ~121 km²) in Godot 4.7 Forward+. Real streets, real building
footprints, real hill elevations, streamed in 256 m tiles.

## Quickstart

```bash
# 1. Bake the city (fetches OSM + DEM, generates tiles). Long one-time run.
python3 pipeline/run_all.py
python3 pipeline/verify_bake.py          # exit 0 = bake valid

# 2. Import assets (two passes — see note below).
godot --headless --path . --import
rm -f data/tiles/*.import data/props/*.import
godot --headless --path . --import

# 3. Play (windowed) or verify headless.
godot --path .                           # on a real GPU / desktop
godot --headless --path . --script tests/smoke.gd
```

**Import quirk:** a fresh glTF whose texture dependencies aren't imported yet
gets `valid=false` stuck in its `.import` file and is never retried. Deleting
the `.import` files between the two passes forces a real import pass once
textures exist. `tools/visual_check.sh` automates desktop screenshots.

## Install on Windows 10/11

You need a GPU with **Vulkan** support (GTX 1060 / RX 580 class or newer —
the 60 fps target assumes RTX 3060-class). Godot itself is a portable exe,
no installer.

**1. Get the project** (~750 MB clone; the baked city ships with the repo, no
bake required):

```powershell
git clone https://github.com/DudeChill/san-francisco-1to1.git
cd san-francisco-1to1
```

(No Git? Download and extract the repo ZIP from the GitHub Code button.)

**2. Get Godot 4.7** — either download **Godot Engine → Standard** (not .NET),
Windows → 64-bit from [godotengine.org/download](https://godotengine.org/download)
and unzip anywhere, or paste this PowerShell block which does it for you
(SmartScreen may prompt on first run — the binary is the official unsigned
Godot build):

```powershell
$v = "4.7.2-stable"
Invoke-WebRequest "https://github.com/godotengine/godot/releases/download/$v/Godot_v${v}_win64.exe.zip" -OutFile "$env:TEMP\godot.zip"
Expand-Archive "$env:TEMP\godot.zip" "C:\Godot" -Force
$godot = "C:\Godot\Godot_v${v}_win64.exe"
```

**3. Import assets (two passes, PowerShell):**

```powershell
$godot = "C:\Godot\Godot_v4.7-stable_win64.exe"   # adjust to your path

& $godot --headless --path . --import
Remove-Item data\tiles\*.import, data\props\*.import
& $godot --headless --path . --import
```

Pass 1 imports textures; the glTF scene import defers and leaves stub
`.import` files that never retry on their own — deleting them forces pass 2
to actually import the ~5.8k tile scenes (~5–10 min on first run).

**4. Play:**

```powershell
& $godot --path .
```

First launch compiles shaders and may hitch for a few seconds. Optional
headless self-test (should print `SMOKE: PASS`):

```powershell
& $godot --headless --path . --script tests/smoke.gd
```

**Optional — re-bake the city from scratch** (only if you want to regenerate
tiles from fresh OSM data; needs Python 3.10+ from python.org, tick
"Add python.exe to PATH" in the installer):

```powershell
python -m pip install numpy pillow shapely
python pipeline\run_all.py     # fetches OSM + DEM, bakes all tiles (long)
python pipeline\verify_bake.py # must print VERIFY OK
```

…then re-run the two-pass import from step 3. The pipeline is pure
cross-platform Python (stdlib + numpy/Pillow/shapely) — no WSL needed.

## Environment switches (verification / debugging)

| Var | Effect |
|-----|--------|
| `SF_TOUR_STOP=n` | teleport to landmark n (1-based index of `index.json:landmarks`) at boot |
| `SF_HOUR=h` | start clock at hour h (e.g. `12.0` noon, `21.5` night) |
| `SF_TOUR_PITCH=p` | camera pitch in radians (e.g. `-0.85` aerial look-down) |
| `SF_CLEAR_FOG=1` | disable volumetric + distance fog |
| `SF_LOWFI=1` | disable SDFGI/SSAO/glow (for software renderers) |

`tools/visual_check.sh <out_dir>` captures five deterministic screenshots on
the shared desktop (display `:98`): Ferry Building spawn, FiDi skyline from
above Salesforce Tower, Golden Gate Bridge, Painted Ladies, and the night
windows pass. Note: a CPU Vulkan implementation (lavapipe) runs ~1 fps with
starved streaming — screenshots there prove content, not performance.
`tools/fix_winding.py`, `tools/fix_terrain_uv.py`,
`tools/merge_prim_overflow.py` are idempotent one-time repair passes for the
baked glTF data (keep for re-bakes).

## Controls

| Key | Action |
|-----|--------|
| WASD | walk / fly |
| Shift | sprint (walk + fly speed) |
| Space | jump; fly up |
| Ctrl | fly down |
| F | toggle free-fly |
| E | enter / exit vehicle |
| T | tour mode: teleport to next landmark |
| N | advance time 1 hour (start: 17:30 golden hour) |
| Esc | release mouse |

## Architecture

Two-stage pipeline; nothing is hand-modeled at scale.

**Stage 1 — offline bake** (`pipeline/`, python3 + numpy/Pillow/shapely only):

- `fetch_dem.py` — AWS terrain tiles (terrarium PNG, z14, ~9.5 m/px) →
  `data_raw/dem.npz` elevation grid.
- `fetch_osm.py` / `parse_osm.py` — Overpass API (UA `sf-city-builder/0.1`),
  buildings/roads/water/piers/trees/parks with `out geom`.
- `districts.py` — neighborhood polygons → district classes + fog-belt flags
  (Richmond/Sunset/Ocean Beach/Presidio socked in, Mission sunny).
- `textures.py` — procedural district facade atlases (albedo + emissive
  window maps, ORM-ish roughness variance), road/sidewalk/terrain/roof tiles.
- `landmarks.py` — procedural meshes at real dimensions: Golden Gate Bridge
  (1,280 m span, 227 m towers, #C0362C), Salesforce Tower (326 m),
  Transamerica Pyramid (260 m), Sutro Tower (298 m), Coit Tower, Ferry
  Building, Palace of Fine Arts, Painted Ladies, Dragon Gate, Alcatraz,
  Sutro Baths, City Hall dome, Bay Bridge.
- `bake_tiles.py` — terrain meshes with roads carved flat along centerlines,
  road ribbons with per-class widths, sidewalk ribbons, crosswalk decals,
  building extrusion from `building:levels`/`height` tags, merged per
  material per tile, worldspace-wrap facade UVs.
- Output: `data/tiles/tile_<i>_<j>.gltf` (+`.bin`, `_lod1` pair), shared
  textures in `data/tiles/tex/`, prop manifests, `data/props/*.gltf` meshes,
  `index.json` manifest (grid origin, spawn, landmarks, cable car polylines,
  per-tile fog flags).

**Stage 2 — Godot runtime**:

- `common/stream_manager.gd` — ring streaming around the active camera:
  full-detail tier ≤ 2 tiles, LOD1 (decimated terrain + untextured prism
  buildings) ≤ 8 tiles, hysteresis unload at +2. Loads via
  `ResourceLoader.load_threaded_request`, instantiates capped per frame,
  swaps `Mat_Facade_*` → facade shader (night windows) and `Mat_Water` →
  wave shader, builds per-type `MultiMeshInstance3D` for props from the
  manifests. Collision comes from glTF node-name hints (`_col` suffix keeps
  the visual mesh and adds a static trimesh body).
- `common/time_of_day.gd` — sun/moon at 37.77°N (equinox model), AgX
  tonemap, SDFGI + SSAO, base volumetric fog, `night_factor` drives window
  emissives.
- `features/world/fog_manager.gd` — Karl the Fog: FogVolume slabs advected
  in from the Pacific, density keyed to fog-belt tiles + hour.
- `features/player/player_controller.gd`, `features/vehicle/` — walk/fly,
  `VehicleBody3D` car (Jolt physics), cable cars on real OSM polylines at
  15 km/h with bell.
- `features/world/world_boot.gd` — spawns everything from `index.json`,
  positional foghorn at the Golden Gate, gulls at the Ferry Building.
- `ui/hud.gd` — position/tiles/fps/time overlay.

## Coordinate system

Local ENU meters. Origin `(37.7700, -122.4355)`; x = east, z = south
(Godot -Z = north), y = elevation. City centered at the origin (float32
precision requirement). Tile `j` indices run negative (south-edge grid
origin); see `data/tiles/index.json` for exact values.

## Performance budgets (desktop)

< 500 visible draw calls, < 1 M visible triangles, < 2 GB VRAM streamed set,
60 fps target on RTX 3060-class GPU. Verify with Godot's Profiler
(`tests/smoke.gd` gates load correctness headless; `tools/visual_check.sh`
captures desktop screenshots).

## Known deviations from the original spec

- Occlusion culling (`OccluderInstance3D`) is not generated — merged
  per-tile meshes + LOD tiers carry the budget instead.
- Interiors are shells (by design); bathymetry is flat.
- Landmarks are procedural approximations at real dimensions, not
  photogrammetry.

## Data provenance

- Street/building/water data © OpenStreetMap contributors, ODbL 1.0.
  Attribution required for any redistribution of baked tiles.
- Elevation: Mapzen/AWS terrain tiles (terrarium) — USGS/SRTM-derived.
- Textures: procedurally generated (no third-party assets).
- Audio: procedurally synthesized (`tools/gen_audio.py`).
