"""Parse raw Overpass JSON (out geom) into normalized layers -> data_raw/parsed.pkl.

Layers (coordinates kept in lon/lat; bake converts to ENU):
  buildings: {id, shell (N,2), holes [(M,2)], height}
  roads:     {id, cls, name, pts (N,2)}
  water_polys: {id, shell, holes}   |  waterways: {id, cls, pts}
  piers:     {id, pts, area:bool}
  green:     {id, shell, holes, kind}
  trees / signals / bus_stops / hydrants / lamps: (N,2)
  cable_ways: {name, pts}
"""
import glob
import json
import os
import pickle
import re

import numpy as np
from common import DATA_RAW

OSM_DIR = os.path.join(DATA_RAW, "osm")


def _pts_from_geometry(geom):
    if not geom:
        return None
    return np.array([(g["lon"], g["lat"]) for g in geom], dtype=np.float64)

_M_RE = re.compile(r"([0-9]*\.?[0-9]+)\s*m\b")
_FT_RE = re.compile(r"([0-9]+)'([0-9]*\.?[0-9]*)\"?")

DEFAULT_LEVELS = {
    "house": 2, "houses": 2, "residential": 2, "detached": 2, "semidetached_house": 2,
    "apartments": 3, "terrace": 2, "commercial": 2, "retail": 2, "office": 3,
    "industrial": 1.5, "warehouse": 1.5, "garage": 1, "garages": 1, "shed": 1,
    "hut": 1, "civic": 4, "public": 3, "government": 4, "school": 2, "university": 3,
    "hospital": 4, "hotel": 4, "train_station": 3, "transportation": 2,
    "church": 8, "cathedral": 10, "chapel": 6, "temple": 8, "mosque": 6, "synagogue": 6,
}
LEVEL_H = 3.2


def parse_height(tags):
    h = tags.get("height")
    if h:
        m = _M_RE.search(h.replace(",", "."))
        if m:
            return float(m.group(1)), "height"
        f = _FT_RE.search(h)
        if f:
            return float(f.group(1)) * 0.3048 + (float(f.group(2)) * 0.3048 if f.group(2) else 0.0), "height"
        try:
            return float(h), "height"
        except ValueError:
            pass
    lv = tags.get("building:levels")
    if lv:
        try:
            return max(1, float(lv)) * LEVEL_H, "levels"
        except ValueError:
            pass
    b = tags.get("building")
    base = DEFAULT_LEVELS.get(b, 2)
    if b in ("house", "houses", "residential", "detached", "semidetached_house", "terrace", "garage", "garages", "shed", "hut"):
        return base * LEVEL_H, "default"
    return base * LEVEL_H, "default"


def load_layer(name):
    els = []
    for p in sorted(glob.glob(os.path.join(OSM_DIR, f"{name}*.json"))):
        with open(p) as f:
            els.extend(json.load(f).get("elements", []))
    seen = set()
    out = []
    for e in els:
        k = (e.get("type"), e.get("id"))
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def rings_from_relation(rel):
    """Return list of outer rings (lonlat arrays) from an 'out geom' multipolygon."""
    outers = []
    for m in rel.get("members", []):
        if m.get("role") in ("outer", "") and m.get("geometry"):
            pts = _pts_from_geometry(m["geometry"])
            if pts is not None and len(pts) >= 4:
                outers.append(pts)
    return outers


def run():
    out_path = os.path.join(DATA_RAW, "parsed.pkl")
    layers = {}

    # ---- buildings ----
    blds = []
    for e in load_layer("buildings"):
        tags = e.get("tags", {}) or {}
        h, hsrc = parse_height(tags)
        if h < 2.0:
            continue
        if e["type"] == "way":
            pts = _pts_from_geometry(e.get("geometry"))
            if pts is None or len(pts) < 4:
                continue
            blds.append({"id": e["id"], "shell": pts[:-1] if (pts[0] == pts[-1]).all() else pts,
                         "holes": [], "height": h})
        elif e["type"] == "relation":
            for ring in rings_from_relation(e):
                blds.append({"id": e["id"], "shell": ring[:-1] if (ring[0] == ring[-1]).all() else ring,
                             "holes": [], "height": h})
    layers["buildings"] = blds
    print(f"[parse] buildings: {len(blds)}")

    # ---- roads ----
    roads = []
    for e in load_layer("roads"):
        if e["type"] != "way":
            continue
        tags = e.get("tags", {}) or {}
        cls = tags.get("highway")
        pts = _pts_from_geometry(e.get("geometry"))
        if pts is None or len(pts) < 2:
            continue
        roads.append({"id": e["id"], "cls": cls, "name": tags.get("name", ""),
                      "pts": pts, "layer": float(tags.get("layer", 0) or 0)})
    layers["roads"] = roads
    print(f"[parse] roads: {len(roads)}")

    # ---- water ----
    wpoly, wway, piers = [], [], []
    for e in load_layer("water"):
        tags = e.get("tags", {}) or {}
        if e["type"] == "way" and tags.get("man_made") == "pier":
            pts = _pts_from_geometry(e.get("geometry"))
            if pts is not None and len(pts) >= 2:
                piers.append({"id": e["id"], "pts": pts, "area": pts[0].tolist() == pts[-1].tolist() and len(pts) >= 4})
            continue
        if tags.get("waterway") in ("river", "stream", "canal"):
            pts = _pts_from_geometry(e.get("geometry"))
            if pts is not None and len(pts) >= 2:
                wway.append({"id": e["id"], "cls": tags["waterway"], "pts": pts})
            continue
        if tags.get("natural") == "water" or tags.get("landuse") in ("reservoir", "basin"):
            rings = []
            if e["type"] == "way":
                pts = _pts_from_geometry(e.get("geometry"))
                if pts is not None and len(pts) >= 4:
                    rings = [pts]
            elif e["type"] == "relation":
                rings = [r for r in rings_from_relation(e)]
            for ring in rings:
                wpoly.append({"id": e["id"], "shell": ring, "holes": []})
    layers["water_polys"], layers["waterways"], layers["piers"] = wpoly, wway, piers
    print(f"[parse] water polys {len(wpoly)}, waterways {len(wway)}, piers {len(piers)}")

    # ---- green ----
    green = []
    for e in load_layer("green"):
        tags = e.get("tags", {}) or {}
        rings = []
        if e["type"] == "way":
            pts = _pts_from_geometry(e.get("geometry"))
            if pts is not None and len(pts) >= 4:
                rings = [pts]
        elif e["type"] == "relation":
            rings = rings_from_relation(e)
        for ring in rings:
            green.append({"id": e["id"], "shell": ring, "holes": [],
                          "kind": tags.get("leisure") or tags.get("landuse")})
    layers["green"] = green
    print(f"[parse] green: {len(green)}")

    # ---- points ----
    pts_by = {"tree": [], "traffic_signals": [], "bus_stop": [], "stop_position": [],
              "fire_hydrant": [], "street_lamp": []}
    for e in load_layer("points"):
        if e["type"] != "node":
            continue
        tags = e.get("tags", {}) or {}
        lon, lat = e.get("lon"), e.get("lat")
        if lon is None:
            continue
        if tags.get("natural") == "tree":
            pts_by["tree"].append((lon, lat))
        elif tags.get("highway") == "traffic_signals":
            pts_by["traffic_signals"].append((lon, lat))
        elif tags.get("highway") == "bus_stop":
            pts_by["bus_stop"].append((lon, lat))
        elif tags.get("public_transport") == "stop_position":
            pts_by["stop_position"].append((lon, lat))
        elif tags.get("emergency") == "fire_hydrant":
            pts_by["fire_hydrant"].append((lon, lat))
        elif tags.get("highway") == "street_lamp":
            pts_by["street_lamp"].append((lon, lat))
    for k, v in pts_by.items():
        layers[k if k != "stop_position" else "bus_stops_extra"] = np.array(v, np.float64).reshape(-1, 2)
        print(f"[parse] {k}: {len(v)}")
    layers["bus_stops"] = np.array(pts_by["bus_stop"] + pts_by["stop_position"], np.float64).reshape(-1, 2)

    # ---- cable car ----
    cable = []
    for e in load_layer("cable"):
        tags = e.get("tags", {}) or {}
        if e["type"] == "way":
            pts = _pts_from_geometry(e.get("geometry"))
            if pts is None or len(pts) < 2:
                continue
            name = tags.get("name", "")
            if tags.get("railway") in ("rail", "tram") or "cable" in (tags.get("railway") or ""):
                cable.append({"name": name, "ref": tags.get("ref", ""), "pts": pts})
        elif e["type"] == "relation":
            ref = tags.get("ref", "")
            nm = tags.get("name", "")
            n_seg = 0
            for m in e.get("members", []):
                if m.get("type") == "way" and m.get("geometry"):
                    pts = _pts_from_geometry(m["geometry"])
                    if pts is not None and len(pts) >= 2:
                        cable.append({"name": nm, "ref": ref, "pts": pts})
                        n_seg += 1
            print(f"[parse] cable relation '{nm}' ref={ref}: {n_seg} segments")
    layers["cable_ways"] = cable
    print(f"[parse] cable ways: {len(cable)}")

    with open(out_path, "wb") as f:
        pickle.dump(layers, f)
    print(f"[parse] wrote {out_path}")
    return out_path


if __name__ == "__main__":
    run()
