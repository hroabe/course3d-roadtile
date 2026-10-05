import math
import random

import numpy as np

from roadtile.tiles import N, ROW_TOP, tile_bounds, tile_of, tile_x7, tile_y7, tiles_in_bbox, tiles_xy7


def slippy(lon, lat):
    # 地図タイルの一般的な式（浮動小数）
    r = math.radians(lat)
    return (int((lon + 180) / 360 * N), int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * N))


def test_matches_standard_formula_away_from_edges():
    rnd = random.Random(1)
    for _ in range(5000):
        lon, lat = rnd.uniform(122, 154), rnd.uniform(20, 46)
        x, y = tile_of(lon, lat)
        w, s, e, n = tile_bounds(x, y)
        if min(lon - w, e - lon, lat - s, n - lat) < 1e-6:
            continue
        assert (x, y) == slippy(lon, lat)


def test_known_tiles():
    assert tile_of(139.0, 35.2) == (3629, 1619)          # 箱根
    assert tile_of(138.75, 35.4) == (3626, 1616)         # 富士吉田のあたり
    w, s, e, n = tile_bounds(3629, 1619)
    assert 7.9 < (e - w) * 111.32 * math.cos(math.radians(35.2)) < 8.1  # 約8km四方
    assert 7.9 < (n - s) * 110.57 < 8.1


def test_edges_belong_to_the_tile_on_their_east_and_south():
    # マスの西端・北端の線上の点は、そのマスに入る
    x, y = 3629, 1619
    lon7 = -(-(x * 3_600_000_000) // N) - 1_800_000_000  # 西端の線上か、そのすぐ東の整数
    assert tile_x7(lon7) == x and tile_x7(lon7 - 1) == x - 1
    assert tile_y7(ROW_TOP[y]) == y and tile_y7(ROW_TOP[y] + 1) == y - 1


def test_vectorized_equals_scalar():
    rnd = random.Random(2)
    lon7 = [rnd.randrange(1_220_000_000, 1_540_000_000) for _ in range(3000)]
    lat7 = [rnd.randrange(200_000_000, 460_000_000) for _ in range(3000)]
    lat7 += ROW_TOP[1500:1700]
    lon7 += lon7[:200]
    xs, ys = tiles_xy7(np.array(lon7), np.array(lat7))
    assert list(zip(xs.tolist(), ys.tolist())) == [(tile_x7(a), tile_y7(b)) for a, b in zip(lon7, lat7)]


def test_bbox_range():
    x0, y0, x1, y1 = tiles_in_bbox(138.95, 35.17, 139.17, 35.27)
    assert (x0, x1) == (3628, 3631) and y0 <= y1
