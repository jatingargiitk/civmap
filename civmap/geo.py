"""Projection and hex-grid geometry.

civmap uses a spherical Lambert azimuthal equal-area projection centred on the
country, so every hex covers (very nearly) the same real area. Map coordinates
are kilometres with x pointing east and y pointing *south* (screen order).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

R_EARTH = 6371.0088
SQRT3 = math.sqrt(3.0)


@dataclass(frozen=True)
class LAEA:
    lon0: float
    lat0: float

    def forward(self, lon, lat):
        lam = np.radians(np.asarray(lon, dtype=float) - self.lon0)
        phi = np.radians(np.asarray(lat, dtype=float))
        phi0 = math.radians(self.lat0)
        cosc = math.sin(phi0) * np.sin(phi) + math.cos(phi0) * np.cos(phi) * np.cos(lam)
        k = np.sqrt(2.0 / np.clip(1.0 + cosc, 1e-12, None))
        x = R_EARTH * k * np.cos(phi) * np.sin(lam)
        y = R_EARTH * k * (math.cos(phi0) * np.sin(phi) - math.sin(phi0) * np.cos(phi) * np.cos(lam))
        return x, -y  # y down

    def inverse(self, x, y):
        x = np.asarray(x, dtype=float)
        y = -np.asarray(y, dtype=float)
        rho = np.hypot(x, y)
        c = 2.0 * np.arcsin(np.clip(rho / (2.0 * R_EARTH), -1, 1))
        phi0 = math.radians(self.lat0)
        with np.errstate(invalid="ignore", divide="ignore"):
            lat = np.arcsin(np.cos(c) * math.sin(phi0) + np.where(rho == 0, 0, y * np.sin(c) * math.cos(phi0) / np.where(rho == 0, 1, rho)))
            lon = self.lon0 + np.degrees(np.arctan2(x * np.sin(c), rho * math.cos(phi0) * np.cos(c) - y * math.sin(phi0) * np.sin(c)))
        return lon, np.degrees(lat)

    def geom(self, g):
        """Project a shapely geometry (lon/lat) into map km."""
        import shapely

        def f(coords):
            x, y = self.forward(coords[:, 0], coords[:, 1])
            return np.column_stack([x, y])

        return shapely.transform(g, f)


# --------------------------------------------------------------------- hexes
# Pointy-top hexes in axial coordinates (q, r). ``size`` is the circumradius.
NEIGHBOURS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def hex_center(q, r, size):
    q = np.asarray(q, dtype=float)
    r = np.asarray(r, dtype=float)
    return size * SQRT3 * (q + r / 2.0), size * 1.5 * r


def hex_round(qf, rf):
    qf = np.asarray(qf, dtype=float)
    rf = np.asarray(rf, dtype=float)
    sf = -qf - rf
    q, r, s = np.round(qf), np.round(rf), np.round(sf)
    dq, dr, ds = np.abs(q - qf), np.abs(r - rf), np.abs(s - sf)
    fix_q = (dq > dr) & (dq > ds)
    fix_r = ~fix_q & (dr > ds)
    q = np.where(fix_q, -r - s, q)
    r = np.where(fix_r, -q - s, r)
    return q.astype(int), r.astype(int)


def point_to_hex(x, y, size):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    qf = (SQRT3 / 3.0 * x - y / 3.0) / size
    rf = (2.0 / 3.0 * y) / size
    return hex_round(qf, rf)


def hex_corners(cx, cy, size):
    """Six corners, starting at the top and going clockwise (screen coords)."""
    out = []
    for i in range(6):
        a = math.radians(60 * i - 90)
        out.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    return out


# edge i of a hex (between corner i and corner i+1) faces this neighbour:
EDGE_NEIGHBOUR = [(1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1)]


def hex_grid(bounds, size):
    """All axial cells whose centres fall inside ``bounds`` (minx, miny, maxx, maxy)."""
    minx, miny, maxx, maxy = bounds
    r0 = int(math.floor(miny / (1.5 * size))) - 1
    r1 = int(math.ceil(maxy / (1.5 * size))) + 1
    qs, rs = [], []
    w = size * SQRT3
    for r in range(r0, r1 + 1):
        q0 = int(math.floor(minx / w - r / 2.0)) - 1
        q1 = int(math.ceil(maxx / w - r / 2.0)) + 1
        for q in range(q0, q1 + 1):
            qs.append(q)
            rs.append(r)
    q = np.array(qs)
    r = np.array(rs)
    x, y = hex_center(q, r, size)
    keep = (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy)
    return q[keep], r[keep]


def hex_size_for(area_km2: float, target_hexes: int) -> float:
    """Circumradius that tiles ``area_km2`` with about ``target_hexes`` hexes."""
    return math.sqrt(area_km2 / (target_hexes * 1.5 * SQRT3))


def haversine_km(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))
