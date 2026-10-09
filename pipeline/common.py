"""Shared constants + helpers for the SF city bake pipeline (offline, Godot 4.7)."""
import json
import math
import os
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DATA_RAW = os.path.join(ROOT, "data_raw")
TILES_DIR = os.path.join(DATA, "tiles")
TEX_DIR = os.path.join(TILES_DIR, "tex")
PROPS_DIR = os.path.join(DATA, "props")
META_DIR = os.path.join(DATA, "meta")
CACHE_DIR = os.path.join(DATA_RAW, "cache")

LAT0, LON0 = 37.7700, -122.4355
KX = 111320.0 * math.cos(math.radians(LAT0))  # m per degree lon at lat0
KZ = 110540.0                                 # m per degree lat

# City bbox (lat_min, lat_max, lon_min, lon_max)
BBOX_LAT_MIN, BBOX_LAT_MAX = 37.708, 37.832
BBOX_LON_MIN, BBOX_LON_MAX = -122.514, -122.357

TILE = 256.0
WATER_LEVEL = 0.0

# Grid origin = SW corner in ENU. z grows southward, so grid_z0 (z of the SOUTHERN
# edge, lat 37.708) is the LARGEST z in the bbox; tile j therefore runs NEGATIVE
# (north) per contract: tile j spans z in [grid_z0 + j*256, grid_z0 + (j+1)*256).
GRID_X0 = (BBOX_LON_MIN - LON0) * KX
GRID_Z0 = (LAT0 - BBOX_LAT_MIN) * KZ
NI = int(math.ceil(((BBOX_LON_MAX - BBOX_LON_MIN) * KX) / TILE))  # i: 0..NI-1 (west->east)
NJ = int(math.ceil(((BBOX_LAT_MAX - BBOX_LAT_MIN) * KZ) / TILE))  # j: -NJ..-1 (north<-south... j=-NJ is northernmost strip edge)
J_MIN, J_MAX = -NJ, -1
I_MIN, I_MAX = 0, NI - 1

WORLD_X_MIN = GRID_X0
WORLD_X_MAX = GRID_X0 + NI * TILE
WORLD_Z_MIN = GRID_Z0 - NJ * TILE   # north edge (most negative)
WORLD_Z_MAX = GRID_Z0               # south edge (most positive)


def enu(lon, lat):
    """lon/lat degrees -> local ENU meters (x east+, z south+)."""
    return (lon - LON0) * KX, (LAT0 - lat) * KZ


def from_enu(x, z):
    """local ENU meters -> lon/lat degrees (inverse of enu())."""
    return LON0 + x / KX, LAT0 - z / KZ


def ensure_dirs():
    for d in (DATA, DATA_RAW, TILES_DIR, TEX_DIR, PROPS_DIR, META_DIR, CACHE_DIR):
        os.makedirs(d, exist_ok=True)


def mark_done(stage, info=None):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, stage + ".done"), "w") as f:
        json.dump({"done_at": time.time(), "info": info or {}}, f)


def is_done(stage):
    return os.path.exists(os.path.join(CACHE_DIR, stage + ".done"))


def save_npz(path, **arrays):
    np.savez_compressed(path, **arrays)


def load_npz(path):
    return np.load(path, allow_pickle=True)


def unpack_dem(path=None):
    """npz -> plain dict of arrays (NpzFile re-decompresses on EVERY key access,
    which is catastrophic in per-point sampling loops)."""
    d = load_npz(path or os.path.join(DATA_RAW, "dem.npz"))
    return {k: d[k] for k in d.files}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def dem_latlon_grid(lat_min, lat_max, lon_min, lon_max):
    """Uniform deg grid approximating native z14 terrarium resolution."""
    ddeg = 360.0 / (1 << 14) / 256.0  # deg per pixel
    nx = int(math.ceil((lon_max - lon_min) / ddeg)) + 1
    ny = int(math.ceil((lat_max - lat_min) / ddeg)) + 1
    lons = lon_min + ddeg * np.arange(nx)
    lats = lat_max - ddeg * np.arange(ny)  # row 0 = north edge
    return lats, lons, ddeg


def dem_sample(dem, lon, lat):
    """Bilinear sample of dem.npz-style dict (lats, lons, elev) at lon/lat."""
    lats, lons, elev = dem["lats"], dem["lons"], dem["elev"]
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    r = (lats[0] - lat) / (lats[0] - lats[-1]) * (len(lats) - 1)
    c = (lon - lons[0]) / (lons[-1] - lons[0]) * (len(lons) - 1)
    r = np.clip(r, 0, len(lats) - 1.001)
    c = np.clip(c, 0, len(lons) - 1.001)
    r0 = np.minimum(r.astype(np.int64), len(lats) - 2)
    c0 = np.minimum(c.astype(np.int64), len(lons) - 2)
    fr = r - r0
    fc = c - c0
    r1 = r0 + 1
    c1 = c0 + 1
    a = elev[r0, c0] * (1 - fr) + elev[r1, c0] * fr
    b = elev[r0, c1] * (1 - fr) + elev[r1, c1] * fr
    out = a * (1 - fc) + b * fc
    return float(out) if out.ndim == 0 else out


def dem_sample_world(dem, x, z):
    """Sample dem at local ENU meters (arrays or scalars)."""
    lon = LON0 + np.asarray(x, dtype=np.float64) / KX
    lat = LAT0 - np.asarray(z, dtype=np.float64) / KZ
    scalar = np.ndim(lon) == 0
    if scalar:
        return float(dem_sample(dem, float(lon), float(lat)))
    return dem_sample(dem, lon, lat)


def smooth1d(a, k):
    """Simple moving average along axis 0 (box filter, edge-clamped). k odd >= 1."""
    if k <= 1:
        return a
    pad = k // 2
    ap = np.pad(a, ((pad, pad),) + ((0, 0),) * (a.ndim - 1), mode="edge")
    cs = np.cumsum(ap, axis=0)
    out = (cs[k - 1:] - np.concatenate([np.zeros_like(cs[0:1]), cs[:-k]], axis=0)) / k
    return out


# ---- Road classes -----------------------------------------------------------
ROAD_WIDTH = {
    "motorway": 16.0, "motorway_link": 9.0, "trunk": 15.0, "trunk_link": 9.0,
    "primary": 12.0, "primary_link": 8.0, "secondary": 11.0, "secondary_link": 7.0,
    "tertiary": 10.0, "tertiary_link": 6.5, "residential": 8.0,
    "unclassified": 8.0, "living_street": 6.5, "service": 5.0, "pedestrian": 6.0,
    "footway": 2.0, "steps": 2.0, "cycleway": 2.0, "track": 3.0, "road": 8.0,
}
MAJOR_ROADS = {"motorway", "motorway_link", "trunk", "trunk_link", "primary",
               "secondary", "secondary_link", "tertiary"}
SIDEWALK_CLASSES = {"primary", "primary_link", "secondary", "secondary_link",
                    "tertiary", "tertiary_link", "residential", "unclassified",
                    "living_street", "pedestrian", "service"}


def road_width(cls, tags):
    w = ROAD_WIDTH.get(cls, 8.0)
    lanes = tags.get("lanes")
    try:
        if lanes and cls in MAJOR_ROADS | {"residential", "unclassified", "service"}:
            w = max(w, float(str(lanes).split(";")[0]) * 3.2)
    except (ValueError, TypeError):
        pass
    return min(w, 22.0)


def tile_range_for_box(x0, z0, x1, z1):
    """Tile (i,j) index range overlapping an axis-aligned world ENU box."""
    i0 = int(math.floor((min(x0, x1) - GRID_X0) / TILE))
    i1 = int(math.floor((max(x0, x1) - GRID_X0 - 1e-6) / TILE))
    j0 = int(math.floor((max(z0, z1) - GRID_Z0) / TILE))   # larger z -> smaller (more negative) j? no: j = floor((z-grid_z0)/256)
    j1 = int(math.floor((min(z0, z1) - GRID_Z0 - 1e-6) / TILE))
    i0 = max(I_MIN, min(I_MAX, i0)); i1 = max(I_MIN, min(I_MAX, i1))
    j0 = max(J_MIN, min(J_MAX, j0)); j1 = max(J_MIN, min(J_MAX, j1))
    return i0, i1, min(j0, j1), max(j0, j1)


def tiles_of_box(x0, z0, x1, z1):
    i0, i1, j0, j1 = tile_range_for_box(x0, z0, x1, z1)
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


def tile_bbox(i, j):
    """World ENU bbox (x0, z0, x1, z1) of tile (i, j)."""
    x0 = GRID_X0 + i * TILE
    x1 = x0 + TILE
    z0 = GRID_Z0 + j * TILE
    z1 = z0 + TILE
    return x0, z0, x1, z1
