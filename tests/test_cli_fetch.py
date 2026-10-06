import hashlib
import http.server
import threading
from functools import partial

import pytest

from fixture import write_pbf
from roadtile.cli import main
from roadtile.fetch import fetch


@pytest.fixture()
def server(tmp_path):
    root = tmp_path / 'www'
    root.mkdir()
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield root, f'http://127.0.0.1:{httpd.server_port}'
    httpd.shutdown()


def test_fetch_checks_md5(server, tmp_path):
    root, base = server
    body = b'pbf' * 100_000
    (root / 'a.osm.pbf').write_bytes(body)
    (root / 'a.osm.pbf.md5').write_text(hashlib.md5(body).hexdigest() + '  a.osm.pbf\n')
    out = fetch(tmp_path / 'data', base + '/a.osm.pbf', log=lambda *_: None)
    assert out.read_bytes() == body
    assert fetch(tmp_path / 'data', base + '/a.osm.pbf', log=lambda *_: None) == out  # 2回目は取り直さない
    (root / 'a.osm.pbf.md5').write_text('0' * 32 + '  a.osm.pbf\n')
    with pytest.raises(ValueError):
        fetch(tmp_path / 'data2', base + '/a.osm.pbf', log=lambda *_: None)
    assert not (tmp_path / 'data2' / 'a.osm.pbf').exists()


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
