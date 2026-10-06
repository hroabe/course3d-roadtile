from fixture import write_pbf
from roadtile.cli import main


def test_cli_build_verify_info_tile(tmp_path, capsys):
    write_pbf(tmp_path / 'in.osm.pbf',
              {1: (1_389_500_000, 352_100_000, {}), 2: (1_389_600_000, 352_100_000, {})},
              [(1, [1, 2], {'highway': 'residential', 'name': '東通り'})])
    assert main(['build', str(tmp_path / 'in.osm.pbf'), '--out', str(tmp_path / 't')]) == 0
    capsys.readouterr()
    assert main(['verify', str(tmp_path / 't' / '2026-10-05'), '--deep']) == 0
    assert '問題なし' in capsys.readouterr().out
    assert main(['info', str(tmp_path / 't' / '2026-10-05')]) == 0
    assert 'マス 2 枚' in capsys.readouterr().out
    assert main(['tile', '139.0', '35.2']) == 0
    assert capsys.readouterr().out.startswith('3629/1619')


def test_peak_memory_is_reported():
    from roadtile.build import _peak_mb
    assert _peak_mb() > 10  # Windows・Mac・Linux のどれでも MB で取れる
