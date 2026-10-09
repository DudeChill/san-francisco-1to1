"""Assemble data/tiles/index.json from baked tiles: spawn, districts, fog, cable car
lines, landmark list. Runs after tiles stage."""
import glob
import json
import math
import os
import re

import numpy as np

import common as C
from common import (I_MIN, I_MAX, J_MIN, J_MAX, GRID_X0, GRID_Z0, TILE, enu,
                    dem_sample_world, save_json, load_json, mark_done, is_done)
from districts import DISTRICT_POLYS, DEFAULT_DISTRICT, FOG_POLYS
from shapely.geometry import Point, Polygon
import landmarks as LM

FALLBACK_CABLE = {
    "Powell-Hyde": [
        (-122.40900, 37.78280), (-122.40860, 37.78430), (-122.40820, 37.78560),
        (-122.40770, 37.78700), (-122.40720, 37.78850), (-122.40670, 37.78970),
        (-122.40620, 37.79080), (-122.40560, 37.79200), (-122.40540, 37.79320),
        (-122.40530, 37.79400), (-122.40580, 37.79460), (-122.40650, 37.79490),
        (-122.40750, 37.79520), (-122.40860, 37.79580), (-122.40930, 37.79650),
        (-122.40980, 37.79750), (-122.41020, 37.79860), (-122.41050, 37.79990),
        (-122.41070, 37.80130), (-122.41080, 37.80260), (-122.41100, 37.80400),
        (-122.41110, 37.80530), (-122.41100, 37.80650), (-122.41060, 37.80770),
        (-122.41030, 37.80900), (-122.41010, 37.81030), (-122.41020, 37.81150),
        (-122.41070, 37.81230), (-122.41130, 37.81270), (-122.41210, 37.81290),
        (-122.41320, 37.81300), (-122.41430, 37.81310), (-122.41530, 37.81320),
    ],
    "Powell-Mason": [
        (-122.40900, 37.78280), (-122.40860, 37.78430), (-122.40820, 37.78560),
        (-122.40770, 37.78700), (-122.40720, 37.78850), (-122.40670, 37.78970),
        (-122.40620, 37.79080), (-122.40560, 37.79200), (-122.40540, 37.79320),
        (-122.40530, 37.79400), (-122.40580, 37.79460), (-122.40650, 37.79490),
        (-122.40750, 37.79520), (-122.40860, 37.79580), (-122.40930, 37.79650),
        (-122.40980, 37.79750), (-122.41020, 37.79860), (-122.41030, 37.79970),
        (-122.41000, 37.80040), (-122.40940, 37.80090), (-122.40850, 37.80130),
        (-122.40750, 37.80180), (-122.40660, 37.80230), (-122.40570, 37.80290),
        (-122.40490, 37.80350), (-122.40420, 37.80420), (-122.40350, 37.80490),
    ],
    "California Street": [
        (-122.40460, 37.79080), (-122.40560, 37.79070), (-122.40660, 37.79070),
        (-122.40760, 37.79060), (-122.40860, 37.79060), (-122.40960, 37.79060),
        (-122.41060, 37.79060), (-122.41160, 37.79060), (-122.41260, 37.79060),
        (-122.41360, 37.79060), (-122.41460, 37.79060), (-122.41560, 37.79060),
        (-122.41660, 37.79060), (-122.41760, 37.79060), (-122.41860, 37.79060),
        (-122.41960, 37.79060), (-122.42060, 37.79060), (-122.42160, 37.79060),
        (-122.42260, 37.79060), (-122.42360, 37.79060), (-122.42460, 37.79060),
        (-122.42560, 37.79060), (-122.42660, 37.79060),
    ],
}


def district_at(lon, lat):
    for name, poly in DISTRICT_POLYS:
        if Polygon(poly).contains(Point(lon, lat)):
            return name
    return DEFAULT_DISTRICT


def foggy_at(lon, lat):
    for poly in FOG_POLYS:
        if Polygon(poly).contains(Point(lon, lat)):
            return True
    return False


def _join_segments(segs):
    """Greedy endpoint-chained ordering of polyline segments -> one polyline."""
    segs = [np.asarray(s, np.float64) for s in segs]
    used = [False] * len(segs)
    out = [segs[0]]
    used[0] = True
    while not all(used):
        tail = out[-1][-1]
        best_i, best_d, best_rev = None, 1e18, False
        for i, s in enumerate(segs):
            if used[i]:
                continue
            d0 = float(np.hypot(*(tail - s[0])))
            d1 = float(np.hypot(*(tail - s[-1])))
            if d0 < best_d:
                best_i, best_d, best_rev = i, d0, False
            if d1 < best_d:
                best_i, best_d, best_rev = i, d1, True
        if best_i is None:
            break
        s = segs[best_i][::-1] if best_rev else segs[best_i]
        out.append(s)
        used[best_i] = True
        if best_d > 500.0:   # disconnected fragment; stop
            break
    return np.concatenate(out, 0)


def cable_car_lines():
    """OSM cable relations (ref PH/PM/C) joined; fallback hardcoded real routes."""
    import pickle
    out = []
    used = set()
    try:
        with open(os.path.join(C.DATA_RAW, "parsed.pkl"), "rb") as f:
            L = pickle.load(f)
    except FileNotFoundError:
        L = {"cable_ways": []}
    want = {"Powell-Hyde": "PH", "Powell-Mason": "PM", "California Street": "C"}
    for want_name, ref in want.items():
        segs = [w["pts"] for w in L.get("cable_ways", []) if w.get("ref") == ref]
        if not segs:
            continue
        pts = _join_segments(segs)
        px, pz = enu(pts[:, 0], pts[:, 1])
        ys = dem_sample_world(C.dem_cache, px, pz) + 0.5
        out.append({"name": want_name, "points": [
            [float(a), float(b), float(c)] for a, b, c in zip(px, ys, pz)]})
        used.add(want_name)
    for name, poly in FALLBACK_CABLE.items():
        if name in used:
            continue
        pts = np.array(poly)
        px, pz = enu(pts[:, 0], pts[:, 1])
        ys = dem_sample_world(C.dem_cache, px, pz) + 0.5
        out.append({"name": name + " (approx)", "points": [
            [float(a), float(b), float(c)] for a, b, c in zip(px, ys, pz)]})
    return out


def main():
    if not is_done("dem"):
        raise RuntimeError("dem stage required")
    C.dem_cache = C.unpack_dem()
    tiles = []
    for j in range(J_MIN, J_MAX + 1):
        for i in range(I_MIN, I_MAX + 1):
            g = os.path.join(C.TILES_DIR, f"tile_{i}_{j}.gltf")
            if not os.path.exists(g):
                continue
            # tile center district + elevations from DEM corners
            x0, z0, x1, z1 = C.tile_bbox(i, j)
            cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
            lon, lat = C.from_enu(cx, cz)
            gx, gz = np.meshgrid(np.linspace(x0, x1, 3), np.linspace(z0, z1, 3))
            ys = dem_sample_world(C.dem_cache, gx, gz)
            land = ys[ys > 0]
            tiles.append({
                "i": i, "j": j,
                "elev_min": float(ys.min() if land.size else 0.0),
                "elev_max": float(ys.max() if land.size else 0.0),
                "foggy": foggy_at(lon, lat),
                "district": district_at(lon, lat),
            })
    spawn = {"x": 0.0, "y": 0.0, "z": 0.0}
    # spawn at Ferry Building plaza, on terrain
    sx, sz = enu(-122.39260, 37.79560)
    spawn = {"x": float(sx), "y": float(dem_sample_world(C.dem_cache, np.array([sx]), np.array([sz]))[0]), "z": float(sz)}

    landmarks = LM.landmark_index()

    idx = {
        "version": 1,
        "origin_lat": C.LAT0, "origin_lon": C.LON0,
        "tile_size": TILE,
        "grid_x0": GRID_X0, "grid_z0": GRID_Z0,
        "spawn": spawn,
        "tiles": tiles,
        "landmarks": landmarks,
        "cable_car_lines": cable_car_lines(),
    }
    save_json(os.path.join(C.TILES_DIR, "index.json"), idx)
    # diagnostics
    dist_counts = {}
    for t in tiles:
        dist_counts[t["district"]] = dist_counts.get(t["district"], 0) + 1
    diag = {"district_tile_counts": dist_counts, "tiles": len(tiles)}
    save_json(os.path.join(C.META_DIR, "districts.json"), diag)
    print(f"[index] {len(tiles)} tiles; spawn {spawn}; {len(landmarks)} landmarks; "
          f"{len(idx['cable_car_lines'])} cable lines")
    mark_done("index")


if __name__ == "__main__":
    main()
