"""geom.py（間引き・向き・切り取り・輪の組み立て）のテスト。素朴な計算と照らし合わせる。"""
import math
import random
from fractions import Fraction

from roadtile.geom import (SIMPLIFY_TOL, area2, assemble_rings, centroid, clip_ring, simplify_line, simplify_ring)
from roadtile.tiles import N, ROW_TOP


def ref_dp(pts, tol):
    """Douglas–Peucker 法を分数で正確に（答え合わせ用）。"""
    if len(pts) <= 2:
        return list(pts)
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    best, bi = Fraction(-1), None
    for i in range(1, len(pts) - 1):
        px, py = pts[i][0] - x0, pts[i][1] - y0
        d = Fraction(px * px + py * py) if L2 == 0 else Fraction((px * dy - py * dx) ** 2, L2)
        if d > best:
            best, bi = d, i
    if best > tol * tol:
        return ref_dp(pts[:bi + 1], tol)[:-1] + ref_dp(pts[bi:], tol)
    return [pts[0], pts[-1]]


def wiggly(seed, n, amp):
    rnd = random.Random(seed)
    x, y, out = 1_389_000_000, 352_000_000, []
    for i in range(n):
        x += rnd.randint(50, 900)
        y = 352_000_000 + int(amp * math.sin(i / 7)) + rnd.randint(-300, 300)
        out.append((x, y))
    return out


def test_simplify_matches_exact_reference():
    for seed in range(20):
        for n in (3, 10, 47, 49, 200, 1000):  # 48 を境に numpy の計算に替わる
            pts = wiggly(seed, n, 4000 if seed % 2 else 150)
            xs, ys = simplify_line([p[0] for p in pts], [p[1] for p in pts])
            assert list(zip(xs, ys)) == ref_dp(pts, SIMPLIFY_TOL), (seed, n)


def test_simplify_keeps_shape_within_tolerance():
    pts = wiggly(3, 500, 3000)
    xs, ys = simplify_line([p[0] for p in pts], [p[1] for p in pts])
    assert 2 < len(xs) < len(pts)
    assert (xs[0], ys[0]) == pts[0] and (xs[-1], ys[-1]) == pts[-1]


def test_simplify_ring_keeps_anchor_and_orientation():
    rnd = random.Random(7)
    n = 300
    xs, ys = [], []
    for i in range(n):  # 反時計回りのでこぼこの円（半径 約 1km）
        r = 100_000 + rnd.randint(-150, 150) + (3000 if i % 37 == 0 else 0)
        xs.append(1_389_500_000 + round(r * math.cos(2 * math.pi * i / n)))
        ys.append(352_000_000 + round(r * math.sin(2 * math.pi * i / n)))
    sx, sy = simplify_ring(xs, ys)
    assert (sx[0], sy[0]) == (xs[0], ys[0])
    assert 8 < len(sx) < n
    assert area2(sx, sy) > 0
    assert abs(area2(sx, sy) - area2(xs, ys)) / area2(xs, ys) < 0.02


def test_area_and_centroid():
    xs, ys = [0, 40, 40, 0], [0, 0, 20, 20]
    assert area2(xs, ys) == 1600
    assert area2(xs[::-1], ys[::-1]) == -1600
    assert centroid(xs, ys) == (20, 10)
    assert centroid([10, 50, 50, 10], [5, 5, 25, 25]) == (30, 15)


# ---------------------------------------------------------------- 切り取り

def winding(px, py, xs, ys):
    """点 (px, py) のまわりの巻き数（nonzero 規則の答え合わせ用）。"""
    w, n = 0, len(xs)
    for i in range(n):
        x0, y0, x1, y1 = xs[i], ys[i], xs[(i + 1) % n], ys[(i + 1) % n]
        if y0 <= py < y1 and (x1 - x0) * (py - y0) - (px - x0) * (y1 - y0) > 0:
            w += 1
        elif y1 <= py < y0 and (x1 - x0) * (py - y0) - (px - x0) * (y1 - y0) < 0:
            w -= 1
    return w


def seg_dist2(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    qx, qy = x0 + t * dx - px, y0 + t * dy - py
    return qx * qx + qy * qy


def near_edge(px, py, xs, ys, d):
    n = len(xs)
    return any(seg_dist2(px, py, xs[i], ys[i], xs[(i + 1) % n], ys[(i + 1) % n]) <= d * d for i in range(n))


def star(seed, cx, cy, r, n=40):
    rnd = random.Random(seed)
    xs, ys = [], []
    for i in range(n):
        rr = r * rnd.uniform(0.35, 1.0)
        xs.append(cx + round(rr * math.cos(2 * math.pi * i / n)))
        ys.append(cy + round(rr * math.sin(2 * math.pi * i / n)))
    return xs, ys


def test_clip_pieces_cover_the_ring_exactly():
    # マス (3628..3630, 1618..1620) の角をまたぐ星形。1e5 の座標で、境目のすぐ近く以外は塗り方が同じになること
    cx, cy = 1_390_000_000, round(ROW_TOP[1620])  # 経度 139.0、行 1619 と 1620 の境目
    for seed in range(4):
        xs, ys = star(seed, cx, cy, 900_000)
        pieces = clip_ring(xs, ys)
        assert len(pieces) >= 4
        x5 = [(x + 50) // 100 for x in xs]
        y5 = [(y + 50) // 100 for y in ys]
        rnd = random.Random(seed)
        lo_x, hi_x, lo_y, hi_y = min(x5), max(x5), min(y5), max(y5)
        for _ in range(1500):
            px, py = rnd.randint(lo_x, hi_x) + 0.5, rnd.randint(lo_y, hi_y) + 0.5
            if near_edge(px, py, x5, y5, 3):
                continue
            want = winding(px, py, x5, y5) != 0
            got = sum(winding(px, py, *p) for p in pieces.values()) != 0
            assert got == want, (seed, px, py)


def test_clip_pieces_stay_in_their_tiles_and_keep_orientation():
    xs, ys = star(11, 1_390_000_000, round(ROW_TOP[1620]), 1_200_000, 60)
    pieces = clip_ring(xs, ys)
    for (tx, ty), (px, py) in pieces.items():
        w = (tx * 360 / N - 180) * 1e5
        e = ((tx + 1) * 360 / N - 180) * 1e5
        s, n = ROW_TOP[ty + 1] / 100, ROW_TOP[ty] / 100
        assert all(w - 1 <= x <= e + 1 for x in px) and all(s - 1 <= y <= n + 1 for y in py)
        assert area2(px, py) > 0
    rev = clip_ring(xs[::-1], ys[::-1])
    assert set(rev) == set(pieces) and all(area2(*p) < 0 for p in rev.values())
    total = sum(area2(*p) for p in pieces.values())
    whole = area2([(x + 50) // 100 for x in xs], [(y + 50) // 100 for y in ys])
    assert abs(total - whole) / whole < 0.001


def test_clip_big_lake_covers_middle_tile_without_vertices():
    w0, w1 = 1_389_400_000, 1_390_500_000          # 3マスの列（3628〜3630）にまたがる長い長方形
    s0, s1 = 352_000_000, 352_100_000
    pieces = clip_ring([w0, w1, w1, w0], [s0, s0, s1, s1])
    assert sorted(pieces) == [(3628, 1619), (3629, 1619), (3630, 1619)]
    mx, my = pieces[(3629, 1619)]
    edge5 = lambda tx: math.floor((Fraction(tx * 360, N) - 180) * 100000 + Fraction(1, 2))
    assert (min(mx), max(mx)) == (edge5(3629), edge5(3630))  # 13895508, 13904297
    assert (min(my), max(my)) == (3520000, 3521000) and len(mx) == 4


def test_clip_single_tile_and_range():
    xs, ys = [1_389_600_000, 1_389_610_000, 1_389_610_000], [352_000_000, 352_000_000, 352_010_000]
    assert clip_ring(xs, ys) == {(3629, 1619): ([13896000, 13896100, 13896100], [3520000, 3520000, 3520100])}
    assert clip_ring(xs, ys, (3628, 1619, 3628, 1619)) == {}
    w0, w1, s0, s1 = 1_389_400_000, 1_390_500_000, 352_000_000, 352_100_000
    assert sorted(clip_ring([w0, w1, w1, w0], [s0, s0, s1, s1], (3629, 1600, 3700, 1700))) == [(3629, 1619), (3630, 1619)]
    # 点が1か所につぶれる小さな輪は入れない
    assert clip_ring([1_389_600_000, 1_389_600_010, 1_389_600_000], [352_000_000, 352_000_000, 352_000_010]) == {}


# ---------------------------------------------------------------- 輪の組み立て

def test_assemble_rings_joins_open_ways_in_any_direction():
    # 正方形の外側を3本の道（1本は逆向き）で、内側を閉じた道1本で描く
    ways = {
        1: (10, 11, [0, 100], [0, 0]),                          # 10 (0,0) → 11 (100,0)
        2: (12, 11, [0, 100, 100], [100, 100, 0]),              # 12 (0,100) → (100,100) → 11（逆向き）
        3: (12, 10, [0, 0], [100, 0]),                          # 12 → 10
        4: (20, 20, [40, 60, 60, 40, 40], [40, 40, 60, 60, 40]),  # 閉じた道
    }
    rings, broken = assemble_rings(ways, [(1, False), (2, False), (3, False), (4, True)])
    assert broken == 0
    assert rings[0] == (False, [0, 100, 100, 0], [0, 0, 100, 100])
    assert rings[1] == (True, [40, 60, 60, 40], [40, 40, 60, 60])


def test_assemble_rings_counts_unclosed_and_skips_missing():
    ways = {1: (10, 11, [0, 100], [0, 0]), 2: (11, 12, [100, 100], [0, 100])}
    rings, broken = assemble_rings(ways, [(1, False), (2, False), (99, False)])
    assert rings == [] and broken == 1
