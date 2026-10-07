"""地名の索引（places.json.gz、0.4.0）のテスト。手で作った架空のデータを使う。"""
import shutil

import pytest

from fixture import write_pbf
from roadtile.build import build
from roadtile.cli import main
from roadtile.placeindex import INDEX_FILE, index_entries, read_index
from roadtile.reader import load_manifest, verify
from roadtile.tags import PLACE_CODE, PLACE_KINDS

LAT = 352_100_000
NODES = {
    1: (1_389_500_000, LAT, {}), 2: (1_389_540_000, LAT, {}),
    3: (1_389_520_000, LAT, {'highway': 'traffic_signals', 'name': '東通り交差点'}),
    10: (1_389_600_000, 352_150_000, {'railway': 'station', 'name': 'テスト'}),
    11: (1_389_605_000, 352_152_000, {'railway': 'halt', 'name': 'テスト'}),           # 約500m 先の同じ名前の駅 → 1つにまとめる
    12: (1_389_900_000, 352_150_000, {'railway': 'station', 'name': 'テスト'}),        # 約3km 先 → 別に残す
    13: (1_389_610_000, 352_160_000, {'place': 'town', 'name': 'テスト町'}),
    14: (1_389_620_000, 352_170_000, {'natural': 'peak', 'name': 'テスト山'}),
    15: (1_389_700_000, 352_000_000, {'place': 'village', 'name': 'テスト'}),          # 駅と同じ名前でも種類が違えば残す
}
WAYS = [(100, [1, 3, 2], {'highway': 'residential'})]


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp('p')
    write_pbf(d / 'in.osm.pbf', NODES, WAYS)
    out, m = build(d / 'in.osm.pbf', d / 'tiles', log=lambda *_: None)
    return d, out, m


def test_index_is_written_and_listed(built):
    _, out, m = built
    pi = m['placeIndex']
    assert pi['file'] == INDEX_FILE and (out / INDEX_FILE).stat().st_size == pi['bytes']
    idx = read_index(out)
    assert idx['kinds'] == list(PLACE_KINDS)
    names = [(PLACE_KINDS[k], n) for k, n, _, _ in idx['places']]
    # 名前の順（同じ名前は種類の番号の順）。テスト山（U+5C71）はテスト町（U+753A）より前
    assert names == [('village', 'テスト'), ('station', 'テスト'), ('station', 'テスト'), ('peak', 'テスト山'), ('town', 'テスト町')]
    assert pi['count'] == 5
    assert not any(n == '東通り交差点' for _, n in names)  # 交差点名は入れない
    assert verify(out, deep=True) == []


def test_dedupe_by_kind_name_and_cell():
    st = PLACE_CODE['station']
    rows = index_entries([(st, 'A', 13896000, 3521000), (st, 'A', 13896050, 3521020), (st, 'A', 13899000, 3521000),
                          (st, '', 1, 1), (PLACE_CODE['junction'], 'J', 1, 1)], PLACE_KINDS)
    assert rows == [(st, 'A', 13896000, 3521000), (st, 'A', 13899000, 3521000)]


def test_index_command_matches_build(built, tmp_path):
    _, out, m = built
    old = tmp_path / 'old'
    shutil.copytree(out, old)
    (old / INDEX_FILE).unlink()
    mm = load_manifest(old)
    del mm['placeIndex']
    from roadtile.build import manifest_text
    (old / 'manifest.json').write_text(manifest_text(mm), encoding='utf-8')
    assert main(['index', str(old)]) == 0
    assert (old / INDEX_FILE).read_bytes() == (out / INDEX_FILE).read_bytes()
    assert (old / 'manifest.json').read_text(encoding='utf-8') == (out / 'manifest.json').read_text(encoding='utf-8')


def test_verify_finds_broken_index(built, tmp_path):
    _, out, _ = built
    bad = tmp_path / 'bad'
    shutil.copytree(out, bad)
    (bad / INDEX_FILE).write_bytes(b'broken')
    assert any(INDEX_FILE in p for p in verify(bad))
    (bad / INDEX_FILE).unlink()
    assert any('ファイルがない' in p for p in verify(bad))
