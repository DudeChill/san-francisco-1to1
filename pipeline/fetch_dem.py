"""Fetch AWS terrain terrarium DEM tiles (z14) covering the city bbox -> data_raw/dem.npz."""
import io
import json
import math
import os
import time
import urllib.request

import numpy as np

from common import (BBOX_LAT_MIN, BBOX_LAT_MAX, BBOX_LON_MIN, BBOX_LON_MAX, DATA_RAW,
                    mark_done, is_done, dem_latlon_grid)

Z = 14
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
UA = "sf-city-builder/0.1 (research)"


def deg2tile_x(lon, z):
    return int((lon + 180.0) / 360.0 * (1 << z))


def lat2tile_y(lat, z):
    r = math.radians(lat)
    return int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * (1 << z))


def fetch(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2.0 * (2 ** i))
    raise RuntimeError(f"fetch failed {url}: {last}")


def run():
    out = os.path.join(DATA_RAW, "dem.npz")
    if is_done("dem"):
        print("[dem] cached")
        return out
    from PIL import Image
    x0, x1 = deg2tile_x(BBOX_LON_MIN, Z), deg2tile_x(BBOX_LON_MAX, Z)
    y0, y1 = lat2tile_y(BBOX_LAT_MAX, Z), lat2tile_y(BBOX_LAT_MIN, Z)
    print(f"[dem] z{Z} x {x0}-{x1}, y {y0}-{y1} -> {(x1-x0+1)*(y1-y0+1)} tiles")
    lats, lons, ddeg = dem_latlon_grid(BBOX_LAT_MIN, BBOX_LAT_MAX, BBOX_LON_MIN, BBOX_LON_MAX)
    ny, nx = len(lats), len(lons)
    elev = np.zeros((ny, nx), dtype=np.float32)
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            p = os.path.join(DATA_RAW, f"terr_{Z}_{tx}_{ty}.png")
            if not os.path.exists(p):
                raw = fetch(URL.format(z=Z, x=tx, y=ty))
                with open(p, "wb") as f:
                    f.write(raw)
            img = np.asarray(Image.open(p), dtype=np.float64)
            h = img[:, :, 0] * 256.0 + img[:, :, 1] + img[:, :, 2] / 256.0 - 32768.0
            # tile bounds in degrees (mercator-square tile)
            lon_t0 = tx / (1 << Z) * 360.0 - 180.0
            lon_t1 = (tx + 1) / (1 << Z) * 360.0 - 180.0
            n = 1 << Z
            def tile_y2lat(yy):
                return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))
            lat_t0 = tile_y2lat(ty)        # top (north)
            lat_t1 = tile_y2lat(ty + 1)    # bottom
            # source pixel grid (row 0 = north)
            src_lon = np.linspace(lon_t0, lon_t1, 257)[:-1] + 0.5 * (lon_t1 - lon_t0) / 256
            src_lat = np.linspace(lat_t0, lat_t1, 257)[:-1] + 0.5 * (lat_t0 - lat_t1) / 256
            # destination window within this tile (indices into global grid)
            ci0 = int(math.floor((lon_t0 - lons[0]) / ddeg)); ci1 = int(math.ceil((lon_t1 - lons[0]) / ddeg))
            ri0 = int(math.floor((lats[0] - lat_t0) / ddeg)); ri1 = int(math.ceil((lats[0] - lat_t1) / ddeg))
            ci0 = max(ci0, 0); ri0 = max(ri0, 0)
            ci1 = min(ci1, nx); ri1 = min(ri1, ny)
            if ci1 <= ci0 or ri1 <= ri0:
                continue
            dlon_w = lons[ci0:ci1]
            dlat_w = lats[ri0:ri1]
            # sample source bilinear at destination points (griddata-free, manual)
            sc = (dlon_w[None, :] - lon_t0) / (lon_t1 - lon_t0) * 255.0
            sr = (lat_t0 - dlat_w[:, None]) / (lat_t0 - lat_t1) * 255.0
            sc = np.clip(sc, 0, 255); sr = np.clip(sr, 0, 255)
            sc0 = np.clip(sc.astype(np.int64), 0, 254).ravel()
            sr0 = np.clip(sr.astype(np.int64), 0, 254).ravel()
            fc = (sc - sc0.reshape(1, -1))
            fr = (sr - sr0.reshape(-1, 1))
            a = h[np.ix_(sr0, sc0)] * (1 - fr) + h[np.ix_(sr0 + 1, sc0)] * fr
            b = h[np.ix_(sr0, sc0 + 1)] * (1 - fr) + h[np.ix_(sr0 + 1, sc0 + 1)] * fr
            elev[ri0:ri1, ci0:ci1] = (a * (1 - fc) + b * fc).astype(np.float32)
        print(f"[dem] row {ty - y0 + 1}/{y1 - y0 + 1} done")
    np.savez_compressed(out, elev=elev, lats=lats.astype(np.float64), lons=lons.astype(np.float64))
    meta = {"z": Z, "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "lat_min": BBOX_LAT_MIN, "lat_max": BBOX_LAT_MAX,
            "lon_min": BBOX_LON_MIN, "lon_max": BBOX_LON_MAX}
    with open(os.path.join(DATA_RAW, "dem_meta.json"), "w") as f:
        json.dump(meta, f)
    mark_done("dem", {"tiles": (x1 - x0 + 1) * (y1 - y0 + 1)})
    print(f"[dem] wrote {out} {elev.shape}")
    return out


if __name__ == "__main__":
    run()
