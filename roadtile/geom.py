"""川の線と水面の形の計算（入出力のない純粋な関数）：点の間引き、輪の向き、マスの四角での切り取り。

座標は OpenStreetMap と同じ 1e7 倍の整数で受け取ります。浮動小数は間引きの距離の比較だけに使い、
足し算・掛け算・割り算（IEEE 754 の丸め）だけにして、どの PC でも同じ結果になるようにしています。
"""
import numpy as np

from .tiles import N, ROW_TOP, tiles_xy7, tile_y7

SIMPLIFY_TOL = 200          # 間引きのずれの上限（1e7 倍の座標。約2m）
_LON_OFF = 1_800_000_000    # 経度 +180°
_COL = 3_600_000_000        # 1マスの幅（経度を N 倍した座標で）
_NUMPY_FROM = 48            # これより長い範囲は numpy で計算する


def _farthest(x, y, a, b, nx=None, ny=None):
    """a〜b の線分から、間の点でいちばん遠い点の (番号, 線分までの距離の2乗)。同じなら前の点。

    nx, ny は x, y と同じ値の numpy 配列（長い範囲の計算に使う）。どちらで計算しても同じ値になる。
    """
    dx, dy = x[b] - x[a], y[b] - y[a]
    L2 = dx * dx + dy * dy
    if nx is not None and b - a > _NUMPY_FROM:
        px = nx[a + 1:b] - x[a]
        py = ny[a + 1:b] - y[a]
        if L2 == 0:
            d = (px * px + py * py).astype(np.float64)
        else:
            c = (px * dy - py * dx).astype(np.float64)
            d = c * c / float(L2)
        i = int(np.argmax(d))
        return a + 1 + i, float(d[i])
    best, bi = -1.0, a + 1
    for k in range(a + 1, b):
        px, py = x[k] - x[a], y[k] - y[a]
        if L2 == 0:
            v = float(px * px + py * py)
        else:
            c = float(px * dy - py * dx)
            v = c * c / float(L2)
        if v > best:
            best, bi = v, k
    return bi, best


def simplify_keep(x, y, a=0, b=None, keep=None, tol=SIMPLIFY_TOL):
    """Douglas–Peucker 法で残す点の印（bool の並び）。両端は残す。x, y は整数の並び。"""
    if b is None:
        b = len(x) - 1
    if keep is None:
        keep = [False] * len(x)
    keep[a] = keep[b] = True
    tol2 = float(tol) * float(tol)
    nx = ny = None
    if b - a > _NUMPY_FROM:
        nx, ny = np.asarray(x, dtype=np.int64), np.asarray(y, dtype=np.int64)
    stack = [(a, b)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        k, d = _farthest(x, y, s, e, nx, ny)
        if d > tol2:
            keep[k] = True
            stack.append((k, e))
            stack.append((s, k))
    return keep


def simplify_line(xs, ys, tol=SIMPLIFY_TOL):
    """線を間引いた (xs, ys)。"""
    if len(xs) <= 2:
        return list(xs), list(ys)
    keep = simplify_keep(xs, ys, tol=tol)
    return [v for v, k in zip(xs, keep) if k], [v for v, k in zip(ys, keep) if k]


def simplify_ring(xs, ys, tol=SIMPLIFY_TOL):
    """輪（最初の点はくり返さない）を間引いた (xs, ys)。最初の点と、そこからいちばん遠い点を残して2つに分けて間引く。"""
    n = len(xs)
    if n <= 3:
        return list(xs), list(ys)
    far, best = 0, -1
    for k in range(1, n):
        d = (xs[k] - xs[0]) ** 2 + (ys[k] - ys[0]) ** 2
        if d > best:
            best, far = d, k
    x2, y2 = list(xs) + [xs[0]], list(ys) + [ys[0]]
    keep = simplify_keep(x2, y2, 0, far, tol=tol)
    simplify_keep(x2, y2, far, n, keep, tol)
    return [x2[i] for i in range(n) if keep[i]], [y2[i] for i in range(n) if keep[i]]


def area2(xs, ys):
    """輪の面積の2倍（反時計回りなら正）。整数で正確に計算する。"""
    n = len(xs)
    if n < 3:
        return 0
    x0, y0 = xs[0], ys[0]
    s = 0
    for i in range(1, n - 1):
        s += (xs[i] - x0) * (ys[i + 1] - y0) - (xs[i + 1] - x0) * (ys[i] - y0)
    return s


def _rdiv(num, den):
    """num / den をいちばん近い整数に（ちょうど半分なら大きいほう）。"""
    if den < 0:
        num, den = -num, -den
    return (2 * num + den) // (2 * den)


def centroid(xs, ys):
    """輪の重心 (x, y)（整数）。面積が 0 なら頂点の平均。"""
    n = len(xs)
    x0, y0 = xs[0], ys[0]
    a = cx = cy = 0
    for i in range(n):
        px, py = xs[i] - x0, ys[i] - y0
        qx, qy = xs[(i + 1) % n] - x0, ys[(i + 1) % n] - y0
        c = px * qy - qx * py
        a += c
        cx += (px + qx) * c
        cy += (py + qy) * c
    if a == 0:
        return sum(xs) // n, sum(ys) // n
    return x0 + _rdiv(cx, 3 * a), y0 + _rdiv(cy, 3 * a)


def _clip(pts, axis, bound, ge):
    """Sutherland–Hodgman 法で、axis（0 = x、1 = y）の値が bound 以上（ge）か以下の側を残す。交点は整数に丸める。"""
    if not pts:
        return pts
    o = 1 - axis
    out = []
    prev = pts[-1]
    pin = prev[axis] >= bound if ge else prev[axis] <= bound
    for cur in pts:
        cin = cur[axis] >= bound if ge else cur[axis] <= bound
        if cin != pin:
            v = prev[o] + _rdiv((cur[o] - prev[o]) * (bound - prev[axis]), cur[axis] - prev[axis])
            out.append((bound, v) if axis == 0 else (v, bound))
        if cin:
            out.append(cur)
        prev, pin = cur, cin
    return out


def _to5(pts):
    """切り取った輪（経度は N 倍した座標）を 1e5 倍の座標の (xs, ys) にする。前と同じ点は落とす。"""
    xs, ys = [], []
    for X, Y in pts:
        x = (X - _LON_OFF * N + 50 * N) // (100 * N)
        y = (Y + 50) // 100
        if xs and xs[-1] == x and ys[-1] == y:
            continue
        xs.append(x)
        ys.append(y)
    while len(xs) > 1 and xs[0] == xs[-1] and ys[0] == ys[-1]:
        xs.pop()
        ys.pop()
    return xs, ys


def clip_ring(xs7, ys7, rng=None):
    """輪をマスの四角で切り取り、{(マス x, マス y): (xs, ys)} を返す（座標は 1e5 倍の整数）。

    rng = (x0, y0, x1, y1) を渡すと、その範囲のマスだけを作る。点が3つ未満の部分と面積が 0 の部分は入れない。
    """
    tx, ty = tiles_xy7(np.asarray(xs7, dtype=np.int64), np.asarray(ys7, dtype=np.int64))
    cx0, cx1, ry0, ry1 = int(tx.min()), int(tx.max()), int(ty.min()), int(ty.max())
    one = cx0 == cx1 and ry0 == ry1
    if rng is not None:
        cx0, cx1, ry0, ry1 = max(cx0, rng[0]), min(cx1, rng[2]), max(ry0, rng[1]), min(ry1, rng[3])
        if cx0 > cx1 or ry0 > ry1:
            return {}
    out = {}

    def put(key, pts):
        x, y = _to5(pts)
        if len(x) >= 3 and area2(x, y) != 0:
            out[key] = (x, y)

    pts = [((x + _LON_OFF) * N, y) for x, y in zip(xs7, ys7)]
    if one:
        put((cx0, ry0), pts)  # 1枚のマスに収まる（ほとんどの池）
        return out
    for c in range(cx0, cx1 + 1):
        col = _clip(_clip(pts, 0, c * _COL, True), 0, (c + 1) * _COL, False)
        if len(col) < 3:
            continue
        ys = [p[1] for p in col]
        r0, r1 = max(ry0, tile_y7(max(ys))), min(ry1, tile_y7(min(ys)))
        for r in range(r0, r1 + 1):
            put((c, r), _clip(_clip(col, 1, ROW_TOP[r + 1], True), 1, ROW_TOP[r], False))
    return out


def assemble_rings(ways, members):
    """マルチポリゴンの輪を組み立てる。

    ways: {way_id: (最初のノード ID, 最後のノード ID, xs7, ys7)}（座標のない点を含む道は入れない）
    members: [(way_id, inner)] をリレーションの並び順で。inner は内側の輪（role=inner）なら True。
    返り値: ([(inner, xs7, ys7)], 組み立てられなかった輪の数)。輪の最初の点はくり返さない。
    外側・内側それぞれで、並び順に、端のノード ID が同じ道をつないで閉じるまで伸ばす。
    """
    rings, broken = [], 0
    for want_inner in (False, True):
        segs = [ways[w] for w, inner in members if inner == want_inner and w in ways]
        ends = {}
        for i, (a, b, _, _) in enumerate(segs):
            if a != b:  # 閉じた道はそれだけで輪になる
                ends.setdefault(a, []).append(i)
                ends.setdefault(b, []).append(i)
        used = [False] * len(segs)
        for i, (start, end, xs, ys) in enumerate(segs):
            if used[i]:
                continue
            used[i] = True
            X, Y = list(xs), list(ys)
            while end != start:
                j = next((k for k in ends.get(end, ()) if not used[k]), None)
                if j is None:
                    break
                used[j] = True
                a, b, xs2, ys2 = segs[j]
                if a == end:
                    X += xs2[1:]
                    Y += ys2[1:]
                    end = b
                else:
                    X += xs2[-2::-1]
                    Y += ys2[-2::-1]
                    end = a
            if end == start and len(X) >= 4:
                rings.append((want_inner, X[:-1], Y[:-1]))
            else:
                broken += 1
    return rings, broken
