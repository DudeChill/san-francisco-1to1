#!/usr/bin/env python3
"""Merge primitives sharing one material inside a glTF mesh when a mesh would
exceed Godot's MAX_MESH_SURFACES (16). Appends geometry to the external .bin."""
import base64
import glob
import json
import os
import struct

import numpy as np

COMPS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
CT = {5125: "<u4", 5123: "<u2", 5126: "<f4"}


def read_acc(d, data, ai):
    acc = d["accessors"][ai]
    view = d["bufferViews"][acc["bufferView"]]
    comps = COMPS[acc["type"]]
    dt = np.dtype(CT[acc["componentType"]])
    raw = data[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]
    arr = np.frombuffer(raw, dtype=dt)
    if acc["type"] != "SCALAR":
        arr = arr.reshape(-1, comps)
    return arr.copy()


def add_acc(d, buffer, arr, type_, comp_type, mn=None, mx=None):
    pad = (4 - len(buffer) % 4) % 4
    buffer.extend(b"\x00" * pad)
    off = len(buffer)
    raw = arr.astype(CT[comp_type]).tobytes()
    buffer.extend(raw)
    d["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": len(raw)})
    acc = {"bufferView": len(d["bufferViews"]) - 1, "componentType": comp_type,
           "count": arr.shape[0], "type": type_}
    if mn is not None:
        acc["min"] = [float(v) for v in mn]
        acc["max"] = [float(v) for v in mx]
    d["accessors"].append(acc)
    return len(d["accessors"]) - 1


def main():
    patched_files = 0
    patched_meshes = 0
    for path in glob.glob("data/tiles/*.gltf"):
        d = json.load(open(path))
        target = None
        for mesh in d["meshes"]:
            prims = mesh["primitives"]
            if len(prims) <= 16:
                continue
            mats = {p["material"] for p in prims}
            if len(mats) != 1:
                print("SKIP multi-material overflow", path, mesh["name"])
                continue
            target = mesh
        if target is None:
            continue
        buf_meta = d["buffers"][0]
        uri = buf_meta["uri"]
        data = bytearray(open(os.path.join(os.path.dirname(path), uri), "rb").read())
        new_prims = []
        by_mat = {}
        for p in target["primitives"]:
            by_mat.setdefault(p["material"], []).append(p)
        for mat, prims in by_mat.items():
            arrays = {}
            for attr in ["POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"]:
                if all(attr in p["attributes"] for p in prims):
                    arrays[attr] = np.concatenate(
                        [read_acc(d, data, p["attributes"][attr]) for p in prims])
            indices = []
            offsets = []
            off = 0
            for p in prims:
                pv = read_acc(d, data, p["attributes"]["POSITION"])
                offsets.append(off)
                off += pv.shape[0]
            indices = np.concatenate([read_acc(d, data, p["indices"]) + offsets[i]
                                      for i, p in enumerate(prims)])
            pos = arrays["POSITION"]
            prim = {"attributes": {}, "material": mat}
            prim["attributes"]["POSITION"] = add_acc(
                d, data, pos, "VEC3", 5126, pos.min(axis=0), pos.max(axis=0))
            if "NORMAL" in arrays:
                prim["attributes"]["NORMAL"] = add_acc(d, data, arrays["NORMAL"], "VEC3", 5126)
            if "TEXCOORD_0" in arrays:
                prim["attributes"]["TEXCOORD_0"] = add_acc(d, data, arrays["TEXCOORD_0"], "VEC2", 5126)
            if "COLOR_0" in arrays:
                prim["attributes"]["COLOR_0"] = add_acc(d, data, arrays["COLOR_0"], "VEC3", 5126)
            prim["indices"] = add_acc(d, data, indices, "SCALAR", 5125)
            new_prims.append(prim)
        target["primitives"] = new_prims
        buf_meta["byteLength"] = len(data)
        open(os.path.join(os.path.dirname(path), uri), "wb").write(bytes(data))
        json.dump(d, open(path, "w"), separators=(",", ":"))
        patched_files += 1
        patched_meshes += 1
    print("patched files:", patched_files, "meshes:", patched_meshes)


if __name__ == "__main__":
    main()
