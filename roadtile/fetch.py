"""Geofabrik から日本全体のファイルを取得し、MD5 で確かめる。"""
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

from . import __version__

GEOFABRIK_JAPAN = 'https://download.geofabrik.de/asia/japan-latest.osm.pbf'


def _open(url):
    req = urllib.request.Request(url, headers={'User-Agent': f'course3d-roadtile/{__version__}'})
    return urllib.request.urlopen(req, timeout=60)


def fetch(dest_dir, url=GEOFABRIK_JAPAN, log=lambda m: print(m, file=sys.stderr, flush=True)):
    """url のファイルを dest_dir に保存して、その場所を返す。MD5 が合わなければ ValueError。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = url.rsplit('/', 1)[-1]
    with _open(url + '.md5') as r:
        expected = r.read().decode('ascii').split()[0].lower()
    final = dest_dir / name
    if final.exists() and _md5(final) == expected:
        log(f'{final} は最新です（MD5 一致）')
        return final
    part = dest_dir / (name + '.part')
    h = hashlib.md5()
    with _open(url) as r, open(part, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        done, step = 0, 0
        for block in iter(lambda: r.read(1 << 20), b''):
            f.write(block)
            h.update(block)
            done += len(block)
            if total and done * 20 // total > step:
                step = done * 20 // total
                log(f'  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB')
    if h.hexdigest() != expected:
        part.unlink()
        raise ValueError(f'MD5 が合いません（期待 {expected}、実際 {h.hexdigest()}）')
    os.replace(part, final)
    log(f'保存しました: {final}')
    return final


def _md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()
