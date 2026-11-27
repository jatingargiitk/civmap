import numpy as np
import pytest
from shapely.geometry import Polygon, box

from civmap.build import Inputs


def _elev(lon, lat):
    lon = np.asarray(lon, float)
    lat = np.asarray(lat, float)
    # a ridge of mountains along the northern edge, lowlands elsewhere
    return np.where(lat > 23.2, 3500 + 900 * np.sin(lon * 7), 200 + 30 * (lon - 75))


def _climate(lon, lat):
    lon = np.asarray(lon, float)
    lat = np.asarray(lat, float)
    rain = 300 + 250 * (lon - 70)       # dry west, wet east
    temp = 26 - 0.4 * (lat - 16)
    return rain, temp, np.zeros_like(lon)


@pytest.fixture
def toy_inputs():
    land = box(70, 16, 80, 24)
    west, east = box(70, 16, 75, 24), box(75, 16, 80, 24)
    cities = [
        {"name": "Westport", "lat": 20.0, "lon": 70.4, "pop": 3_000_000, "fcode": "PPLA", "admin1": "1"},
        {"name": "Capitol", "lat": 21.0, "lon": 77.0, "pop": 1_500_000, "fcode": "PPLC", "admin1": "2"},
        {"name": "Smalltown", "lat": 18.0, "lon": 74.0, "pop": 120_000, "fcode": "PPL", "admin1": "1"},
    ]
    unis = [{"name": f"U{i}", "lat": 21.0 + i * 0.01, "lon": 77.0, "natural": False} for i in range(8)]
    unis.append({"name": "Far U", "lat": 17.0, "lon": 79.0, "natural": False})
    return Inputs(
        name="Toyland", iso2="TL", iso3="TOY", land=land,
        neighbours=[("Otherland", box(80, 16, 84, 24))],
        states=[("West", west), ("East", east)],
        elevation=_elev, climate=_climate, cities=cities,
        airports=[{"name": "Capitol Intl", "lat": 21.1, "lon": 77.1, "kind": "large", "iata": "CAP"}],
        ports=[{"name": "Westport Harbour", "lat": 20.0, "lon": 70.1}],
        power=[{"name": "Big Coal", "lat": 18.1, "lon": 74.1, "mw": 4000.0, "fuel": "Coal"},
               {"name": "Small Hydro", "lat": 23.0, "lon": 78.0, "mw": 100.0, "fuel": "Hydro"}],
        universities=unis,
        heritage=[{"name": "Old Fort", "lat": 20.1, "lon": 70.5, "natural": False},
                  {"name": "Wild Park", "lat": 23.5, "lon": 76.0, "natural": True}],
        parks=[],
        rivers=[("Long River", 3, Polygon([(72, 23), (76, 18), (76.01, 18.01)]).exterior)],
        lakes=[], regions=[], seas=[], stats={"population": 1e7, "populationYear": "2024"},
    )
