"""テスト用の小さな OpenStreetMap ファイルを作る道具と、結果を照らし合わせるための素朴な計算（答え合わせ用）。

ここのデータは手で作った架空のもので、OpenStreetMap のデータではありません。
"""
from collections import Counter

import osmium

from roadtile.tags import road_attrs
from roadtile.tiles import tile_x7, tile_y7

TIMESTAMP = '2026-10-05T21:00:00Z'


def write_pbf(path, nodes, ways, relations=(), timestamp=TIMESTAMP):
    """nodes: {id: (lon7, lat7, tags)}、ways: [(id, [ノード ID], tags)]、relations: [(id, [('w', ID, role)], tags)]。

    座標は 1e7 倍の整数。
    """
    h = osmium.io.Header()
    if timestamp:
        h.set('osmosis_replication_timestamp', timestamp)
    w = osmium.SimpleWriter(str(path), header=h, overwrite=True)
    for nid in sorted(nodes):
        x, y, tags = nodes[nid]
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(x / 1e7, y / 1e7), tags=tags))
    for wid, refs, tags in sorted(ways, key=lambda r: r[0]):
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags))
    for rid, members, tags in sorted(relations, key=lambda r: r[0]):
        w.add_relation(osmium.osm.mutable.Relation(id=rid, members=members, tags=tags))
    w.close()


def r5(v7):
    return (v7 + 50) // 100


def expected_edges(nodes, ways):
    """区切った区間を素朴に計算する。{(way, seg): (way, seg, u, v, kind, flags, name, ref, xs, ys)}"""
    road = []
    for wid, refs, tags in ways:
        a = road_attrs(tags)
        if a is not None and len(refs) >= 2:
            road.append((wid, refs, a))
    cnt = Counter()
    for _, refs, _ in road:
        cnt.update(refs)
        cnt[refs[0]] += 1
        cnt[refs[-1]] += 1
    out = {}
    for wid, refs, (kind, flags, name, ref) in road:
        cuts = [0] + [i for i in range(1, len(refs) - 1) if cnt[refs[i]] >= 2] + [len(refs) - 1]
        for seg, (s, e) in enumerate(zip(cuts, cuts[1:])):
            part = refs[s:e + 1]
            if any(r not in nodes for r in part):
                continue
            if part[0] == part[-1] and len(part) == 2:
                continue
            pts = [(r5(nodes[r][0]), r5(nodes[r][1])) for r in part]
            keep = [pts[0]]
            for p in pts[1:-1]:
                if p != keep[-1]:
                    keep.append(p)
            keep.append(pts[-1])
            out[(wid, seg)] = (wid, seg, part[0], part[-1], kind, flags, name, ref,
                               [p[0] for p in keep], [p[1] for p in keep])
    return out


def expected_tiles_of_edge(nodes, refs):
    """区間が入るはずのマス（各線分の両端のマスの範囲を合わせたもの）。"""
    t = [(tile_x7(nodes[r][0]), tile_y7(nodes[r][1])) for r in refs]
    out = set()
    for (x0, y0), (x1, y1) in zip(t, t[1:]):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                out.add((x, y))
    return out
