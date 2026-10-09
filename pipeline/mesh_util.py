"""Geometry helpers shared by landmark/prop/tile bakers (numpy + shapely only)."""
import numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import triangulate as shp_triangulate
from shapely import contains_xy

import common as C


def triangulate_poly(enu_pts, holes=None, tol=1e-9):
    """Triangulate a simple polygon (ENU (N,2)) with optional hole rings.
    Returns (verts (M,2), tris (K,3)) or None if degenerate."""
    try:
        if holes:
            poly = Polygon(enu_pts, holes)
        else:
            poly = Polygon(enu_pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
            if poly.is_empty or poly.geom_type != "Polygon":
                return None
            enu_pts = np.asarray(poly.exterior.coords)[:-1]
            holes = [np.asarray(r.coords)[:-1] for r in poly.interiors]
            poly = Polygon(enu_pts, holes)
        if poly.area < 0.5:
            return None
        tris = shp_triangulate(poly)
        verts, out_t = [], []
        for t in tris:
            c = t.representative_point()
            if not poly.contains(c):
                continue
            cs = np.asarray(t.exterior.coords)[:-1]
            base = len(verts)
            verts.extend(cs.tolist())
            out_t.append([base, base + 1, base + 2])
        if not out_t:
            return None
        return np.array(verts, dtype=np.float64), np.array(out_t, dtype=np.int64)
    except Exception:
        return None


def polygon_area(enu_pts):
    x, z = enu_pts[:, 0], enu_pts[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(z, 1)) - np.dot(z, np.roll(x, 1)))


def perp_normals(pts):
    """Per-vertex perpendicular unit normals of polyline pts (N,2): left of travel."""
    d = np.gradient(pts, axis=0)
    seg = pts[1:] - pts[:-1]
    if len(pts) > 2:
        n = np.zeros_like(pts)
        n[1:-1] = seg[:-1] + seg[1:]
        n[0] = seg[0]; n[-1] = seg[-1]
    else:
        n = seg.copy()
        n = np.concatenate([n, n[-1:]], 0)
    ln = np.hypot(n[:, 0], n[:, 1])
    ln[ln < 1e-9] = 1.0
    nx, nz = n[:, 0] / ln, n[:, 1] / ln
    # left-of-travel perpendicular: (-nz, nx)? For dir (dx,dz), left normal = (-dz, dx)
    return np.stack([-nz, nx], axis=1), seg


def ribbon(pts_xz, width, y, uv_scale=1.0 / 8.0, extend=0.0, y_top_off=0.0):
    """Build a flat ribbon mesh along polyline. pts_xz (N,2), width scalar or (N,),
    y scalar or (N,). Returns verts (2N,3), uvs (2N,2), tris."""
    pts = np.asarray(pts_xz, np.float64)
    N = len(pts)
    w = np.broadcast_to(np.asarray(width, np.float64), (N,)).copy()
    yy = np.broadcast_to(np.asarray(y, np.float64), (N,)).copy()
    n, seg = perp_normals(pts)
    if extend > 0.0 and N >= 2:
        d0 = seg[0] / max(np.hypot(*seg[0]), 1e-9)
        d1 = seg[-1] / max(np.hypot(*seg[-1]), 1e-9)
        pts = np.concatenate([[pts[0] - d0 * extend], pts, [pts[-1] + d1 * extend]], 0)
        n = np.concatenate([[n[0]], n, [n[-1]]], 0)
        w = np.concatenate([[w[0]], w, [w[-1]]], 0)
        yy = np.concatenate([[yy[0]], yy, [yy[-1]]], 0)
        N = len(pts)
    hw = w * 0.5
    left = pts + n * hw[:, None]
    right = pts - n * hw[:, None]
    d = np.concatenate([[0.0], np.cumsum(np.hypot(*(pts[1:] - pts[:-1]).T))])
    u = d * uv_scale
    verts = np.empty((2 * N, 3))
    verts[0::2, 0] = left[:, 0]; verts[0::2, 1] = yy + y_top_off; verts[0::2, 2] = left[:, 1]
    verts[1::2, 0] = right[:, 0]; verts[1::2, 1] = yy + y_top_off; verts[1::2, 2] = right[:, 1]
    uvs = np.empty((2 * N, 2))
    uvs[0::2, 0] = u; uvs[0::2, 1] = 1.0
    uvs[1::2, 0] = u; uvs[1::2, 1] = 0.0
    tris = []
    for k in range(N - 1):
        a = 2 * k; b = 2 * k + 1; c2 = 2 * k + 2; d2 = 2 * k + 3
        tris.append([a, b, d2]); tris.append([a, d2, c2])
    return verts, uvs, np.array(tris, np.int64)


def box(cx, y0, cz, sx, sy, sz, rot_y=0.0):
    """Axis box centered (cx, cz), bottom y0, rotated rot_y around Y (radians)."""
    hx, hz = sx / 2.0, sz / 2.0
    corners = np.array([[-hx, -hz], [hx, -hz], [hx, hz], [-hx, hz]], np.float64)
    if rot_y:
        cs, sn = np.cos(rot_y), np.sin(rot_y)
        x = corners[:, 0] * cs + corners[:, 1] * sn
        z = -corners[:, 0] * sn + corners[:, 1] * cs
        corners = np.stack([x, z], 1)
    p = corners + np.array([cx, cz])
    y1 = y0 + sy
    verts = np.array([[p[0][0], y0, p[0][1]], [p[1][0], y0, p[1][1]], [p[2][0], y0, p[2][1]], [p[3][0], y0, p[3][1]],
                      [p[0][0], y1, p[0][1]], [p[1][0], y1, p[1][1]], [p[2][0], y1, p[2][1]], [p[3][0], y1, p[3][1]]])
    tris = np.array([[0, 2, 1], [0, 3, 2],  # bottom
                     [4, 5, 6], [4, 6, 7],  # top
                     [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                     [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], np.int64)
    return verts, tris


def prism(pts_xz, y0, y1):
    """Extrude closed polygon pts_xz (N,2) from y0 to y1. verts (2N,3), tris."""
    pts = np.asarray(pts_xz, np.float64)
    N = len(pts)
    verts = np.empty((2 * N, 3))
    verts[:N, 0] = pts[:, 0]; verts[:N, 1] = y0; verts[:N, 2] = pts[:, 1]
    verts[N:, 0] = pts[:, 0]; verts[N:, 1] = y1; verts[N:, 2] = pts[:, 1]
    tris = []
    for k in range(N):
        j = (k + 1) % N
        tris.append([k, N + k, N + j]); tris.append([k, N + j, j])
    return verts, np.array(tris, np.int64)


def cylinder(cx, y0, cz, r, h, n=12, r_top=None, cap_bottom=False, cap_top=True):
    """Vertical cylinder/cone (r -> r_top). verts, tris."""
    rt = r if r_top is None else r_top
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring0 = np.stack([cx + r * np.cos(ang), np.full(n, y0), cz + r * np.sin(ang)], 1)
    ring1 = np.stack([cx + rt * np.cos(ang), np.full(n, y0 + h), cz + rt * np.sin(ang)], 1)
    verts = np.concatenate([ring0, ring1], 0)
    tris = []
    for k in range(n):
        j = (k + 1) % n
        tris.append([k, n + k, n + j]); tris.append([k, n + j, j])
    if cap_top:
        c = len(verts)
        verts = np.concatenate([verts, [[cx, y0 + h, cz]]], 0)
        for k in range(n):
            j = (k + 1) % n
            tris.append([n + k, c, n + j])
    if cap_bottom:
        c = len(verts)
        verts = np.concatenate([verts, [[cx, y0, cz]]], 0)
        for k in range(n):
            j = (k + 1) % n
            tris.append([k, j, c])
    return verts, np.array(tris, np.int64)


def dome(cx, y0, cz, r, h=None, n=16, rings=6):
    """Hemisphere-ish dome sitting at y0 (rings of quads up to apex)."""
    h = h if h is not None else r
    verts, tris = [], []
    base = []
    for i in range(1, rings + 1):
        t = i / rings
        z = np.cos(t * np.pi / 2)
        rr = r * np.sin(t * np.pi / 2)
        yv = y0 + h * z
        ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
        ring = np.stack([cx + rr * np.cos(ang), np.full(n, yv), cz + rr * np.sin(ang)], 1)
        base.append((ring, t))
    # bottom ring at y0 radius r
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring0 = np.stack([cx + r * np.cos(ang), np.full(n, y0), cz + r * np.sin(ang)], 1)
    prev = ring0
    prev_t = 0.0
    for ring, t in base:
        k = len(verts)
        verts.extend(prev.tolist()); verts.extend(ring.tolist())
        for a in range(n):
            b2 = (a + 1) % n
            tris.append([k + a, k + n + a, k + n + b2]); tris.append([k + a, k + n + b2, k + b2])
        prev = ring; prev_t = t
    k = len(verts)
    verts.append([cx, y0 + h, cz])
    idx_prev = len(verts) - 1 - n
    for a in range(n):
        b2 = (a + 1) % n
        tris.append([idx_prev + a, k, idx_prev + b2])
    return np.array(verts), np.array(tris, np.int64)


def tube_along(pts3, r, nside=4, close=False):
    """Square/round tube along 3D polyline (for suspension cables)."""
    pts = np.asarray(pts3, np.float64)
    N = len(pts)
    # frame: tangent + fixed up
    verts = np.empty((N, nside, 3))
    ang = np.linspace(0, 2 * np.pi, nside, endpoint=False)
    up = np.array([0.0, 1.0, 0.0])
    rings = []
    for i in range(N):
        t = pts[min(i + 1, N - 1)] - pts[max(i - 1, 0)]
        tl = float(np.linalg.norm(t))
        if tl < 1e-9:
            t = np.array([1.0, 0.0, 0.0])
        else:
            t = t / tl
        side = np.cross(t, up)
        sl = float(np.linalg.norm(side))
        side = side / sl if sl > 1e-9 else np.array([1.0, 0.0, 0.0])
        upv = np.cross(side, t)
        ring = pts[i] + r * (np.outer(np.cos(ang), side) + np.outer(np.sin(ang), upv))
        rings.append(ring)
    verts = np.concatenate([r for r in rings], 0)
    tris = []
    for i in range(N - 1):
        for a in range(nside):
            b2 = (a + 1) % nside
            p0 = i * nside + a; p1 = i * nside + b2
            q0 = (i + 1) * nside + a; q1 = (i + 1) * nside + b2
            tris.append([p0, q0, q1]); tris.append([p0, q1, p1])
    return verts, np.array(tris, np.int64)


def parabola_cable(p0, p1, y_low, n=40):
    """Sample catenary-like curve between p0,p1 (3D) with lowest y_low at mid."""
    p0 = np.asarray(p0, np.float64); p1 = np.asarray(p1, np.float64)
    t = np.linspace(0, 1, n)
    pts = p0[None, :] + (p1 - p0)[None, :] * t[:, None]
    y_mid = (p0[1] + p1[1]) / 2
    sag = y_mid - y_low
    pts[:, 1] -= 4 * sag * t * (1 - t)
    return pts


def transform(verts, dx=0.0, dy=0.0, dz=0.0, rot_y=0.0, scale=1.0):
    v = verts * scale
    if rot_y:
        cs, sn = np.cos(rot_y), np.sin(rot_y)
        x = v[:, 0] * cs + v[:, 2] * sn
        z = -v[:, 0] * sn + v[:, 2] * cs
        v = np.stack([x, v[:, 1], z], 1)
    v = v + np.array([dx, dy, dz])
    return v


def part(name, mat, color, verts, tris, col=False, normals=None, uv=None):
    return {"name": name, "mat": mat, "color": color, "verts": np.asarray(verts, np.float64),
            "tris": np.asarray(tris, np.int64), "col": col}


def mesh_stats(parts):
    v = sum(len(p["verts"]) for p in parts)
    t = sum(len(p["tris"]) for p in parts)
    return v, t
