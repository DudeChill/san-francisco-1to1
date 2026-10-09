"""Procedural landmark meshes with real dimensions.

Bridges (Golden Gate, Bay Bridge) are built once in world coords and sliced into
overlapping tiles. Simple landmarks are triangle-split into the tiles they overlap.
Node naming per contract: root-level mesh nodes "Landmark_<Name>[_<Part>]" with
"_col" suffix on solid walkable parts (e.g. Landmark_GGB_Deck_col).

Also provides: building suppression zones (OSM footprints replaced by landmarks),
Lombard St switchback road replacement, LOD1 silhouette boxes.
"""
import math
import os

import numpy as np
from shapely.geometry import Polygon, Point

import common as C
from common import enu, TILE, mark_done, is_done
from mesh_util import (box, cylinder, dome, prism, tube_along, parabola_cable,
                       triangulate_poly, ribbon, part)
from gltf import GltfScene

INTL_ORANGE = [0.753, 0.212, 0.173]   # #C0362C
CABLE_STEEL = [0.72, 0.73, 0.75]
DECK_GRAY = [0.35, 0.36, 0.38]
TOWER_WHITE = [0.86, 0.86, 0.87]

# ---------------------------------------------------------------------------
# Golden Gate Bridge: main span 1280 m, towers 227 m, deck clearance 67 m,
# total 2737 m incl approaches. Fort Point (SF) to Marin across the strait.
# ---------------------------------------------------------------------------
def build_ggb():
    x0t, z0t = enu(-122.47670, 37.81000)   # SF-side tower
    x1t, z1t = enu(-122.47830, 37.81990)   # Marin-side tower
    axis = np.array([x1t - x0t, z1t - z0t])
    axis = axis / np.hypot(*axis)
    perp = np.array([-axis[1], axis[0]])
    cx = (x0t + x1t) / 2.0
    cz = (z0t + z1t) / 2.0
    MAIN = 1280.0
    TOWER_H = 227.0
    DECK_Y = 67.0
    DECK_W = 27.0
    P = []

    def tpos(off):
        return cx + axis[0] * off, cz + axis[1] * off

    # towers: two legs + cross braces above deck
    for off in (-MAIN / 2, MAIN / 2):
        tx, tz = tpos(off)
        for s in (-1, 1):
            lx = tx + perp[0] * s * (DECK_W * 0.5 - 1.5)
            lz = tz + perp[1] * s * (DECK_W * 0.5 - 1.5)
            v, t = box(lx, -10.0, lz, 10.0, TOWER_H + 10.0, 10.0)
            P.append(part("GGB_Tower", "Mat_Landmark_GGB", INTL_ORANGE, v, t, col=True))
        for hy in (0.10, 0.40, 0.68, 0.88):
            y = TOWER_H * hy
            v, t = box(tx, y - 3.0, tz, DECK_W + 4.0, 6.0, 12.0)
            P.append(part("GGB_Tower", "Mat_Landmark_GGB", INTL_ORANGE, v, t))

    # deck: roadway slab + truss, from Fort Point approach to Marin approach
    deck_len = MAIN + 460.0
    ss = np.linspace(-deck_len / 2, deck_len / 2, 150)
    deck_pts = np.stack([cx + axis[0] * ss, cz + axis[1] * ss], 1)
    v, u, t = ribbon(deck_pts, DECK_W, DECK_Y + 7.0)
    P.append(part("GGB_Deck", "Mat_Landmark_GGB_Deck", DECK_GRAY, v, t, col=True))
    for s in (-1, 1):
        tp = deck_pts + perp * s * (DECK_W * 0.5)
        v, u, t = ribbon(tp, 2.0, DECK_Y)
        P.append(part("GGB_Truss", "Mat_Landmark_GGB_Deck", DECK_GRAY, v, t))
        rp = deck_pts + perp * s * (DECK_W * 0.5 - 0.4)
        v, u, t = ribbon(rp, 0.5, DECK_Y + 8.8)
        P.append(part("GGB_Railing", "Mat_Landmark_GGB", INTL_ORANGE, v, t))

    # main cables (two sides): anchorage -> tower -> mid -> tower -> anchorage
    for s in (-1, 1):
        sx = perp[0] * s * (DECK_W * 0.5 - 1.5)
        sz = perp[1] * s * (DECK_W * 0.5 - 1.5)
        tw0 = np.array([cx + axis[0] * (-MAIN / 2) + sx, TOWER_H, cz + axis[1] * (-MAIN / 2) + sz])
        tw1 = np.array([cx + axis[0] * (MAIN / 2) + sx, TOWER_H, cz + axis[1] * (MAIN / 2) + sz])
        mid = DECK_Y + 8.0
        a0 = np.array([cx + axis[0] * (-MAIN / 2 - 230) + sx, DECK_Y + 9.0,
                       cz + axis[1] * (-MAIN / 2 - 230) + sz])
        a1 = np.array([cx + axis[0] * (MAIN / 2 + 230) + sx, DECK_Y + 9.0,
                       cz + axis[1] * (MAIN / 2 + 230) + sz])
        pts = np.concatenate([parabola_cable(a0, tw0, DECK_Y + 6, 14),
                              parabola_cable(tw0, tw1, mid, 48),
                              parabola_cable(tw1, a1, DECK_Y + 6, 14)], 0)
        v, t = tube_along(pts, 0.9, nside=6)
        P.append(part("GGB_Cable", "Mat_Landmark_GGB", CABLE_STEEL, v, t))
        for k in range(0, len(pts), 9):
            p = pts[k]
            along = (p[0] - cx) * axis[0] + (p[2] - cz) * axis[1]
            if p[1] > DECK_Y + 8.3 and abs(along) < MAIN / 2:
                v, t = box(p[0], DECK_Y + 7.0, p[2], 0.55, p[1] - DECK_Y - 7.0, 0.55)
                P.append(part("GGB_Suspender", "Mat_Landmark_GGB", CABLE_STEEL, v, t))

    # anchorages + Fort Point arch
    for off in (-MAIN / 2 - 240, MAIN / 2 + 240):
        ax, az = tpos(off)
        v, t = box(ax, 0.0, az, 30.0, 42.0, 30.0)
        P.append(part("GGB_Anchorage", "Mat_Landmark_GGB_Deck", DECK_GRAY, v, t, col=True))
    fx, fz = tpos(-MAIN / 2 - 180)
    v, t = box(fx, DECK_Y - 18.0, fz, 80.0, 4.0, DECK_W + 12.0)
    P.append(part("GGB_FortPointArch", "Mat_Landmark_GGB", INTL_ORANGE, v, t))
    return P


# ---------------------------------------------------------------------------
# Bay Bridge west span (SF <-> Yerba Buena Island), towers ~152 m, deck ~58 m
# ---------------------------------------------------------------------------
def build_bay_bridge():
    x0, z0 = enu(-122.37780, 37.79050)   # SF anchorage
    x1, z1 = enu(-122.36700, 37.81520)   # Yerba Buena Island
    axis = np.array([x1 - x0, z1 - z0])
    L = np.hypot(*axis)
    axis /= L
    perp = np.array([-axis[1], axis[0]])
    DECK_Y = 58.0
    TOWER_H = 152.0
    DECK_W = 24.0
    P = []
    for frac in (0.28, 0.74):
        cx = x0 + axis[0] * L * frac
        cz = z0 + axis[1] * L * frac
        for s in (-1, 1):
            v, t = box(cx + perp[0] * s * (DECK_W * 0.5), 0.0,
                       cz + perp[1] * s * (DECK_W * 0.5), 8.0, TOWER_H, 8.0)
            P.append(part("BayBridge_Tower", "Mat_Landmark_BayBridge", TOWER_WHITE, v, t, col=True))
        v, t = box(cx, TOWER_H - 8.0, cz, DECK_W + 8.0, 8.0, 10.0)
        P.append(part("BayBridge_Tower", "Mat_Landmark_BayBridge", TOWER_WHITE, v, t))
    ss = np.linspace(-100, L + 100, 90)
    deck_pts = np.stack([x0 + axis[0] * ss, z0 + axis[1] * ss], 1)
    v, u, t = ribbon(deck_pts, DECK_W, DECK_Y)
    P.append(part("BayBridge_Deck", "Mat_Landmark_BayBridge", DECK_GRAY, v, t, col=True))
    for s in (-1, 1):
        side = perp * s * (DECK_W * 0.5 - 1.0)
        p_start = np.array([x0 + side[0], DECK_Y + 70.0, z0 + side[1]])
        tw1 = np.array([x0 + axis[0] * L * 0.28 + side[0], TOWER_H, z0 + axis[1] * L * 0.28 + side[1]])
        mid = np.array([x0 + axis[0] * L * 0.50 + side[0], DECK_Y + 6.0, z0 + axis[1] * L * 0.50 + side[1]])
        tw2 = np.array([x0 + axis[0] * L * 0.74 + side[0], TOWER_H, z0 + axis[1] * L * 0.74 + side[1]])
        p_end = np.array([x0 + axis[0] * (L + 80) + side[0], DECK_Y + 5.0,
                          z0 + axis[1] * (L + 80) + side[1]])
        pts = np.concatenate([parabola_cable(p_start, tw1, DECK_Y + 4, 14),
                              parabola_cable(tw1, mid, DECK_Y + 5, 22),
                              parabola_cable(mid, tw2, DECK_Y + 5, 22),
                              parabola_cable(tw2, p_end, DECK_Y + 4, 14)], 0)
        v, t = tube_along(pts, 0.8, nside=6)
        P.append(part("BayBridge_Cable", "Mat_Landmark_BayBridge", CABLE_STEEL, v, t))
    return P


# ---------------------------------------------------------------------------
# Simple landmarks (local coords, centered at origin, +Y up)
# ---------------------------------------------------------------------------
PAINTED_LADY_COLORS = [
    [0.80, 0.55, 0.55], [0.85, 0.78, 0.55], [0.65, 0.78, 0.85],
    [0.80, 0.62, 0.72], [0.85, 0.70, 0.50], [0.62, 0.76, 0.66],
]


def _salesforce_tower():
    P = []
    H, base = 326.0, 62.0
    nseg = 10
    ang = np.linspace(0, 2 * np.pi, 8, endpoint=False)
    for k in range(nseg):
        y0, y1 = k * H / nseg, (k + 1) * H / nseg
        s0 = base * (1 - 0.011 * k)
        s1 = base * (1 - 0.011 * (k + 1))
        ring0 = np.stack([s0 / 2 * np.cos(ang), s0 / 2 * np.sin(ang)], 1)
        ring1 = np.stack([s1 / 2 * np.cos(ang), s1 / 2 * np.sin(ang)], 1)
        N = 8
        verts = np.empty((2 * N, 3))
        verts[:N, 0] = ring0[:, 0]; verts[:N, 2] = ring0[:, 1]; verts[:N, 1] = y0
        verts[N:, 0] = ring1[:, 0]; verts[N:, 2] = ring1[:, 1]; verts[N:, 1] = y1
        tris = []
        for a in range(N):
            b2 = (a + 1) % N
            tris.append([a, N + a, N + b2]); tris.append([a, N + b2, b2])
        P.append(part("Salesforce_Tower", "Mat_Landmark_Salesforce",
                      [0.42, 0.52, 0.60], verts, np.array(tris), col=(k == 0)))
    v, t = cylinder(0, H, 0, 6.0, 14.0, n=10, r_top=2.0)
    P.append(part("Salesforce_Crown", "Mat_Landmark_Salesforce", [0.9, 0.9, 0.95], v, t))
    return P


def _transamerica():
    P = []
    H, b = 260.0, 48.0
    nseg = 12
    for k in range(nseg):
        y0, y1 = k * H / nseg, (k + 1) * H / nseg
        s0 = b * (1 - k / nseg)
        s1 = b * (1 - (k + 1) / nseg)
        h0 = np.array([[-s0/2, -s0/2], [s0/2, -s0/2], [s0/2, s0/2], [-s0/2, s0/2]])
        h1 = np.array([[-s1/2, -s1/2], [s1/2, -s1/2], [s1/2, s1/2], [-s1/2, s1/2]])
        N = 4
        verts = np.empty((2 * N, 3))
        verts[:N, 0] = h0[:, 0]; verts[:N, 2] = h0[:, 1]; verts[:N, 1] = y0
        verts[N:, 0] = h1[:, 0]; verts[N:, 2] = h1[:, 1]; verts[N:, 1] = y1
        tris = []
        for a in range(N):
            b2 = (a + 1) % N
            tris.append([a, N + a, N + b2]); tris.append([a, N + b2, b2])
        P.append(part("Transamerica_Tower", "Mat_Landmark_Transamerica",
                      [0.82, 0.80, 0.76], verts, np.array(tris), col=(k == 0)))
    v, t = cylinder(0, H, 0, 1.6, 18.0, n=8, r_top=0.4)
    P.append(part("Transamerica_Spire", "Mat_Landmark_Transamerica", [0.95, 0.95, 0.98], v, t))
    return P


def _sutro_tower():
    P = []
    H = 298.0
    r_foot = 37.0
    for k in range(3):
        a = k * 2 * np.pi / 3
        x0 = r_foot * np.cos(a); z0 = r_foot * np.sin(a)
        x1 = 3.0 * np.cos(a); z1 = 3.0 * np.sin(a)
        pts = np.array([[x0, 0, z0], [x0 * 0.6, H * 0.42, z0 * 0.6], [x1, H * 0.78, z1]])
        v, t = tube_along(pts, 2.8, nside=4)
        P.append(part("SutroTower_Leg", "Mat_Landmark_SutroTower", [0.90, 0.90, 0.92], v, t, col=(k == 0)))
    for hy, rr in ((0.40, 22.0), (0.78, 12.0)):
        y = H * hy
        ang = np.linspace(0, 2 * np.pi, 3, endpoint=False)
        ring = np.stack([rr * np.cos(ang), rr * np.sin(ang)], 1)
        vv = np.zeros((6, 3))
        vv[:3, 0] = ring[:, 0]; vv[:3, 2] = ring[:, 1]; vv[:3, 1] = y
        vv[3:, 0] = ring[:, 0]; vv[3:, 2] = ring[:, 1]; vv[3:, 1] = y + 14
        tris = [[0, 3, 4], [0, 4, 1], [1, 4, 5], [1, 5, 2], [2, 5, 3], [2, 3, 0]]
        P.append(part("SutroTower_Deck", "Mat_Landmark_SutroTower", [0.90, 0.90, 0.92], vv, np.array(tris)))
    v, t = cylinder(0, H * 0.80, 0, 1.8, H * 0.20, n=6, r_top=0.5)
    P.append(part("SutroTower_Mast", "Mat_Landmark_SutroTower", [0.85, 0.85, 0.88], v, t))
    return P


def _coit_tower():
    P = []
    H = 64.0
    v, t = cylinder(0, 0, 0, 4.6, H, n=14)
    P.append(part("CoitTower_Column", "Mat_Landmark_CoitTower", [0.88, 0.85, 0.80], v, t, col=True))
    v, t = cylinder(0, H, 0, 6.2, 9.0, n=14, r_top=5.0)
    P.append(part("CoitTower_Top", "Mat_Landmark_CoitTower", [0.85, 0.82, 0.78], v, t))
    return P


def _ferry_building():
    P = []
    v, t = box(0, 0, 0, 201.0, 15.0, 23.0)
    P.append(part("FerryBuilding_Hall", "Mat_Landmark_FerryBuilding", [0.90, 0.88, 0.82], v, t, col=True))
    v, t = box(0, 15.0, 0, 18.0, 43.0, 18.0)
    P.append(part("FerryBuilding_Tower", "Mat_Landmark_FerryBuilding", [0.92, 0.90, 0.84], v, t, col=True))
    v, t = box(0, 58.0, 0, 15.0, 6.0, 15.0)
    P.append(part("FerryBuilding_TowerTop", "Mat_Landmark_FerryBuilding", [0.86, 0.84, 0.78], v, t))
    v, t = cylinder(0, 64.0, 0, 0.8, 10.0, n=8)
    P.append(part("FerryBuilding_Spike", "Mat_Landmark_FerryBuilding", [0.7, 0.68, 0.62], v, t))
    return P


def _palace():
    P = []
    v, t = dome(0, 22.0, 0, 17.0, 15.0, n=14, rings=5)
    P.append(part("Palace_Dome", "Mat_Landmark_Palace", [0.85, 0.83, 0.78], v, t))
    for k in range(8):
        a = k * np.pi / 4
        v, t = cylinder(17 * np.cos(a), 0, 17 * np.sin(a), 1.2, 22.0, n=8)
        P.append(part("Palace_Column", "Mat_Landmark_Palace", [0.85, 0.83, 0.78], v, t, col=(k < 2)))
    v, t = cylinder(0, 0, 0, 19.5, 2.5, n=14)
    P.append(part("Palace_Base", "Mat_Landmark_Palace", [0.80, 0.78, 0.73], v, t))
    return P


def _painted_ladies():
    P = []
    for k in range(6):
        x = (k - 2.5) * 13.0
        v, t = box(x, 0, 0, 11.5, 13.0, 14.0)
        P.append(part(f"PaintedLadies_House{k}", "Mat_Landmark_PaintedLadies",
                      PAINTED_LADY_COLORS[k], v, t, col=True))
        v, t = box(x, 13.0, 0, 12.0, 3.0, 14.5)
        P.append(part(f"PaintedLadies_Roof{k}", "Mat_Landmark_PaintedLadies", [0.35, 0.25, 0.28], v, t))
    return P


def _dragon_gate():
    P = []
    GREEN = [0.20, 0.42, 0.30]
    for x in (-4.2, 0.0, 4.2):
        h = 4.6 if x == 0 else 3.4
        v, t = box(x, 0, 0, 1.4, h, 5.0)
        P.append(part("DragonGate_Pillar", "Mat_Landmark_DragonGate", [0.85, 0.82, 0.75], v, t, col=(x == 0)))
    for y, w in ((5.2, 12.0), (6.6, 9.0)):
        v, t = box(0, y, 0, w, 1.2, 6.0)
        P.append(part("DragonGate_Roof", "Mat_Landmark_DragonGate", GREEN, v, t))
    return P


def _alcatraz():
    P = []
    v, t = box(0, 0, 0, 100.0, 20.0, 30.0)
    P.append(part("Alcatraz_Cellhouse", "Mat_Landmark_Alcatraz", [0.78, 0.76, 0.70], v, t, col=True))
    v, t = box(-22, 0, 12, 36.0, 10.0, 22.0)
    P.append(part("Alcatraz_Wing", "Mat_Landmark_Alcatraz", [0.70, 0.68, 0.62], v, t))
    v, t = cylinder(0, 20, -12, 4.0, 6.0, n=10, r_top=3.2)
    P.append(part("Alcatraz_Lighthouse", "Mat_Landmark_Alcatraz", [0.9, 0.9, 0.9], v, t))
    return P


def _dolores():
    P = []
    v, t = box(0, 0, 0, 15.0, 12.0, 40.0)
    P.append(part("Dolores_Nave", "Mat_Landmark_Dolores", [0.92, 0.90, 0.85], v, t, col=True))
    v, t = box(11.0, 0, -8.0, 8.0, 24.0, 8.0)
    P.append(part("Dolores_Tower", "Mat_Landmark_Dolores", [0.92, 0.90, 0.85], v, t, col=True))
    v, t = dome(0, 12.0, 10.0, 5.0, 4.0, n=10, rings=4)
    P.append(part("Dolores_Dome", "Mat_Landmark_Dolores", [0.80, 0.60, 0.45], v, t))
    return P


def _city_hall():
    P = []
    v, t = box(0, 0, 0, 90.0, 28.0, 80.0)
    P.append(part("CityHall_Hall", "Mat_Landmark_CityHall", [0.90, 0.88, 0.82], v, t, col=True))
    v, t = cylinder(0, 28.0, 0, 14.0, 26.0, n=12)
    P.append(part("CityHall_Drum", "Mat_Landmark_CityHall", [0.90, 0.88, 0.82], v, t))
    v, t = dome(0, 54.0, 0, 15.5, 24.0, n=12, rings=5)
    P.append(part("CityHall_Dome", "Mat_Landmark_CityHall", [0.85, 0.72, 0.55], v, t))
    return P


def _deyoung():
    P = []
    v, t = box(0, 0, 0, 18.0, 44.0, 18.0)
    P.append(part("DeYoung_Tower", "Mat_Landmark_DeYoung", [0.45, 0.35, 0.28], v, t, col=True))
    v, t = dome(40, 0, 20, 20.0, 10.0, n=12, rings=4)
    P.append(part("DeYoung_AcademyDome", "Mat_Landmark_DeYoung", [0.55, 0.62, 0.45], v, t))
    return P


def _sutro_baths():
    P = []
    GRAY = [0.55, 0.54, 0.50]
    for k in range(4):
        v, t = box(-60 + k * 40, 0, 0, 2.0, 3.0 + (k % 2), 60.0)
        P.append(part("SutroBaths_Wall", "Mat_Landmark_SutroBaths", GRAY, v, t, col=(k == 0)))
    v, t = box(0, 0, -28, 130.0, 2.0, 2.0)
    P.append(part("SutroBaths_Wall", "Mat_Landmark_SutroBaths", GRAY, v, t))
    return P


def lombard_polyline():
    """Absolute ENU polyline with 8 switchbacks; y from DEM (top of hill to bottom)."""
    # block: Hyde St (west) high ~ 73 m; Leavenworth St (east) low ~ 48 m
    xw, zw = enu(-122.41885, 37.80055)
    xe, ze = enu(-122.41710, 37.80160)
    n = 8
    pts = []
    for k in range(2 * n + 1):
        t = k / (2 * n)
        x = xw + (xe - xw) * t
        z = zw + (ze - zw) * t
        off = 14.0 * (1 if (k // 2) % 2 == 0 else -1)
        if k in (0, 2 * n):
            off = 0.0
        perp = np.array([-(ze - zw), (xe - xw)])
        perp /= np.hypot(*perp)
        pts.append([x + perp[0] * off, z + perp[1] * off])
    pts = np.array(pts)
    ys = C.dem_sample_world(C.dem_cache, pts[:, 0], pts[:, 1])
    return pts, ys


# ---------------------------------------------------------------------------
# Registry: (index_name, node_prefix, lon, lat, heading_deg, builder)
# ---------------------------------------------------------------------------
REGISTRY = [
    ("Salesforce Tower",    "Salesforce",   -122.39691, 37.78978, 0.0,   _salesforce_tower),
    ("Transamerica Pyramid","Transamerica", -122.40279, 37.79517, 0.0,   _transamerica),
    ("Sutro Tower",         "SutroTower",   -122.45270, 37.75527, 0.0,   _sutro_tower),
    ("Coit Tower",          "CoitTower",    -122.40583, 37.80238, 0.0,   _coit_tower),
    ("Ferry Building",      "FerryBuilding",-122.39343, 37.79554, 90.0,  _ferry_building),
    ("Palace of Fine Arts", "Palace",       -122.44839, 37.80292, 0.0,   _palace),
    ("Painted Ladies",      "PaintedLadies",-122.43280, 37.77626, 90.0,  _painted_ladies),
    ("Chinatown Dragon Gate","DragonGate",  -122.40559, 37.79069, 0.0,   _dragon_gate),
    ("Alcatraz Cellhouse",  "Alcatraz",     -122.42250, 37.82700, 0.0,   _alcatraz),
    ("Mission Dolores",     "Dolores",      -122.42681, 37.76419, 0.0,   _dolores),
    ("Civic Center Dome",   "CityHall",     -122.41920, 37.77859, 90.0,  _city_hall),
    ("de Young + Academy",  "DeYoung",      -122.46860, 37.77160, 0.0,   _deyoung),
    ("Sutro Baths",         "SutroBaths",   -122.51390, 37.78020, 90.0,  _sutro_baths),
]

# LOD1 skyline silhouette boxes: name, x, z, half_w, half_d, y0, y1
LOD_BOXES = []


def _init():
    global LOD_BOXES
    if LOD_BOXES:
        return
    ysf = _ground_y(-122.39394, 37.78981)
    LOD_BOXES.extend([
        ("Salesforce", *enu(-122.39394, 37.78981), 26, 26, ysf, ysf + 326),
        ("Transamerica", *enu(-122.40312, 37.79543), 20, 20, _ground_y(-122.40312, 37.79543),
         _ground_y(-122.40312, 37.79543) + 260),
        ("SutroTower", *enu(-122.45270, 37.75527), 20, 20, _ground_y(-122.45270, 37.75527),
         _ground_y(-122.45270, 37.75527) + 298),
        ("CoitTower", *enu(-122.40260, 37.80237), 7, 7, _ground_y(-122.40260, 37.80237),
         _ground_y(-122.40260, 37.80237) + 64),
    ])


def _ground_y(lon, lat):
    x, z = enu(lon, lat)
    return float(C.dem_sample_world(C.dem_cache, np.array([x]), np.array([z]))[0])


def load():
    if C.dem_cache is None:
        C.dem_cache = C.unpack_dem()
    _init()


# ---------------------------------------------------------------------------
# Suppression: OSM buildings replaced by landmark geometry
# ---------------------------------------------------------------------------
SUPPRESS = []


def _init_suppress():
    if SUPPRESS:
        return
    zones = [
        ("Ferry Building", Polygon([enu(-122.39420, 37.79340), enu(-122.39260, 37.79340),
                                    enu(-122.39260, 37.79770), enu(-122.39420, 37.79770)])),
        ("Painted Ladies", Polygon([enu(-122.43330, 37.77590), enu(-122.43160, 37.77590),
                                    enu(-122.43160, 37.77730), enu(-122.43330, 37.77730)])),
        ("Salesforce", Polygon([enu(-122.39760, 37.78910), enu(-122.39620, 37.78910),
                                enu(-122.39620, 37.79050), enu(-122.39760, 37.79050)])),
        ("Transamerica", Polygon([enu(-122.40360, 37.79450), enu(-122.40200, 37.79450),
                                  enu(-122.40200, 37.79580), enu(-122.40360, 37.79580)])),
        ("CoitTower", Polygon([enu(-122.40660, 37.80180), enu(-122.40500, 37.80180),
                               enu(-122.40500, 37.80300), enu(-122.40660, 37.80300)])),
        ("CityHall", Polygon([enu(-122.41990, 37.77800), enu(-122.41840, 37.77800),
                              enu(-122.41840, 37.77920), enu(-122.41990, 37.77920)])),
        ("DeYoung", Polygon([enu(-122.46970, 37.77080), enu(-122.46740, 37.77080),
                             enu(-122.46740, 37.77240), enu(-122.46970, 37.77240)])),
        ("Dolores", Polygon([enu(-122.42760, 37.76350), enu(-122.42600, 37.76350),
                             enu(-122.42600, 37.76490), enu(-122.42760, 37.76490)])),
        ("Alcatraz", Polygon([enu(-122.42330, 37.82640), enu(-122.42170, 37.82640),
                              enu(-122.42170, 37.82760), enu(-122.42330, 37.82760)])),
        ("Palace", Polygon([enu(-122.44900, 37.80230), enu(-122.44770, 37.80230),
                            enu(-122.44770, 37.80350), enu(-122.44900, 37.80350)])),
    ]
    SUPPRESS.extend(zones)


def suppressed(x, z):
    _init_suppress()
    p = Point(x, z)
    for _, poly in SUPPRESS:
        if poly.contains(p):
            return True
    return False


# Lombard St: OSM road drop zone (name-matched)
LOMBARD_ZONE = None


def is_lombard(name, pts):
    global LOMBARD_ZONE
    if LOMBARD_ZONE is None:
        LOMBARD_ZONE = Polygon([enu(-122.41910, 37.80020), enu(-122.41680, 37.80020),
                                enu(-122.41680, 37.80180), enu(-122.41910, 37.80180)])
    if "lombard" not in (name or "").lower():
        return False
    for lon, lat in pts[:: max(1, len(pts) // 12)]:
        if LOMBARD_ZONE.contains(Point(lon, lat)):
            return True
    return False


# ---------------------------------------------------------------------------
# Tile baking
# ---------------------------------------------------------------------------
_GGB = None
_BB = None


def bridge_parts():
    global _GGB, _BB
    if _GGB is None:
        _GGB = build_ggb()
    if _BB is None:
        _BB = build_bay_bridge()
    return _GGB, _BB


def _overlaps_tile(verts, x0, z0, pad=2.0):
    x1, z1 = x0 + TILE, z0 + TILE
    return not (verts[:, 0].max() < x0 - pad or verts[:, 0].min() > x1 + pad or
                verts[:, 2].max() < z0 - pad or verts[:, 2].min() > z1 + pad)


def bake_into_tile(scene, i, j, x0, z0):
    """Add all landmark geometry overlapping tile (i,j). Bridges sliced per part;
    simple landmarks triangle-split to tile bbox."""
    load()
    ggb, bb = bridge_parts()
    for p in ggb + bb:
        if _overlaps_tile(p["verts"], x0, z0):
            v = p["verts"].copy()
            v[:, 0] -= x0
            v[:, 2] -= z0
            mat = scene.material(p["mat"], base_color=p["color"], roughness=0.8)
            mi = scene.new_mesh(p["name"])
            scene.add_prim(mi, v, p["tris"], mat)
            node = f"Landmark_{p['name']}_col" if p["col"] else f"Landmark_{p['name']}"
            scene.add_node(node, mi)

    for name, prefix, lon, lat, head, builder in REGISTRY:
        lx, lz = enu(lon, lat)
        if not (x0 - TILE <= lx < x0 + 2 * TILE and z0 - TILE <= lz < z0 + 2 * TILE):
            continue
        parts = builder()
        hd = math.radians(head)
        cs, sn = math.cos(hd), math.sin(hd)
        for p in parts:
            v = p["verts"].copy()
            xx = v[:, 0] * cs + v[:, 2] * sn + lx
            zz = -v[:, 0] * sn + v[:, 2] * cs + lz
            inside = (xx > x0 - 3) & (xx < x0 + TILE + 3) & (zz > z0 - 3) & (zz < z0 + TILE + 3)
            if not inside.any():
                continue
            t = p["tris"]
            keep = inside[t].any(axis=1)
            if not keep.any():
                continue
            v[:, 0] = xx - x0
            v[:, 2] = zz - z0
            mat = scene.material(p["mat"], base_color=p["color"], roughness=0.85)
            mi = scene.new_mesh(p["name"])
            scene.add_prim(mi, v, t[keep], mat)
            node = f"Landmark_{p['name']}_col" if p["col"] else f"Landmark_{p['name']}"
            scene.add_node(node, mi)


def landmark_index():
    load()
    out = []
    for name, prefix, lon, lat, head, builder in REGISTRY:
        out.append({"name": name, "x": float(enu(lon, lat)[0]),
                    "y": float(_ground_y(lon, lat)), "z": float(enu(lon, lat)[1])})
    ggb, bb = bridge_parts()
    for parts, nm, y in ((ggb, "Golden Gate Bridge", 74.0), (bb, "Bay Bridge", 58.0)):
        gx = np.concatenate([p["verts"][:, 0] for p in parts])
        gz = np.concatenate([p["verts"][:, 2] for p in parts])
        out.append({"name": nm, "x": float(np.median(gx)), "y": float(y), "z": float(np.median(gz))})
    return out