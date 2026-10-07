"""道路タイル1枚の詰め方と戻し方（docs/FORMAT.md の「マスのファイル」）。入出力のない純粋な関数。"""
import gzip
import json

FORMAT_VERSION = 1


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def gzip_bytes(data):
    # mtime=0 にして、同じ中身なら同じバイト列になるようにする
    return gzip.compress(data, compresslevel=6, mtime=0)


def _line_rows(lines):
    """鉄道・川の線 (way, part, kind, flags, xs, ys) を行にする。"""
    rows, prev_way = [], 0
    for way, part, kind, flags, xs, ys in sorted(lines, key=lambda r: (r[0], r[1])):
        row = [kind, flags, way - prev_way, part, xs[0], ys[0]]
        prev_way = way
        px, py = xs[0], ys[0]
        for k in range(1, len(xs)):
            dx, dy = xs[k] - px, ys[k] - py
            if dx == 0 and dy == 0 and k < len(xs) - 1:
                continue  # 前の点と同じ点は落とす（最後の点は残す）
            row += [dx, dy]
            px, py = xs[k], ys[k]
        rows.append(row)
    return rows


def _water_rows(water):
    """水面の輪 (src, ring, kind, flags, xs, ys) を行にする。輪の点はそのまま（作る側で重なりを落としてある）。"""
    rows = []
    for src, _ring, kind, flags, xs, ys in sorted(water, key=lambda r: (r[0], r[1])):
        row = [kind, flags, src, xs[0], ys[0]]
        for k in range(1, len(xs)):
            row += [xs[k] - xs[k - 1], ys[k] - ys[k - 1]]
        rows.append(row)
    return rows


def encode_tile(tx, ty, z, edges, places, rails=(), rivers=(), water=()):
    """マス1枚を JSON のバイト列にする。

    edges:  (way, seg, u, v, kind, flags, name, ref, xs, ys) の並び。
            xs, ys は両端を含む座標（経度・緯度の 1e5 倍の整数）。
    places: (kind, name, x, y, osm_type, osm_id) の並び。osm_type は 0=ノード、1=道（面）、2=リレーション。
    rails:  (way, part, kind, flags, xs, ys) の並び。鉄道の線のひと続き（地図に描くだけ）。
    rivers: (way, part, kind, flags, xs, ys) の並び。川の線のひと続き（地図に描くだけ）。
    water:  (src, ring, kind, flags, xs, ys) の並び。水面の輪をこのマスで切り取ったもの。
            src は道なら ID、リレーションなら -ID。ring は src の中での輪の番号（並べるためだけに使う）。
    """
    edges = sorted(edges, key=lambda e: (e[0], e[1]))
    places = sorted(places, key=lambda p: (p[0], p[2], p[3], p[1], p[4], p[5]))

    node_xy = {}
    for e in edges:
        xs, ys = e[8], e[9]
        node_xy[e[2]] = (xs[0], ys[0])
        node_xy[e[3]] = (xs[-1], ys[-1])
    ids = sorted(node_xy)
    index = {nid: i for i, nid in enumerate(ids)}
    nodes, xy = [], []
    pid = px = py = 0
    for nid in ids:
        x, y = node_xy[nid]
        nodes.append(nid - pid)
        xy += [x - px, y - py]
        pid, px, py = nid, x, y

    names, name_index = [''], {'': 0}

    def nm(s):
        i = name_index.get(s)
        if i is None:
            i = name_index[s] = len(names)
            names.append(s)
        return i

    rows, prev_way = [], 0
    for way, seg, u, v, kind, flags, name, ref, xs, ys in edges:
        row = [index[u], index[v], kind, flags, nm(name), nm(ref), way - prev_way, seg]
        prev_way = way
        px, py = xs[0], ys[0]
        for k in range(1, len(xs) - 1):
            dx, dy = xs[k] - px, ys[k] - py
            if dx == 0 and dy == 0:
                continue  # 前の点と同じ点は落とす
            row += [dx, dy]
            px, py = xs[k], ys[k]
        rows.append(row)

    prow, px, py = [], 0, 0
    for kind, name, x, y, _t, _i in places:
        prow.append([kind, nm(name), x - px, y - py])
        px, py = x, y

    return _dumps({'v': FORMAT_VERSION, 'z': z, 'x': tx, 'y': ty, 'nodes': nodes, 'xy': xy,
                   'edges': rows, 'names': names, 'places': prow, 'rails': _line_rows(rails),
                   'rivers': _line_rows(rivers), 'water': _water_rows(water)})


def _decode_lines(rows):
    out, way = [], 0
    for row in rows:
        kind, flags, dway, part, x, y = row[:6]
        way += dway
        xs, ys = [x], [y]
        for k in range(6, len(row), 2):
            x += row[k]
            y += row[k + 1]
            xs.append(x)
            ys.append(y)
        out.append((way, part, kind, flags, xs, ys))
    return out


def decode_tile(data):
    """encode_tile（gzip 済みでもよい）を戻す。

    返り値: {'x', 'y', 'z', 'nodes': {id: (x, y)},
             'edges': [(way, seg, u, v, kind, flags, name, ref, xs, ys)],
             'places': [(kind, name, x, y)],
             'rails': [(way, part, kind, flags, xs, ys)],
             'rivers': [(way, part, kind, flags, xs, ys)],
             'water': [(kind, flags, src, xs, ys)]}   （ない項目は空。rails は 0.2.0、rivers・water は 0.3.0 から）
    """
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    t = json.loads(data)
    if t.get('v') != FORMAT_VERSION:
        raise ValueError(f'unsupported tile format version: {t.get("v")}')
    ids, coords = [], []
    nid = x = y = 0
    for i, d in enumerate(t['nodes']):
        nid += d
        x += t['xy'][2 * i]
        y += t['xy'][2 * i + 1]
        ids.append(nid)
        coords.append((x, y))
    names = t['names']
    edges, way = [], 0
    for row in t['edges']:
        ui, vi, kind, flags, ni, ri, dway, seg = row[:8]
        way += dway
        x, y = coords[ui]
        xs, ys = [x], [y]
        for k in range(8, len(row), 2):
            x += row[k]
            y += row[k + 1]
            xs.append(x)
            ys.append(y)
        xs.append(coords[vi][0])
        ys.append(coords[vi][1])
        edges.append((way, seg, ids[ui], ids[vi], kind, flags, names[ni], names[ri], xs, ys))
    places, x, y = [], 0, 0
    for kind, ni, dx, dy in t['places']:
        x += dx
        y += dy
        places.append((kind, names[ni], x, y))
    water = []
    for row in t.get('water', []):
        kind, flags, src, x, y = row[:5]
        xs, ys = [x], [y]
        for k in range(5, len(row), 2):
            x += row[k]
            y += row[k + 1]
            xs.append(x)
            ys.append(y)
        water.append((kind, flags, src, xs, ys))
    return {'x': t['x'], 'y': t['y'], 'z': t['z'], 'nodes': dict(zip(ids, coords)), 'edges': edges, 'places': places,
            'rails': _decode_lines(t.get('rails', [])), 'rivers': _decode_lines(t.get('rivers', [])), 'water': water}
