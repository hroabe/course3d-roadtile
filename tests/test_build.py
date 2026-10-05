import random
import shutil

import pytest

from fixture import expected_edges, expected_tiles_of_edge, r5, write_pbf
from roadtile.build import build, tile_relpath
from roadtile.reader import load_area, load_manifest, read_tile, verify
from roadtile.tags import F_BRIDGE, F_MOTOR_ONLY, F_ONEWAY, PLACE_CODE

LAT = 352_100_000  # 35.21°（マス y=1619）

NODES = {
    1: (1_389_500_000, LAT, {}), 2: (1_389_540_000, LAT, {}),
    3: (1_389_560_000, LAT, {'highway': 'traffic_signals', 'name': '東通り交差点'}),  # 経度 138.9550781 がマスの境目
    4: (1_389_600_000, LAT, {'highway': 'traffic_signals'}), 5: (1_389_650_000, LAT, {}),
    6: (1_389_560_000, 352_150_000, {}), 7: (1_389_560_000, 352_050_000, {}),
    8: (1_389_700_000, 352_200_000, {}), 9: (1_389_650_000, 352_150_000, {}),
    20: (1_389_520_000, 352_000_000, {}), 21: (1_389_530_000, 352_000_000, {}), 22: (1_389_525_000, 352_010_000, {}),
    23: (1_389_680_000, LAT, {}),
    30: (1_388_000_000, 352_110_000, {}), 31: (1_391_000_000, 352_110_000, {}),  # 4マスを1本の線分で横切る
    40: (1_389_700_000, 352_000_000, {}), 41: (1_389_700_000, 352_000_000, {}), 42: (1_389_710_000, 352_000_000, {}),
    50: (1_389_720_000, 352_050_000, {}), 51: (1_389_730_000, 352_050_000, {}), 52: (1_389_750_000, 352_050_000, {}),
    53: (1_389_730_000, 352_060_000, {}),
    55: (1_389_400_000, 352_000_000, {}), 56: (1_389_410_000, 352_000_000, {}), 57: (1_389_405_000, 352_010_000, {}),
    60: (1_389_580_000, 352_120_000, {'place': 'village', 'name': 'テスト村'}),
    63: (1_389_450_000, 352_130_000, {'railway': 'station', 'name': 'テスト駅'}),
    71: (1_389_610_000, 352_030_000, {}), 72: (1_389_620_000, 352_030_000, {}),
    73: (1_389_620_000, 352_040_000, {}), 74: (1_389_610_000, 352_040_000, {}),
}
WAYS = [
    (10, [1, 2, 3, 4, 5], {'highway': 'residential', 'name': '東通り'}),
    (11, [6, 3, 7], {'highway': 'tertiary', 'ref': '75', 'bridge': 'yes'}),
    (12, [8, 9], {'highway': 'motorway', 'name': 'テスト道路'}),
    (13, [9, 4], {'highway': 'motorway_link'}),
    (14, [20, 21, 22, 20], {'highway': 'path'}),
    (15, [5, 23], {'highway': 'construction'}),
    (16, [30, 31], {'highway': 'track'}),
    (17, [40, 41, 42], {'highway': 'service'}),
    (18, [50, 51, 999, 52], {'highway': 'unclassified'}),  # 999 はファイルにないノード
    (19, [51, 53], {'highway': 'footway'}),
    (20, [55, 56, 57, 55], {'highway': 'footway', 'area': 'yes'}),
    (70, [71, 72, 73, 74, 71], {'amenity': 'school', 'name': '第一小学校'}),
    (80, [71, 73], {'amenity': 'school', 'name': '閉じていない'}),
]


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp('b')
    write_pbf(d / 'in.osm.pbf', NODES, WAYS)
    out, m = build(d / 'in.osm.pbf', d / 'tiles', log=lambda *_: None)
    return d, out, m


def test_version_and_manifest(built):
    d, out, m = built
    assert out.name == '2026-10-05'
    assert m['dataVersion'] == '2026-10-05' and m['source']['timestamp'] == '2026-10-05T21:00:00Z'
    assert {(t[0], t[1]) for t in m['tiles']} == {(3627, 1619), (3628, 1619), (3629, 1619), (3630, 1619)}
    assert load_manifest(out) == m
    assert verify(out, deep=True) == []


def test_edges_match_reference(built):
    _, out, _ = built
    area = load_area(out)
    assert area['edges'] == expected_edges(NODES, WAYS)


def test_junctions_and_flags(built):
    _, out, _ = built
    e = load_area(out)['edges']
    assert sorted(k for k in e if k[0] == 10) == [(10, 0), (10, 1), (10, 2)]  # 3 と 4 で区切れる
    assert (e[(10, 0)][2], e[(10, 0)][3]) == (1, 3)
    assert e[(11, 0)][5] == F_BRIDGE and e[(11, 0)][7] == '75'
    assert e[(12, 0)][5] == F_ONEWAY | F_MOTOR_ONLY
    assert e[(13, 0)][5] == F_MOTOR_ONLY
    assert (e[(14, 0)][2], e[(14, 0)][3]) == (20, 20)  # 輪になった道
    assert e[(17, 0)][8] == [r5(1_389_700_000), r5(1_389_710_000)]  # 同じ座標の途中の点は落ちる
    assert (18, 0) in e and (18, 1) not in e  # 座標のないノードを含む区間は落とす
    assert not any(k[0] in (15, 20, 70, 80) for k in e)  # 工事中・面の歩道・施設は道路に入らない


def test_edge_is_copied_into_every_tile_it_crosses(built):
    _, out, m = built
    where = {}
    for x, y, *_ in m['tiles']:
        for ed in read_tile(out, x, y)['edges']:
            where.setdefault((ed[0], ed[1]), set()).add((x, y))
    assert where[(10, 0)] == {(3628, 1619), (3629, 1619)}
    assert where[(16, 0)] == {(3627, 1619), (3628, 1619), (3629, 1619), (3630, 1619)}
    for key, tiles in where.items():
        way = next(w for w in WAYS if w[0] == key[0])
        ed = load_area(out)['edges'][key]
        refs = way[1][way[1].index(ed[2]):] if key != (14, 0) else way[1]
        refs = refs[:refs.index(ed[3], 1) + 1] if key != (14, 0) else refs
        assert tiles == expected_tiles_of_edge(NODES, refs), key


def test_places(built):
    _, out, _ = built
    p = sorted(load_area(out)['places'])
    assert (PLACE_CODE['village'], 'テスト村', r5(1_389_580_000), r5(352_120_000)) in p
    assert (PLACE_CODE['station'], 'テスト駅', r5(1_389_450_000), r5(352_130_000)) in p
    assert (PLACE_CODE['junction'], '東通り交差点', r5(1_389_560_000), r5(LAT)) in p
    assert (PLACE_CODE['school'], '第一小学校', r5(1_389_615_000), r5(352_035_000)) in p  # 面の中心
    assert len(p) == 4  # 名前のない信号・閉じていない道は入らない


def test_same_input_gives_same_bytes(built, tmp_path):
    d, out, m = built
    out2, m2 = build(d / 'in.osm.pbf', tmp_path / 'tiles', log=lambda *_: None)
    assert m2 == m
    assert (out2 / 'manifest.json').read_bytes() == (out / 'manifest.json').read_bytes()
    for x, y, *_ in m['tiles']:
        assert (out2 / tile_relpath(x, y)).read_bytes() == (out / tile_relpath(x, y)).read_bytes()


def test_existing_version_needs_force(built, tmp_path):
    d, _, _ = built
    build(d / 'in.osm.pbf', tmp_path, log=lambda *_: None)
    with pytest.raises(FileExistsError):
        build(d / 'in.osm.pbf', tmp_path, log=lambda *_: None)
    build(d / 'in.osm.pbf', tmp_path, force=True, log=lambda *_: None)


def test_verify_finds_problems(built, tmp_path):
    _, out, m = built
    v = tmp_path / 'v'
    shutil.copytree(out, v)
    x, y = m['tiles'][0][:2]
    p = v / tile_relpath(x, y)
    p.write_bytes(p.read_bytes() + b'x')
    x2, y2 = m['tiles'][1][:2]
    (v / tile_relpath(x2, y2)).unlink()
    (v / '12' / '1' ).mkdir()
    (v / '12' / '1' / '1.json.gz').write_bytes(b'')
    problems = '\n'.join(verify(v))
    assert f'{tile_relpath(x, y)}: ハッシュが違う' in problems
    assert f'{tile_relpath(x2, y2)}: ファイルがない' in problems
    assert '12/1/1.json.gz: 目録にないファイル' in problems


def test_bbox_limits_tiles(built, tmp_path):
    d, _, _ = built
    _, m = build(d / 'in.osm.pbf', tmp_path, bbox=(138.96, 35.18, 139.0, 35.24), log=lambda *_: None)
    assert [(t[0], t[1]) for t in m['tiles']] == [(3629, 1619)]


def test_date_is_required_without_timestamp(tmp_path):
    write_pbf(tmp_path / 'a.osm.pbf', {1: (1_389_500_000, LAT, {}), 2: (1_389_510_000, LAT, {})},
              [(1, [1, 2], {'highway': 'path'})], timestamp=None)
    with pytest.raises(ValueError):
        build(tmp_path / 'a.osm.pbf', tmp_path / 't', log=lambda *_: None)
    out, _ = build(tmp_path / 'a.osm.pbf', tmp_path / 't', date='2026-10-01', log=lambda *_: None)
    assert out.name == '2026-10-01'


def random_network(seed, n=24):
    """格子の上を歩く道をたくさん作る。マスの境目（縦・横）をまたぐ。"""
    rnd = random.Random(seed)
    x0, y0, step = 1_388_900_000, 352_200_000, 4_000_000 // n * 10  # 約0.1°四方の外まで
    nodes, nid = {}, {}
    for i in range(n):
        for j in range(n):
            k = 1000 + i * n + j
            nid[(i, j)] = k
            nodes[k] = (x0 + i * step + rnd.randrange(-500, 500), y0 + j * step + rnd.randrange(-500, 500), {})
    kinds = ['residential', 'tertiary', 'path', 'footway', 'motorway', 'service', 'construction', 'steps']
    ways, wid = [], 1
    for _ in range(n * 3):
        i, j = rnd.randrange(n), rnd.randrange(n)
        refs = [nid[(i, j)]]
        for _ in range(rnd.randrange(1, 14)):
            di, dj = rnd.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
            i, j = min(max(i + di, 0), n - 1), min(max(j + dj, 0), n - 1)
            refs.append(nid[(i, j)])
        tags = {'highway': rnd.choice(kinds)}
        if rnd.random() < 0.3:
            tags['name'] = f'道{wid % 7}'
        if rnd.random() < 0.2:
            tags['bridge'] = 'yes'
        ways.append((wid, refs, tags))
        wid += 1
    return nodes, ways


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_random_network_stitches_back(tmp_path, seed):
    nodes, ways = random_network(seed)
    write_pbf(tmp_path / 'r.osm.pbf', nodes, ways)
    out, m = build(tmp_path / 'r.osm.pbf', tmp_path / 't', log=lambda *_: None)
    assert len(m['tiles']) >= 4
    assert load_area(out)['edges'] == expected_edges(nodes, ways)
    assert verify(out, deep=True) == []


def test_small_chunks_and_batches_give_same_result(tmp_path, monkeypatch):
    import roadtile.build as B
    nodes, ways = random_network(4)
    write_pbf(tmp_path / 'r.osm.pbf', nodes, ways)
    _, m1 = build(tmp_path / 'r.osm.pbf', tmp_path / 'a', log=lambda *_: None)
    monkeypatch.setattr(B, 'CHUNK_VERTS', 7)
    monkeypatch.setattr(B, 'BATCH', 3)
    out2, m2 = build(tmp_path / 'r.osm.pbf', tmp_path / 'b', log=lambda *_: None)
    assert m2 == m1
    assert load_area(out2)['edges'] == expected_edges(nodes, ways)
