"""Geofabrik の PBF から道路タイルを作る。手順は docs/PIPELINE.md を参照。

1. 水面のマルチポリゴン（リレーション）を読み、道を読んで道路のノード ID を数える（交差点 = 2本以上の道が
   共有するノード、と道の両端）。マルチポリゴンの部品の道のノード ID も集める
2. 道をもう一度読み、交差点で区切った区間をマスごとの一時ファイルに書く（面の施設、鉄道・川の線、水面も）。
   最後にマルチポリゴンの部品の道を読み、輪を組み立てて書く
3. ノードを読み、地名・駅・山頂・交差点名・施設を一時ファイルに書く
4. 一時ファイルをまとめてマスのファイルを書き、最後に目録（manifest.json）を書く
"""
import array
import hashlib
import json
import marshal
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import osmium
import osmium.filter as F

from . import __version__
from .encode import FORMAT_VERSION, encode_tile, gzip_bytes
from .geom import area2, assemble_rings, centroid, clip_ring, simplify_line, simplify_ring
from .tags import (FLAGS, NODE_KEYS, PLACE_CODE, PLACE_KINDS, RAIL_KINDS, RIVER_KINDS, ROAD_KINDS, WATER_CODE,
                   WATER_KINDS, WAY_KEYS, place_kind, rail_attrs, river_attrs, road_attrs, water_attrs)
from .tiles import N, Z, tile_x7, tile_y7, tiles_in_bbox, tiles_xy7

UNDEF = 2147483647          # osmium の「座標なし」
CHUNK_VERTS = 500_000       # まとめて計算する頂点の数
BUCKET_SHIFT = 4            # 一時ファイルは 16×16 マス（ズーム8）ずつ
BATCH = 2048                # 一時ファイルにまとめて書く記録の数
RAIL_PART = 64              # 鉄道・川の線は、この頂点数ずつに分けてマスに入れる
LAKE_MIN_AREA7 = 1_000_000_000  # 湖の名前を地名に入れる水面の広さ（1e7 倍の座標での面積。北緯35度で約10ha）
LAKE_WATER = frozenset(WATER_CODE[k] for k in ('lake', 'reservoir', 'pond', 'water'))
FORMAT_NAME = 'course3d-roadtile'

# 一時ファイルの記録の種類（先頭の値）
R_EDGE, R_PLACE, R_RAIL, R_RIVER, R_WATER = range(5)


def _log_default(msg):
    print(msg, file=sys.stderr, flush=True)


def _peak_mb():
    """これまでに使ったメモリの最大（MB）。分からなければ nan。"""
    try:
        if sys.platform == 'win32':
            return _peak_mb_windows()
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1024 / 1024 if sys.platform == 'darwin' else r / 1024
    except Exception:
        return float('nan')


def _peak_mb_windows():
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

    kernel32, psapi = ctypes.WinDLL('kernel32'), ctypes.WinDLL('psapi')
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    c = Counters()
    c.cb = ctypes.sizeof(Counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        return float('nan')
    return c.PeakWorkingSetSize / 1024 / 1024


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def source_info(pbf, date=None):
    """元ファイルの情報。版の日付は、指定がなければ PBF の見出しの更新時刻（UTC）の日付。"""
    reader = osmium.io.Reader(str(pbf), osmium.osm.NOTHING)
    try:
        ts = reader.header().get('osmosis_replication_timestamp', '') or None
    finally:
        reader.close()
    if date is None:
        if not ts:
            raise ValueError('PBF に更新時刻がありません。--date YYYY-MM-DD で版の日付を指定してください')
        date = ts[:10]
    return {'file': Path(pbf).name, 'bytes': os.path.getsize(pbf), 'sha256': _sha256_file(pbf),
            'timestamp': ts, 'date': date}


# ---------------------------------------------------------------- 1. ノード ID を数える

class WaterRels:
    """水面のマルチポリゴン（リレーション）。rels は (ID, 種類, 印, 名前, [(道の ID, 内側か)]) を ID の順に。"""

    def __init__(self, rels):
        self.rels = rels
        self.members = np.unique(np.array([w for r in rels for w, _ in r[4]], dtype=np.int64))
        self.outer = frozenset(w for r in rels for w, inner in r[4] if not inner)


def read_water_relations(pbf, log=_log_default):
    """水面のマルチポリゴンを読む（type=multipolygon で、water_attrs に合うもの）。"""
    rels = []
    fp = osmium.FileProcessor(str(pbf), osmium.osm.RELATION).with_filter(F.KeyFilter('natural', 'waterway'))
    for r in fp:
        tags = r.tags
        if tags.get('type') != 'multipolygon':
            continue
        a = water_attrs(tags)
        if a is None:
            continue
        members = [(m.ref, m.role == 'inner') for m in r.members if m.type == 'w']
        if members:
            rels.append((r.id, a[0], a[1], tags.get('name') or '', members))
    rels.sort(key=lambda r: r[0])
    w = WaterRels(rels)
    log(f'  水面のマルチポリゴン {len(rels):,}（部品の道 {len(w.members):,} 本）')
    return w


def collect_refs(pbf, log=_log_default, water=None):
    """(交差点のノード ID, 座標が要るノード ID) を、どちらも小さい順の numpy 配列で返す。"""
    road = array.array('q')   # 道路の各頂点＋両端をもう1回ずつ。2回以上出てくれば区切り点
    other = array.array('q')  # 面の施設・鉄道・川・水面の頂点（座標だけ要る）
    outer = water.outer if water is not None else frozenset()
    n_ways = 0
    fp = osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(F.KeyFilter(*WAY_KEYS))
    for w in fp:
        tags = w.tags
        is_road = road_attrs(tags) is not None
        is_place = place_kind(tags, node=False) is not None
        is_line = rail_attrs(tags) is not None or river_attrs(tags) is not None
        is_water = water_attrs(tags) is not None
        if not (is_road or is_place or is_line or is_water):
            continue
        refs = [n.ref for n in w.nodes]
        if is_road and len(refs) >= 2:
            road.extend(refs)
            road.append(refs[0])
            road.append(refs[-1])
            n_ways += 1
        if is_place and len(refs) >= 4 and refs[0] == refs[-1]:
            other.extend(refs)
        if is_line and len(refs) >= 2:
            other.extend(refs)
        if is_water and len(refs) >= 4 and refs[0] == refs[-1] and w.id not in outer:
            other.extend(refs)
    if water is not None and len(water.members):
        idw = F.IdFilter(water.members)
        for w in osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(idw):
            other.extend(n.ref for n in w.nodes)
    a = np.frombuffer(road, dtype=np.int64)  # 写さずにその場で並べ替える（メモリを倍にしない）
    a.sort()
    first = np.ones(len(a), dtype=bool)       # 同じ ID の並びの先頭
    np.not_equal(a[1:], a[:-1], out=first[1:])
    again = np.zeros(len(a), dtype=bool)      # すぐ後ろに同じ ID がある
    again[:-1] = ~first[1:]
    junc = a[first & again]
    need = a[first]
    del a, first, again, road
    if len(other):
        need = np.union1d(need, np.frombuffer(other, dtype=np.int64))
    del other
    log(f'  道路 {n_ways:,} 本、区切り点 {len(junc):,}、座標が要るノード {len(need):,}')
    return junc, need, {'roadWays': n_ways}


# ---------------------------------------------------------------- 一時ファイル

class Buckets:
    """マスの記録を、ズーム8 のまとまりごとの一時ファイルに書きためる。"""

    def __init__(self, workdir, rng=None):
        self.dir = Path(workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rng = rng
        self.files = {}
        self.pending = {}
        self.records = 0
        try:  # 一時ファイルを同時にたくさん開くので、開けるファイルの数の上限を上げておく
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            want = 4096 if hard == resource.RLIM_INFINITY else min(4096, hard)
            if soft < want:
                resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
        except Exception:
            pass

    def inside(self, tx, ty):
        r = self.rng
        return r is None or (r[0] <= tx <= r[2] and r[1] <= ty <= r[3])

    def put(self, tx, ty, rec):
        if not self.inside(tx, ty):
            return
        key = (tx >> BUCKET_SHIFT, ty >> BUCKET_SHIFT)
        batch = self.pending.get(key)
        if batch is None:
            batch = self.pending[key] = []
        batch.append((tx, ty, rec))
        self.records += 1
        if len(batch) >= BATCH:
            self._write(key, batch)
            self.pending[key] = []

    def _write(self, key, batch):
        f = self.files.get(key)
        if f is None:
            f = self.files[key] = open(self._path(key), 'ab', buffering=1 << 20)
        marshal.dump(batch, f)

    def _path(self, key):
        return self.dir / f'{key[0]}_{key[1]}.bin'

    def close(self):
        for key, batch in self.pending.items():
            if batch:
                self._write(key, batch)
        self.pending = {}
        for f in self.files.values():
            f.close()

    def keys(self):
        return sorted(self.files)

    def read(self, key):
        with open(self._path(key), 'rb') as f:
            while True:
                try:
                    batch = marshal.load(f)
                except EOFError:
                    return
                yield from batch

    def remove(self, key):
        self._path(key).unlink()


# ---------------------------------------------------------------- 2. 区間を書く

class _Chunk:
    def __init__(self):
        self.R = array.array('q')
        self.X = array.array('i')
        self.Y = array.array('i')
        self.starts = array.array('q')
        self.meta = []

    def add(self, way_id, attrs, pts):
        self.starts.append(len(self.R))
        rs, xs, ys = zip(*pts)
        self.R.extend(rs)
        self.X.extend(xs)
        self.Y.extend(ys)
        self.meta.append((way_id,) + attrs)

    def __len__(self):
        return len(self.R)


def _cover(tx, ty, s, e):
    """区間の各線分の両端が入るマスの範囲を合わせた、区間が通る（かもしれない）マス。"""
    out = set()
    for k in range(s, e):
        x0, x1 = sorted((tx[k], tx[k + 1]))
        y0, y1 = sorted((ty[k], ty[k + 1]))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                out.add((x, y))
    return sorted(out)


def _flush(c, junc, buckets, st):
    if not c.meta:
        return
    R = np.frombuffer(c.R, dtype=np.int64)
    X = np.frombuffer(c.X, dtype=np.int32).astype(np.int64)
    Y = np.frombuffer(c.Y, dtype=np.int32).astype(np.int64)
    starts = np.frombuffer(c.starts, dtype=np.int64)
    n = len(R)
    ends = np.empty_like(starts)
    ends[:-1] = starts[1:]
    ends[-1] = n

    cut = np.zeros(n, dtype=bool)
    if len(junc):
        p = np.searchsorted(junc, R)
        p[p == len(junc)] = 0
        cut = junc[p] == R
    cut[starts] = True
    cut[ends - 1] = True
    P = np.flatnonzero(cut)
    W = np.searchsorted(starts, P, side='right') - 1
    same = W[:-1] == W[1:]
    S, E, WI = P[:-1][same], P[1:][same], W[:-1][same]
    seg = np.arange(len(S)) - np.searchsorted(WI, WI, side='left')

    miss = (X == UNDEF) | (Y == UNDEF)
    cm = np.concatenate(([0], np.cumsum(miss)))
    bad = (cm[E + 1] - cm[S]) > 0
    tx, ty = tiles_xy7(np.where(miss, 0, X), np.where(miss, 0, Y))
    tid = tx * N + ty
    cc = np.concatenate(([0], np.cumsum(tid[1:] != tid[:-1])))
    single = (cc[E] - cc[S]) == 0
    x5 = ((X + 50) // 100).tolist()
    y5 = ((Y + 50) // 100).tolist()

    Rl, txl, tyl = R.tolist(), tx.tolist(), ty.tolist()
    meta = c.meta
    for s, e, wi, sg, b, one in zip(S.tolist(), E.tolist(), WI.tolist(), seg.tolist(), bad.tolist(), single.tolist()):
        if b:
            st['droppedEdges'] += 1  # 座標のないノードを含む（抜き出しの境目など）
            continue
        u, v = Rl[s], Rl[e]
        if u == v and e - s == 1:
            continue  # 同じノードが続くだけの区間
        tiles = [(txl[s], tyl[s])] if one else _cover(txl, tyl, s, e)
        if buckets.rng is not None:
            tiles = [t for t in tiles if buckets.inside(*t)]
            if not tiles:
                continue
        way, kind, flags, name, ref = meta[wi]
        rec = (R_EDGE, way, sg, u, v, kind, flags, name, ref, x5[s:e + 1], y5[s:e + 1])
        st['edges'] += 1
        if len(tiles) > 1:
            st['multiTileEdges'] += 1
        for a, bb in tiles:
            buckets.put(a, bb, rec)


def _emit_line(rtype, way_id, attrs, pts, buckets, st, count, simplify=False):
    """鉄道・川の線を RAIL_PART 頂点ずつ（端の点は重ねる）に分け、通るマスすべてに書く。座標のない点で線を切る。

    simplify=True（川）は、分ける前にひと続きごとに点を間引く。
    """
    kind, flags = attrs
    runs, cur = [], []
    for _, x, y in pts:
        if x == UNDEF or y == UNDEF:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
        else:
            cur.append((x, y))
    if len(cur) >= 2:
        runs.append(cur)
    part = 0
    for run in runs:
        xs, ys = [p[0] for p in run], [p[1] for p in run]
        if simplify:
            xs, ys = simplify_line(xs, ys)
        for s in range(0, len(xs) - 1, RAIL_PART - 1):
            xs7 = np.array(xs[s:s + RAIL_PART], dtype=np.int64)
            ys7 = np.array(ys[s:s + RAIL_PART], dtype=np.int64)
            tx, ty = tiles_xy7(xs7, ys7)
            tiles = _cover(tx.tolist(), ty.tolist(), 0, len(xs7) - 1)
            if buckets.rng is not None:
                tiles = [t for t in tiles if buckets.inside(*t)]
            if tiles:
                rec = (rtype, way_id, part, kind, flags, ((xs7 + 50) // 100).tolist(), ((ys7 + 50) // 100).tolist())
                for a, b in tiles:
                    buckets.put(a, b, rec)
                st[count] += 1
            part += 1


def _emit_ring(src, ring_no, kind, flags, xs7, ys7, inner, buckets, st):
    """水面の輪を間引き、向きをそろえ（外側は反時計回り、内側は時計回り）、マスの四角で切り取って書く。"""
    xs, ys = simplify_ring(xs7, ys7)
    a = area2(xs, ys)
    if len(xs) < 3 or a == 0:
        return
    if (a > 0) == inner:
        xs.reverse()
        ys.reverse()
    pieces = clip_ring(xs, ys, buckets.rng)
    for (tx, ty), (x5, y5) in pieces.items():
        buckets.put(tx, ty, (R_WATER, src, ring_no, kind, flags, x5, y5))
    if pieces:
        st['waterRings'] += 1
        st['waterPieces'] += len(pieces)


def _emit_lake(name, kind, rings, osm_type, osm_id, buckets, st):
    """名前のある広い水面を、地名（lake）として、いちばん大きい外側の輪の重心に書く。rings は [(内側か, xs7, ys7)]。"""
    if not name or kind not in LAKE_WATER:
        return
    total, best, big = 0, None, -1
    for inner, xs, ys in rings:
        a = abs(area2(xs, ys))
        total += -a if inner else a
        if not inner and a > big:
            big, best = a, (xs, ys)
    if best is None or total < 2 * LAKE_MIN_AREA7:
        return
    cx, cy = centroid(*best)
    buckets.put(tile_x7(cx), tile_y7(cy), (R_PLACE, PLACE_CODE['lake'], name, (cx + 50) // 100, (cy + 50) // 100,
                                           osm_type, osm_id))
    st['lakes'] += 1


def _read_member_ways(pbf, ids, lh):
    """マルチポリゴンの部品の道を、座標つきで読む。{道の ID: (最初のノード ID, 最後のノード ID, xs7, ys7)}。"""
    idw = F.IdFilter(ids)
    idw.enable_for(osmium.osm.WAY)
    reader = osmium.io.Reader(str(pbf), osmium.osm.WAY)
    ways = {}
    try:
        for w in osmium.OsmFileIterator(reader, idw, lh):
            nodes = w.nodes
            if len(nodes) < 2:
                continue
            xs, ys = array.array('i'), array.array('i')
            for n in nodes:
                if n.x == UNDEF or n.y == UNDEF:
                    break
                xs.append(n.x)
                ys.append(n.y)
            else:
                ways[w.id] = (nodes[0].ref, nodes[-1].ref, xs, ys)
    finally:
        reader.close()
    return ways


def _emit_water_relations(pbf, water, lh, buckets, st, log):
    ways = _read_member_ways(pbf, water.members, lh)
    for rid, kind, flags, name, members in water.rels:
        rings, broken = assemble_rings(ways, members)
        st['waterBroken'] += broken
        rings = [(inner, list(xs), list(ys)) for inner, xs, ys in rings]
        for i, (inner, xs, ys) in enumerate(rings):
            _emit_ring(-rid, i, kind, flags, xs, ys, inner, buckets, st)
        _emit_lake(name, kind, rings, 2, rid, buckets, st)
    log(f'  マルチポリゴンの部品の道 {len(ways):,} 本、組み立てられなかった輪 {st["waterBroken"]:,}')


def emit_ways(pbf, junc, need_box, buckets, node_store='flex_mem', log=_log_default, water=None):
    """道をもう一度読み、区切った区間・面の施設・鉄道と川の線・水面を一時ファイルに書く。

    need_box は {'need': 配列}。読み込みの絞り込みを作ったあとで配列を手放すため、箱に入れて渡す。
    water（WaterRels）を渡すと、最後にマルチポリゴンの部品の道を読み、輪を組み立てて書く。
    """
    st = {'edges': 0, 'multiTileEdges': 0, 'droppedEdges': 0, 'placeWays': 0, 'railParts': 0,
          'riverParts': 0, 'waterRings': 0, 'waterPieces': 0, 'waterBroken': 0, 'lakes': 0}
    outer = water.outer if water is not None else frozenset()
    need = need_box.pop('need')
    idf = F.IdFilter(need)  # 座標が要るノードだけを覚える
    del need
    idf.enable_for(osmium.osm.NODE)
    store = osmium.index.create_map(node_store)
    lh = osmium.NodeLocationsForWays(store)
    lh.ignore_errors()
    ef = F.EntityFilter(osmium.osm.WAY)
    kf = F.KeyFilter(*WAY_KEYS)
    handlers = (idf, lh, ef, kf)  # 読み終わるまで参照を持っておく（手放すと osmium が落ちる）
    reader = osmium.io.Reader(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
    chunk = _Chunk()
    try:
        for w in osmium.OsmFileIterator(reader, *handlers):
            tags = w.tags
            attrs = road_attrs(tags)
            pk = place_kind(tags, node=False)
            ra = rail_attrs(tags)
            rv = river_attrs(tags)
            wa = water_attrs(tags)
            if attrs is None and pk is None and ra is None and rv is None and wa is None:
                continue
            pts = [(n.ref, n.x, n.y) for n in w.nodes]
            if attrs is not None and len(pts) >= 2:
                chunk.add(w.id, attrs, pts)
                if len(chunk) >= CHUNK_VERTS:
                    _flush(chunk, junc, buckets, st)
                    chunk = _Chunk()
            if pk is not None and len(pts) >= 4 and pts[0][0] == pts[-1][0]:
                ok = [(x, y) for _, x, y in pts[:-1] if x != UNDEF and y != UNDEF]
                if ok:
                    cx = sum(x for x, _ in ok) // len(ok)
                    cy = sum(y for _, y in ok) // len(ok)
                    buckets.put(tile_x7(cx), tile_y7(cy),
                                (R_PLACE, pk, tags.get('name'), (cx + 50) // 100, (cy + 50) // 100, 1, w.id))
                    st['placeWays'] += 1
            if ra is not None and len(pts) >= 2:
                _emit_line(R_RAIL, w.id, ra, pts, buckets, st, 'railParts')
            if rv is not None and len(pts) >= 2:
                _emit_line(R_RIVER, w.id, rv, pts, buckets, st, 'riverParts', simplify=True)
            if (wa is not None and len(pts) >= 4 and pts[0][0] == pts[-1][0] and w.id not in outer
                    and all(x != UNDEF and y != UNDEF for _, x, y in pts)):
                xs = [x for _, x, _ in pts[:-1]]
                ys = [y for _, _, y in pts[:-1]]
                _emit_ring(w.id, 0, wa[0], wa[1], xs, ys, False, buckets, st)
                _emit_lake(tags.get('name'), wa[0], [(False, xs, ys)], 1, w.id, buckets, st)
        _flush(chunk, junc, buckets, st)
    finally:
        reader.close()
    log(f'  区間 {st["edges"]:,}（マスをまたぐもの {st["multiTileEdges"]:,}、座標がなく落としたもの {st["droppedEdges"]:,}）、'
        f'面の施設 {st["placeWays"]:,}、鉄道の線 {st["railParts"]:,} 本、川の線 {st["riverParts"]:,} 本')
    if water is not None and water.rels:
        _emit_water_relations(pbf, water, lh, buckets, st, log)
    del handlers, store, lh
    log(f'  水面の輪 {st["waterRings"]:,}（マスで切った部分 {st["waterPieces"]:,}）、湖の名前 {st["lakes"]:,}')
    return st


# ---------------------------------------------------------------- 3. 地名を書く

def emit_place_nodes(pbf, buckets, log=_log_default):
    n = 0
    fp = (osmium.FileProcessor(str(pbf), osmium.osm.NODE)
          .with_filter(F.KeyFilter('name'))
          .with_filter(F.KeyFilter(*NODE_KEYS)))
    for node in fp:
        k = place_kind(node.tags, node=True)
        if k is None:
            continue
        loc = node.location
        if not loc.valid():
            continue
        x, y = loc.x, loc.y
        buckets.put(tile_x7(x), tile_y7(y), (R_PLACE, k, node.tags.get('name'), (x + 50) // 100, (y + 50) // 100, 0, node.id))
        n += 1
    log(f'  地名・施設（ノード） {n:,}')
    return {'placeNodes': n}


# ---------------------------------------------------------------- 4. マスのファイルを書く

def tile_relpath(x, y):
    return f'{Z}/{x}/{y}.json.gz'


def write_tiles(buckets, outdir, log=_log_default):
    outdir = Path(outdir)
    entries = []
    for key in buckets.keys():
        groups = {}
        for tx, ty, rec in buckets.read(key):
            g = groups.get((tx, ty))
            if g is None:
                g = groups[(tx, ty)] = ([], [], [], [], [])
            g[rec[0]].append(rec[1:])
        for tx, ty in sorted(groups):
            edges, places, rails, rivers, water = groups[(tx, ty)]
            data = gzip_bytes(encode_tile(tx, ty, Z, edges, places, rails, rivers, water))
            path = outdir / tile_relpath(tx, ty)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entries.append([tx, ty, len(data), hashlib.sha256(data).hexdigest(), len(edges), len(places)])
        del groups
        buckets.remove(key)
    entries.sort()
    log(f'  マス {len(entries):,} 枚、合計 {sum(e[2] for e in entries) / 1e6:,.1f} MB')
    return entries


def manifest_text(m):
    """目録の JSON。マスの行は1行に1枚。"""
    head = {k: v for k, v in m.items() if k != 'tiles'}
    s = json.dumps(head, ensure_ascii=False, indent=2)
    assert s.endswith('\n}')
    rows = ',\n'.join('    ' + json.dumps(t, separators=(',', ':')) for t in m['tiles'])
    return s[:-2] + ',\n  "tiles": [\n' + rows + ('\n' if rows else '') + '  ]\n}\n'


def build(pbf, out_root, *, date=None, bbox=None, node_store='flex_mem', force=False, log=_log_default):
    """道路タイルの版を1つ作り、(版のフォルダ, 目録) を返す。

    bbox: (西経度, 南緯度, 東経度, 北緯度)。指定するとその範囲にかかるマスだけを書く（試し用）。
    """
    t0 = time.time()
    pbf, out_root = Path(pbf), Path(out_root)

    def step(msg):
        log(f'[{time.time() - t0:7.1f}s, 最大 {_peak_mb():,.0f} MB] {msg}')

    step(f'元ファイル {pbf}')
    src = source_info(pbf, date)
    final = out_root / src['date']
    if final.exists() and not force:
        raise FileExistsError(f'{final} はすでにあります（作り直すときは --force）')
    partial = out_root / f'.{src["date"]}.partial'
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    rng = tiles_in_bbox(*bbox) if bbox else None

    step('1/4 道路のノード ID を数える（水面のマルチポリゴンも読む）')
    water = read_water_relations(pbf, log)
    junc, need, st1 = collect_refs(pbf, log, water)
    buckets = Buckets(partial / '.work', rng)
    box = {'need': need}
    del need
    step('2/4 区間を区切ってマスに分ける')
    st2 = emit_ways(pbf, junc, box, buckets, node_store, log, water)
    del junc, water
    step('3/4 地名・施設を拾う')
    st3 = emit_place_nodes(pbf, buckets, log)
    buckets.close()
    step('4/4 マスのファイルを書く')
    tiles = write_tiles(buckets, partial, log)
    shutil.rmtree(partial / '.work')

    m = {
        'format': FORMAT_NAME,
        'formatVersion': FORMAT_VERSION,
        'dataVersion': src['date'],
        'source': {k: src[k] for k in ('file', 'bytes', 'sha256', 'timestamp')},
        'generator': {'name': FORMAT_NAME, 'version': __version__},
        'zoom': Z,
        'coordScale': 100000,
        'bbox': list(bbox) if bbox else None,
        'roadKinds': list(ROAD_KINDS),
        'flags': FLAGS,
        'placeKinds': list(PLACE_KINDS),
        'railKinds': list(RAIL_KINDS),
        'riverKinds': list(RIVER_KINDS),
        'waterKinds': list(WATER_KINDS),
        'attribution': '© OpenStreetMap contributors',
        'license': 'ODbL-1.0',
        'counts': {'tiles': len(tiles), 'bytes': sum(t[2] for t in tiles),
                   'edgeRecords': sum(t[4] for t in tiles), 'places': sum(t[5] for t in tiles),
                   'edges': st2['edges'], 'multiTileEdges': st2['multiTileEdges'],
                   'droppedEdges': st2['droppedEdges'], 'roadWays': st1['roadWays'], 'railParts': st2['railParts'],
                   'riverParts': st2['riverParts'], 'waterRings': st2['waterRings'], 'waterPieces': st2['waterPieces'],
                   'waterRingsBroken': st2['waterBroken'], 'lakes': st2['lakes']},
        'tiles': tiles,
    }
    (partial / 'manifest.json').write_text(manifest_text(m), encoding='utf-8')
    if final.exists():
        shutil.rmtree(final)
    os.replace(partial, final)
    step(f'できあがり {final}')
    return final, m
