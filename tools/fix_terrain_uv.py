#!/usr/bin/env python3
"""Remap Terrain UVs to seamless worldspace tiling (world/32) and regenerate
terrain.png as a single seamless grass/dirt texture. The baked 2x2 quadrant
atlas sampled per-vertex produced checker noise under worldspace UVs."""
import glob
import json
import os

import numpy as np

SCALE = 32.0
COMPS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_acc(data, d, ai, dtype="<f4"):
    acc = d["accessors"][ai]
    view = d["bufferViews"][acc["bufferView"]]
    comps = COMPS[acc["type"]]
    arr = np.frombuffer(data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]], dtype=dtype)
    return arr.copy() if acc["type"] == "SCALAR" else arr.reshape(-1, comps).copy()


def make_grass_texture(path):
    """512x512 seamless grass/dirt mottle with occasional dry patches."""
    rng = np.random.default_rng(1849)
    n = 512
    base = np.zeros((n, n, 3), np.float32)
    for oct_, amp, scale in [(1, 0.55, 8), (2, 0.28, 16), (3, 0.17, 32)]:
        noise = rng.random((scale, scale, 1)).astype(np.float32)
        img = np.kron(noise, np.ones((n // scale, n // scale, 1), np.float32))
        # Make it tileable by blending mirrored copies.
        img = 0.5 * img + 0.25 * img[::-1] + 0.25 * img[:, ::-1]
        base += img * amp
    # Color ramp: dry grass -> green -> dirt.
    t = np.clip(base[:, :, 0], 0, 1)
    green = np.array([0.30, 0.42, 0.20], np.float32)
    dry = np.array([0.55, 0.50, 0.30], np.float32)
    dirt = np.array([0.38, 0.30, 0.22], np.float32)
    col = np.where(t[..., None] < 0.45, green, np.where(t[..., None] < 0.75, dry, dirt))
    col *= 0.85 + 0.3 * t[..., None]
    # Ensure seamless edges by blending border with mirrored content.
    w = 32
    col[:w] = 0.5 * col[:w] + 0.5 * col[-w:][::-1]
    col[:, :w] = 0.5 * col[:, :w] + 0.5 * col[:, -w:][:, ::-1]
    import zlib, struct
    rgb = (np.clip(col, 0, 1) * 255).astype(np.uint8)
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(n))
    def chunk(tag, payload):
        c = tag + payload
        return struct.pack(">I", len(payload)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    open(path, "wb").write(png)


def main():
    tex_path = "data/tiles/tex/terrain.png"
    make_grass_texture(tex_path)
    n = 0
    for path in glob.glob("data/tiles/*.gltf"):
        d = json.load(open(path))
        bin_path = os.path.join(os.path.dirname(path), d["buffers"][0]["uri"])
        data = bytearray(open(bin_path, "rb").read())
        origin = (float(path.split("_")[1]) * 256.0, float(path.split("_")[2].split(".")[0]) * 256.0)
        changed = False
        for mesh in d.get("meshes", []):
            if mesh["name"] != "Terrain":
                continue
            for prim in mesh["primitives"]:
                if "TEXCOORD_0" not in prim["attributes"] or "POSITION" not in prim["attributes"]:
                    continue
                pos = read_acc(data, d, prim["attributes"]["POSITION"])
                uv = read_acc(data, d, prim["attributes"]["TEXCOORD_0"], "<f4")
                wx = pos[:, 0] + origin[0]
                wz = pos[:, 2] + origin[1]
                uv[:, 0] = wx / SCALE
                uv[:, 1] = wz / SCALE
                acc = d["accessors"][prim["attributes"]["TEXCOORD_0"]]
                view = d["bufferViews"][acc["bufferView"]]
                data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]] = \
                    uv.astype("<f4").tobytes()
                changed = True
        if changed:
            open(bin_path, "wb").write(bytes(data))
            d["asset"]["generator"] = "sf-terrain-uv-fix"
            json.dump(d, open(path, "w"), separators=(",", ":"))
            n += 1
    print("remapped terrain UVs in", n, "tiles")


if __name__ == "__main__":
    main()
