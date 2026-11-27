import json

import numpy as np

from civmap import terrain as T
from civmap.build import build, main_landmass
from civmap.countries import find_country
from civmap.render import gallery_html, html_for


def test_build_toy_country(toy_inputs):
    d = build(toy_inputs, target_hexes=600)
    h = d["hex"]
    own = np.array(h["o"]) == 0
    assert 450 < own.sum() < 750
    # every hex of ours belongs to a state; foreign/water hexes do not
    s = np.array(h["s"])
    assert (s[own] >= 0).all() and (s[~own] == -1).all()
    assert {st["name"] for st in d["states"]} == {"West", "East"}
    assert d["states"][0]["color"] != d["states"][1]["color"]
    assert d["borders"]["country"] and d["borders"]["state"]
    # the neighbour shows up as foreign land
    assert d["neighbours"] == ["Otherland"] and (np.array(h["o"]) == 1).any()
    # northern ridge -> mountains; dry west -> desert or plains
    t = np.array(h["t"])
    assert (t[own] == T.MOUNTAINS).any()
    assert (t[own] == T.DESERT).any()
    # water around the land
    assert ((t == T.OCEAN) | (t == T.COAST)).any()
    json.dumps(d)  # serialisable


def test_cities_districts_and_wonders(toy_inputs):
    d = build(toy_inputs, target_hexes=600)
    names = [c["name"] for c in d["cities"]]
    assert names[:2] == ["Westport", "Capitol"]
    cap = next(c for c in d["cities"] if c["name"] == "Capitol")
    assert cap["capital"] and {"government", "campus", "aerodrome"} <= {x["id"] for x in cap["districts"]}
    west = next(c for c in d["cities"] if c["name"] == "Westport")
    assert {"harbor", "theater"} <= {x["id"] for x in west["districts"]}
    assert len(d["wonders"]) == 2 and any(w["natural"] for w in d["wonders"])
    assert any(r["k"] == "coal" and r["mw"] == 4000 for r in d["resources"])
    # river hexes get a river flag
    assert sum(d["hex"]["rv"]) > 5
    assert sum(d["hex"]["sci"]) == 9


def test_html_is_self_contained(toy_inputs):
    d = build(toy_inputs, target_hexes=300)
    d["cities"][0]["name"] = "</script><b>x"
    html = html_for(d)
    assert "window.CIVMAP_DATA=" in html and "__JS__" not in html and "__CSS__" not in html
    assert "</script><b>x" not in html  # escaped so it cannot break out of the script tag
    assert "Toyland" in html
    g = gallery_html([{"iso2": "TL", "name": "Toyland"}])
    assert "window.CIVMAP_INDEX=" in g


def test_main_landmass_drops_far_territories():
    from shapely.geometry import MultiPolygon, box
    home = box(0, 40, 10, 50)
    near_island = box(11, 41, 12, 42)
    far = box(-60, 0, -59, 1)
    kept = main_landmass(MultiPolygon([home, near_island, far]))
    assert kept.area == home.area + near_island.area


def test_find_country():
    feats = [{"properties": {"NAME": "India", "ISO_A2_EH": "IN", "ADM0_A3": "IND"}},
             {"properties": {"NAME": "United Kingdom", "ISO_A2_EH": "GB", "ADM0_A3": "GBR", "NAME_LONG": "United Kingdom"}},
             {"properties": {"NAME": "France", "ISO_A2": "-99", "ISO_A2_EH": "FR", "ADM0_A3": "FRA"}}]
    assert find_country(feats, "IN")["properties"]["NAME"] == "India"
    assert find_country(feats, "ind")["properties"]["NAME"] == "India"
    assert find_country(feats, "united kingdom")["properties"]["ADM0_A3"] == "GBR"
    assert find_country(feats, "FR")["properties"]["NAME"] == "France"
    assert find_country(feats, "Fra")["properties"]["NAME"] == "France"


def test_merge_urban_duplicates_prefers_the_seat_name():
    from civmap.build import merge_urban_duplicates
    cities = [
        {"name": "Suburb", "lat": 0.0, "lon": 0.0, "pop": 1_700_000, "fcode": "PPL"},
        {"name": "Seat", "lat": 0.0, "lon": 0.05, "pop": 1_000_000, "fcode": "PPLA2"},
        {"name": "Far", "lat": 5.0, "lon": 5.0, "pop": 500_000, "fcode": "PPL"},
    ]
    out = merge_urban_duplicates(cities, lambda c: (c["lon"] * 111, c["lat"] * 111), size=15)
    assert [(c["name"], c["pop"]) for c in out] == [("Seat", 1_700_000), ("Far", 500_000)]


def test_cross_check_populations_keeps_smaller_disputed_figure():
    from civmap.build import cross_check_populations
    cities = [{"gid": "1", "name": "District-sized", "pop": 1_700_000},
              {"gid": "2", "name": "Fine", "pop": 1_000_000},
              {"gid": "3", "name": "Unknown", "pop": 900_000}]
    out = cross_check_populations(cities, "TL", lookup=lambda ids, tag: {"1": 60_000, "2": 1_100_000})
    assert [c["pop"] for c in out] == [60_000, 1_000_000, 900_000]
    assert out[0]["popSource"] == "Wikidata" and "popSource" not in out[1]


def test_capital_inside_a_bigger_city_marks_that_city():
    from civmap.build import merge_urban_duplicates
    cities = [{"name": "Delhi", "lat": 28.65, "lon": 77.23, "pop": 11_000_000, "fcode": "PPLA"},
              {"name": "New Delhi", "lat": 28.61, "lon": 77.21, "pop": 317_000, "fcode": "PPLC"}]
    out = merge_urban_duplicates(cities, lambda c: (c["lon"] * 98, c["lat"] * 111), size=15)
    assert len(out) == 1 and out[0]["name"] == "Delhi" and out[0]["capitalOf"] == "New Delhi"
