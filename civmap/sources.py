"""Download and cache the open datasets civmap is built from.

Every fetcher stores raw responses under a cache directory so that a second
run is fully offline. Nothing here is country specific; filtering happens in
the parsers below.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Iterable

USER_AGENT = "civmap/0.1 (https://github.com/jatingargiitk/civmap)"

NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
GEONAMES_CITIES = "https://download.geonames.org/export/dump/cities15000.zip"
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
WRI_POWER = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database/master/"
    "output_database/global_power_plant_database.csv"
)
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
NASA_POWER = (
    "https://power.larc.nasa.gov/api/temporal/climatology/regional?parameters={param}"
    "&community=AG&longitude-min={lon0}&longitude-max={lon1}&latitude-min={lat0}"
    "&latitude-max={lat1}&format=JSON"
)
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WORLD_BANK = "https://api.worldbank.org/v2/country/{iso3}/indicator/{ind}?format=json&mrnev=1"

# Natural Earth ships "point of view" editions of the admin-0 layer. When a
# country has one we draw it the way that country draws itself.
NE_POV = {
    "ARG", "BGD", "BRA", "CHN", "DEU", "EGY", "ESP", "FRA", "GBR", "GRC", "IDN",
    "IND", "ISR", "ITA", "JPN", "KOR", "MAR", "NEP", "NLD", "PAK", "POL", "PRT",
    "PSE", "RUS", "SAU", "SWE", "TUR", "TWN", "UKR", "USA", "VNM",
}


def cache_dir() -> Path:
    d = Path(os.environ.get("CIVMAP_CACHE", Path.home() / ".cache" / "civmap"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _offline() -> bool:
    return os.environ.get("CIVMAP_OFFLINE") == "1"


def fetch(url: str, name: str | None = None, *, data: bytes | None = None,
          headers: dict | None = None, retries: int = 4, timeout: int = 120) -> bytes:
    """Return the bytes at ``url``, using the on-disk cache when possible."""
    key = name or hashlib.sha1((url + (data.decode() if data else "")).encode()).hexdigest()
    path = cache_dir() / key
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    if _offline():
        raise FileNotFoundError(f"{url} is not cached and CIVMAP_OFFLINE=1")
    import requests  # imported lazily so the offline test-suite never needs it

    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            if data is None:
                r = requests.get(url, headers=hdrs, timeout=timeout)
            else:
                r = requests.post(url, data=data, headers=hdrs, timeout=timeout)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            return r.content
        except FileNotFoundError:
            raise
        except Exception as exc:  # network hiccup: back off and retry
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


# ---------------------------------------------------------------- Natural Earth
def natural_earth(layer: str) -> dict:
    raw = fetch(NE_BASE + layer + ".geojson", f"ne/{layer}.geojson")
    return json.loads(raw)


def admin0_layer(iso3: str) -> dict:
    if iso3 in NE_POV:
        try:
            return natural_earth(f"ne_10m_admin_0_countries_{iso3.lower()}")
        except FileNotFoundError:
            pass
    return natural_earth("ne_10m_admin_0_countries")


# ---------------------------------------------------------------- GeoNames
GEONAMES_COLS = [
    "geonameid", "name", "asciiname", "alternatenames", "lat", "lon", "fclass",
    "fcode", "cc", "cc2", "admin1", "admin2", "admin3", "admin4", "population",
    "elevation", "dem", "tz", "modified",
]


def parse_geonames(lines: Iterable[str], iso2: str) -> list[dict]:
    out = []
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 19 or parts[8] != iso2:
            continue
        row = dict(zip(GEONAMES_COLS, parts))
        out.append({
            "name": row["name"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "pop": int(row["population"] or 0),
            "fcode": row["fcode"],
            "admin1": row["admin1"],
        })
    return out


def cities(iso2: str) -> list[dict]:
    raw = fetch(GEONAMES_CITIES, "geonames/cities15000.zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        text = zf.read("cities15000.txt").decode("utf-8")
    return parse_geonames(text.splitlines(), iso2)


# ---------------------------------------------------------------- OurAirports
def parse_airports(text: str, iso2: str) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("iso_country") != iso2:
            continue
        kind = row.get("type", "")
        if kind not in ("large_airport", "medium_airport"):
            continue
        if row.get("scheduled_service") != "yes":
            continue
        out.append({
            "name": row["name"],
            "lat": float(row["latitude_deg"]),
            "lon": float(row["longitude_deg"]),
            "kind": "large" if kind == "large_airport" else "medium",
            "iata": row.get("iata_code") or "",
        })
    return out


def airports(iso2: str) -> list[dict]:
    raw = fetch(OURAIRPORTS, "ourairports/airports.csv")
    return parse_airports(raw.decode("utf-8"), iso2)


# ---------------------------------------------------------------- WRI power plants
def parse_power(text: str, iso3: str) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("country") != iso3:
            continue
        try:
            mw = float(row["capacity_mw"])
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, ValueError):
            continue
        out.append({"name": row["name"], "lat": lat, "lon": lon, "mw": mw,
                    "fuel": row.get("primary_fuel", "Other")})
    return out


def power_plants(iso3: str) -> list[dict]:
    raw = fetch(WRI_POWER, "wri/global_power_plant_database.csv")
    return parse_power(raw.decode("utf-8"), iso3)


# ---------------------------------------------------------------- Ports
def ports(bbox: tuple[float, float, float, float]) -> list[dict]:
    lon0, lat0, lon1, lat1 = bbox
    gj = natural_earth("ne_10m_ports")
    out = []
    for f in gj["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        if lon0 <= lon <= lon1 and lat0 <= lat <= lat1:
            out.append({"name": f["properties"].get("name") or "Port", "lat": lat, "lon": lon})
    return out


# ---------------------------------------------------------------- Terrarium DEM
def decode_terrarium(rgb) -> "np.ndarray":
    import numpy as np

    a = np.asarray(rgb, dtype=np.float64)
    return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0


def terrarium_tile(z: int, x: int, y: int):
    from PIL import Image

    raw = fetch(TERRARIUM.format(z=z, x=x, y=y), f"terrarium/{z}/{x}/{y}.png")
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return decode_terrarium(img)


# ---------------------------------------------------------------- NASA POWER
def nasa_power_grid(param: str, bbox: tuple[float, float, float, float]) -> list[tuple[float, float, float]]:
    """Annual climatology of ``param`` as (lon, lat, value) on POWER's 0.5° grid.

    POWER limits regional requests to 10°x10° and one parameter, so the box
    is tiled.
    """
    lon0, lat0, lon1, lat1 = bbox
    pts: list[tuple[float, float, float]] = []
    lo = int(lon0 // 10 * 10)
    while lo < lon1:
        la = int(lat0 // 10 * 10)
        while la < lat1:
            a0, a1 = max(lo, -180), min(lo + 10, 180)
            b0, b1 = max(la, -90), min(la + 10, 90)
            url = NASA_POWER.format(param=param, lon0=a0, lon1=a1, lat0=b0, lat1=b1)
            try:
                gj = json.loads(fetch(url, f"power/{param}_{a0}_{b0}.json"))
            except Exception:
                gj = {"features": []}
            for f in gj.get("features", []):
                lon, lat = f["geometry"]["coordinates"][:2]
                v = f["properties"]["parameter"][param].get("ANN")
                if v is not None and v > -900:
                    pts.append((lon, lat, float(v)))
            la += 10
        lo += 10
    return pts


# ---------------------------------------------------------------- Wikidata
WIKIDATA_QUERIES = {
    "heritage": """
SELECT ?item ?itemLabel ?coord ?natural WHERE {{
  ?item wdt:P1435 wd:Q9259; wdt:P17 wd:{qid}; wdt:P625 ?coord.
  OPTIONAL {{ ?item wdt:P31/wdt:P279* wd:Q473972. BIND(1 AS ?natural) }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}""",
    "universities": """
SELECT DISTINCT ?item ?itemLabel ?coord WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q3918; wdt:P17 wd:{qid}; wdt:P625 ?coord.
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}""",
    "parks": """
SELECT DISTINCT ?item ?itemLabel ?coord WHERE {{
  ?item wdt:P31 wd:Q46169; wdt:P17 wd:{qid}; wdt:P625 ?coord.
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}""",
}


def parse_sparql(payload: dict) -> list[dict]:
    seen = {}
    for b in payload["results"]["bindings"]:
        coord = b["coord"]["value"]  # "Point(lon lat)"
        try:
            lon, lat = coord[coord.index("(") + 1: coord.index(")")].split()
            lon, lat = float(lon), float(lat)
        except ValueError:
            continue
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        name = b.get("itemLabel", {}).get("value", qid)
        rec = seen.setdefault(qid, {"id": qid, "name": name, "lat": lat, "lon": lon,
                                    "natural": False})
        if "natural" in b:
            rec["natural"] = True
    return list(seen.values())


def wikidata(kind: str, country_qid: str) -> list[dict]:
    q = WIKIDATA_QUERIES[kind].format(qid=country_qid)
    raw = fetch(WIKIDATA_SPARQL, f"wikidata/{kind}_{country_qid}.json",
                data=("query=" + _urlquote(q)).encode(),
                headers={"Accept": "application/sparql-results+json",
                         "Content-Type": "application/x-www-form-urlencoded"})
    return parse_sparql(json.loads(raw))


def country_qid(iso2: str) -> str:
    q = ('SELECT ?c WHERE { ?c wdt:P297 "' + iso2 + '". '
         'FILTER NOT EXISTS { ?c wdt:P576 ?end. } }')
    raw = fetch(WIKIDATA_SPARQL, f"wikidata/qid_{iso2}.json",
                data=("query=" + _urlquote(q)).encode(),
                headers={"Accept": "application/sparql-results+json",
                         "Content-Type": "application/x-www-form-urlencoded"})
    b = json.loads(raw)["results"]["bindings"]
    return b[0]["c"]["value"].rsplit("/", 1)[-1]


def _urlquote(s: str) -> str:
    from urllib.parse import quote

    return quote(s, safe="")


# ---------------------------------------------------------------- World Bank
def world_bank(iso3: str, indicator: str) -> tuple[float | None, str | None]:
    try:
        raw = fetch(WORLD_BANK.format(iso3=iso3, ind=indicator), f"worldbank/{iso3}_{indicator}.json")
        payload = json.loads(raw)
        rec = payload[1][0]
        return (float(rec["value"]) if rec["value"] is not None else None, rec["date"])
    except Exception:
        return (None, None)
