"""Assemble a civmap: hex grid + terrain + states + cities + districts + wonders."""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon, box, shape

from . import geo, sources, terrain as T
from .countries import codes, find_country
from .districts import assign_districts

PALETTE = [
    "#d9534f", "#3b7dd8", "#e0a526", "#8e5bd0", "#2fa37a", "#e06a2c",
    "#c2417f", "#3aa6b9", "#9aae2e", "#b07a46", "#5866c9", "#d4527b",
]

FUEL_ICON = {"Coal": "coal", "Gas": "gas", "Oil": "oil", "Petcoke": "oil", "Nuclear": "uranium",
             "Hydro": "hydro", "Solar": "solar", "Wind": "wind", "Geothermal": "geothermal",
             "Biomass": "biomass", "Waste": "biomass", "Wave and Tidal": "hydro"}


@dataclass
class Inputs:
    """Everything the builder needs, already loaded. Tests construct this by hand."""
    name: str
    iso2: str
    iso3: str
    land: object                     # shapely geometry of the country, lon/lat
    neighbours: list                 # [(name, geometry lon/lat)]
    states: list                     # [(name, geometry lon/lat)]
    elevation: Callable              # f(lon[], lat[]) -> metres[]
    climate: Callable                # f(lon[], lat[]) -> (rain mm/yr[], temp °C[], grid elev m[])
    cities: list = field(default_factory=list)
    airports: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    power: list = field(default_factory=list)
    universities: list = field(default_factory=list)
    heritage: list = field(default_factory=list)
    parks: list = field(default_factory=list)
    rivers: list = field(default_factory=list)   # [(name, scalerank, geometry lon/lat)]
    lakes: list = field(default_factory=list)    # [geometry lon/lat]
    regions: list = field(default_factory=list)  # [(name, kind, scalerank, geometry lon/lat)]
    seas: list = field(default_factory=list)     # [(name, scalerank, geometry lon/lat)]
    stats: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def main_landmass(geom, max_gap_km: float = 1100.0):
    """Drop far-away overseas parts (territories on other continents, remote islets).

    A part is kept when it lies within ``max_gap_km`` of a part already kept,
    starting from the largest, so island chains survive but far territories do not.
    """
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    if len(parts) == 1:
        return geom
    parts.sort(key=lambda p: -p.area)
    kept, rest = [parts[0]], parts[1:]
    changed = True
    while changed and rest:
        changed = False
        for p in list(rest):
            lat = p.representative_point().y
            # degrees -> km, conservatively using the smaller (longitude) scale
            deg = min(shapely.distance(p, k) for k in kept)
            if deg * 111.2 * max(math.cos(math.radians(lat)), 0.2) <= max_gap_km:
                kept.append(p)
                rest.remove(p)
                changed = True
    return MultiPolygon(kept) if len(kept) > 1 else kept[0]


SEAT_RANK = {"PPLC": 4, "PPLA": 3, "PPLA2": 2, "PPLA3": 1}


def merge_urban_duplicates(cities: list[dict], xy, size: float) -> list[dict]:
    """GeoNames sometimes lists a big suburb above the city it belongs to
    (e.g. Rasapudipalem above Visakhapatnam). When two entries sit within one
    hex radius, keep one entry with the administrative seat's name and the
    larger population."""
    cities = sorted(cities, key=lambda c: -c["pop"])
    out: list[dict] = []
    pos: list[tuple[float, float]] = []
    for c in cities:
        x, y = (float(v) for v in xy(c))
        hit = next((k for k, (a, b) in enumerate(pos) if math.hypot(a - x, b - y) < size), None)
        if hit is None:
            out.append(dict(c))
            pos.append((x, y))
            continue
        big = out[hit]
        if SEAT_RANK.get(c.get("fcode"), 0) > SEAT_RANK.get(big.get("fcode"), 0) and c["pop"] >= 0.25 * big["pop"]:
            out[hit] = dict(c, pop=big["pop"], lat=big["lat"], lon=big["lon"])
    return sorted(out, key=lambda c: -c["pop"])


def group_admin1(units: list[dict], max_units: int = 60) -> list:
    """Admin-1 units as (name, geometry). Countries with very many small units
    (UK counties, Italian provinces) are merged into their Natural Earth region."""
    if len(units) > max_units:
        regions = [u["properties"].get("region") for u in units]
        names = {r for r in regions if r}
        if all(regions) and 4 <= len(names) <= 40:
            groups: dict[str, list] = {}
            for u, r in zip(units, regions):
                groups.setdefault(r, []).append(shapely.make_valid(shape(u["geometry"])))
            return [(r, shapely.union_all(gs)) for r, gs in sorted(groups.items())]
    return [(u["properties"].get("name") or u["properties"].get("name_en") or "?",
             shapely.make_valid(shape(u["geometry"]))) for u in units]


def _color_states(n, adjacency):
    order = sorted(range(n), key=lambda i: -len(adjacency[i]))
    colors = [-1] * n
    for i in order:
        used = {colors[j] for j in adjacency[i]}
        c = 0
        while c in used:
            c += 1
        colors[i] = c
    return [PALETTE[c % len(PALETTE)] for c in colors]


def _fmt_pop(n: float) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.1f}M".replace(".0M", "M")
    if n >= 1e3:
        return f"{round(n / 1e3)}K"
    return str(int(n))


# ------------------------------------------------------------------ build
def build(inp: Inputs, target_hexes: int = 5000, log: Callable = lambda *_: None, aspect: float = 1.7,
          max_frame_hexes: int = 34000) -> dict:
    t0 = time.time()
    land = inp.land
    lon_c, lat_c = land.centroid.x, land.centroid.y
    proj = geo.LAEA(lon_c, lat_c)
    land_p = shapely.make_valid(proj.geom(land))
    area = land_p.area
    size = geo.hex_size_for(area, target_hexes)
    minx, miny, maxx, maxy = land_p.bounds
    # keep the whole frame (land + sea + neighbours) to a size browsers draw smoothly
    for _ in range(3):
        pad = 4 * size
        fw, fh = maxx - minx + 2 * pad, maxy - miny + 2 * pad
        fa = max(fw, fh * aspect) * max(fh, fw / aspect)
        if fa / (1.5 * geo.SQRT3 * size * size) <= max_frame_hexes:
            break
        size = math.sqrt(fa / (max_frame_hexes * 1.5 * geo.SQRT3))
    pad = 4 * size
    frame = [minx - pad, miny - pad, maxx + pad, maxy + pad]
    # widen to a landscape aspect so the map fills a screen edge to edge
    fw, fh = frame[2] - frame[0], frame[3] - frame[1]
    if fw / fh < aspect:
        grow = (fh * aspect - fw) / 2
        frame[0] -= grow
        frame[2] += grow
    else:
        grow = (fw / aspect - fh) / 2
        frame[1] -= grow
        frame[3] += grow
    frame = tuple(frame)
    q, r = geo.hex_grid(frame, size)
    x, y = geo.hex_center(q, r, size)
    n = len(q)
    log(f"grid: {n} hexes, circumradius {size:.1f} km")

    # ownership: 0 = this country, 1 = neighbour, 2 = water
    shapely.prepare(land_p)
    owner = np.full(n, 2, dtype=np.int8)
    own = shapely.contains_xy(land_p, x, y)
    index = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(q, r))}
    # make sure small islands get at least one hex
    parts = list(land_p.geoms) if hasattr(land_p, "geoms") else [land_p]
    hex_area = 1.5 * geo.SQRT3 * size * size
    for part in parts:
        if part.area < 0.08 * hex_area:
            continue
        if not shapely.contains_xy(part, x, y).any():
            pt = part.representative_point()
            hq, hr = geo.point_to_hex(pt.x, pt.y, size)
            i = index.get((int(hq), int(hr)))
            if i is not None:
                own[i] = True
    owner[own] = 0

    frame_box = box(*frame)
    # lon/lat box around the frame: clip inputs to it before projecting, so that
    # huge far-away polygons (oceans, continents) never wrap around the sphere
    ex = np.linspace(frame[0], frame[2], 40)
    ey = np.linspace(frame[1], frame[3], 40)
    bx = np.concatenate([ex, ex, np.full(40, frame[0]), np.full(40, frame[2])])
    by = np.concatenate([np.full(40, frame[1]), np.full(40, frame[3]), ey, ey])
    blon, blat = proj.inverse(bx, by)
    ll_box = box(max(-180, blon.min() - 1), max(-89.9, blat.min() - 1), min(180, blon.max() + 1), min(89.9, blat.max() + 1))

    def P(g):
        g = shapely.make_valid(g).intersection(ll_box)
        if g.is_empty:
            return g
        return shapely.make_valid(proj.geom(g))
    neighbour_id = np.full(n, -1, dtype=np.int32)
    neighbour_names = []
    for name, g in inp.neighbours:
        gp = P(g).intersection(frame_box)
        if gp.is_empty:
            continue
        shapely.prepare(gp)
        m = shapely.contains_xy(gp, x, y) & (owner == 2)
        if m.any():
            neighbour_id[m] = len(neighbour_names)
            owner[m] = 1
            neighbour_names.append(name)

    lon, lat = proj.inverse(x, y)

    # elevation: centre + six points at 60% of the radius
    offs = [(0.0, 0.0)] + [(0.6 * size * math.cos(math.radians(60 * k)), 0.6 * size * math.sin(math.radians(60 * k))) for k in range(6)]
    sx = np.concatenate([x + dx for dx, _ in offs])
    sy = np.concatenate([y + dy for _, dy in offs])
    slon, slat = proj.inverse(sx, sy)
    samples = np.asarray(inp.elevation(slon, slat), float).reshape(len(offs), n)
    elev = samples.mean(axis=0)
    relief = samples.max(axis=0) - samples.min(axis=0)
    log(f"elevation sampled ({time.time() - t0:.1f}s)")

    rain, temp_grid, grid_elev = inp.climate(lon, lat)
    rain = np.asarray(rain, float)
    temp = T.lapse_rate_temp(temp_grid, np.maximum(elev, 0), np.maximum(np.asarray(grid_elev, float), 0))

    is_land = owner < 2
    ter, feat, hills = T.classify_land(elev, relief, rain, temp)
    # water
    lake = np.zeros(n, bool)
    for g in inp.lakes:
        gp = P(g)
        if not gp.is_empty:
            lake |= shapely.contains_xy(gp, x, y)
    ter = ter.astype(np.int8)
    ter[~is_land] = T.OCEAN
    ter[lake & is_land] = T.LAKE
    feat[~is_land | lake] = T.NONE
    hills[~is_land | lake] = False

    nbr = np.full((n, 6), -1, dtype=np.int64)
    for k, (dq, dr) in enumerate(geo.EDGE_NEIGHBOUR):
        for i in range(n):
            j = index.get((int(q[i]) + dq, int(r[i]) + dr))
            if j is not None:
                nbr[i, k] = j
    land_nb = np.zeros(n, bool)
    for k in range(6):
        j = nbr[:, k]
        ok = j >= 0
        land_nb[ok] |= is_land[j[ok]] & ~lake[j[ok]]
    coast = ~is_land & land_nb
    ter[coast] = T.COAST
    ter[lake & is_land] = T.LAKE

    # rivers
    river = np.zeros(n, bool)
    river_lines = []
    for name, rank, g in inp.rivers:
        gp = P(g).intersection(frame_box)
        if gp.is_empty:
            continue
        lines = list(gp.geoms) if hasattr(gp, "geoms") else [gp]
        for ln in lines:
            if ln.geom_type != "LineString" or ln.length < size * 0.5:
                continue
            ln = ln.simplify(size * 0.08)
            pts = np.asarray(ln.coords)[:, :2]
            dens = [ln.interpolate(d).coords[0] for d in np.arange(0, ln.length, size * 0.5)]
            if dens:
                dq, dr = geo.point_to_hex(np.array([p[0] for p in dens]), np.array([p[1] for p in dens]), size)
                for a, b in zip(dq, dr):
                    i = index.get((int(a), int(b)))
                    if i is not None and is_land[i]:
                        river[i] = True
            river_lines.append({"w": round(max(0.7, (11 - float(rank)) / 3.2), 2),
                                "n": name or "",
                                "p": np.round(pts, 1).ravel().tolist()})
    feat[river & (feat == T.NONE) & ((ter == T.DESERT) | (ter == T.PLAINS))] = T.FLOODPLAINS

    # states
    state_id = np.full(n, -1, dtype=np.int32)
    st_geoms = [P(g) for _, g in inp.states]
    own_idx = np.where(owner == 0)[0]
    if st_geoms:
        tree = shapely.STRtree(st_geoms)
        pts = shapely.points(x[own_idx], y[own_idx])
        hit_pt, hit_geom = tree.query(pts, predicate="within")
        state_id[own_idx[hit_pt]] = hit_geom
        miss = own_idx[state_id[own_idx] < 0]
        if len(miss):
            state_id[miss] = tree.nearest(shapely.points(x[miss], y[miss]))
    adjacency = [set() for _ in st_geoms]

    def corner(i, k):
        a = math.radians(60 * k - 90)
        return (x[i] + size * math.cos(a), y[i] + size * math.sin(a))

    country_edges, state_edges = [], []
    for i in own_idx:
        for k in range(6):
            j = nbr[i, k]
            c1, c2 = corner(i, k), corner(i, (k + 1) % 6)
            seg = [round(c1[0], 1), round(c1[1], 1), round(c2[0], 1), round(c2[1], 1)]
            if j < 0 or owner[j] != 0:
                country_edges.append(seg)
            elif state_id[j] != state_id[i] and state_id[i] >= 0 and state_id[j] >= 0:
                adjacency[state_id[i]].add(int(state_id[j]))
                if i < j:
                    state_edges.append(seg)
    colors = _color_states(len(st_geoms), adjacency) if st_geoms else []

    # ---------------------------------------------------------------- points
    def locate(items, own_only=True):
        if not items:
            return np.zeros(0, int), []
        px, py = proj.forward([it["lon"] for it in items], [it["lat"] for it in items])
        hq, hr = geo.point_to_hex(px, py, size)
        idx, kept = [], []
        for it, a, b, X, Y in zip(items, hq, hr, px, py):
            i = index.get((int(a), int(b)))
            if i is None:
                continue
            if own_only and owner[i] != 0:
                # allow points sitting just offshore of our coast (ports, islands)
                near = [j for j in nbr[i] if j >= 0 and owner[j] == 0]
                if owner[i] != 2 or not near:
                    continue
                i = int(near[0])
            it = dict(it, x=float(X), y=float(Y), hex=int(i))
            idx.append(i)
            kept.append(it)
        return np.array(idx, int), kept

    _, cities = locate(merge_urban_duplicates(
        [c for c in inp.cities if c.get("fcode") != "PPLX"],  # PPLX = a section of a bigger place
        lambda c: proj.forward(c["lon"], c["lat"]), size))
    _, airports = locate(inp.airports)
    _, ports = locate(inp.ports)
    _, power = locate(inp.power)
    _, unis = locate(inp.universities)
    _, heritage = locate(inp.heritage)
    _, parks = locate(inp.parks)

    citizens = np.zeros(n)
    for c in cities:
        citizens[c["hex"]] += c["pop"]
    power_mw = np.zeros(n)
    for p in power:
        power_mw[p["hex"]] += p["mw"]
    sci = np.zeros(n)
    for u in unis:
        sci[u["hex"]] += 1
    cul = np.zeros(n)
    for h in heritage:
        cul[h["hex"]] += 3
    for p in parks:
        cul[p["hex"]] += 1
    gold = np.zeros(n)
    for a in airports:
        gold[a["hex"]] += 3 if a["kind"] == "large" else 1
    for p in ports:
        gold[p["hex"]] += 2
    gold += np.where(citizens >= 1e5, np.floor(np.log10(np.maximum(citizens, 1)) - 4), 0)

    food, prod = T.base_yields(ter, feat, hills, river)
    prod += np.minimum(4, np.floor(power_mw / 500.0))

    # ---------------------------------------------------------------- cities
    radius = max(35.0, 2.2 * size)
    total_pop = sum(c["pop"] for c in cities) or 1
    banners, chosen = [], []
    for c in cities:
        if len(banners) >= 48:
            break
        if any(math.hypot(c["x"] - b["x"], c["y"] - b["y"]) < 3.4 * size for b in chosen):
            if c.get("fcode") != "PPLC":
                continue
        chosen.append(c)
        banners.append(c)
    for c in cities:  # the capital always gets a banner (or merges into a bigger neighbour)
        if c.get("fcode") == "PPLC" and c not in banners:
            host = next((b for b in banners if math.hypot(c["x"] - b["x"], c["y"] - b["y"]) < 3.4 * size), None)
            if host is None:
                banners.append(c)
            else:
                host["capitalOf"] = c["name"]
            break
    assign_districts(banners, {
        "universities": unis, "power": power, "airports": airports, "ports": ports,
        "heritage": heritage, "parks": parks,
    }, radius_km=radius, total_pop=total_pop, coast=lambda i: any(nbr[i, k] >= 0 and ter[nbr[i, k]] in (T.COAST, T.OCEAN) for k in range(6)))

    city_out = []
    for rank, c in enumerate(banners):
        city_out.append({
            "name": c["name"], "x": round(c["x"], 1), "y": round(c["y"], 1), "pop": c["pop"],
            "popLabel": _fmt_pop(c["pop"]), "capital": c.get("fcode") == "PPLC" or "capitalOf" in c,
            "seat": c.get("fcode") == "PPLA", "state": int(state_id[c["hex"]]),
            "districts": c["districts"], "epithet": c.get("epithet", ""), "rank": rank,
        })
    towns = [{"name": c["name"], "x": round(c["x"], 1), "y": round(c["y"], 1), "pop": c["pop"]}
             for c in cities if c not in banners and c["pop"] >= 100000][:600]

    # ---------------------------------------------------------------- resources & wonders
    resources = []
    by_fuel: dict[str, list] = {}
    for p in power:
        by_fuel.setdefault(FUEL_ICON.get(p["fuel"], "other"), []).append(p)
    for kind, items in by_fuel.items():
        items.sort(key=lambda p: -p["mw"])
        for p in items[:28]:
            if p["mw"] >= 50:
                resources.append({"k": kind, "x": round(p["x"], 1), "y": round(p["y"], 1),
                                  "n": p["name"], "mw": round(p["mw"])})
    for a in airports:
        if a["kind"] == "large":
            resources.append({"k": "airport", "x": round(a["x"], 1), "y": round(a["y"], 1), "n": a["name"]})
    for p in ports:
        resources.append({"k": "port", "x": round(p["x"], 1), "y": round(p["y"], 1), "n": p["name"]})
    wonders = [{"n": h["name"], "x": round(h["x"], 1), "y": round(h["y"], 1), "natural": bool(h.get("natural"))}
               for h in heritage]

    # ---------------------------------------------------------------- labels
    states_out = []
    for s, (name, _) in enumerate(inp.states):
        m = state_id == s
        cnt = int(m.sum())
        if cnt == 0:
            continue
        # label at the hex deepest inside the state (most same-state neighbours, near centroid)
        mx, my = x[m].mean(), y[m].mean()
        states_out.append({"id": s, "name": name, "color": colors[s], "hexes": cnt,
                           "lx": round(float(mx), 1), "ly": round(float(my), 1)})
    foreign = []
    for k, name in enumerate(neighbour_names):
        m = neighbour_id == k
        if m.sum() >= 25:
            foreign.append({"name": name, "x": round(float(x[m].mean()), 1), "y": round(float(y[m].mean()), 1),
                            "hexes": int(m.sum())})
    regions = []
    for name, kind, rank, g in inp.regions:
        if rank > 5:
            continue
        gp = P(g)
        if gp.is_empty or not gp.intersects(land_p):
            continue
        inter = gp.intersection(land_p)
        if inter.area < 0.1 * gp.area or inter.area < 12 * hex_area:
            continue
        pt = inter.representative_point()
        regions.append({"n": name, "k": kind, "x": round(pt.x, 1), "y": round(pt.y, 1), "r": rank})
    seas = []
    for name, rank, g in inp.seas:
        gp = P(g).intersection(frame_box)
        if gp.is_empty or gp.area < 30 * hex_area:
            continue
        pt = gp.representative_point()
        seas.append({"n": name, "x": round(pt.x, 1), "y": round(pt.y, 1), "r": rank})

    def r1(a, k=0):
        return np.round(a, k).astype(int if k == 0 else float).tolist()

    out = {
        "version": 1,
        "meta": {
            "name": inp.name, "iso2": inp.iso2, "iso3": inp.iso3,
            "hexSize": round(size, 3), "hexAreaKm2": round(hex_area, 1),
            "landHexes": int((owner == 0).sum()), "center": [round(lon_c, 4), round(lat_c, 4)],
            "generated": time.strftime("%Y-%m-%d"), "stats": inp.stats, "notes": inp.notes,
            "counts": {"cities15k": len(cities), "airports": len(airports), "ports": len(ports),
                       "powerPlants": len(power), "powerMW": round(float(power_mw.sum())),
                       "universities": len(unis), "heritage": len(heritage), "parks": len(parks)},
        },
        "frame": [round(v, 1) for v in frame],
        "hex": {
            "q": q.tolist(), "r": r.tolist(), "o": owner.tolist(), "t": ter.tolist(),
            "f": feat.tolist(), "h": hills.astype(int).tolist(), "rv": river.astype(int).tolist(),
            "e": r1(elev), "rl": r1(relief), "p": r1(np.where(is_land, rain, 0)),
            "tc": r1(np.where(is_land, temp, 0), 1), "s": state_id.tolist(),
            "nb": neighbour_id.tolist(),
            "food": r1(food), "prod": r1(prod), "gold": r1(gold), "sci": r1(sci), "cul": r1(cul),
            "cit": r1(citizens), "mw": r1(power_mw),
        },
        "neighbours": neighbour_names,
        "states": states_out,
        "borders": {"country": country_edges, "state": state_edges},
        "rivers": river_lines,
        "cities": city_out, "towns": towns,
        "resources": resources, "wonders": wonders,
        "regions": regions, "seas": seas, "foreign": foreign,
    }
    log(f"built in {time.time() - t0:.1f}s")
    return out


# ------------------------------------------------------------------ data gathering (network)
class TerrariumSampler:
    def __init__(self, bbox, cell_km, max_tiles=260):
        lon0, lat0, lon1, lat1 = bbox
        latm = math.radians(max(abs(lat0), abs(lat1)) if lat0 * lat1 > 0 else 0)
        z = int(math.ceil(math.log2(40075 * math.cos(latm) / (256 * max(cell_km, 0.3)))))
        z = max(3, min(9, z))
        while True:
            x0, y1 = self._tile(lon0, lat0, z)
            x1, y0 = self._tile(lon1, lat1, z)
            if (x1 - x0 + 1) * (y1 - y0 + 1) <= max_tiles or z <= 3:
                break
            z -= 1
        self.z = z
        self.tiles = {}
        jobs = [(z, tx, ty) for tx in range(x0, x1 + 1) for ty in range(y0, y1 + 1)]
        with ThreadPoolExecutor(12) as ex:
            for key, arr in zip(jobs, ex.map(self._get, jobs)):
                self.tiles[key[1:]] = arr

    @staticmethod
    def _get(job):
        z, x, y = job
        try:
            return sources.terrarium_tile(z, x, y)
        except Exception:
            return None

    @staticmethod
    def _tile(lon, lat, z):
        n = 2 ** z
        lat = max(min(lat, 85.0), -85.0)
        x = int((lon + 180) / 360 * n)
        y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
        return min(max(x, 0), n - 1), min(max(y, 0), n - 1)

    def __call__(self, lon, lat):
        n = 2 ** self.z
        lon = np.asarray(lon, float)
        lat = np.clip(np.asarray(lat, float), -85, 85)
        gx = (lon + 180) / 360 * n * 256
        gy = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n * 256
        tx, ty = (gx // 256).astype(int), (gy // 256).astype(int)
        px, py = (gx % 256).astype(int), (gy % 256).astype(int)
        out = np.zeros(lon.shape)
        for key in set(zip(tx.tolist(), ty.tolist())):
            arr = self.tiles.get(key)
            m = (tx == key[0]) & (ty == key[1])
            if arr is not None:
                out[m] = arr[py[m], px[m]]
        return out


class PowerClimate:
    """Nearest-neighbour lookup on NASA POWER's 0.5° x 0.625° climatology grid."""

    def __init__(self, bbox):
        rain = sources.nasa_power_grid("PRECTOTCORR", bbox)
        temp = sources.nasa_power_grid("T2M", bbox)
        self.ok = bool(rain and temp)
        self.rain = {(round(lo / 0.625), round(la / 0.5)): v * 365.25 for lo, la, v in rain}
        self.temp = {(round(lo / 0.625), round(la / 0.5)): v for lo, la, v in temp}
        self.elev = {}
        for lo, la, _ in temp:
            self.elev[(round(lo / 0.625), round(la / 0.5))] = 0.0
        self._grid_elev(bbox)

    def _grid_elev(self, bbox):
        # POWER returns the grid cell elevation as the third coordinate
        import json
        lon0, lat0, lon1, lat1 = bbox
        for path in (sources.cache_dir() / "power").glob("T2M_*.json"):
            try:
                gj = json.loads(path.read_bytes())
            except Exception:
                continue
            for f in gj.get("features", []):
                c = f["geometry"]["coordinates"]
                if len(c) > 2:
                    self.elev[(round(c[0] / 0.625), round(c[1] / 0.5))] = float(c[2])

    def _look(self, table, lon, lat, default):
        out = np.empty(len(lon))
        for i, (lo, la) in enumerate(zip(lon, lat)):
            k = (round(lo / 0.625), round(la / 0.5))
            v = table.get(k)
            if v is None:
                for d in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                    v = table.get((k[0] + d[0], k[1] + d[1]))
                    if v is not None:
                        break
            out[i] = default if v is None else v
        return out

    def __call__(self, lon, lat):
        lon, lat = np.asarray(lon), np.asarray(lat)
        fallback_t = 28 - 0.45 * np.abs(lat)
        rain = self._look(self.rain, lon, lat, np.nan)
        temp = self._look(self.temp, lon, lat, np.nan)
        elev = self._look(self.elev, lon, lat, 0.0)
        rain = np.where(np.isnan(rain), 800.0, rain)
        temp = np.where(np.isnan(temp), fallback_t, temp)
        return rain, temp, elev


def _bbox_lonlat(geom, pad_deg):
    a, b, c, d = geom.bounds
    return (max(a - pad_deg, -180), max(b - pad_deg, -89), min(c + pad_deg, 180), min(d + pad_deg, 89))


def cross_check_populations(cities: list[dict], tag: str, top: int = 150, lookup=None) -> list[dict]:
    """GeoNames occasionally gives a town its whole district's population.
    For the biggest entries, compare with Wikidata (matched on the GeoNames id)
    and keep the smaller figure when they disagree by more than 2x."""
    lookup = lookup or sources.wikidata_populations
    big = sorted(cities, key=lambda c: -c["pop"])[:top]
    wd = lookup([c["gid"] for c in big if c.get("gid")], tag)
    out = []
    for c in cities:
        p = wd.get(c.get("gid"))
        if p and 0 < p < 0.5 * c["pop"]:
            c = dict(c, pop=int(p), popSource="Wikidata")
        out.append(c)
    return out


def gather(query: str, target_hexes: int = 5000, log: Callable = print) -> Inputs:
    """Download (or read from cache) every dataset for one country."""
    base = sources.natural_earth("ne_10m_admin_0_countries")
    f = find_country(base["features"], query)
    iso2, iso3, name = codes(f)
    layer = sources.admin0_layer(iso3)
    feats = layer["features"]
    try:
        f = next(g for g in feats if g["properties"].get("ADM0_A3") == iso3)
    except StopIteration:
        pass
    land = main_landmass(shapely.make_valid(shape(f["geometry"])))
    log(f"{name} ({iso2}/{iso3})")
    area_deg = land.area
    size_deg = math.sqrt(area_deg / (target_hexes * 2.6))
    bbox = _bbox_lonlat(land, 6 * size_deg + 0.5)
    lon_span = (bbox[2] - bbox[0]) * math.cos(math.radians((bbox[1] + bbox[3]) / 2))
    lat_span = bbox[3] - bbox[1]
    if lon_span < 1.75 * lat_span:  # leave room for the landscape frame
        extra = (1.75 * lat_span - lon_span) / 2 / max(0.2, math.cos(math.radians((bbox[1] + bbox[3]) / 2)))
        bbox = (max(bbox[0] - extra, -180), bbox[1], min(bbox[2] + extra, 180), bbox[3])
    else:
        extra = (lon_span / 1.75 - lat_span) / 2
        bbox = (bbox[0], max(bbox[1] - extra, -89), bbox[2], min(bbox[3] + extra, 89))
    frame = box(*bbox)

    neighbours = []
    for g in feats:
        p = g["properties"]
        if p.get("ADM0_A3") == iso3:
            continue
        geom = shape(g["geometry"])
        if geom.intersects(frame):
            neighbours.append((p.get("NAME") or p.get("NAME_EN"), shapely.make_valid(geom)))

    admin1 = sources.natural_earth("ne_10m_admin_1_states_provinces")
    units = [g for g in admin1["features"] if g["properties"].get("adm0_a3") == iso3]
    states = group_admin1(units)

    rivers = []
    for g in sources.natural_earth("ne_10m_rivers_lake_centerlines")["features"]:
        geom = shape(g["geometry"])
        if geom.intersects(frame):
            p = g["properties"]
            rivers.append((p.get("name_en") or p.get("name") or "", p.get("scalerank") or 9, geom))
    lakes = [shape(g["geometry"]) for g in sources.natural_earth("ne_10m_lakes")["features"]
             if g["properties"].get("featurecla") != "Alkaline Lake"  # mostly dry salt pans
             and shape(g["geometry"]).intersects(frame)]
    regions = []
    for g in sources.natural_earth("ne_10m_geography_regions_polys")["features"]:
        p = g["properties"]
        if p["FEATURECLA"] in ("Island", "Island group", "Continent", "Coast", "Dragons-be-here", "Pen/cape"):
            continue
        geom = shapely.make_valid(shape(g["geometry"]))
        if geom.intersects(frame):
            regions.append(((p.get("NAME_EN") or p["NAME"]).title(), p["FEATURECLA"], p["SCALERANK"], geom))
    seas = []
    for g in sources.natural_earth("ne_10m_geography_marine_polys")["features"]:
        p = g["properties"]
        geom = shapely.make_valid(shape(g["geometry"]))
        if geom.intersects(frame):
            seas.append(((p.get("name_en") or p.get("name") or "").strip(), p.get("scalerank") or 9, geom))

    log("cities, airports, ports, power plants…")
    cities = sources.cities(iso2)
    try:
        cities = cross_check_populations(cities, iso2)
    except Exception as exc:
        log(f"  (population cross-check skipped: {exc})")
    airports = sources.airports(iso2)
    ports = sources.ports(bbox)
    power = sources.power_plants(iso3)
    log("wikidata: universities, world heritage, national parks…")
    notes = []
    try:
        qid = sources.country_qid(iso2)
        unis = sources.wikidata("universities", qid)
        heritage = sources.wikidata("heritage", qid)
        parks = sources.wikidata("parks", qid)
    except Exception as exc:  # Wikidata is occasionally slow; the map still works
        unis, heritage, parks = [], [], []
        notes.append(f"Wikidata unavailable: {exc}")
    gdp, gdp_year = sources.world_bank(iso3, "NY.GDP.MKTP.CD")
    pop, pop_year = sources.world_bank(iso3, "SP.POP.TOTL")
    stats = {"gdpUSD": gdp, "gdpYear": gdp_year, "population": pop, "populationYear": pop_year}

    log("elevation tiles…")
    cell_km = geo.hex_size_for(geo.LAEA(land.centroid.x, land.centroid.y).geom(land).area, target_hexes) / 8
    elevation = TerrariumSampler(bbox, cell_km)
    log(f"  terrarium zoom {elevation.z}, {len(elevation.tiles)} tiles")
    log("NASA POWER climatology…")
    climate = PowerClimate(bbox)
    if not climate.ok:
        notes.append("NASA POWER climatology unavailable; terrain used a latitude fallback")

    return Inputs(name=name, iso2=iso2, iso3=iso3, land=land, neighbours=neighbours, states=states,
                  elevation=elevation, climate=climate, cities=cities, airports=airports, ports=ports,
                  power=power, universities=unis, heritage=heritage, parks=parks, rivers=rivers,
                  lakes=lakes, regions=regions, seas=seas, stats=stats, notes=notes)
