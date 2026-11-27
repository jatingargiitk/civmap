"""Pick Civ-style districts for each city from what is actually around it.

A city earns a district when the thing the district stands for is concentrated
near it. "Concentrated" means a location quotient: the city's share of the
national total divided by its share of the national (GeoNames) population.
Every district carries a human-readable reason built from the real counts.
"""
from __future__ import annotations

import math

DISTRICTS = {
    "campus": ("Campus", "Science"),
    "industrial": ("Industrial Zone", "Production"),
    "harbor": ("Harbor", "Gold"),
    "aerodrome": ("Aerodrome", "Gold"),
    "theater": ("Theater Square", "Culture"),
    "preserve": ("Preserve", "Culture"),
    "government": ("Government Plaza", "Influence"),
}

EPITHET = {
    "campus": "Scholar city",
    "industrial": "Powerhouse",
    "harbor": "Port city",
    "aerodrome": "Air hub",
    "theater": "Heritage city",
    "preserve": "Gateway to the wild",
    "government": "Seat of power",
}


def _near(c, items, radius_km):
    r2 = radius_km * radius_km
    return [it for it in items if (it["x"] - c["x"]) ** 2 + (it["y"] - c["y"]) ** 2 <= r2]


def location_quotient(local: float, national: float, pop_share: float) -> float:
    if national <= 0 or pop_share <= 0:
        return 0.0
    return (local / national) / pop_share


def assign_districts(cities, layers, radius_km, total_pop, coast=lambda i: False):
    """Mutates every city dict: adds ``districts`` (list) and ``epithet`` (str)."""
    unis = layers.get("universities", [])
    power = layers.get("power", [])
    airports = layers.get("airports", [])
    ports = layers.get("ports", [])
    heritage = layers.get("heritage", [])
    parks = layers.get("parks", [])
    total_mw = sum(p["mw"] for p in power)
    for c in cities:
        # population "near" the city: the city itself, floored so tiny towns
        # do not get absurd quotients
        share = max(c["pop"], 0.002 * total_pop) / max(total_pop, 1)
        found = []
        u = _near(c, unis, radius_km)
        lq = location_quotient(len(u), len(unis), share)
        if len(u) >= 3 and lq >= 1.5:
            found.append(("campus", 1.2 * lq, f"{len(u)} universities within {radius_km:.0f} km "
                                        f"({lq:.1f}x the national rate per resident)"))
        pw = _near(c, power, radius_km)
        mw = sum(p["mw"] for p in pw)
        lq = location_quotient(mw, total_mw, share)
        if mw >= 1000 and lq >= 1.5:
            top = max(pw, key=lambda p: p["mw"])
            found.append(("industrial", min(lq, 50) / 2, f"{mw:,.0f} MW of power plants within {radius_km:.0f} km "
                                                       f"(largest: {top['name']}, {top['mw']:,.0f} MW {top['fuel'].lower()})"))
        pt = _near(c, ports, radius_km * 0.6)
        if pt:
            found.append(("harbor", 1.8 + 0.3 * len(pt), f"seaport: {pt[0]['name']}"))
        elif c.get("hex") is not None and coast(c["hex"]) and c["pop"] > 0.01 * total_pop:
            found.append(("harbor", 0.9, "on the coast"))
        ap = [a for a in _near(c, airports, radius_km) if a["kind"] == "large"]
        if ap:
            found.append(("aerodrome", 0.9 + 0.2 * len(ap), f"large airport: {ap[0]['name']}"))
        h = _near(c, heritage, radius_km)
        hc = [x for x in h if not x.get("natural")]
        if hc:
            found.append(("theater", 1.3 + 0.4 * len(hc), f"{len(hc)} World Heritage site{'s' if len(hc) > 1 else ''} nearby: "
                                                    + ", ".join(x["name"] for x in hc[:2])))
        pk = _near(c, parks, radius_km * 1.4)
        if pk and not hc:
            found.append(("preserve", 0.5 + 0.1 * len(pk), f"national park nearby: {pk[0]['name']}"))
        if c.get("fcode") == "PPLC":
            found.append(("government", 100.0, "national capital"))
        elif c.get("capitalOf"):
            found.append(("government", 100.0, f"the national capital, {c['capitalOf']}, lies within it"))
        elif c.get("fcode") == "PPLA":
            found.append(("government", 0.7, "state / province capital"))
        found.sort(key=lambda t: -t[1])
        c["districts"] = [{"id": k, "name": DISTRICTS[k][0], "yield": DISTRICTS[k][1],
                           "why": why, "score": round(s, 2)} for k, s, why in found[:4]]
        c["epithet"] = EPITHET[found[0][0]] if found else ""
    return cities
