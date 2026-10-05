"""地図タイル（ズーム12）の番号の計算。

経度・緯度は 1e7 倍の整数（OpenStreetMap の内部と同じ）で受け取り、整数の比較だけでマスを決めます。
同じ入力からは、どの PC でも同じマスになるようにするためです（緯度の境目の表だけ最初に浮動小数で作る）。
"""
import bisect
import math

import numpy as np

Z = 12
N = 1 << Z
_LON_SPAN = 3_600_000_000  # 360° × 1e7


def _row_edges():
    # 行 y の上端の緯度（1e7 倍の整数）。y = 0..N。北から南へ減っていく。
    out = []
    for y in range(N + 1):
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / N))))
        out.append(round(lat * 1e7))
    return out


ROW_TOP = _row_edges()
_NEG_TOP = [-v for v in ROW_TOP]          # 増えていく並び（二分探索用）
_NEG_TOP_NP = np.array(_NEG_TOP, dtype=np.int64)


def tile_x7(lon7):
    x = ((lon7 + 1_800_000_000) * N) // _LON_SPAN
    return min(max(x, 0), N - 1)


def tile_y7(lat7):
    y = bisect.bisect_right(_NEG_TOP, -lat7) - 1
    return min(max(y, 0), N - 1)


def tiles_xy7(lon7, lat7):
    """numpy の配列（int64）でまとめて計算する。"""
    lon7 = np.asarray(lon7, dtype=np.int64)
    lat7 = np.asarray(lat7, dtype=np.int64)
    x = ((lon7 + 1_800_000_000) * N) // _LON_SPAN
    y = np.searchsorted(_NEG_TOP_NP, -lat7, side='right') - 1
    return np.clip(x, 0, N - 1), np.clip(y, 0, N - 1)


def tile_of(lon, lat):
    """経度・緯度（度）からマスの番号 (x, y) を返す。"""
    return tile_x7(round(lon * 1e7)), tile_y7(round(lat * 1e7))


def tile_bounds(x, y):
    """マスの範囲 (西経度, 南緯度, 東経度, 北緯度) を度で返す。"""
    lon0 = x * 360 / N - 180
    lon1 = (x + 1) * 360 / N - 180
    return lon0, ROW_TOP[y + 1] / 1e7, lon1, ROW_TOP[y] / 1e7


def tiles_in_bbox(lon0, lat0, lon1, lat1):
    """範囲にかかるマスの番号の範囲 (x0, y0, x1, y1)（両端を含む）を返す。"""
    x0, y1 = tile_of(lon0, lat0)
    x1, y0 = tile_of(lon1, lat1)
    return x0, y0, x1, y1
