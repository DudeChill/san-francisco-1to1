"""Procedural texture generation (PIL/numpy) -> data/tiles/tex/*.png.

All textures are procedural (no photo downloads needed): documented in the report.
Facade albedo/emissive pairs are generated per district; worldspace UV scale is
1 texture repeat per 12 m in both u and v.
"""
import os

import numpy as np
from PIL import Image

from common import TEX_DIR, ensure_dirs
from districts import DISTRICT_POLYS, DEFAULT_DISTRICT, FACADE_STYLE

FACADE_REPEAT_M = 12.0   # world meters per texture repeat
FACADE_UV = 1.0 / FACADE_REPEAT_M


# ---------- tileable noise ----------
def vnoise(size, cells, seed):
    rng = np.random.default_rng(seed)
    lat = rng.random((cells, cells))
    t = np.linspace(0.0, cells, size, endpoint=False)
    tf = np.floor(t).astype(np.int64) % cells
    f = t - np.floor(t)
    f = f * f * (3 - 2 * f)
    t0 = tf
    t1 = (tf + 1) % cells
    y0, x0 = np.meshgrid(t0, t0, indexing="ij")
    y1, x1 = np.meshgrid(t1, t1, indexing="ij")
    fy, fx = np.meshgrid(f, f, indexing="ij")
    v00 = lat[y0, x0]; v01 = lat[y0, x1]; v10 = lat[y1, x0]; v11 = lat[y1, x1]
    a = v00 * (1 - fy) + v10 * fy
    b = v01 * (1 - fy) + v11 * fy
    return a * (1 - fx) + b * fx


def fbm(size, cells0, octaves, seed, gain=0.55):
    out = np.zeros((size, size))
    amp = 1.0
    total = 0.0
    for o in range(octaves):
        out += amp * vnoise(size, cells0 << o, seed * 977 + o)
        total += amp
        amp *= gain
    return out / total


def to_u8(a):
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


def save(arr_u8, name):
    os.makedirs(TEX_DIR, exist_ok=True)
    Image.fromarray(arr_u8).save(os.path.join(TEX_DIR, name))
    print(f"[tex] {name} {arr_u8.shape[1]}x{arr_u8.shape[0]}")


# ---------- material styles ----------
def _stucco(size, seed, base, grain=0.05, blotch=0.06):
    n = fbm(size, 24, 4, seed, 0.6)
    b = fbm(size, 3, 2, seed + 7, 0.5)
    col = np.array(base, dtype=np.float64) / 255.0
    img = col[None, None, :] * (1 + (n - 0.5) * 2 * grain)[:, :, None]
    img *= (1 + (b - 0.5) * 2 * blotch)[..., None]
    return np.clip(img, 0, 1)


def _brick(size, seed, base, mortar=(200, 195, 185), courses=26):
    col = np.array(base, dtype=np.float64) / 255.0
    mor = np.array(mortar, dtype=np.float64) / 255.0
    img = np.tile(mor, (size, size, 1))
    yy = np.arange(size)[:, None] * np.ones(size)[None, :]
    xx = np.arange(size)[None, :] * np.ones(size)[:, None]
    course = np.floor(yy * courses / size)
    in_row = (yy * courses / size) - course
    offset = (course % 2) * 0.5
    brick_len = size / 4.0
    bx = ((xx + offset * brick_len) % brick_len) / brick_len
    in_brick = np.clip((in_row - 0.10) / 0.78, 0, 1) * np.clip((bx - 0.02) / 0.06, 0, 1) * np.clip((0.98 - bx) / 0.06, 0, 1)
    tone = 0.85 + 0.3 * vnoise(size, 32, seed)  # per-brick-ish tone noise
    tone = (0.9 + 0.2 * np.cos(bx * np.pi * 2 + course) * 0.3) * (0.9 + 0.25 * vnoise(size, 16, seed + 3))
    wall = col[None, None, :] * tone[..., None]
    img = img * (1 - in_brick[..., None]) + wall * in_brick[..., None]
    return np.clip(img, 0, 1)


def _siding(size, seed, base, planks=32):
    col = np.array(base, dtype=np.float64) / 255.0
    grain = fbm(size, 64, 3, seed + 11, 0.55)
    shade = fbm(size, 8, 2, seed + 5, 0.5)
    img = col[None, None, :] * (0.92 + 0.16 * grain[..., None]) * (0.95 + 0.1 * shade[..., None])
    yy = np.arange(size)[:, None] * np.ones(size)[None, :]
    p = (yy * planks / size) % 1.0
    img *= (0.78 + 0.22 * np.clip(p * 6, 0, 1))[..., None]  # plank shadow at each seam
    return np.clip(img, 0, 1)


def _glass(size, seed, base, win):
    # curtain-wall: mullion grid + bluish panels with per-panel variation
    wall = np.array(base, dtype=np.float64) / 255.0
    win_c = np.array(win, dtype=np.float64) / 255.0
    img = np.tile(wall, (size, size, 1))
    yy = np.arange(size)[:, None] * np.ones(size)[None, :]
    xx = np.arange(size)[None, :] * np.ones(size)[:, None]
    px, py = 128.0, 128.0
    wx = (xx % px) / px
    wy = (yy % py) / py
    in_win = (wx > 0.06) * (wx < 0.94) * (wy > 0.08) * (wy < 0.90)
    reflect = 0.75 + 0.25 * ((1 - wy) * 0.8 + 0.2)  # sky gradient
    tint = 0.85 + 0.3 * vnoise(size, 16, seed)
    panel = win_c[None, None, :] * reflect[..., None] * tint[..., None]
    img = img * (1 - in_win[..., None]) + panel * in_win[..., None]
    # mullion shadow AO at window edges
    edge = np.clip(1 - np.abs(wx - 0.5) * 2, 0, 1) * np.clip(1 - np.abs(wy - 0.5) * 2, 0, 1)
    img *= (0.8 + 0.2 * edge)[..., None]
    return np.clip(img, 0, 1)


def _windows_overlay(img, size, seed, wall_style, win, lit, glow, glassy=False):
    """Draw window grid (4x4 per repeat) + grime + AO into albedo; return (albedo, emissive)."""
    yy = np.arange(size)[:, None] * np.ones(size)[None, :]
    xx = np.arange(size)[None, :] * np.ones(size)[:, None]
    px = size / 4.0
    wx = (xx % px) / px
    wy = (yy % px) / px
    win_c = np.array(win, dtype=np.float64) / 255.0
    glow_c = np.array(glow, dtype=np.float64) / 255.0
    # window aperture
    fx = wx - 0.5
    fy = wy - 0.5
    wx0, wx1 = 0.22, 0.78
    wy0, wy1 = 0.18, 0.74
    in_win = (wx > wx0) * (wx < wx1) * (wy > wy0) * (wy < wy1)
    frame = (~in_win) * (wx > wx0 - 0.06) * (wx < wx1 + 0.06) * (wy > wy0 - 0.05) * (wy < wy1 + 0.05)
    if wall_style == "glass":
        return _glass(size, seed, np.array([150, 158, 165]) * 0, win)  # unused branch
    # per-window variation
    cx = np.floor(xx / px).astype(np.int64)
    cy = np.floor(yy / px).astype(np.int64)
    rng_seed = (cx * 73856093) ^ (cy * 19349663) ^ seed
    rng01 = (np.sin(rng_seed.astype(np.float64)) * 43758.5453) % 1.0
    rng01 = np.abs(rng01)
    # glass fill: vertical gradient + tint per window
    ref = 0.55 + 0.45 * (1 - (wy - wy0) / (wy1 - wy0))
    tint = 0.8 + 0.4 * rng01
    glass = win_c[None, None, :] * ref[..., None] * tint[..., None]
    # inset shadow (AO) inside window near top
    shadow = np.clip(1.4 * (wy - wy0), 0, 1) * 0.5
    glass *= (1 - shadow * (1 - glassy))[..., None]
    albedo = img.copy()
    # frame paint (darker wall)
    albedo[frame] *= 0.85
    albedo[in_win] = glass[in_win]
    # sill highlight
    sill = (wy >= wy1) * (wy < wy1 + 0.05)
    albedo[sill] = np.clip(albedo[sill] * 1.15, 0, 1)
    # grime under windows + bottom band AO
    band = np.clip(0.25 - (1 - wy) * 0.25, 0, 1)  # near bottom (wy near 1)
    streak = np.clip((wy - wy1) * 6, 0, 1) * in_win * 0 + np.clip(1 - (wy - wy1) * 8, 0, 1)
    grime = np.clip(np.maximum(streak * 0.25, band) * fbm(size, 12, 3, seed + 31, 0.5) * 1.6, 0, 0.35)
    # AO floor bands
    ao = 1 - 0.10 * np.clip(((yy % px) / px - 0.9) * 10, 0, 1)
    albedo = albedo * (1 - grime)[..., None] * ao[..., None]
    # emissive: lit windows
    emissive = np.zeros((size, size, 3))
    lit_mask = in_win * (rng01 < lit)
    flick = 0.75 + 0.5 * rng01
    warm = glow_c[None, None, :] * flick[..., None]
    emissive = np.where(lit_mask[..., None], warm, emissive)
    # interior hint on unlit windows (dim cool)
    dim = np.where(in_win[..., None] & ~lit_mask[..., None], win_c[None, None, :] * 0.25, emissive)
    emissive = np.where(in_win[..., None], np.maximum(emissive, dim), emissive)
    return np.clip(albedo, 0, 1), np.clip(emissive, 0, 1)


FACADE_PARAMS = {
    "financial":      dict(style="glass",  wall=(188, 194, 200), win=(72, 96, 122),  lit=0.45, glow=(205, 222, 255)),
    "soma":           dict(style="glass",  wall=(178, 180, 184), win=(86, 102, 118), lit=0.35, glow=(225, 205, 160)),
    "chinatown":      dict(style="brick",  wall=(168, 82, 66),   win=(60, 58, 62),   lit=0.35, glow=(255, 190, 110), mortar=(225, 205, 180)),
    "north_beach":    dict(style="brick",  wall=(176, 108, 84),  win=(58, 56, 60),   lit=0.35, glow=(255, 195, 120), mortar=(215, 200, 185)),
    "nob_hill":       dict(style="stucco", wall=(196, 178, 152), win=(66, 64, 66),   lit=0.32, glow=(255, 200, 130)),
    "pacific_heights":dict(style="siding", wall=(214, 200, 178), win=(62, 60, 64),   lit=0.28, glow=(255, 205, 135)),
    "presidio":       dict(style="plain",  wall=(216, 214, 200), win=(70, 68, 66),   lit=0.20, glow=(255, 220, 170)),
    "marina":         dict(style="stucco", wall=(225, 205, 185), win=(64, 70, 76),   lit=0.30, glow=(255, 210, 140)),
    "richmond":       dict(style="stucco", wall=(206, 190, 168), win=(64, 62, 64),   lit=0.28, glow=(255, 200, 130)),
    "sunset":         dict(style="stucco", wall=(198, 186, 170), win=(66, 64, 66),   lit=0.28, glow=(255, 205, 140)),
    "twin_peaks":     dict(style="stucco", wall=(202, 192, 176), win=(64, 62, 64),   lit=0.26, glow=(255, 205, 140)),
    "mission":        dict(style="stucco", wall=(222, 178, 138), win=(70, 62, 58),   lit=0.30, glow=(255, 200, 130)),
    "castro":         dict(style="siding", wall=(216, 190, 160), win=(66, 58, 56),   lit=0.30, glow=(255, 200, 135)),
    "haight":         dict(style="siding", wall=(205, 170, 150), win=(66, 58, 56),   lit=0.30, glow=(255, 195, 130)),
    "western_addition": dict(style="siding", wall=(210, 186, 160), win=(66, 60, 58), lit=0.30, glow=(255, 200, 135)),
    "potrero_hill":   dict(style="stucco", wall=(200, 184, 168), win=(66, 64, 62),   lit=0.28, glow=(255, 205, 140)),
    "bayview":        dict(style="stucco", wall=(208, 178, 148), win=(70, 64, 60),   lit=0.26, glow=(255, 200, 130)),
    "residential":    dict(style="stucco", wall=(204, 190, 170), win=(66, 64, 64),   lit=0.28, glow=(255, 205, 140)),
}


def generate_all():
    ensure_dirs()
    S = 512
    # ---- facades ----
    for name, _ in DISTRICT_POLYS + [(DEFAULT_DISTRICT, None)]:
        p = FACADE_PARAMS[name]
        seed = hash(name) % 100000
        if p["style"] == "brick":
            img = _brick(S, seed, p["wall"], p.get("mortar", (200, 195, 185)))
        elif p["style"] == "siding":
            img = _siding(S, seed, p["wall"])
        elif p["style"] == "glass":
            img = _glass(S, seed, p["wall"], p["win"])
        elif p["style"] == "plain":
            img = _stucco(S, seed, p["wall"], grain=0.03, blotch=0.03)
        else:
            img = _stucco(S, seed, p["wall"])
        if p["style"] != "glass":
            albedo, emissive = _windows_overlay(img, S, seed, p["style"], p["win"], p["lit"], p["glow"])
        else:
            # glass style: emissive from panel grid, lit fraction via hash of panel
            yy, xx = np.mgrid[0:S, 0:S]
            cx = np.floor(xx / (S / 4)).astype(np.int64)
            cy = np.floor(yy / (S / 4)).astype(np.int64)
            rng01 = np.abs((np.sin((cx * 73856093 ^ cy * 19349663 ^ seed).astype(np.float64)) * 43758.5453) % 1.0)
            lit = (rng01 < p["lit"]).astype(np.float64)
            soft = (xx % (S // 4) > 16) * (yy % (S // 4) > 16)
            emissive = np.where(((lit * soft) > 0)[..., None],
                                np.array(p["glow"], np.float64)[None, None, :] / 255.0, 0.0)
            albedo = img
        save(to_u8(albedo), f"facade_{name}_albedo.png")
        save(to_u8(emissive), f"facade_{name}_emissive.png")

    # ---- roof ----
    n = fbm(S, 40, 4, 12345, 0.6)
    n2 = fbm(S, 6, 2, 12346, 0.5)
    gray = 0.52 + 0.28 * n + 0.10 * n2
    speck = (vnoise(S, 128, 99) > 0.82).astype(np.float64) * 0.15
    img = np.repeat((gray + speck)[:, :, None], 3, axis=2)
    save(to_u8(img), "roof.png")

    # ---- road (plain asphalt, tileable) ----
    n = fbm(S, 48, 4, 555, 0.6)
    n2 = fbm(S, 6, 2, 556, 0.5)
    g = 0.16 + 0.10 * n + 0.05 * n2
    img = np.repeat(g[:, :, None], 3, axis=2)
    # faint tire-wear two lanes darker stripes
    xx = np.linspace(0, 1, S)[None, :]
    wear = 1 - 0.12 * np.exp(-((xx - 0.25) / 0.08) ** 2) - 0.12 * np.exp(-((xx - 0.75) / 0.08) ** 2)
    img *= wear[..., None]
    save(to_u8(img), "road.png")

    # ---- sidewalk (concrete slabs) ----
    n = fbm(S, 64, 3, 777, 0.55)
    n2 = fbm(S, 5, 2, 778, 0.5)
    g = 0.62 + 0.10 * n + 0.08 * n2
    yy, xx = np.mgrid[0:S, 0:S]
    slabs = 8
    slab_px = S // slabs
    gx_edge = np.clip((xx % slab_px) / 2.5, 0, 1)
    gy_edge = np.clip((yy % slab_px) / 2.5, 0, 1)
    grid = (0.88 + 0.12 * np.minimum(gx_edge, gy_edge))
    dirt = fbm(S, 4, 2, 779, 0.5) * 0.15
    img = np.repeat((g * grid - dirt)[:, :, None], 3, axis=2)
    save(to_u8(img), "sidewalk.png")

    # ---- crosswalk (zebra, alpha decal) ----
    C = 128
    img = np.zeros((C, C, 4), np.uint8)
    stripes = np.zeros((C, C), bool)
    yy, xx = np.mgrid[0:C, 0:C]
    stripes = ((xx % 32) < 18) & (yy > 8) & (yy < C - 8)
    img[stripes] = (235, 235, 230, 255)
    img[~stripes] = (20, 20, 20, 0)
    save(img, "crosswalk.png")

    # ---- terrain atlas 2x2 (grass | sand / dirt | scrub) ----
    T = 1024
    half = T // 2

    def grass(seed):
        n = fbm(half, 40, 4, seed, 0.55)
        n2 = fbm(half, 90, 2, seed + 1, 0.5)
        g = np.array([0.30, 0.45, 0.20]) / 1.0
        dry = fbm(half, 8, 2, seed + 2, 0.5)
        col = g[None, None, :] * (0.75 + 0.5 * n[..., None]) * (0.9 + 0.3 * n2[..., None])
        col = col + 0.10 * dry[..., None] * np.array([0.2, 0.1, -0.05])[None, None, :]
        return np.clip(col, 0, 1)

    def sand(seed):
        n = fbm(half, 60, 3, seed, 0.5)
        col = np.array([0.78, 0.70, 0.52])[None, None, :] * (0.85 + 0.3 * n[..., None])
        ripples = 0.04 * np.sin(np.arange(half)[None, :] * 0.35)
        col *= (1 + ripples)[..., None]
        return np.clip(col, 0, 1)

    def dirt(seed):
        n = fbm(half, 30, 4, seed, 0.6)
        col = np.array([0.45, 0.36, 0.26])[None, None, :] * (0.8 + 0.45 * n[..., None])
        return np.clip(col, 0, 1)

    atlas = np.zeros((T, T, 3))
    atlas[:half, :half] = grass(11)
    atlas[:half, half:] = sand(22)
    atlas[half:, :half] = dirt(33)
    atlas[half:, half:] = grass(44) * np.array([1.15, 1.05, 0.8])[None, None, :]  # dry scrub
    save(to_u8(atlas), "terrain.png")


if __name__ == "__main__":
    generate_all()
