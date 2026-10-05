import gzip
import json

from roadtile.encode import decode_tile, encode_tile, gzip_bytes

E1 = (500, 0, 7, 9, 10, 1, '東通り', '', [13900000, 13900010, 13900010, 13900030], [3520000, 3520005, 3520005, 3520000])
E2 = (120, 2, 9, 3, 8, 0, '', '75', [13900030, 13900030, 13900050], [3520000, 3520020, 3520040])
P1 = (8, '箱根湯本', 13900100, 3520100, 0, 55)
P2 = (1, '箱根町', 13900000, 3520200, 0, 54)


def test_roundtrip():
    t = decode_tile(gzip_bytes(encode_tile(3629, 1619, 12, [E1, E2], [P1, P2])))
    assert (t['x'], t['y'], t['z']) == (3629, 1619, 12)
    by = {(e[0], e[1]): e for e in t['edges']}
    # 前の点と同じ途中の点は落ちる
    assert by[(500, 0)] == (500, 0, 7, 9, 10, 1, '東通り', '', [13900000, 13900010, 13900030], [3520000, 3520005, 3520000])
    assert by[(120, 2)] == E2
    assert t['nodes'] == {3: (13900050, 3520040), 7: (13900000, 3520000), 9: (13900030, 3520000)}
    assert t['places'] == [(1, '箱根町', 13900000, 3520200), (8, '箱根湯本', 13900100, 3520100)]


def test_layout_and_determinism():
    a = encode_tile(1, 2, 12, [E1, E2], [P1, P2])
    b = encode_tile(1, 2, 12, [E2, E1], [P2, P1])
    assert a == b
    assert gzip_bytes(a) == gzip_bytes(b)
    j = json.loads(a)
    assert j['names'][0] == ''
    assert j['nodes'] == [3, 4, 2]                # ID の差分
    assert [r[6] for r in j['edges']] == [120, 380]  # 道の ID の差分（小さい順に並ぶ）
    assert gzip.decompress(gzip_bytes(a)) == a


def test_empty_tile():
    t = decode_tile(encode_tile(0, 0, 12, [], [P1]))
    assert t['edges'] == [] and t['nodes'] == {} and len(t['places']) == 1
