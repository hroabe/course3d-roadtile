"""Geofabrik から日本全体のファイルを取得し、MD5 で確かめる。

途中で接続が切れても、取れたところから続きを取り直す（HTTP の Range）。取得中に元のファイルが
更新されたときは、ETag で気づいて最初から取り直す。
"""
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

GEOFABRIK_JAPAN = 'https://download.geofabrik.de/asia/japan-latest.osm.pbf'
RETRIES = 30


class Incomplete(OSError):
    """受け取った大きさが足りない（接続が途中で切れた）。"""


def _log_default(m):
    print(m, file=sys.stderr, flush=True)


def _open(url, headers=None, timeout=60):
    h = {'User-Agent': f'course3d-roadtile/{__version__}'}
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)


def _get_md5(url):
    with _open(url + '.md5') as r:
        return r.read().decode('ascii').split()[0].lower()


def _md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _download(url, part, meta_path, log):
    """part に続きを書き足す。終わりまで取れたら戻る。切れたら OSError などを投げる。"""
    have = part.stat().st_size if part.exists() else 0
    meta = {}
    if have and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    headers = {}
    if have:
        headers['Range'] = f'bytes={have}-'
        validator = meta.get('etag') or meta.get('lastModified')
        if validator:
            headers['If-Range'] = validator  # 元のファイルが変わっていたら、全体が返ってくる
    try:
        r = _open(url, headers)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have and meta.get('total') == have:
            return  # もう全部ある
        if e.code == 416:
            part.unlink()  # 範囲が合わない（元が小さくなったなど）。最初から
            meta_path.unlink(missing_ok=True)
        raise
    with r:
        if have and r.status == 206:
            m = re.search(r'/(\d+)$', r.headers.get('Content-Range', ''))
            total = int(m.group(1)) if m else have + int(r.headers.get('Content-Length') or 0)
            mode = 'ab'
            log(f'  {have / 1e6:,.0f} MB から続きを取ります')
        else:
            if have:
                log('  元のファイルが変わったか、続きから取れないため、最初から取り直します')
            have = 0
            total = int(r.headers.get('Content-Length') or 0)
            mode = 'wb'
        if mode == 'wb' or not meta:
            meta = {'etag': r.headers.get('ETag'), 'lastModified': r.headers.get('Last-Modified'), 'total': total}
            meta_path.write_text(json.dumps(meta), encoding='utf-8')
        done = have
        step = done * 20 // total if total else 0
        with open(part, mode) as f:
            for block in iter(lambda: r.read(1 << 20), b''):
                f.write(block)
                done += len(block)
                if total and done * 20 // total > step:
                    step = done * 20 // total
                    log(f'  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB')
    if total and part.stat().st_size != total:
        raise Incomplete(f'{part.stat().st_size} / {total} bytes')


def fetch(dest_dir, url=GEOFABRIK_JAPAN, log=_log_default, retries=RETRIES, sleep=time.sleep):
    """url のファイルを dest_dir に保存して、その場所を返す。MD5 が合わなければ ValueError。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = url.rsplit('/', 1)[-1]
    final = dest_dir / name
    part = dest_dir / (name + '.part')
    meta_path = dest_dir / (name + '.part.json')
    expected = _get_md5(url)
    if final.exists() and _md5(final) == expected:
        log(f'{final} は最新です（MD5 一致）')
        return final

    restarted = False
    while True:
        attempt = 0
        while True:
            try:
                _download(url, part, meta_path, log)
                break
            except (OSError, http.client.HTTPException) as e:  # 接続が切れた、時間切れなど
                if isinstance(e, urllib.error.HTTPError) and e.code not in (416, 429, 500, 502, 503, 504):
                    raise  # 404 など、待っても直らないもの
                attempt += 1
                if attempt > retries:
                    raise
                wait = min(60, 5 * attempt)
                log(f'  接続が切れました（{e.__class__.__name__}: {e}）。{wait} 秒後に続きから取ります（{attempt}/{retries}）')
                sleep(wait)
        got = _md5(part)
        if got == expected or got == (expected := _get_md5(url)):
            break
        part.unlink()
        meta_path.unlink(missing_ok=True)
        if restarted:
            raise ValueError(f'MD5 が合いません（期待 {expected}、実際 {got}）')
        log('  MD5 が合わないため、最初から取り直します')
        restarted = True

    os.replace(part, final)
    meta_path.unlink(missing_ok=True)
    log(f'保存しました: {final}')
    return final
