import numpy as np

from civmap import terrain as T


def classify(elev, relief, rain, temp):
    t, f, h = T.classify_land([elev], [relief], [rain], [temp])
    return int(t[0]), int(f[0]), bool(h[0])


def test_desert():
    assert classify(200, 50, 150, 27)[0] == T.DESERT


def test_wet_tropics_are_jungle_grassland():
    t, f, h = classify(50, 30, 2500, 27)
    assert t == T.GRASSLAND and f == T.JUNGLE and not h


def test_temperate_forest():
    t, f, _ = classify(300, 100, 1400, 12)
    assert t == T.GRASSLAND and f == T.FOREST


def test_mountains_by_height_or_relief():
    assert classify(4500, 300, 400, -2)[0] == T.MOUNTAINS
    assert classify(800, 1800, 900, 15)[0] == T.MOUNTAINS


def test_hills_are_an_overlay():
    t, _, h = classify(600, 500, 700, 22)
    assert t == T.PLAINS and h


def test_cold_is_tundra_then_snow():
    assert classify(100, 20, 400, -3)[0] == T.TUNDRA
    assert classify(100, 20, 300, -15)[0] == T.SNOW


def test_lapse_rate():
    assert np.isclose(T.lapse_rate_temp(20.0, 2000.0, 1000.0), 13.5)


def test_yields():
    terrain = np.array([T.GRASSLAND, T.PLAINS, T.DESERT, T.MOUNTAINS])
    feature = np.array([T.FOREST, T.NONE, T.NONE, T.NONE])
    hills = np.array([False, True, False, False])
    river = np.array([False, False, True, True])
    food, prod = T.base_yields(terrain, feature, hills, river)
    assert food.tolist() == [2, 1, 2, 0]      # desert + river = floodplain bonus
    assert prod.tolist() == [1, 2, 0, 0]      # forest +1, plains 1 + hills 1
