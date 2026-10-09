#!/usr/bin/env python3
"""Fix inverted face winding: where a primitive's average face normal points
down (avg.y < -0.5), swap index winding and negate NORMAL values in-place.
Touches every tile + prop gltf/glb so Godot reimports them."""
import glob
import json
import os
import struct

import numpy as np

COMPS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
CT = {5125: "<u4", 5123: "<u2", 5126: "<f4"}


def read_acc(data, d, ai):
    acc = d["accessors"][ai]
    view = d["bufferViews"][acc["bufferView"]]
    comps = COMPS[acc["type"]]
    dt = np.dtype(CT[acc["componentType"]])
    raw = data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]
    arr = np.frombuffer(raw, dtype=dt)
    if acc["type"] != "SCALAR":
        arr = arr.reshape(-1, comps)
    return arr.copy(), view, dt


def fix_gltf_json(d, data):
    """Returns True if buffer bytes were modified (data mutated in place)."""
    touched = False
    for mesh in d.get("meshes", []):
        for prim in mesh["primitives"]:
            ai = prim.get("indices")
            if ai is None or "POSITION" not in prim["attributes"]:
                continue
            idx, view, dt = read_acc(data, d, ai)
            pos, _, _ = read_acc(data, d, prim["attributes"]["POSITION"])
            tris = idx.reshape(-1, 3)
            n = min(len(tris), 100)
            if n == 0:
                continue
            a = pos[tris[:n, 0]]
            b = pos[tris[:n, 1]]
            c = pos[tris[:n, 2]]
            avg_y = float(np.cross(b - a, c - a)[:, 1].mean())
            if avg_y >= -0.5:
                continue
            # Flip winding: swap b and c per triangle.
            tris[:, [1, 2]] = tris[:, [2, 1]]
            data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]] = \
                tris.astype(dt).tobytes()
            touched = True
            if "NORMAL" in prim["attributes"]:
                ni = prim["attributes"]["NORMAL"]
                nrm, nview, ndt = read_acc(data, d, ni)
                data[nview["byteOffset"]:nview["byteOffset"] + nview["byteLength"]] = \
                    (-nrm).astype(ndt).tobytes()
    return touched


def patch(path):
    data = bytearray(open(path, "rb").read())
    if path.endswith(".glb"):
        magic, ver, total = struct.unpack("<III", data[:12])
        off = 12
        chunks = []
        while off < total:
            clen, ctype = struct.unpack("<II", data[off:off + 8])
            chunks.append((ctype, off + 8, clen))
            off += 8 + clen
        js = json.loads(bytes(data[chunks[0][1]:chunks[0][1] + chunks[0][2]]).decode())
        bin_off, bin_len = (chunks[1][1], chunks[1][2]) if len(chunks) > 1 else (0, 0)
        sub = data[bin_off:bin_off + bin_len]
        if fix_gltf_json(js, sub):
            data[bin_off:bin_off + bin_len] = sub
            new_json = json.dumps(js, separators=(",", ":")).encode()
            pad = (4 - len(new_json) % 4) % 4
            new_json += b" " * pad
            head = struct.pack("<III", 0x46546C67, 2, 0)
            out = head + struct.pack("<II", len(new_json), 0x4E4F534A) + new_json
            bpad = (4 - bin_len % 4) % 4
            out += struct.pack("<II", bin_len + bpad, 0x004E4942) + bytes(sub) + b"\x00" * bpad
            out = out[:8] + struct.pack("<I", len(out)) + out[12:]
            open(path, "wb").write(out)
            return True
        return False
    d = json.loads(open(path).read())
    bin_path = os.path.join(os.path.dirname(path), d["buffers"][0]["uri"])
    data = bytearray(open(bin_path, "rb").read())
    if fix_gltf_json(d, data):
        open(bin_path, "wb").write(bytes(data))
        json.dump(d, open(path, "w"), separators=(",", ":"))  # mtime bump
        return True
    return False


if __name__ == "__main__":
    n = 0
    for path in glob.glob("data/tiles/*.gltf") + glob.glob("data/props/*.gltf") + glob.glob("data/props/*.glb"):
        if patch(path):
            n += 1
    print("fixed winding in", n, "files")
