"""取得（fetch）のテスト。途中で接続を切る、元のファイルが途中で変わる、などをまねる小さなサーバーを使う。"""
import hashlib
import http.server
import random
import re
import threading
import urllib.error

import pytest

from roadtile.fetch import fetch


class Site:
    def __init__(self, body):
        self.body = body
        self.etag = '"v1"'
        self.md5 = None          # None なら body の MD5 を返す
        self.drops = []          # 本体のリクエストごとに、何バイト送って切るか（None は切らない）
        self.after = []          # 本体のリクエストのあとに呼ぶ関数
        self.requests = []       # (Range, If-Range)


def make_handler(site):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body, headers=()):
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.path.startswith('/a.osm.pbf'):
                return self._send(404, b'not found')
            if self.path.endswith('.md5'):
                md5 = site.md5 or hashlib.md5(site.body).hexdigest()
                return self._send(200, f'{md5}  a.osm.pbf\n'.encode())
            rng, if_range = self.headers.get('Range'), self.headers.get('If-Range')
            site.requests.append((rng, if_range))
            body, start, status, extra = site.body, 0, 200, [('ETag', site.etag)]
            if rng and (if_range is None or if_range == site.etag):
                start = int(re.match(r'bytes=(\d+)-', rng).group(1))
                if start >= len(body):
                    return self._send(416, b'', [('Content-Range', f'bytes */{len(body)}')])
                status = 206
                extra.append(('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}'))
            chunk = body[start:]
            self.send_response(status)
            self.send_header('Content-Length', str(len(chunk)))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            cut = site.drops.pop(0) if site.drops else None
            self.wfile.write(chunk if cut is None else chunk[:cut])
            self.wfile.flush()
            if site.after:
                site.after.pop(0)()
            self.close_connection = True

    return Handler


@pytest.fixture()
def site():
    body = random.Random(1).randbytes(300_000)
    s = Site(body)
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_handler(s))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    s.url = f'http://127.0.0.1:{httpd.server_port}/a.osm.pbf'
    yield s
    httpd.shutdown()


def run(site, dest, **kw):
    logs, waits = [], []
    out = fetch(dest, site.url, log=logs.append, sleep=waits.append, **kw)
    return out, logs, waits


def test_downloads_and_skips_when_latest(site, tmp_path):
    out, _, waits = run(site, tmp_path)
    assert out.read_bytes() == site.body and waits == []
    assert not (tmp_path / 'a.osm.pbf.part').exists() and not (tmp_path / 'a.osm.pbf.part.json').exists()
    n = len(site.requests)
    _, logs, _ = run(site, tmp_path)
    assert len(site.requests) == n and '最新' in logs[-1]


def test_resumes_after_connection_drops(site, tmp_path):
    site.drops = [50_000, 20_000, 100_000]
    out, logs, waits = run(site, tmp_path)
    assert out.read_bytes() == site.body
    assert len(waits) == 3
    assert site.requests == [(None, None), ('bytes=50000-', '"v1"'), ('bytes=70000-', '"v1"'), ('bytes=170000-', '"v1"')]


def test_restarts_when_source_changes_midway(site, tmp_path):
    new = random.Random(2).randbytes(250_000)

    def update():
        site.body, site.etag = new, '"v2"'

    site.drops = [50_000]
    site.after = [update]
    out, logs, _ = run(site, tmp_path)
    assert out.read_bytes() == new  # 古い版と混ざらない
    assert site.requests[1] == ('bytes=50000-', '"v1"')
    assert any('最初から取り直します' in m for m in logs)


def test_old_partial_file_without_info_is_checked_by_md5(site, tmp_path):
    (tmp_path / 'a.osm.pbf.part').write_bytes(b'x' * 1000)  # 前の版の取りかけ（情報ファイルなし）
    out, logs, _ = run(site, tmp_path)
    assert out.read_bytes() == site.body
    assert any('MD5 が合わない' in m for m in logs)


def test_wrong_md5_raises(site, tmp_path):
    site.md5 = '0' * 32
    with pytest.raises(ValueError):
        run(site, tmp_path)
    assert not (tmp_path / 'a.osm.pbf').exists() and not (tmp_path / 'a.osm.pbf.part').exists()


def test_gives_up_after_retries_but_keeps_partial_file(site, tmp_path):
    site.drops = [10_000] * 10
    with pytest.raises(Exception):
        run(site, tmp_path, retries=3)
    assert (tmp_path / 'a.osm.pbf.part').stat().st_size == 40_000  # 次に実行すれば続きから
    site.drops = []
    out, _, _ = run(site, tmp_path)
    assert out.read_bytes() == site.body


def test_not_found_fails_without_waiting(site, tmp_path):
    waits = []
    with pytest.raises(urllib.error.HTTPError):
        fetch(tmp_path, site.url.replace('a.osm.pbf', 'b.osm.pbf'), log=lambda *_: None, sleep=waits.append)
    assert waits == []
