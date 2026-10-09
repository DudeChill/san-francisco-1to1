#!/usr/bin/env python3
"""Run the full SF city bake: textures -> DEM -> OSM -> parse -> props -> tiles.

Per-stage caches live in data_raw/cache/*.done; re-runs skip completed stages
(delete the .done marker to force). Landmark/index assembly happens after tiles.
"""
import os
import subprocess
import sys
import time

from common import ROOT, DATA, ensure_dirs, is_done, mark_done, load_json, save_json
import common as C

STAGES = ["textures", "dem", "osm", "parse", "props", "tiles", "index"]


def run_stage(name, script):
    if is_done(name):
        print(f"[run_all] {name}: cached, skipping")
        return
    t0 = time.time()
    print(f"[run_all] === {name} ===")
    r = subprocess.run([sys.executable, script], cwd=os.path.dirname(script))
    if r.returncode != 0:
        print(f"[run_all] stage {name} FAILED ({r.returncode})")
        sys.exit(r.returncode)
    mark_done(name)
    print(f"[run_all] {name} done in {time.time()-t0:.1f}s")


def main():
    only = sys.argv[1:] or None
    ensure_dirs()
    P = ROOT + "/pipeline/"
    if only is None or "textures" in only:
        run_stage("textures", P + "textures.py")
    if only is None or "dem" in only:
        run_stage("dem", P + "fetch_dem.py")
    if only is None or "osm" in only:
        run_stage("osm", P + "fetch_osm.py")
    if only is None or "parse" in only:
        run_stage("parse", P + "parse_osm.py")
    if only is None or "props" in only:
        run_stage("props", P + "bake_props.py")
    if only is None or "tiles" in only:
        run_stage("tiles", P + "bake_tiles.py")
    if only is None or "index" in only:
        run_stage("index", P + "build_index.py")
    print("[run_all] complete")


if __name__ == "__main__":
    main()
