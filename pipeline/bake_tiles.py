"""Bake city tiles: terrain (real DEM, roads carved), buildings (extruded OSM
footprints, merged per district material), road/sidewalk ribbons, crosswalk decals,
water, piers, landmark slices -> data/tiles/tile_<i>_<j>.gltf/.bin (+ _lod1 pair)
and props_<i>_<j>.json manifests.

Coordinates: tile geometry is LOCAL to tile origin (world - (x0, 0, z0)).
Terrain sampling: C.dem_cache holds the raw DEM; road/sidewalk ribbon heights use a
smoothed DEM profile along the centerline, matching the carve stamp exactly.
"""
import json
import math
import os
import pickle
import sys
import time

import numpy as np
from shapely.geometry import Polygon, Point, LineString, box as sbox
from shapely.strtree import STRtree
from shapely import contains_xy, intersects_xy

import common as C
from common import (TILE, GRID_X0, GRID_Z0, I_MIN, I_MAX, J_MIN, J_MAX,
                    dem_sample_world, enu, save_json, is_done, mark_done,
                    MAJOR_ROADS, SIDEWALK_CLASSES, road_width)
import districts as D
from mesh_util import triangulate_poly, ribbon, prism
from gltf import GltfScene
import landmarks as LM

RES = 8.0          # terrain grid spacing in meters -> 33x33 verts per 256 m tile
CARVE_FEATHER = 2.5
SIDEWALK_OFFSET = 1.9
ROAD_Y = 0.05
SW_Y = 0.15
CW_Y = 0.10
PAD_SINK = 0.10

LAY = None
DEM = None


def get_layers():
    global LAY
    if LAY is None:
        src = os.environ.get("SF_PARSED_PKL", os.path.join(C.DATA_RAW, "parsed.pkl"))
        with open(src, "rb") as f:
            L = pickle.load(f)
        lay = Layers()
        lay.load(L)
        LAY = lay
        print(f"[tiles] spatial index: {len(lay.bld_polys)} buildings, "
              f"{len(lay.road_lines)} roads, {len(lay.wpoly)} water, "
              f"{len(lay.gpoly)} green")
    return LAY


class Layers:
    def load(self, L):
        self.buildings = L["buildings"]
        self.roads = L["roads"]
        self.water_polys = L["water_polys"]
        self.waterways = L["waterways"]
        self.piers = L["piers"]
        self.green = L["green"]
        self.trees = L["tree"]
        self.signals = L["traffic_signals"]
        self.bus_stops = L["bus_stops"]
        self.hydrants = L["fire_hydrant"]
        self.lamps = L["street_lamp"]
        self.cable_ways = L["cable_ways"]
        self.build_spatial()

    def build_spatial(self):
        self.bld_polys = []
        keep = []
        for b in self.buildings:
            poly = Polygon(b["shell"], b["holes"] or None)
            if not poly.is_valid:
                poly = poly.buffer(0)
                if poly.is_empty:
                    continue
                if poly.geom_type == "MultiPolygon":
                    for g in poly.geoms:
                        if g.area * C.KX * C.KZ < 4.0:
                            continue
                        bb = {"id": b["id"], "height": b["height"],
                              "shell": np.asarray(g.exterior.coords)[:-1],
                              "holes": [np.asarray(r.coords)[:-1] for r in g.interiors]}
                        pp = Polygon(bb["shell"], bb["holes"] or None)
                        keep.append(pp)
                        self.bld_polys.append((bb, pp))
                    continue
                b = dict(b)
                b["shell"] = np.asarray(poly.exterior.coords)[:-1]
                b["holes"] = [np.asarray(r.coords)[:-1] for r in poly.interiors]
                poly = Polygon(b["shell"], b["holes"] or None)
            if poly.area * C.KX * C.KZ < 4.0:
                continue
            keep.append(poly)
            self.bld_polys.append((b, poly))
        self.bld_tree = STRtree([p for _, p in self.bld_polys])
        self.bld_objs = [b for b, _ in self.bld_polys]

        self.wpoly = []
        for w in self.water_polys:
            p = Polygon(w["shell"])
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty and p.area * C.KX * C.KZ > 40.0:
                self.wpoly.append(p)
        self.wtree = STRtree(self.wpoly)

        self.gpoly = []
        self.gkind = []
        for g in self.green:
            p = Polygon(g["shell"])
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty and p.area * C.KX * C.KZ > 20.0:
                self.gpoly.append(p)
                self.gkind.append(g.get("kind", ""))
        self.gtree = STRtree(self.gpoly)

        self.road_lines = []
        self.road_meta = []
        for r in self.roads:
            ls = LineString(r["pts"])
            if ls.length * C.KZ < 6.0:
                continue
            self.road_lines.append(ls)
            self.road_meta.append(r)
        self.rtree = STRtree(self.road_lines)

        self.pier_polys = []
        self.pier_lines = []
        for p in self.piers:
            if p["area"]:
                poly = Polygon(p["pts"])
                if poly.is_valid and poly.area * C.KX * C.KZ > 20:
                    self.pier_polys.append(poly)
            else:
                ls = LineString(p["pts"])
                if ls.length * C.KZ > 8.0:
                    self.pier_lines.append(ls)


def district_at(lon, lat):
    from shapely.geometry import Point as SPoint
    pt = SPoint(lon, lat)
    for name, poly in D.DISTRICT_POLYS:
        if Polygon(poly).contains(pt):
            return name
    return D.DEFAULT_DISTRICT


def foggy_at(lon, lat):
    for poly in D.FOG_POLYS:
        if Polygon(poly).contains(Point(lon, lat)):
            return True
    return False


# ============================================================================
# Height profiles (shared by carve + ribbons)
# ============================================================================
def dem_pts(xabs, zabs):
    return dem_sample_world(DEM, xabs, zabs)


def road_profile(pabs):
    """Smoothed DEM elevation along an absolute-ENU polyline (window ~50 m)."""
    if len(pabs) < 2:
        return np.zeros(1)
    ys = dem_pts(pabs[:, 0], pabs[:, 1])
    k = 5 if len(pabs) >= 5 else (len(pabs) if len(pabs) % 2 else len(pabs) - 1)
    return C.smooth1d(ys.reshape(-1, 1), max(k, 1)).ravel()


def resample_poly(pabs, spacing=12.0):
    d = np.concatenate([[0.0], np.cumsum(np.hypot(*(pabs[1:] - pabs[:-1]).T))])
    if d[-1] < 1.0:
        return pabs
    n = max(2, int(d[-1] / spacing) + 2)
    ss = np.linspace(0, d[-1], n)
    xs = np.interp(ss, d, pabs[:, 0])
    zs = np.interp(ss, d, pabs[:, 1])
    return np.stack([xs, zs], 1)


# ============================================================================
# Tile feature gathering
# ============================================================================
def tile_lonlat_bbox(i, j):
    x0, z0, x1, z1 = C.tile_bbox(i, j)
    cs = [C.from_enu(x0, z0), C.from_enu(x1, z0), C.from_enu(x0, z1), C.from_enu(x1, z1)]
    lons = [c[0] for c in cs]
    lats = [c[1] for c in cs]
    return min(lons), min(lats), max(lons), max(lats)


def gather_tile_features(i, j):
    x0, z0, x1, z1 = C.tile_bbox(i, j)
    lay = get_layers()
    lon0, lat0, lon1, lat1 = tile_lonlat_bbox(i, j)
    q = sbox(lon0, lat0, lon1, lat1)
    feats = {}

    # ---- buildings (drop OSM footprints inside landmark suppression zones)
    blds = []
    for k in lay.bld_tree.query(q):
        b = lay.bld_objs[k]
        px, pz = enu(b["shell"][:, 0], b["shell"][:, 1])
        if px.min() > x1 or px.max() < x0 or pz.min() > z1 or pz.max() < z0:
            continue
        if LM.suppressed(px.mean(), pz.mean()):
            continue
        sh = np.stack([px, pz], 1)
        if len(sh) > 40:
            sh = sh[::max(1, len(sh) // 40)]
        ys = dem_pts(sh[:, 0], sh[:, 1])
        blds.append({"shell": sh, "height": float(b["height"]),
                     "dist": district_at(b["shell"][:, 0].mean(), b["shell"][:, 1].mean()),
                     "y0": float(ys.min()) - PAD_SINK,
                     "ytop": float(ys.max()) + float(b["height"])})
    feats["buildings"] = blds

    # ---- roads + sidewalks
    roads, sw = [], []
    for k in lay.rtree.query(q):
        r = lay.road_meta[k]
        if LM.is_lombard(r.get("name", ""), r["pts"]):
            continue   # replaced by landmark switchback geometry
        ls = lay.road_lines[k]
        seg = ls.intersection(q.buffer(0.0008))
        if seg.is_empty:
            continue
        geoms = [seg] if seg.geom_type == "LineString" else (
            list(seg.geoms) if seg.geom_type == "MultiLineString" else [])
        cls = r["cls"]
        wdt = road_width(cls, r.get("tags") or {})
        for g in geoms:
            pts = np.array(g.coords)
            if len(pts) < 2:
                continue
            px, pz = enu(pts[:, 0], pts[:, 1])
            pabs = resample_poly(np.stack([px, pz], 1))
            dlen = np.hypot(*(pabs[-1] - pabs[0]))
            if dlen < 6.0 and cls not in ("footway", "cycleway", "steps"):
                continue
            y = road_profile(pabs)
            if float(y.max()) < 0.3:
                continue   # bridge/causeway over open water: deck handled by landmarks
            roads.append({"pts": pabs, "cls": cls, "width": wdt, "y": y})
            if cls in SIDEWALK_CLASSES and cls not in ("service", "pedestrian"):
                nrm, _ = perp_normals(pabs)
                off = wdt * 0.5 + SIDEWALK_OFFSET
                for s in (1, -1):
                    poff = pabs + nrm * (s * off)
                    sw.append({"pts": poff, "width": 3.2, "y": y + (SW_Y - ROAD_Y)})
    feats["roads"], feats["sidewalks"] = roads, sw

    # Lombard St switchback (landmark road replacement)
    lx0, lz0 = enu(np.array([-122.41885]), np.array([37.80055]))
    if x0 - 40 <= lx0[0] < x0 + TILE + 40 and z0 - 40 <= lz0[0] < z0 + TILE + 40:
        pts, ys = LM.lombard_polyline()
        roads.append({"pts": pts, "cls": "road", "width": 6.0, "y": ys})

    # ---- signals -> crosswalk quads
    cw = []
    sig = np.array(lay.signals, np.float64).reshape(-1, 2)
    for slon, slat in sig:
        sx, sz = enu(np.array([slon]), np.array([slat]))
        if not (x0 - 30 <= sx[0] < x1 + 30 and z0 - 30 <= sz[0] < z1 + 30):
            continue
        best = None
        for k in lay.rtree.query(Point(slon, slat).buffer(0.00020)):
            r = lay.road_meta[k]
            if r["cls"] in ("footway", "steps", "cycleway", "track"):
                continue
            dpx = lay.road_lines[k].distance(Point(slon, slat))
            if best is None or dpx < best[0]:
                best = (dpx, k)
        if best is None or best[0] > 0.00020:
            continue
        ls = lay.road_lines[best[1]]
        r = lay.road_meta[best[1]]
        t = ls.project(Point(slon, slat))
        p_near = np.array(ls.interpolate(t).coords[0])
        nx_, nz_ = enu(np.array([p_near[0]]), np.array([p_near[1]]))
        a0 = ls.interpolate(max(t - 6, 0)).coords[0]
        a1 = ls.interpolate(min(t + 6, ls.length)).coords[0]
        dxl = (a1[0] - a0[0]) * C.KX
        dzl = -(a1[1] - a0[1]) * C.KZ
        dll = math.hypot(dxl, dzl) or 1.0
        dxl /= dll; dzl /= dll
        ax, az = -dzl, dxl
        hw = road_width(r["cls"], r.get("tags") or {}) * 0.5
        y = dem_pts(np.array([nx_[0]]), np.array([nz_[0]]))[0] + CW_Y
        depth = 1.4
        q0 = (nx_[0] + ax * hw + dxl * depth, nz_[0] + az * hw + dzl * depth)
        q1 = (nx_[0] + ax * hw - dxl * depth, nz_[0] + az * hw - dzl * depth)
        q2 = (nx_[0] - ax * hw - dxl * depth, nz_[0] - az * hw - dzl * depth)
        q3 = (nx_[0] - ax * hw + dxl * depth, nz_[0] - az * hw + dzl * depth)
        cw.append((q0, q1, q2, q3, y))
    feats["crosswalks"] = cw

    # ---- water: tidal (DEM < -0.3) as flat quads + inland OSM lakes
    water_lakes = []
    for k in lay.wtree.query(q):
        p = lay.wpoly[k]
        if not p.intersects(q):
            continue
        cx, cy = p.centroid.x, p.centroid.y
        wx, wz = enu(np.array([cx]), np.array([cy]))
        surf = dem_pts(np.array([wx[0]]), np.array([wz[0]]))[0]
        if surf > 0.4:   # inland lake/reservoir above sea level
            px, pz = enu(*np.asarray(p.exterior.coords).T)
            water_lakes.append(np.stack([px, pz], 1))
    feats["water_lakes"] = water_lakes
    feats["has_tidal_water"] = bool((dem_grid_tile(x0, z0, x1, z1) < -0.3).any())

    # ---- waterway ribbons
    ww_parts = []
    for w in lay.waterways:
        ls = LineString(w["pts"])
        if not ls.intersects(q.buffer(0.004)):
            continue
        seg = ls.intersection(q.buffer(0.004))
        gs = [seg] if seg.geom_type == "LineString" else (
            list(seg.geoms) if seg.geom_type == "MultiLineString" else [])
        for g in gs:
            pts = np.array(g.coords)
            if len(pts) < 2:
                continue
            px, pz = enu(pts[:, 0], pts[:, 1])
            wd = 18.0 if w["cls"] == "river" else 5.0
            v, u, t = ribbon(np.stack([px, pz], 1), wd, 0.05, extend=3.0)
            ww_parts.append({"verts": v, "uvs": u, "tris": t})
    feats["waterways"] = ww_parts

    # ---- piers
    pier_parts = []
    for k, p in enumerate(lay.pier_polys):
        if not p.intersects(q):
            continue
        px, pz = enu(*np.asarray(p.exterior.coords).T)
        pier_parts.append({"poly": np.stack([px, pz], 1)})
    for pl in lay.pier_lines:
        if not pl.intersects(q.buffer(0.004)):
            continue
        seg = pl.intersection(q.buffer(0.004))
        gs = [seg] if seg.geom_type == "LineString" else (
            list(seg.geoms) if seg.geom_type == "MultiLineString" else [])
        for g in gs:
            pts = np.array(g.coords)
            if len(pts) < 2:
                continue
            px, pz = enu(pts[:, 0], pts[:, 1])
            pier_parts.append({"line": np.stack([px, pz], 1)})
    feats["piers"] = pier_parts

    # ---- green
    green_parts = []
    for k in lay.gtree.query(q):
        p = lay.gpoly[k]
        if not p.intersects(q):
            continue
        px, pz = enu(*np.asarray(p.exterior.coords).T)
        green_parts.append((np.stack([px, pz], 1), lay.gkind[k]))
    feats["green"] = green_parts

    # ---- props
    def pts_in(arr):
        a = np.array(arr, np.float64).reshape(-1, 2)
        if len(a) == 0:
            return a[:, :0]
        px, pz = enu(a[:, 0], a[:, 1])
        m = (px >= x0 - 20) & (px < x1 + 20) & (pz >= z0 - 20) & (pz < z1 + 20)
        return np.stack([px[m], pz[m]], 1)

    props = {"streetlight": [], "tree": [], "hydrant": [], "bus_stop": []}
    for p in pts_in(lay.trees):
        props["tree"].append([float(p[0]), float(dem_pts(p[0:1], p[1:2])[0]), float(p[1]), 0.0])
    for p in pts_in(lay.lamps):
        props["streetlight"].append([float(p[0]), float(dem_pts(p[0:1], p[1:2])[0]), float(p[1]), 0.0])
    for p in pts_in(lay.hydrants):
        props["hydrant"].append([float(p[0]), float(dem_pts(p[0:1], p[1:2])[0]), float(p[1]), 0.0])
    for p in pts_in(lay.bus_stops):
        props["bus_stop"].append([float(p[0]), float(dem_pts(p[0:1], p[1:2])[0]), float(p[1]), 0.0])
    # streetlights: OSM lamps + generated lamps along arterials (spacing ~72 m)
    n_gen = 0
    for r in roads:
        if r["cls"] not in ("primary", "secondary"):
            continue
        step = 6   # ~72 m with 12 m resampling
        for idx in range(0, len(r["pts"]), step):
            if idx == len(r["pts"]) - 1 or n_gen >= 30:
                break
            p = r["pts"][idx]
            props["streetlight"].append([float(p[0]), float(r["y"][idx] + 0.15),
                                         float(p[1]), 0.0])
            n_gen += 1
    feats["props"] = props
    return feats


def perp_normals(pabs):
    d = pabs[1:] - pabs[:-1]
    n = np.zeros_like(pabs)
    if len(pabs) > 2:
        n[1:-1] = d[:-1] + d[1:]
        n[0] = d[0]; n[-1] = d[-1]
    else:
        n[:] = d[0]
    ln = np.hypot(n[:, 0], n[:, 1])
    ln[ln < 1e-9] = 1.0
    return np.stack([-n[:, 1] / ln, n[:, 0] / ln], 1), d


def dem_grid_tile(x0, z0, x1, z1, n=17):
    xa = np.linspace(x0, x1, n)
    za = np.linspace(z0, z1, n)
    gx, gz = np.meshgrid(xa, za)
    return dem_pts(gx, gz)


# ============================================================================
# Terrain build + carve
# ============================================================================
def terrain_grid(x0, z0, x1, z1, n=None):
    if n is None:
        n = int(round(TILE / RES)) + 1
    xa = np.linspace(x0, x1, n)
    za = np.linspace(z0, z1, n)
    gx, gz = np.meshgrid(xa, za)
    base = dem_pts(gx, gz)
    return xa, za, base


def carve_and_flatten(x0, z0, x1, z1, xa, za, base, feats):
    N = len(xa)
    carved = base.copy()
    # roads
    for r in feats["roads"]:
        if r["cls"] in ("footway", "steps", "cycleway", "track", "pedestrian"):
            continue
        pts = r["pts"]
        ys = r["y"]
        r_m = r["width"] * 0.5 + SIDEWALK_OFFSET + CARVE_FEATHER - 1.2
        for idx in range(len(pts)):
            cx, cz = pts[idx]
            target = ys[idx]
            c0 = max(int((cx - r_m - x0) / (x1 - x0) * (N - 1)), 0)
            c1 = min(int((cx + r_m - x0) / (x1 - x0) * (N - 1)) + 1, N)
            r0 = max(int((cz - r_m - z0) / (z1 - z0) * (N - 1)), 0)
            r1 = min(int((cz + r_m - z0) / (z1 - z0) * (N - 1)) + 1, N)
            if c1 <= c0 or r1 <= r0:
                continue
            gxs = xa[None, c0:c1]
            gzs = za[r0:r1, None]
            d = np.hypot(gxs - cx, gzs - cz)
            mask = d < r_m
            if not mask.any():
                continue
            sub = carved[r0:r1, c0:c1]
            # flat core, feathered edge blending back to terrain
            w = np.clip((r_m - d) / max(CARVE_FEATHER, 0.1), 0, 1)
            sub[mask] = np.minimum(sub[mask], target + (1 - w[mask]) * 1.2)
            carved[r0:r1, c0:c1] = sub
    # building pads: flatten ring around footprints to min terrain, keep hole mask
    holes = np.zeros((N, N), bool)
    for b in feats["buildings"]:
        sh = b["shell"]
        poly = Polygon(sh)
        if not poly.is_valid or poly.is_empty:
            continue
        pad = poly.buffer(3.0)
        if pad.is_empty or pad.geom_type != "Polygon":
            continue
        minx, miny, maxx, maxy = pad.bounds
        c0 = max(int((minx - x0) / (x1 - x0) * (N - 1)), 0)
        c1 = min(int((maxx - x0) / (x1 - x0) * (N - 1)) + 1, N)
        r0 = max(int((miny - z0) / (z1 - z0) * (N - 1)), 0)
        r1 = min(int((maxy - z0) / (z1 - z0) * (N - 1)) + 1, N)
        if c1 <= c0 or r1 <= r0:
            continue
        gxs = xa[None, c0:c1]
        gzs = za[r0:r1, None]
        inside = contains_xy(pad, gxs, gzs)
        hole = contains_xy(poly.buffer(1.5), gxs, gzs)
        holes[r0:r1, c0:c1] |= hole
        if not inside.any():
            continue
        flat = float(b["y0"]) + PAD_SINK
        sub = carved[r0:r1, c0:c1]
        sub[inside] = np.minimum(sub[inside], flat)
        carved[r0:r1, c0:c1] = sub
    return carved, holes


def build_terrain_arrays(x0, z0, xa, za, carved, holes):
    N = int(round(TILE / RES)) + 1
    vid = {}
    verts, uvs, cols, tris = [], [], [], []
    for iz in range(N):
        for ix in range(N):
            if holes[iz, ix]:
                continue
            vid[(ix, iz)] = len(verts)
            verts.append((xa[ix], carved[iz, ix], za[iz]))
            u = ((x0 + xa[ix]) / 24.0) % 1.0
            v = ((z0 + za[iz]) / 24.0) % 1.0
            uvs.append([u, v])
            cols.append([1.0, 1.0, 1.0])
    for iz in range(N - 1):
        for ix in range(N - 1):
            a, b, c2, d = vid.get((ix, iz)), vid.get((ix + 1, iz)), vid.get((ix + 1, iz + 1)), vid.get((ix, iz + 1))
            if a is None or b is None or c2 is None or d is None:
                continue
            tris.append([a, b, c2]); tris.append([a, c2, d])
    verts = np.array(verts, np.float64)
    uvs = np.array(uvs, np.float64)
    cols = np.array(cols, np.float64)
    # quadrant mapping: terrain.png 2x2 -> grass TL, sand TR, dirt BL, scrub BR
    green_mask = np.zeros(len(verts), bool)
    for gparts, kind in _tile_green:
        poly = Polygon(gparts)
        if not poly.is_valid or poly.is_empty:
            continue
        green_mask |= intersects_xy(poly, verts[:, 0], verts[:, 2])
    # sand near tidal shoreline
    sand_mask = np.zeros(len(verts), bool)
    if _tile_has_tidal:
        near = _near_water(verts)
        sand_mask = near & (verts[:, 1] > 0.0) & (verts[:, 1] < 6.0)
    v, u = uvs[:, 1], uvs[:, 0]
    grass = green_mask
    sand = sand_mask & ~grass
    uvs[grass, 0] = u[grass] * 0.5
    uvs[grass, 1] = v[grass] * 0.5
    uvs[sand, 0] = u[sand] * 0.5 + 0.5
    uvs[sand, 1] = v[sand] * 0.5
    rest = ~grass & ~sand
    uvs[rest, 0] = u[rest] * 0.5
    uvs[rest, 1] = v[rest] * 0.5 + 0.5
    cols[grass] = [0.92, 1.0, 0.88]
    cols[sand] = [1.0, 0.96, 0.85]
    return verts, uvs, cols, np.array(tris, np.int64)


_tile_green = []
_tile_has_tidal = False


def _near_water(verts):
    """True where any DEM sample within ±40 m is below sea level (beach zone)."""
    xw = verts[:, 0] + _tile_x0
    zw = verts[:, 2] + _tile_z0
    out = np.zeros(len(verts), bool)
    for dx, dz in ((40, 0), (-40, 0), (0, 40), (0, -40)):
        out |= dem_pts(xw + dx, zw + dz) < 0.0
    return out


_tile_x0 = 0.0
_tile_z0 = 0.0
_holes_to_idx = None


def terrain_normals(verts, tris):
    n = np.zeros_like(verts)
    t = tris
    if len(t) == 0:
        return np.zeros_like(verts)
    v0, v1, v2 = verts[t[:, 0]], verts[t[:, 1]], verts[t[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    for k in range(3):
        np.add.at(n, t[:, k], fn)
    ln = np.hypot(n[:, 0], n[:, 1], n[:, 2])
    ln[ln < 1e-12] = 1.0
    return n / ln[:, None]


# ============================================================================
# Buildings
# ============================================================================
def bake_buildings(blds, x0, z0):
    facade, roof = {}, {}
    FUV = 1.0 / 12.0
    for b in blds:
        sh, h = b["shell"], b["height"]
        y0, ytop = b["y0"], b["ytop"]
        tv = triangulate_poly(sh)
        N = len(sh)
        if N < 3:
            continue
        verts = np.empty((2 * N, 3))
        verts[:N, 0] = sh[:, 0]; verts[:N, 1] = y0; verts[:N, 2] = sh[:, 1]
        verts[N:, 0] = sh[:, 0]; verts[N:, 1] = ytop; verts[N:, 2] = sh[:, 1]
        u = ((x0 + sh[:, 0]) + (z0 + sh[:, 1])) * FUV
        uvs = np.empty((2 * N, 2))
        uvs[:N, 0] = u; uvs[N:, 0] = u
        uvs[:N, 1] = 0.0
        uvs[N:, 1] = ((ytop - y0) * FUV) % 1.0
        tris_wall = []
        for k in range(N):
            j = (k + 1) % N
            tris_wall.append([k, N + k, N + j]); tris_wall.append([k, N + j, j])

        def add(store, key, v, u2, t):
            if key not in store:
                store[key] = {"verts": [], "uvs": [], "tris": [], "n": 0}
            s = store[key]
            s["verts"].append(v); s["uvs"].append(u2); s["tris"].append(np.asarray(t) + s["n"])
            s["n"] += len(v)

        add(facade, f"Mat_Facade_{b['dist']}", verts, uvs, tris_wall)
        if tv is not None:
            rv = np.empty((len(tv[0]), 3))
            rv[:, 0] = tv[0][:, 0]; rv[:, 1] = ytop; rv[:, 2] = tv[0][:, 1]
            ruv = np.stack([tv[0][:, 0] * 0.06, tv[0][:, 1] * 0.06], 1)
            add(roof, f"Mat_Roof_{b['dist']}", rv, ruv, tv[1])
    out = {}
    for store in (facade, roof):
        for key, s in store.items():
            out[key] = {"verts": np.concatenate(s["verts"]), "uvs": np.concatenate(s["uvs"]),
                        "tris": np.concatenate(s["tris"])}
    # facade keys prefix 'Mat_Facade_', roof 'Mat_Roof_'
    return ({k: v for k, v in out.items() if k.startswith("Mat_Facade_")},
            {k: v for k, v in out.items() if k.startswith("Mat_Roof_")})


# ============================================================================
# Water / piers
# ============================================================================
def tidal_water_quads(x0, z0, x1, z1):
    """Flat quads at y=0 where DEM < -0.3 (bay + ocean). Row-strip merged."""
    n = 25
    xa = np.linspace(x0, x1, n)
    za = np.linspace(z0, z1, n)
    gx, gz = np.meshgrid(xa, za)
    ys = dem_pts(gx, gz)
    mask = ys < -0.3
    verts, tris = [], []
    cw = (x1 - x0) / (n - 1)
    ch = (z1 - z0) / (n - 1)
    for iz in range(n - 1):
        ix = 0
        while ix < n - 1:
            if mask[iz, ix] and mask[iz, ix + 1]:
                ix2 = ix + 1
                while ix2 + 1 < n - 1 and mask[iz, ix2 + 1]:
                    ix2 += 1
                base = len(verts)
                verts.append((xa[ix], 0.02, za[iz]))
                verts.append((xa[ix2] + cw, 0.02, za[iz]))
                verts.append((xa[ix2] + cw, 0.02, za[iz + 1] + ch))
                verts.append((xa[ix], 0.02, za[iz + 1] + ch))
                tris.append([base, base + 1, base + 2]); tris.append([base, base + 2, base + 3])
                ix = ix2 + 1
            else:
                ix += 1
    if not verts:
        return None
    return np.array(verts), np.array(tris, np.int64)


def bake_water(feats, x0, z0):
    groups = []
    tq = tidal_water_quads(x0, z0, x1 := x0 + TILE, z1 := z0 + TILE)
    if tq is not None:
        v, t = tq
        uvs = np.stack([v[:, 0] * 0.02, v[:, 2] * 0.02], 1)
        groups.append({"verts": v, "uvs": uvs, "tris": t})
    for wp in feats["waterways"]:
        groups.append(wp)
    for poly in feats["water_lakes"]:
        tv = triangulate_poly(poly)
        if tv is None:
            continue
        ys = dem_pts(tv[0][:, 0], tv[0][:, 1])
        surf = float(ys.min()) - 0.25
        v = np.empty((len(tv[0]), 3))
        v[:, 0] = tv[0][:, 0]; v[:, 1] = surf; v[:, 2] = tv[0][:, 1]
        uvs = np.stack([tv[0][:, 0] * 0.02, tv[0][:, 1] * 0.02], 1)
        groups.append({"verts": v, "uvs": uvs, "tris": tv[1]})
    return groups


def bake_piers(feats, x0, z0):
    groups = []
    for p in feats["piers"]:
        if "poly" in p:
            poly = p["poly"]
            tv = triangulate_poly(poly)
            if tv is None:
                continue
            ys = dem_pts(tv[0][:, 0], tv[0][:, 1])
            deck = float(np.clip(ys.min() + 2.0, 3.0, 6.0))
            v = np.empty((len(tv[0]), 3))
            v[:, 0] = tv[0][:, 0]; v[:, 1] = deck; v[:, 2] = tv[0][:, 1]
            uvs = np.stack([tv[0][:, 0] * 0.05, tv[0][:, 1] * 0.05], 1)
            groups.append({"verts": v, "uvs": uvs, "tris": tv[1]})
            # skirt down to water
            ring = poly
            N = len(ring)
            sv = np.empty((2 * N, 3))
            sv[:N, 0] = ring[:, 0]; sv[:N, 1] = deck; sv[:N, 2] = ring[:, 1]
            sv[N:, 0] = ring[:, 0]; sv[N:, 1] = 0.0; sv[N:, 2] = ring[:, 1]
            st = []
            for k in range(N):
                j = (k + 1) % N
                st.append([k, N + k, N + j]); st.append([k, N + j, j])
            groups.append({"verts": sv, "uvs": np.zeros((2 * N, 2)),
                           "tris": np.array(st, np.int64)})
        else:
            v, u, t = ribbon(p["line"], 8.0, 4.2, extend=1.5)
            groups.append({"verts": v, "uvs": u, "tris": t})
    return groups


# ============================================================================
# Per-tile driver
# ============================================================================
def tile_stats(i, j):
    """DEM stats + feature presence to decide bake/skip."""
    x0, z0, x1, z1 = C.tile_bbox(i, j)
    ys = dem_grid_tile(x0, z0, x1, z1, 9)
    lon0, lat0, lon1, lat1 = tile_lonlat_bbox(i, j)
    q = sbox(lon0, lat0, lon1, lat1)
    lay = get_layers()
    n_feat = (len(lay.bld_tree.query(q)) + len(lay.rtree.query(q)) +
              len(lay.wtree.query(q)) + len(lay.gtree.query(q)) + len(lay.pier_polys))
    return ys, n_feat


def process_tile(i, j):
    x0, z0, x1, z1 = C.tile_bbox(i, j)
    global _tile_green, _tile_has_tidal, _tile_x0, _tile_z0
    _tile_x0, _tile_z0 = x0, z0
    feats = gather_tile_features(i, j)
    _tile_green = feats["green"]
    _tile_has_tidal = feats["has_tidal_water"]

    xa, za, base = terrain_grid(x0, z0, x1, z1)
    carved, holes = carve_and_flatten(x0, z0, x1, z1, xa, za, base, feats)

    ymax = float(carved.max())
    ymin = float(carved.min())
    water_only = ymax < -0.3 and feats["has_tidal_water"] and not feats["buildings"] \
        and not feats["piers"] and not feats["roads"]
    if water_only:
        verts, uvs, cols, tris = None, None, None, None
    else:
        verts, uvs, cols, tris = build_terrain_arrays(x0, z0, xa, za, carved, holes)

    scene = GltfScene()
    local = np.array([x0, 0.0, z0])

    if verts is not None and len(tris):
        m_terrain = scene.material("Mat_Terrain", base_tex="tex/terrain.png", roughness=1.0)
        mi = scene.new_mesh("Terrain")
        scene.add_prim(mi, verts - local, tris, m_terrain,
                       normals=terrain_normals(verts, tris), uvs=uvs, colors=cols)
        scene.add_node("Terrain_col", mi)

    # buildings
    facade_groups, roof_groups = bake_buildings(feats["buildings"], x0, z0)
    tri_b = 0
    if facade_groups or roof_groups:
        bmesh = scene.new_mesh("Buildings")
        for key in sorted(facade_groups):
            dist = key.replace("Mat_Facade_", "")
            g = facade_groups[key]
            mi_f = scene.material(key, base_tex=f"tex/facade_{dist}_albedo.png",
                                  emissive_tex=f"tex/facade_{dist}_emissive.png",
                                  emissive_factor=[1.0, 1.0, 1.0], roughness=0.85)
            # uvs already worldspace-wrapped (bake_buildings); keep as-is
            scene.add_prim(bmesh, g["verts"] - local, g["tris"], mi_f, uvs=g["uvs"])
            tri_b += len(g["tris"])
        for key in sorted(roof_groups):
            g = roof_groups[key]
            dist = key.replace("Mat_Roof_", "")
            mi_r = scene.material(key, base_color=D.DISTRICT_ROOF_TINT.get(dist, [0.5, 0.47, 0.44]),
                                  base_tex="tex/roof.png", roughness=1.0)
            scene.add_prim(bmesh, g["verts"] - local, g["tris"], mi_r, uvs=g["uvs"])
            tri_b += len(g["tris"])
        scene.add_node("Buildings_col", bmesh)

    # roads
    if feats["roads"]:
        verts_r, uvs_r, tris_r = [], [], []
        base_n = 0
        for r in feats["roads"]:
            v, u, t = ribbon(r["pts"], r["width"], r["y"] + ROAD_Y, extend=2.0)
            verts_r.append(v); uvs_r.append(u); tris_r.append(t + base_n)
            base_n += len(v)
        m_road = scene.material("Mat_Road", base_tex="tex/road.png", roughness=0.95)
        mi = scene.new_mesh("Roads")
        verts_r = np.concatenate(verts_r); uvs_r = np.concatenate(uvs_r)
        tris_r = np.concatenate(tris_r)
        scene.add_prim(mi, verts_r - local, tris_r, m_road, normals=terrain_normals(verts_r, tris_r), uvs=uvs_r)
        scene.add_node("Roads", mi)

    # sidewalks
    if feats["sidewalks"]:
        verts_s, uvs_s, tris_s = [], [], []
        base_n = 0
        for s in feats["sidewalks"]:
            v, u, t = ribbon(s["pts"], s["width"], s["y"], extend=1.2)
            verts_s.append(v); uvs_s.append(u); tris_s.append(t + base_n)
            base_n += len(v)
        m_sw = scene.material("Mat_Sidewalk", base_tex="tex/sidewalk.png", roughness=1.0)
        mi = scene.new_mesh("Sidewalks")
        verts_s = np.concatenate(verts_s); uvs_s = np.concatenate(uvs_s)
        tris_s = np.concatenate(tris_s)
        scene.add_prim(mi, verts_s - local, tris_s, m_sw, normals=terrain_normals(verts_s, tris_s), uvs=uvs_s)
        scene.add_node("Sidewalks", mi)

    # crosswalks
    if feats["crosswalks"]:
        verts_c, uvs_c, tris_c = [], [], []
        base_n = 0
        for q4 in feats["crosswalks"]:
            (q0, q1, q2, q3), y = q4[:-1], q4[-1]
            v = np.array([[q0[0], y, q0[1]], [q1[0], y, q1[1]],
                          [q2[0], y, q2[1]], [q3[0], y, q3[1]]])
            u = np.array([[0, 0], [1, 0], [1, 1], [0, 1]])
            t = np.array([[0, 1, 2], [0, 2, 3]]) + base_n
            verts_c.append(v); uvs_c.append(u); tris_c.append(t)
            base_n += 4
        m_cw = scene.material("Mat_Crosswalk", base_tex="tex/crosswalk.png", roughness=0.9,
                              alpha_mode="BLEND", double_sided=True)
        mi = scene.new_mesh("Crosswalks")
        scene.add_prim(mi, np.concatenate(verts_c) - local, np.concatenate(tris_c), m_cw,
                       uvs=np.concatenate(uvs_c))
        scene.add_node("Crosswalks", mi)

    # water
    water_groups = bake_water(feats, x0, z0) if (feats["has_tidal_water"] or
                                                 feats["water_lakes"] or feats["waterways"]) else []
    if water_groups:
        m_w = scene.material("Mat_Water", base_color=[0.10, 0.22, 0.30], roughness=0.25)
        mi = scene.new_mesh("Water")
        for g in water_groups:
            if "uvs" not in g:
                g["uvs"] = np.zeros((len(g["verts"]), 2))
            scene.add_prim(mi, g["verts"] - local, g["tris"], m_w, uvs=g["uvs"])
        scene.add_node("Water", mi)

    # piers
    pier_groups = bake_piers(feats, x0, z0)
    if pier_groups:
        m_p = scene.material("Mat_Sidewalk", base_tex="tex/sidewalk.png", roughness=1.0)
        mi = scene.new_mesh("Piers")
        for g in pier_groups:
            scene.add_prim(mi, g["verts"] - local, g["tris"], m_p, uvs=g["uvs"])
        scene.add_node("Piers_col", mi)

    # landmark geometry overlapping this tile
    LM.bake_into_tile(scene, i, j, x0, z0)

    gltf_path = os.path.join(C.TILES_DIR, f"tile_{i}_{j}.gltf")
    scene.save(gltf_path, gltf_path.replace(".gltf", ".bin"))
    save_json(os.path.join(C.TILES_DIR, f"props_{i}_{j}.json"), feats["props"])
    bake_lod1(i, j, x0, z0, xa, za, carved, feats)

    return {"tri": (len(tris) if tris is not None else 0) + tri_b, "blds": len(feats["buildings"]),
            "roads": len(feats["roads"]), "elev_min": ymin, "elev_max": ymax,
            "water_only": water_only}


def bake_lod1(i, j, x0, z0, xa, za, carved, feats):
    scene = GltfScene()
    local = np.array([x0, 0.0, z0])
    step = 4
    water_only = float(carved.max()) < -0.3 and not feats["buildings"] \
        and not feats["roads"] and not feats["piers"]
    xs = xa[::step]; zs = za[::step]
    ys = carved[::step, ::step]
    if water_only:
        # far LOD of a water tile: single flat water quad
        v = np.array([[0, 0.02, 0], [TILE, 0.02, 0], [TILE, 0.02, TILE], [0, 0.02, TILE]])
        t = np.array([[0, 1, 2], [0, 2, 3]])
        m_w = scene.material("Mat_Water", base_color=[0.10, 0.22, 0.30], roughness=0.25)
        mi = scene.new_mesh("Water")
        scene.add_prim(mi, v, t, m_w)
        scene.add_node("Water", mi)
        path = os.path.join(C.TILES_DIR, f"tile_{i}_{j}_lod1.gltf")
        scene.save(path, path.replace(".gltf", ".bin"))
        return
    gx, gz = np.meshgrid(xs, zs)
    verts = np.stack([gx.ravel(), ys.ravel(), gz.ravel()], 1)
    nx = len(xs)
    tris = []
    for iz in range(len(zs) - 1):
        for ix in range(nx - 1):
            a = iz * nx + ix
            tris.append([a, a + 1, a + nx + 1]); tris.append([a, a + nx + 1, a + nx])
    tris = np.array(tris, np.int64)
    # district tint by elevation
    t = np.clip((ys - 0.0) / 280.0, 0, 1)
    colv = np.stack([0.45 + 0.25 * t, 0.52 - 0.18 * t, 0.36 - 0.10 * t], -1).reshape(-1, 3)
    m = scene.material("Mat_Lod1_Terrain", base_color=[1, 1, 1], roughness=1.0)
    mi = scene.new_mesh("Terrain")
    scene.add_prim(mi, verts - local, tris, m, colors=colv)
    scene.add_node("Terrain_col", mi)

    groups = {}
    for b in feats["buildings"]:
        key = b["dist"]
        v, t2 = prism(b["shell"], b["y0"], b["ytop"])
        g = groups.setdefault(key, {"v": [], "t": [], "n": 0})
        g["v"].append(v); g["t"].append(t2 + g["n"]); g["n"] += len(v)
    if groups:
        bm = scene.new_mesh("Buildings")
        for key, g in groups.items():
            v = np.concatenate(g["v"])
            tint = np.array(D.DISTRICT_ROOF_TINT.get(key, [0.5, 0.45, 0.4]))
            cols = np.repeat(tint[None, :], len(v), 0)
            mk = scene.material(f"Mat_Roof_{key}", base_color=tint)
            scene.add_prim(bm, v - local, np.concatenate(g["t"]), mk, colors=cols)
        scene.add_node("Buildings_col", bm)

    major = [r for r in feats["roads"] if r["cls"] in MAJOR_ROADS]
    if major:
        verts_r, uvs_r, tris_r = [], [], []
        base_n = 0
        for r in major:
            v, u, t2 = ribbon(r["pts"], r["width"], r["y"] + ROAD_Y, extend=2.0)
            verts_r.append(v); uvs_r.append(u); tris_r.append(t2 + base_n)
            base_n += len(v)
        m_r = scene.material("Mat_Road", base_tex="tex/road.png", roughness=0.95)
        mi = scene.new_mesh("Roads")
        scene.add_prim(mi, np.concatenate(verts_r) - local, np.concatenate(tris_r), m_r,
                       uvs=np.concatenate(uvs_r))
        scene.add_node("Roads", mi)

    # landmark silhouette boxes for skyline continuity
    for name, bx, bz, hw, hd, y0, y1 in LM.LOD_BOXES:
        if not (x0 - 60 <= bx < x0 + TILE + 60 and z0 - 60 <= bz < z0 + TILE + 60):
            continue
        v = np.array([[bx - hw, y0, bz - hd], [bx + hw, y0, bz - hd], [bx + hw, y0, bz + hd],
                      [bx - hw, y0, bz + hd], [bx - hw, y1, bz - hd], [bx + hw, y1, bz - hd],
                      [bx + hw, y1, bz + hd], [bx - hw, y1, bz + hd]])
        tris_b = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                           [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
        mk = scene.material("Mat_Lod1_Landmark", base_color=[0.30, 0.31, 0.34])
        mi = scene.new_mesh(f"Landmark_{name}_box")
        scene.add_prim(mi, v - local, tris_b, mk)
        scene.add_node(f"Landmark_{name}_box", mi)

    path = os.path.join(C.TILES_DIR, f"tile_{i}_{j}_lod1.gltf")
    scene.save(path, path.replace(".gltf", ".bin"))


def should_bake(i, j):
    ys, n_feat = tile_stats(i, j)
    has_water = bool((ys < -0.3).any())
    has_land = bool((ys > 0.2).any())
    if n_feat == 0 and not has_water and not has_land:
        return False
    # deep-ocean tiles with zero features are skipped (empty ocean far out)
    if ys.max() < -25.0 and n_feat == 0:
        return False
    return True


def run_range(i0, j0, i1, j1):
    global DEM
    DEM = C.unpack_dem()
    C.dem_cache = DEM
    LM.load()
    get_layers()
    stats = {"tiles": 0, "tri": 0, "blds": 0, "roads": 0, "water_only": 0}
    t0 = time.time()
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            if not should_bake(i, j):
                continue
            s = process_tile(i, j)
            stats["tiles"] += 1
            stats["tri"] += s["tri"]
            stats["blds"] += s["blds"]
            stats["roads"] += s["roads"]
            stats["water_only"] += int(s["water_only"])
        print(f"[tiles] j={j} done tiles={stats['tiles']} "
              f"({time.time() - t0:.0f}s elapsed)", flush=True)
    mark_done("tiles", stats)
    print(f"[tiles] baked {stats['tiles']} tiles ({stats['water_only']} water-only), "
          f"{stats['blds']} buildings, {stats['roads']} road segs in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    a = [int(v) for v in sys.argv[1:5]]
    if len(a) == 4:
        run_range(a[0], a[1], a[2], a[3])
    else:
        run_range(I_MIN, J_MIN, I_MAX, J_MAX)