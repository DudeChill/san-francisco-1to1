#!/usr/bin/env python3
"""Verify the baked city: index/tile/lod/texture consistency + elevation spot checks.
Exit 0 on success."""
import json
import os
import sys

import numpy as np

import common as C
from common import load_json, dem_sample_world

fail = []


def check(cond, msg):
    print(("  OK " if cond else "FAIL ") + msg)
    if not cond:
        fail.append(msg)


def main():
    idx_path = os.path.join(C.TILES_DIR, "index.json")
    check(os.path.exists(idx_path), "index.json exists")
    idx = load_json(idx_path)
    tiles = idx["tiles"]
    print(f"index.json: {len(tiles)} tiles, {len(idx['landmarks'])} landmarks, "
          f"{len(idx.get('cable_car_lines', []))} cable lines")

    # every listed tile has gltf+bin+lod1
    missing = []
    for t in tiles:
        i, j = t["i"], t["j"]
        for suffix in (".gltf", ".bin", "_lod1.gltf", "_lod1.bin"):
            p = os.path.join(C.TILES_DIR, f"tile_{i}_{j}{suffix}")
            if not os.path.exists(p) or os.path.getsize(p) < 50:
                missing.append((i, j, suffix))
    check(not missing, f"all {len(tiles)} tiles have .gltf/.bin/_lod1 pair" +
          (f" (missing: {missing[:8]}...)" if missing else ""))

    # props manifests for all tiles
    pmissing = [t for t in tiles if not os.path.exists(
        os.path.join(C.TILES_DIR, f"props_{t['i']}_{t['j']}.json"))]
    check(not pmissing, f"props manifests present ({len(pmissing)} missing)")

    # referenced textures exist
    tex_ref = set()
    for t in tiles:
        p = os.path.join(C.TILES_DIR, f"tile_{t['i']}_{t['j']}.gltf")
        with open(p) as f:
            g = json.load(f)
        for img in g.get("images", []):
            tex_ref.add(img["uri"])
    tex_missing = [u for u in sorted(tex_ref)
                   if not os.path.exists(os.path.join(C.TILES_DIR, u))]
    check(not tex_missing, f"all {len(tex_ref)} referenced textures exist" +
          (f" (missing: {tex_missing})" if tex_missing else ""))

    # prop glbs exist
    for t in tiles:
        pj = load_json(os.path.join(C.TILES_DIR, f"props_{t['i']}_{t['j']}.json"))
        for k in pj:
            if pj[k]:
                check2 = os.path.exists(os.path.join(C.PROPS_DIR, f"{k}.glb"))
                if not check2:
                    fail.append(f"prop glb missing for {k}")
                    break
    print("  OK  prop glbs exist for every used prop type" if not any(
        "prop glb missing" in f for f in fail) else "  FAIL prop glb missing")
    # materials named per contract (spot check)
    bad_mat = []
    spot = tiles[: min(6, len(tiles))]
    for t in spot:
        with open(os.path.join(C.TILES_DIR, f"tile_{t['i']}_{t['j']}.gltf")) as f:
            g = json.load(f)
        for m in g.get("materials", []):
            name = m["name"]
            ok = (name.startswith(("Mat_Terrain", "Mat_Road", "Mat_Sidewalk",
                                   "Mat_Crosswalk", "Mat_Water", "Mat_Facade_",
                                   "Mat_Roof_", "Mat_Prop_", "Mat_Landmark_"))
                  or name == "Mat_Pier")
            if not ok:
                bad_mat.append(name)
    check(not bad_mat, f"material names match contract (checked {len(spot)} tiles)")

    # node names per contract (_col suffix for collision)
    bad_node = []
    for t in spot:
        with open(os.path.join(C.TILES_DIR, f"tile_{t['i']}_{t['j']}.gltf")) as f:
            g = json.load(f)
        for n in g.get("nodes", []):
            nm = n.get("name", "")
            if nm in ("Terrain", "Buildings", "Piers"):
                bad_node.append(nm)   # must be Terrain_col etc
    check(not bad_node, "collision nodes use _col suffix")

    # elevation spot checks
    dem = C.unpack_dem()
    C.dem_cache = dem
    spots = [("Twin Peaks (Noe summit)", -122.44775, 37.75160, 277.0),
             ("Ocean Beach", -122.51250, 37.77500, 4.0),
             ("Bay water (Aquatic Park)", -122.44300, 37.80700, -3.0),
             ("Mount Sutro", -122.45718, 37.75811, 278.0)]
    for name, lon, lat, approx in spots:
        x, z = C.enu(lon, lat)
        y = float(dem_sample_world(dem, np.array([x]), np.array([z]))[0])
        ok = abs(y - approx) < 40.0
        print(f"  {'OK ' if ok else 'FAIL'} {name}: DEM elevation {y:.1f} m (expect ~{approx})")
        if not ok:
            fail.append(f"elevation {name} off: {y:.1f} vs {approx}")

    # spot-check one tile's buildings mesh (downtown: Transamerica tile)
    dt = next((t for t in tiles if t["i"] == 40 and t["j"] == -38), tiles[0])
    i, j = dt["i"], dt["j"]
    with open(os.path.join(C.TILES_DIR, f"tile_{i}_{j}.gltf")) as f:
        g = json.load(f)
        tri_total = 0
        bld_tris = 0
        for m in g["meshes"]:
            n_tris = 0
            for p in m["primitives"]:
                cnt = g["accessors"][p["indices"]]["count"]
                n_tris += cnt // 3
            tri_total += n_tris
            if m["name"] == "Buildings":
                bld_tris = n_tris
        print(f"  spot tile ({i},{j}): total tris {tri_total}, buildings tris {bld_tris}")
        check(0 < tri_total < 2_000_000, "spot tile tri count plausible")
        check(bld_tris >= 150, "spot tile buildings triangles plausible (hundreds-thousands expected)")

    # counts summary
    n_props = 0
    for t in tiles:
        pj = load_json(os.path.join(C.TILES_DIR, f"props_{t['i']}_{t['j']}.json"))
        n_props += sum(len(v) for v in pj.values())
    # city-wide stats from source layer
    import pickle
    with open(os.path.join(C.DATA_RAW, "parsed.pkl"), "rb") as f:
        L = pickle.load(f)
    n_blds = len(L["buildings"])
    road_km = 0.0
    for r in L["roads"]:
        px, pz = C.enu(r["pts"][:, 0], r["pts"][:, 1])
        road_km += float(np.hypot(px[1:] - px[:-1], pz[1:] - pz[:-1]).sum())
    road_km /= 1000.0
    print(f"summary: tiles={len(tiles)} buildings={n_blds} road_km={road_km:.1f} "
          f"props_instances={n_props} textures={len(tex_ref)}")
    if fail:
        print(f"VERIFY FAILED: {len(fail)} problems")
        for f in fail:
            print("   -", f)
        sys.exit(1)
    print("VERIFY OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
