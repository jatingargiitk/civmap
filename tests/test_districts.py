from civmap.districts import assign_districts, location_quotient


def test_location_quotient():
    assert location_quotient(10, 100, 0.05) == 2.0
    assert location_quotient(0, 0, 0.1) == 0.0


def test_campus_and_capital():
    city = {"name": "A", "x": 0.0, "y": 0.0, "pop": 1_000_000, "fcode": "PPLC"}
    town = {"name": "B", "x": 500.0, "y": 0.0, "pop": 1_000_000, "fcode": "PPL"}
    unis = [{"name": f"u{i}", "x": 1.0, "y": 1.0} for i in range(9)] + [{"name": "far", "x": 900.0, "y": 0.0}]
    assign_districts([city, town], {"universities": unis}, radius_km=40, total_pop=10_000_000)
    ids = [d["id"] for d in city["districts"]]
    assert ids[0] == "government" and "campus" in ids
    assert "9 universities" in next(d["why"] for d in city["districts"] if d["id"] == "campus")
    assert town["districts"] == [] and town["epithet"] == ""


def test_industrial_zone_needs_real_capacity():
    city = {"name": "P", "x": 0.0, "y": 0.0, "pop": 200_000, "fcode": "PPL"}
    power = [{"name": "Plant", "x": 5.0, "y": 5.0, "mw": 3000.0, "fuel": "Coal"},
             {"name": "Elsewhere", "x": 999.0, "y": 0.0, "mw": 3000.0, "fuel": "Gas"}]
    assign_districts([city], {"power": power}, radius_km=40, total_pop=10_000_000)
    assert city["districts"][0]["id"] == "industrial"
    assert city["epithet"] == "Powerhouse"
