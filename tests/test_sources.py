import json

import numpy as np
import pytest

from civmap import sources


def test_parse_geonames():
    row = ["1275339", "Mumbai", "Mumbai", "Bombay", "19.07283", "72.88261", "P", "PPLA", "IN", "",
           "16", "", "", "", "12691836", "", "8", "Asia/Kolkata", "2023-01-01"]
    other = list(row)
    other[8] = "PK"
    out = sources.parse_geonames(["\t".join(row), "\t".join(other)], "IN")
    assert out == [{"gid": "1275339", "name": "Mumbai", "lat": 19.07283, "lon": 72.88261, "pop": 12691836,
                    "fcode": "PPLA", "admin1": "16"}]


def test_parse_airports_keeps_scheduled_large_and_medium():
    text = (
        "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,iso_region,"
        "municipality,scheduled_service,icao_code,iata_code\n"
        "1,VABB,large_airport,Mumbai Intl,19.08,72.86,39,AS,IN,IN-MM,Mumbai,yes,VABB,BOM\n"
        "2,VA00,small_airport,Tiny Strip,19.0,72.0,10,AS,IN,IN-MM,X,no,,\n"
        "3,VOPB,medium_airport,Port Blair,11.6,92.7,14,AS,IN,IN-AN,Port Blair,yes,VOPB,IXZ\n"
        "4,OPKC,large_airport,Karachi,24.9,67.1,100,AS,PK,PK-SD,Karachi,yes,OPKC,KHI\n"
    )
    out = sources.parse_airports(text, "IN")
    assert [a["iata"] for a in out] == ["BOM", "IXZ"]
    assert out[0]["kind"] == "large" and out[1]["kind"] == "medium"


def test_parse_power():
    text = ("country,country_long,name,gppd_idnr,capacity_mw,latitude,longitude,primary_fuel\n"
            "IND,India,Mundra,X1,4620,22.8,69.5,Coal\n"
            "IND,India,Broken,X2,,22.8,69.5,Coal\n"
            "PAK,Pakistan,Tarbela,X3,4888,34.1,72.7,Hydro\n")
    out = sources.parse_power(text, "IND")
    assert out == [{"name": "Mundra", "lat": 22.8, "lon": 69.5, "mw": 4620.0, "fuel": "Coal"}]


def test_parse_sparql_dedupes_and_flags_natural():
    payload = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q9141"}, "itemLabel": {"value": "Taj Mahal"},
         "coord": {"value": "Point(78.0421 27.175)"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q9141"}, "itemLabel": {"value": "Taj Mahal"},
         "coord": {"value": "Point(78.0421 27.175)"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Kaziranga"},
         "coord": {"value": "Point(93.36 26.66)"}, "natural": {"value": "1"}},
    ]}}
    out = sources.parse_sparql(payload)
    assert len(out) == 2
    taj = next(o for o in out if o["id"] == "Q9141")
    assert (taj["lon"], taj["lat"], taj["natural"]) == (78.0421, 27.175, False)
    assert next(o for o in out if o["id"] == "Q1")["natural"] is True


def test_decode_terrarium():
    # elevation = R*256 + G + B/256 - 32768
    rgb = np.array([[[128, 0, 0], [128, 100, 128], [127, 0, 0]]], dtype=np.uint8)
    assert sources.decode_terrarium(rgb).tolist() == [[0.0, 100.5, -256.0]]


def test_fetch_uses_cache_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVMAP_CACHE", str(tmp_path))
    monkeypatch.setenv("CIVMAP_OFFLINE", "1")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a.json").write_text(json.dumps({"ok": 1}))
    assert json.loads(sources.fetch("https://example.invalid/a", "x/a.json")) == {"ok": 1}
    with pytest.raises(FileNotFoundError):
        sources.fetch("https://example.invalid/b", "x/b.json")


def test_world_bank_parses_cached_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVMAP_CACHE", str(tmp_path))
    monkeypatch.setenv("CIVMAP_OFFLINE", "1")
    (tmp_path / "worldbank").mkdir()
    (tmp_path / "worldbank" / "TOY_SP.POP.TOTL.json").write_text(
        json.dumps([{"page": 1}, [{"value": 12345, "date": "2024"}]]))
    assert sources.world_bank("TOY", "SP.POP.TOTL") == (12345.0, "2024")
    assert sources.world_bank("TOY", "NY.GDP.MKTP.CD") == (None, None)


def test_dedupe_heritage_one_wonder_per_property():
    recs = [
        {"id": "Q1", "name": "Nanda Devi and Valley of Flowers National Parks", "lat": 30.7, "lon": 79.9,
         "natural": True, "whs": {"335", "335bis"}},
        {"id": "Q2", "name": "Valley of Flowers National Park", "lat": 30.7, "lon": 79.6,
         "natural": True, "whs": {"335-002"}},
        {"id": "Q3", "name": "Taj Mahal", "lat": 27.17, "lon": 78.04, "natural": False, "whs": {"252"}},
        {"id": "Q4", "name": "No id", "lat": 0, "lon": 0, "natural": False},
    ]
    out = sources.dedupe_heritage(recs)
    assert [o["id"] for o in out] == ["Q3", "Q1"]
    assert out[1]["whs"] == "335" and out[1]["natural"]
