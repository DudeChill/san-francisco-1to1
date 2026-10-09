"""Bake instanced prop meshes -> data/props/<type>.glb (streetlight, tree, hydrant,
bus_stop). One GLB per type; origin at ground contact point, +Y up."""
import os

import numpy as np

from common import PROPS_DIR, ensure_dirs
import mesh_util as MU
from gltf import GltfScene


def build_streetlight():
    parts = []
    # pole 6 m with curved arm
    v, t = MU.cylinder(0, 0, 0, 0.10, 6.0, n=8)
    parts.append(MU.part("pole", "Mat_Prop_streetlight", [0.35, 0.36, 0.38], v, t, col=True))
    pts = np.array([[0, 6.0, 0], [0.15, 6.4, 0], [0.6, 6.7, 0], [1.15, 6.7, 0]])
    v, t = MU.tube_along(pts, 0.08, nside=6)
    parts.append(MU.part("arm", "Mat_Prop_streetlight", [0.35, 0.36, 0.38], v, t))
    v, t = MU.box(1.25, 6.45, 0, 0.5, 0.14, 0.22)
    parts.append(MU.part("head", "Mat_Prop_streetlight", [0.25, 0.25, 0.27], v, t))
    # base
    v, t = MU.cylinder(0, 0, 0, 0.22, 0.5, n=8)
    parts.append(MU.part("base", "Mat_Prop_streetlight", [0.30, 0.31, 0.33], v, t))
    return parts


def build_tree():
    parts = []
    rng = MU
    # cypress-ish: trunk + stacked foliage ellipsoids
    v, t = MU.cylinder(0, 0, 0, 0.22, 2.2, n=7)
    parts.append(MU.part("trunk", "Mat_Prop_tree", [0.35, 0.26, 0.18], v, t))
    y = 1.6
    r = 1.9
    for k in range(4):
        v, t = MU.dome(0, y, 0, r, 1.4, n=10, rings=4)
        parts.append(MU.part(f"foliage{k}", "Mat_Prop_tree", [0.18 + 0.02 * k, 0.38 + 0.02 * k, 0.16], v, t))
        y += 1.1
        r *= 0.82
    return parts


def build_hydrant():
    parts = []
    v, t = MU.cylinder(0, 0, 0, 0.16, 0.72, n=8)
    parts.append(MU.part("body", "Mat_Prop_hydrant", [0.85, 0.10, 0.10], v, t, col=True))
    v, t = MU.cylinder(0, 0.72, 0, 0.10, 0.12, n=8, r_top=0.05)
    parts.append(MU.part("cap", "Mat_Prop_hydrant", [0.85, 0.10, 0.10], v, t))
    v, t = MU.box(0, 0.35, 0, 0.5, 0.09, 0.09)
    parts.append(MU.part("side", "Mat_Prop_hydrant", [0.85, 0.10, 0.10], v, t))
    return parts


def build_bus_stop():
    parts = []
    STEEL = [0.30, 0.32, 0.35]
    GLASS = [0.55, 0.62, 0.65]
    v, t = MU.box(0, 2.6, 0, 4.2, 0.12, 1.4)     # roof
    parts.append(MU.part("roof", "Mat_Prop_bus_stop", [0.25, 0.27, 0.30], v, t))
    for x in (-1.9, 1.9):
        v, t = MU.box(x, 0, 0.55, 0.09, 2.6, 0.09)
        parts.append(MU.part("post", "Mat_Prop_bus_stop", STEEL, v, t))
        v, t = MU.box(x, 0, -0.55, 0.09, 2.6, 0.09)
        parts.append(MU.part("post2", "Mat_Prop_bus_stop", STEEL, v, t))
    v, t = MU.box(0, 0.1, -0.65, 4.0, 2.3, 0.06)  # back glass panel
    parts.append(MU.part("glass", "Mat_Prop_bus_stop", GLASS, v, t))
    v, t = MU.box(0, 0.45, -0.2, 3.6, 0.08, 0.35)  # bench
    parts.append(MU.part("bench", "Mat_Prop_bus_stop", STEEL, v, t))
    return parts


def write_glb(name, parts):
    scene = GltfScene()
    mi = scene.new_mesh(name)
    for p in parts:
        mat = scene.material(p["mat"], base_color=p["color"], roughness=0.85)
        scene.add_prim(mi, p["verts"], p["tris"], mat)
    scene.add_node(name, mi)   # root node; runtime instances this mesh
    path = os.path.join(PROPS_DIR, f"{name}.glb")
    scene.save(path)
    print(f"[props] {path} ({len(parts)} parts)")


def run():
    ensure_dirs()
    for name, fn in (("streetlight", build_streetlight), ("tree", build_tree),
                     ("hydrant", build_hydrant), ("bus_stop", build_bus_stop)):
        parts = fn()
        write_glb(name, parts)


if __name__ == "__main__":
    run()
