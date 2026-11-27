"""Turn measured elevation, relief, rainfall and temperature into Civ-style terrain.

The rules are deliberately simple and documented so that anyone can argue with
them. Inputs are real measurements; the categories are civmap's own.
"""
from __future__ import annotations

import numpy as np

# base terrain codes
OCEAN, COAST, LAKE, GRASSLAND, PLAINS, DESERT, TUNDRA, SNOW, MOUNTAINS = range(9)
TERRAIN_NAMES = ["Ocean", "Coast", "Lake", "Grassland", "Plains", "Desert", "Tundra", "Snow", "Mountains"]

# features layered on top of base terrain
NONE, FOREST, JUNGLE, FLOODPLAINS, MARSH = range(5)
FEATURE_NAMES = ["", "Forest", "Jungle", "Floodplains", "Marsh"]


def classify_land(elev, relief, rain_mm, temp_c):
    """Vectorised land classification.

    elev     mean elevation of the hex in metres
    relief   max - min elevation sampled inside the hex, metres
    rain_mm  mean annual precipitation, mm/year
    temp_c   mean annual 2 m air temperature, °C (already lapse-rate adjusted)

    Returns (terrain, feature, hills) arrays.
    """
    elev = np.asarray(elev, float)
    relief = np.asarray(relief, float)
    rain = np.asarray(rain_mm, float)
    temp = np.asarray(temp_c, float)

    terrain = np.full(elev.shape, PLAINS, dtype=np.int8)
    terrain[rain >= 900] = GRASSLAND
    terrain[(rain < 300) | ((rain < 450) & (temp > 20))] = DESERT
    terrain[temp < 1.0] = TUNDRA
    terrain[temp < -7.0] = SNOW

    mountains = (elev > 3200) | (relief > 1500) | ((elev > 1500) & (relief > 900))
    terrain[mountains] = MOUNTAINS
    terrain[(elev > 5200) & ~mountains] = SNOW

    hills = ((relief > 380) | (elev > 1000)) & ~mountains

    feature = np.zeros(elev.shape, dtype=np.int8)
    land = (terrain == GRASSLAND) | (terrain == PLAINS) | (terrain == TUNDRA)
    feature[land & (rain >= 1250) & (temp < 22)] = FOREST
    feature[land & (rain >= 700) & (temp < 8)] = FOREST
    feature[land & (rain >= 1700) & (temp >= 22)] = JUNGLE
    return terrain, feature, hills


def lapse_rate_temp(t_grid_c, elev_hex_m, elev_grid_m):
    """Correct a coarse temperature to the hex's own elevation (6.5 °C/km)."""
    return np.asarray(t_grid_c) - 0.0065 * (np.asarray(elev_hex_m) - np.asarray(elev_grid_m))


FOOD = {GRASSLAND: 2, PLAINS: 1, DESERT: 0, TUNDRA: 1, SNOW: 0, MOUNTAINS: 0,
        COAST: 1, OCEAN: 1, LAKE: 1}
PROD = {GRASSLAND: 0, PLAINS: 1, DESERT: 0, TUNDRA: 0, SNOW: 0, MOUNTAINS: 0,
        COAST: 0, OCEAN: 0, LAKE: 0}


def base_yields(terrain, feature, hills, river):
    """Food and production in the spirit of Civ VI's tile yields."""
    terrain = np.asarray(terrain)
    food = np.vectorize(FOOD.get)(terrain).astype(float)
    prod = np.vectorize(PROD.get)(terrain).astype(float)
    feature = np.asarray(feature)
    hills = np.asarray(hills, bool)
    river = np.asarray(river, bool)
    prod[feature == FOREST] += 1
    prod[feature == JUNGLE] += 1
    food[feature == JUNGLE] = np.maximum(food[feature == JUNGLE], 1)
    prod[hills] += 1
    food[river & (terrain != MOUNTAINS)] += 1
    floodplain = river & ((terrain == DESERT) | (terrain == PLAINS)) & (feature == NONE)
    food[floodplain] += 1
    return food, prod
