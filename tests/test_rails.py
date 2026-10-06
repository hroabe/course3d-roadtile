"""鉄道の線（地図に描くだけ）のテスト。手で作った架空のデータを使う。"""
import pytest

from fixture import expected_edges, expected_tiles_of_edge, r5, write_pbf
from roadtile.build import RAIL_PART, build
from roadtile.reader import load_area, load_manifest, read_tile, verify
from roadtile.tags import F_BRIDGE, F_TUNNEL, RAIL_CODE, rail_attrs

LAT = 352_050_000

RAIL_NODES = {}
for i in range(70):  # 138.90° から東へ約0.0014° おき。マスの境目（138.9551°）をまたぐ
    RAIL_NODES[9001 + i] = (1_389_000_000 + i * 14_500, LAT, {})
RAIL_NODES.update({
    9101: (1_389_600_000, 352_150_000, {}), 9102: (1_389_620_000, 352_150_000, {}),
    9201: (1_389_700_000, 352_150_000, {}), 9202: (1_389_710_000, 352_150_000, {}),
    9203: (1_389_730_000, 352_150_000, {}), 9204: (1_389_740_000, 352_150_000, {}),
    9301: (1_389_800_000, 352_150_000, {}), 9302: (1_389_810_000, 352_160_000, {}), 9303: (1_389_820_000, 352_170_000, {}),
    9401: (1_389_850_000, 352_100_000, {}), 9402: (1_389_870_000, 352_100_000, {}),
    9501: (1_389_600_000, 352_180_000, {}), 9502: (1_389_610_000, 352_180_000, {}), 9503: (1_389_620_000, 352_180_000, {}),
    9601: (1_389_610_000, 352_170_000, {}), 9602: (1_389_610_000, 352_190_000, {}),
})
RAIL_WAYS = [
    (900, list(range(9001, 9071)), {'railway': 'rail', 'name': 'テスト線'}),
    (901, [9101, 9102], {'railway': 'rail', 'bridge': 'yes'}),
    (902, [9101, 9102], {'railway': 'rail', 'service': 'yard'}),
    (903, [9101, 9102], {'railway': 'abandoned'}),
    (904, [9301, 9302, 9303], {'aerialway': 'gondola'}),
    (905, [9201, 9202, 99999, 9203, 9204], {'railway': 'rail'}),  # 99999 はファイルにない
    (906, [9401, 9402], {'railway': 'subway', 'tunnel': 'yes'}),
    (950, [9501, 9502, 9503], {'highway': 'residential'}),          # 踏切：9502 を鉄道と共有
    (907, [9601, 9502, 9602], {'railway': 'rail'}),
]


def expected_rails(nodes, ways):
    out = {}
    for wid, refs, tags in ways:
        a = rail_attrs(tags)
        if a is None:
            continue
        runs, cur = [], []
        for r in refs:
            if r in nodes:
                cur.append(r)
            else:
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
        if len(cur) >= 2:
            runs.append(cur)
        part = 0
        for run in runs:
            for s in range(0, len(run) - 1, RAIL_PART - 1):
                seg = run[s:s + RAIL_PART]
                pts = [(r5(nodes[r][0]), r5(nodes[r][1])) for r in seg]
                keep = [pts[0]]
                for i, p in enumerate(pts[1:], 1):
                    if p != keep[-1] or i == len(pts) - 1:
                        keep.append(p)
                out[(wid, part)] = ((wid, part, a[0], a[1], [p[0] for p in keep], [p[1] for p in keep]), seg)
                part += 1
    return out


def test_rail_attrs():
    assert rail_attrs({'railway': 'rail'}) == (RAIL_CODE['rail'], 0)
    assert rail_attrs({'railway': 'narrow_gauge', 'bridge': 'viaduct'}) == (RAIL_CODE['narrow_gauge'], F_BRIDGE)
    assert rail_attrs({'railway': 'subway', 'tunnel': 'yes'}) == (RAIL_CODE['subway'], F_TUNNEL)
    assert rail_attrs({'aerialway': 'cable_car'}) == (RAIL_CODE['aerialway'], 0)
    for tags in ({'railway': 'abandoned'}, {'railway': 'rail', 'service': 'siding'}, {'railway': 'platform'},
                 {'railway': 'aerialway'}, {'aerialway': 'chair_lift'}, {'railway': 'rail', 'area': 'yes'}):
        assert rail_attrs(tags) is None, tags


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp('r')
    write_pbf(d / 'in.osm.pbf', RAIL_NODES, RAIL_WAYS)
    out, m = build(d / 'in.osm.pbf', d / 'tiles', log=lambda *_: None)
    return out, m


def test_rails_match_reference(built):
    out, m = built
    got = load_area(out)['rails']
    exp = expected_rails(RAIL_NODES, RAIL_WAYS)
    assert got == {k: v[0] for k, v in exp.items()}
    assert sorted(k for k in got if k[0] == 900) == [(900, 0), (900, 1)]   # 70頂点 → 64 と 7（境目の点は重ねる）
    assert sorted(k for k in got if k[0] == 905) == [(905, 0), (905, 1)]   # 座標のない点で切る
    assert not any(k[0] in (902, 903) for k in got)                        # 操車場・廃線は入れない
    assert m['railKinds'][got[(904, 0)][2]] == 'aerialway'
    assert m['counts']['railParts'] == len(got)


def test_rail_parts_go_into_every_tile_they_cross(built):
    out, m = built
    where = {}
    for x, y, *_ in m['tiles']:
        for r in read_tile(out, x, y)['rails']:
            where.setdefault((r[0], r[1]), set()).add((x, y))
    for key, (_, refs) in expected_rails(RAIL_NODES, RAIL_WAYS).items():
        assert where[key] == expected_tiles_of_edge(RAIL_NODES, refs), key
    assert len(where[(900, 0)]) == 2


def test_rails_do_not_split_roads(built):
    out, _ = built
    e = load_area(out)['edges']
    assert e == expected_edges(RAIL_NODES, RAIL_WAYS)
    assert [k for k in e if k[0] == 950] == [(950, 0)]  # 踏切で道路は区切らない


def test_manifest_and_verify(built):
    out, m = built
    assert load_manifest(out)['railKinds'][0] == 'rail'
    assert verify(out, deep=True) == []
