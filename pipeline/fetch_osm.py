"""Fetch OSM feature layers from Overpass API (POST, UA header, mirrors, retries,
bbox-quadrant chunking) -> data_raw/osm/*.json."""
import json
import os
import time
import urllib.request
import urllib.error

from common import (BBOX_LAT_MIN, BBOX_LAT_MAX, BBOX_LON_MIN, BBOX_LON_MAX, DATA_RAW,
                    mark_done, is_done)

UA = "sf-city-builder/0.1 (research)"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OSM_DIR = os.path.join(DATA_RAW, "osm")

LAYERS = {
    # name -> (quadrants, [query clauses per quadrant; {} = single full-bbox query])
    "buildings": (True, [
        'way["building"];relation["building"];',
    ]),
    "roads": (True, [
        'way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|'
        'secondary|secondary_link|tertiary|tertiary_link|residential|unclassified|'
        'living_street|service|pedestrian|footway|steps|cycleway|track|road)$"];',
    ]),
    "water": (False, [
        'way["natural"="water"];relation["natural"="water"];way["waterway"~"^(river|stream|canal)$"];'
        'way["man_made"="pier"];way["landuse"~"^(reservoir|basin)$"];',
    ]),
    "green": (False, [
        'way["leisure"~"^(park|garden|playground|golf_course)$"];'
        'way["landuse"~"^(grass|forest|meadow|cemetery|recreation_ground)$"];',
    ]),
    "points": (False, [
        'node["natural"="tree"];node["highway"="traffic_signals"];'
        'node["highway"="bus_stop"];node["public_transport"="stop_position"];'
        'node["emergency"="fire_hydrant"];node["highway"="street_lamp"];',
    ]),
    "cable": (False, [
        'way["railway"]["name"~"Powell|California Street|Hyde|Mason",i];'
        'way["railway"]["cable_car"];relation["route"="tram"]["name"~"Powell|California"];',
    ]),
}


def overpass_post(query, tries=6):
    last = None
    for attempt in range(tries):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        url = ep + "?data="  # POST body carries the query
        data = query.encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={
                "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=660) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            wait = min(30.0 * (2 ** attempt), 300.0)
            print(f"[osm] attempt {attempt+1} on {ep} failed: {e}; retry in {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"overpass failed after {tries} tries: {last}")


def bbox_str(lat_min, lon_min, lat_max, lon_max):
    # Overpass bbox: (south, west, north, east)
    return f"{lat_min:.6f},{lon_min:.6f},{lat_max:.6f},{lon_max:.6f}"


def full_bbox():
    return (BBOX_LAT_MIN, BBOX_LON_MIN, BBOX_LAT_MAX, BBOX_LON_MAX)


def quadrant_bboxes():
    lat_mid = (BBOX_LAT_MIN + BBOX_LAT_MAX) / 2
    lon_mid = (BBOX_LON_MIN + BBOX_LON_MAX) / 2
    return [
        (BBOX_LAT_MIN, BBOX_LON_MIN, lat_mid, lon_mid),      # SW
        (BBOX_LAT_MIN, lon_mid, lat_mid, BBOX_LON_MAX),      # SE
        (lat_mid, BBOX_LON_MIN, BBOX_LAT_MAX, lon_mid),      # NW
        (lat_mid, lon_mid, BBOX_LAT_MAX, BBOX_LON_MAX),      # NE
    ]


def run_layer(name, quadrants, clauses):
    os.makedirs(OSM_DIR, exist_ok=True)
    if quadrants:
        for qi, (lat0, lon0, lat1, lon1) in enumerate(quadrant_bboxes()):
            out = os.path.join(OSM_DIR, f"{name}_q{qi}.json")
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                print(f"[osm] {name} q{qi} cached")
                continue
            parts = []
            for cl in clauses:
                for clause in cl.split(";"):
                    clause = clause.strip()
                    if not clause:
                        continue
                    parts.append(clause.rstrip(";") + f"({bbox_str(lat0,lon0,lat1,lon1)});")
            q = f"[out:json][timeout:600];({''.join(parts)});out geom;"
            print(f"[osm] fetching {name} q{qi} ...")
            t0 = time.time()
            res = overpass_post(q)
            with open(out, "w") as f:
                json.dump(res, f)
            n = len(res.get("elements", []))
            print(f"[osm] {name} q{qi}: {n} elements in {time.time()-t0:.0f}s -> {out}")
    else:
        out = os.path.join(OSM_DIR, f"{name}.json")
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            print(f"[osm] {name} cached")
            return
        parts = []
        for cl in clauses:
            for clause in cl.split(";"):
                clause = clause.strip()
                if not clause:
                    continue
                s, w, n_, e = full_bbox()
                parts.append(clause.rstrip(";") + f"({bbox_str(s,w,n_,e)});")
        q = f"[out:json][timeout:600];({''.join(parts)});out geom;"
        print(f"[osm] fetching {name} (full bbox) ...")
        t0 = time.time()
        res = overpass_post(q)
        with open(out, "w") as f:
            json.dump(res, f)
        print(f"[osm] {name}: {len(res.get('elements', []))} elements in {time.time()-t0:.0f}s")


def run():
    if is_done("osm"):
        print("[osm] cached")
        return
    order = ["cable", "water", "green", "points", "roads", "buildings"]
    for name in order:
        quadrants, clauses = LAYERS[name]
        run_layer(name, quadrants, clauses)
    mark_done("osm")


if __name__ == "__main__":
    run()
