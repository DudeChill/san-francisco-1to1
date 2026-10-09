"""Minimal glTF 2.0 writer: .gltf + external .bin + external texture URIs, and .glb.

No dependencies beyond numpy/stdlib. Supports POSITION/NORMAL/TEXCOORD_0/COLOR_0,
indexed primitives, multiple materials per mesh, external PNG textures with REPEAT
samplers, emissive maps, alpha blending. Node names preserved exactly (Godot uses
trailing `_col` suffixes as import hints).
"""
import json
import os
import struct

import numpy as np

REPEAT = 10497
LINEAR = 9729
LINEAR_MIPMAP_LINEAR = 9987


class GltfScene:
    def __init__(self):
        self.materials = []
        self.material_index = {}
        self.textures = []
        self._tex_index = {}
        self.meshes = []
        self.nodes = []
        self.roots = []
        # per-primitive stash: dict(mesh_idx -> list of prim dicts)
        self._prims = {}
        self._images = []          # list of uri strings
        self._image_index = {}

    # ---- materials/textures -------------------------------------------------
    def texture(self, uri):
        if uri in self._tex_index:
            return self._tex_index[uri]
        idx = len(self._images)
        self._images.append(uri)
        self._tex_index[uri] = len(self.textures)
        self.textures.append({"sampler": 0, "source": idx})
        return self._tex_index[uri]

    def material(self, name, base_color=None, base_tex=None, emissive_tex=None,
                 emissive_factor=None, metallic=0.0, roughness=0.9,
                 alpha_mode="OPAQUE", double_sided=False):
        key = name
        if key in self.material_index:
            return self.material_index[key]
        pbr = {"metallicFactor": metallic, "roughnessFactor": roughness}
        if base_color is not None:
            pbr["baseColorFactor"] = list(base_color)
        if base_tex is not None:
            pbr["baseColorTexture"] = {"index": self.texture(base_tex)}
        m = {"name": name, "pbrMetallicRoughness": pbr}
        if emissive_tex is not None:
            m["emissiveTexture"] = {"index": self.texture(emissive_tex)}
            m["emissiveFactor"] = list(emissive_factor or [1.0, 1.0, 1.0])
        elif emissive_factor is not None:
            m["emissiveFactor"] = list(emissive_factor)
        if alpha_mode != "OPAQUE":
            m["alphaMode"] = alpha_mode
        if double_sided:
            m["doubleSided"] = True
        idx = len(self.materials)
        self.materials.append(m)
        self.material_index[key] = idx
        return idx

    # ---- geometry -----------------------------------------------------------
    def new_mesh(self, name):
        idx = len(self.meshes)
        self.meshes.append({"name": name, "primitives": []})
        self._prims[idx] = []
        return idx

    def add_prim(self, mesh_idx, positions, indices, material, normals=None,
                 uvs=None, colors=None):
        """positions float32 (N,3); indices uint32 (M,); uvs float32 (N,2);
        colors float32 (N,3)."""
        assert len(positions) == len(uvs) if uvs is not None else True
        self._prims[mesh_idx].append(dict(
            pos=np.ascontiguousarray(positions, dtype="<f4"),
            nrm=None if normals is None else np.ascontiguousarray(normals, dtype="<f4"),
            uv=None if uvs is None else np.ascontiguousarray(uvs, dtype="<f4"),
            col=None if colors is None else np.ascontiguousarray(colors, dtype="<f4"),
            idx=np.ascontiguousarray(indices, dtype="<u4"),
            mat=material))

    def add_node(self, name, mesh_idx, translation=None, children=None):
        node = {"name": name, "mesh": mesh_idx}
        if translation:
            node["translation"] = list(translation)
        if children:
            node["children"] = children
        idx = len(self.nodes)
        self.nodes.append(node)
        self.roots.append(idx)
        return idx

    def add_empty_node(self, name, children=None):
        node = {"name": name}
        if children:
            node["children"] = children
        idx = len(self.nodes)
        self.nodes.append(node)
        self.roots.append(idx)
        return idx

    # ---- serialization ------------------------------------------------------
    def _pack_prims(self, mesh_idx, buffer, views, accessors, glb):
        prims_out = []
        for p in self._prims[mesh_idx]:
            attrs = {}
            pos = p["pos"]
            # POSITION accessor needs min/max
            mn = pos.min(axis=0).astype("<f4")
            mx = pos.max(axis=0).astype("<f4")
            ai = self._add_accessor(buffer, views, accessors, pos, 5126, "VEC3", mn, mx)
            attrs["POSITION"] = ai
            if p["nrm"] is not None:
                attrs["NORMAL"] = self._add_accessor(buffer, views, accessors, p["nrm"], 5126, "VEC3")
            if p["uv"] is not None:
                attrs["TEXCOORD_0"] = self._add_accessor(buffer, views, accessors, p["uv"], 5126, "VEC2")
            if p["col"] is not None:
                attrs["COLOR_0"] = self._add_accessor(buffer, views, accessors, p["col"], 5126, "VEC3")
            ii = self._add_accessor(buffer, views, accessors, p["idx"], 5125, "SCALAR")
            prim = {"attributes": attrs, "indices": ii, "material": p["mat"]}
            prims_out.append(prim)
        return prims_out

    def _add_accessor(self, buffer, views, accessors, arr, comp_type, type_, mn=None, mx=None):
        # 4-byte align
        while len(buffer) % 4:
            buffer.append(0)
        off = len(buffer)
        data = arr.tobytes()
        buffer.extend(data)
        view = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        views.append(view)
        comps = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[type_]
        acc = {"bufferView": len(views) - 1, "componentType": comp_type,
               "count": arr.size // comps, "type": type_}
        if mn is not None:
            acc["min"] = [float(v) for v in mn]
            acc["max"] = [float(v) for v in mx]
        accessors.append(acc)
        return len(accessors) - 1

    def save(self, path_gltf, path_bin=None):
        """Write .gltf (+ external .bin). If path_bin is None and filename endswith
        .glb, embed buffer as GLB chunk."""
        glb = path_gltf.endswith(".glb")
        buffer = bytearray()
        views, accessors = [], []
        mesh_out = []
        for mi in range(len(self.meshes)):
            prims = self._pack_prims(mi, buffer, views, accessors, glb)
            mesh_out.append({"name": self.meshes[mi]["name"], "primitives": prims})
        # cleanup byteStride None
        for v in views:
            if v["byteStride"] is None:
                del v["byteStride"]
        while len(buffer) % 4:
            buffer.append(0)

        images = [{"uri": u} for u in self._images]
        doc = {
            "asset": {"version": "2.0", "generator": "sf-city-builder pipeline"},
            "scene": 0,
            "scenes": [{"nodes": self.roots, "name": "tile"}],
            "nodes": self.nodes,
            "meshes": mesh_out,
            "materials": self.materials,
            "accessors": accessors,
            "bufferViews": views,
        }
        if self.textures:
            doc["textures"] = self.textures
            doc["samplers"] = [{"wrapS": REPEAT, "wrapT": REPEAT,
                                "minFilter": LINEAR_MIPMAP_LINEAR, "magFilter": LINEAR}]
        if images:
            doc["images"] = images
        if glb:
            doc["buffers"] = [{"byteLength": len(buffer)}]
            json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
            while len(json_bytes) % 4:
                json_bytes += b" "
            while len(buffer) % 4:
                buffer.append(0)
            total = 12 + 8 + len(json_bytes) + 8 + len(buffer)
            os.makedirs(os.path.dirname(path_gltf), exist_ok=True)
            with open(path_gltf, "wb") as f:
                f.write(struct.pack("<III", 0x46546C67, 2, total))
                f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
                f.write(json_bytes)
                f.write(struct.pack("<II", len(buffer), 0x004E4942))
                f.write(bytes(buffer))
        else:
            bin_name = os.path.basename(path_bin)
            doc["buffers"] = [{"uri": bin_name, "byteLength": len(buffer)}]
            os.makedirs(os.path.dirname(path_gltf), exist_ok=True)
            with open(path_gltf, "w") as f:
                json.dump(doc, f, separators=(",", ":"))
            with open(path_bin, "wb") as f:
                f.write(bytes(buffer))
