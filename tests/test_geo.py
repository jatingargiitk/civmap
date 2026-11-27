import math

import numpy as np

from civmap import geo


def test_laea_round_trip():
    p = geo.LAEA(78.0, 22.0)
    lon = np.array([68.0, 78.0, 97.0, 75.5])
    lat = np.array([8.0, 22.0, 35.0, 30.2])
    x, y = p.forward(lon, lat)
    lon2, lat2 = p.inverse(x, y)
    assert np.allclose(lon, lon2, atol=1e-7)
    assert np.allclose(lat, lat2, atol=1e-7)


def test_laea_y_points_south():
    p = geo.LAEA(0.0, 0.0)
    _, y_north = p.forward(0.0, 10.0)
    assert y_north < 0


def test_laea_is_equal_area():
    # a 1x1 degree cell at the equator is ~12,364 km²
    from shapely.geometry import box
    p = geo.LAEA(10.0, 0.0)
    a = p.geom(box(10, 0, 11, 1)).area
    assert abs(a - 12364) / 12364 < 0.01


def test_hex_center_round_trip():
    q, r = np.meshgrid(np.arange(-5, 6), np.arange(-5, 6))
    q, r = q.ravel(), r.ravel()
    x, y = geo.hex_center(q, r, 10.0)
    q2, r2 = geo.point_to_hex(x + 2.0, y - 3.0, 10.0)  # small offset stays in the same hex
    assert (q2 == q).all() and (r2 == r).all()


def test_neighbours_are_equidistant():
    x0, y0 = geo.hex_center(0, 0, 5.0)
    for dq, dr in geo.NEIGHBOURS:
        x, y = geo.hex_center(dq, dr, 5.0)
        assert math.isclose(math.hypot(x - x0, y - y0), 5.0 * math.sqrt(3), rel_tol=1e-9)


def test_edge_neighbour_matches_corner_order():
    # the midpoint of edge k must point towards EDGE_NEIGHBOUR[k]
    corners = geo.hex_corners(0.0, 0.0, 1.0)
    for k, (dq, dr) in enumerate(geo.EDGE_NEIGHBOUR):
        mx = (corners[k][0] + corners[(k + 1) % 6][0]) / 2
        my = (corners[k][1] + corners[(k + 1) % 6][1]) / 2
        nx, ny = geo.hex_center(dq, dr, 1.0)
        cos = (mx * nx + my * ny) / (math.hypot(mx, my) * math.hypot(nx, ny))
        assert math.isclose(cos, 1.0, abs_tol=1e-9)


def test_hex_size_for_area():
    size = geo.hex_size_for(1_000_000, 4000)
    hex_area = 1.5 * math.sqrt(3) * size * size
    assert math.isclose(hex_area * 4000, 1_000_000, rel_tol=1e-9)


def test_hex_grid_covers_bounds():
    q, r = geo.hex_grid((0, 0, 100, 80), 5.0)
    x, y = geo.hex_center(q, r, 5.0)
    assert x.min() >= 0 and x.max() <= 100 and y.min() >= 0 and y.max() <= 80
    expected = 100 * 80 / (1.5 * math.sqrt(3) * 25)
    assert abs(len(q) - expected) / expected < 0.15


def test_haversine():
    # one degree of latitude ~ 111.2 km
    assert abs(float(geo.haversine_km(0, 0, 0, 1)) - 111.2) < 0.3
