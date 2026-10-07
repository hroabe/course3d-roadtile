"""川の線と水面（0.3.0）のテスト。手で作った架空のデータを使う。"""
import math

import pytest

from fixture import r5, write_pbf
from roadtile.build import LAKE_MIN_AREA7, RAIL_PART, build
from roadtile.geom import area2, simplify_line
from roadtile.reader import load_area, load_manifest, read_tile, verify
from roadtile.tags import F_INTERMITTENT, PLACE_CODE, RIVER_CODE, WATER_CODE, river_attrs, water_attrs
from roadtile.tiles import tile_x7, tile_y7

NODES, WAYS, RELS = {}, [], []
_next = [100_000]


def nd(x, y, tags=None):
    _next[0] += 1
    NODES[_next[0]] = (x, y, tags or {})
    return _next[0]


def box(w, s, e, n, ccw=True):
    """長方形の閉じた道のノード ID の並び（最初の点をくり返す）。"""
    ids = [nd(w, s), nd(e, s), nd(e, n), nd(w, n)]
    if not ccw:
        ids = ids[::-1]
    return ids + [ids[0]]


# 川：138.90° から 139.00° へ（マスの境目 138.9551° をまたぐ）。小さなゆれは間引かれ、大きな曲がりは残る
RIVER = [nd(1_389_000_000 + i * 8_400, 352_100_000 + (5_000 if i in (30, 31, 90) else (i % 3) * 40)) for i in range(120)]
WAYS += [
    (1001, RIVER, {'waterway': 'river', 'name': '早川'}),
    (1002, [nd(1_389_600_000, 352_150_000), nd(1_389_610_000, 352_152_000), nd(1_389_620_000, 352_150_000)],
     {'waterway': 'stream', 'intermittent': 'yes'}),
    (1003, [nd(1_389_600_000, 352_160_000), nd(1_389_610_000, 352_160_000)], {'waterway': 'stream', 'tunnel': 'culvert'}),
    (1004, [nd(1_389_600_000, 352_170_000), nd(1_389_610_000, 352_170_000)], {'waterway': 'ditch'}),
    # 小さな池（約1ha、時計回りで描いたもの）→ 向きを直す。名前は地名に入れない
    (1101, box(1_389_700_000, 352_200_000, 1_389_710_000, 352_210_000, ccw=False),
     {'natural': 'water', 'water': 'pond', 'name': 'テスト池'}),
    # 3マスにまたがる細長い湖（約550ha）
    (1102, box(1_389_400_000, 352_000_000, 1_390_500_000, 352_050_000), {'natural': 'water', 'water': 'lake', 'name': 'テスト湖'}),
    (1601, box(1_389_720_000, 352_200_000, 1_389_730_000, 352_210_000), {'natural': 'water', 'water': 'wastewater'}),
    (1701, box(1_389_740_000, 352_200_000, 1_389_750_000, 352_210_000), {'waterway': 'riverbank'}),
]

# マルチポリゴン：外側を3本の開いた道（1本は逆向き）、内側を閉じた道で描いた貯水池。行の境目（35.1738°）をまたぐ
a, b, c, d = nd(1_390_000_000, 351_650_000), nd(1_390_200_000, 351_650_000), nd(1_390_200_000, 351_850_000), nd(1_390_000_000, 351_850_000)
WAYS += [
    (1201, [a, b], {}),                                   # 南の辺 a → b
    (1202, [d, nd(1_390_100_000, 351_850_000), c], {}),   # 北の辺 d → c（つなぐときは逆向きに使う）
    (1203, [c, b], {}),                                   # 東の辺 c → b（逆向き）
    (1205, [d, a], {}),                                   # 西の辺 d → a
    (1204, box(1_390_050_000, 351_760_000, 1_390_100_000, 351_800_000), {}),  # 島
]
RELS.append((2001, [('w', 1201, 'outer'), ('w', 1202, 'outer'), ('w', 1203, 'outer'), ('w', 1205, 'outer'),
                    ('w', 1204, 'inner')],
             {'type': 'multipolygon', 'natural': 'water', 'water': 'reservoir', 'name': 'テスト貯水池'}))
# 部品が足りない（ファイルにない道 99999）
WAYS.append((1301, [nd(1_389_800_000, 352_220_000), nd(1_389_810_000, 352_220_000)], {}))
RELS.append((2002, [('w', 1301, 'outer'), ('w', 99999, 'outer')], {'type': 'multipolygon', 'natural': 'water'}))
# 古い書き方：外側の閉じた道にも natural=water がある → 道だけでは描かない（穴が塗られないように）
WAYS += [
    (1401, box(1_389_100_000, 352_300_000, 1_389_200_000, 352_380_000), {'natural': 'water', 'name': '古い書き方の湖'}),
    (1402, box(1_389_140_000, 352_330_000, 1_389_160_000, 352_350_000), {}),
]
RELS.append((2003, [('w', 1401, 'outer'), ('w', 1402, 'inner')],
             {'type': 'multipolygon', 'natural': 'water', 'name': '古い書き方の湖'}))
# 川の面の穴の中にある池：池は道として描き、川の面の穴にもなる
WAYS += [
    (1501, box(1_389_250_000, 352_330_000, 1_389_260_000, 352_340_000), {'natural': 'water', 'water': 'pond'}),
    (1502, box(1_389_220_000, 352_300_000, 1_389_300_000, 352_380_000), {}),
]
RELS.append((2004, [('w', 1502, 'outer'), ('w', 1501, 'inner')], {'type': 'multipolygon', 'waterway': 'riverbank'}))


def test_tag_rules():
    assert river_attrs({'waterway': 'river'}) == (RIVER_CODE['river'], 0)
    assert river_attrs({'waterway': 'stream', 'intermittent': 'yes'}) == (RIVER_CODE['stream'], F_INTERMITTENT)
    assert river_attrs({'waterway': 'canal', 'tunnel': 'no'}) == (RIVER_CODE['canal'], 0)
    for tags in ({'waterway': 'ditch'}, {'waterway': 'drain'}, {'waterway': 'stream', 'tunnel': 'culvert'},
                 {'waterway': 'river', 'tunnel': 'yes'}, {'waterway': 'riverbank'}, {'waterway': 'dam'}):
        assert river_attrs(tags) is None, tags
    assert water_attrs({'natural': 'water'}) == (WATER_CODE['water'], 0)
    assert water_attrs({'natural': 'water', 'water': 'oxbow'}) == (WATER_CODE['lake'], 0)
    assert water_attrs({'natural': 'water', 'water': 'river'}) == (WATER_CODE['river'], 0)
    assert water_attrs({'natural': 'water', 'water': 'ditch', 'intermittent': 'yes'}) == (WATER_CODE['canal'], F_INTERMITTENT)
    assert water_attrs({'waterway': 'riverbank'}) == (WATER_CODE['river'], 0)
    assert water_attrs({'natural': 'water', 'water': 'wastewater'}) is None
    assert water_attrs({'natural': 'wood'}) is None


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp('w')
    write_pbf(d / 'in.osm.pbf', NODES, WAYS, RELS)
    out, m = build(d / 'in.osm.pbf', d / 'tiles', log=lambda *_: None)
    return d, out, m


def by_src(area):
    out = {}
    for tx, ty, kind, flags, src, xs, ys in area['water']:
        out.setdefault(src, []).append((tx, ty, kind, flags, xs, ys))
    return out


def test_river_lines_are_simplified_and_split(built):
    _, out, m = built
    rv = load_area(out)['rivers']
    assert sorted({k[0] for k in rv}) == [1001, 1002]
    xs7 = [NODES[n][0] for n in RIVER]
    ys7 = [NODES[n][1] for n in RIVER]
    sx, sy = simplify_line(xs7, ys7)
    assert 6 <= len(sx) < 20  # ゆれ（約0.4m）は間引き、曲がり（約55m）は残す
    assert len(sx) <= RAIL_PART and rv[(1001, 0)][4:] == ([r5(x) for x in sx], [r5(y) for y in sy])
    assert m['riverKinds'][rv[(1001, 0)][2]] == 'river'
    assert rv[(1002, 0)][2:4] == (RIVER_CODE['stream'], F_INTERMITTENT)
    where = {(x, y) for x, y, *_ in m['tiles'] for r in read_tile(out, x, y)['rivers'] if r[0] == 1001}
    assert where == {(3628, 1619), (3629, 1619)}  # 138.90°〜139.00°


def test_water_rings(built):
    _, out, m = built
    w = by_src(load_area(out))
    assert set(w) == {1101, 1102, 1501, 1701, -2001, -2003, -2004}   # 1601（下水）・1401（古い書き方の外側）・2002（壊れた）はない
    pond = w[1101]
    assert len(pond) == 1 and area2(pond[0][4], pond[0][5]) > 0     # 時計回りで描いた池を反時計回りに直す
    assert m['waterKinds'][pond[0][2]] == 'pond'
    lake = sorted(w[1102])
    assert [(p[0], p[1]) for p in lake] == [(3628, 1619), (3629, 1619), (3630, 1619)]
    assert all(area2(p[4], p[5]) > 0 for p in lake)
    assert m['waterKinds'][w[1701][0][2]] == 'river'


def test_multipolygon_is_assembled_and_clipped(built):
    _, out, m = built
    w = by_src(load_area(out))
    rel = w[-2001]
    assert {(p[0], p[1]) for p in rel} == {(3629, 1619), (3629, 1620)}  # 行の境目をまたぐ
    assert all(m['waterKinds'][p[2]] == 'reservoir' for p in rel)
    outer = [p for p in rel if area2(p[4], p[5]) > 0]
    inner = [p for p in rel if area2(p[4], p[5]) < 0]
    assert len(outer) == 2 and len(inner) == 1                         # 外側は2つに切れ、内側（島）は時計回り
    total = sum(area2(p[4], p[5]) for p in rel)
    assert total == 2 * (2000 * 2000 - 500 * 400)                       # 1e5 の座標で、外側 − 内側
    old = w[-2003]
    assert sorted(area2(p[4], p[5]) > 0 for p in old) == [False, True]  # 古い書き方も、穴が抜ける
    river = w[-2004]
    assert sorted(area2(p[4], p[5]) > 0 for p in river) == [False, True]
    assert area2(w[1501][0][4], w[1501][0][5]) > 0                      # 穴の中の池は池として塗る


def test_lakes_become_places(built):
    _, out, m = built
    lakes = sorted((p[1], p[2], p[3]) for p in load_area(out)['places'] if p[0] == PLACE_CODE['lake'])
    assert [n for n, *_ in lakes] == ['テスト湖', 'テスト貯水池', '古い書き方の湖']  # テスト池は小さいので入れない
    x, y = next((x, y) for n, x, y in lakes if n == 'テスト湖')
    assert (x, y) == (r5(1_389_950_000), r5(352_025_000))
    assert m['placeKinds'][-1] == 'lake'


def test_counts_and_verify(built):
    _, out, m = built
    c = m['counts']
    assert c['waterRingsBroken'] == 1
    assert c['lakes'] == 3
    assert c['riverParts'] == len(load_area(out)['rivers'])
    assert c['waterPieces'] == len(load_area(out)['water'])
    assert load_manifest(out)['waterKinds'][0] == 'lake'
    assert verify(out, deep=True) == []


def test_same_bytes_and_bbox(built, tmp_path):
    d, out, m = built
    out2, m2 = build(d / 'in.osm.pbf', tmp_path / 'again', log=lambda *_: None)
    assert [t[3] for t in m2['tiles']] == [t[3] for t in m['tiles']]
    _, mb = build(d / 'in.osm.pbf', tmp_path / 'b', bbox=(139.05, 35.18, 139.06, 35.24), log=lambda *_: None)
    assert [(t[0], t[1]) for t in mb['tiles']] == [(3630, 1619)]
    t = read_tile(tmp_path / 'b' / '2026-10-05', 3630, 1619)
    assert [w[2] for w in t['water']] == [1102]


def test_lake_centroid_tile():
    assert (tile_x7(1_389_950_000), tile_y7(352_025_000)) == (3629, 1619)
    assert math.isclose(LAKE_MIN_AREA7 * (111_320e-7 * math.cos(math.radians(35))) * 110_574e-7, 1e5, rel_tol=0.01)
