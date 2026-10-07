"""地名の索引（places.json.gz）：範囲を地名で探すための、名前と位置の一覧（docs/FORMAT.md「地名の索引」）。"""
import hashlib
import json
from pathlib import Path

from .encode import _dumps, gzip_bytes

INDEX_FILE = 'places.json.gz'
INDEX_VERSION = 1
SKIP_KINDS = frozenset(('junction',))  # 交差点名は範囲を探すのに使わない
CELL = 1000                            # 同じ名前を1つにまとめる升目（1e5 倍の座標で。約1km）


def index_entries(places, kinds):
    """地名 (kind, name, x, y) の並びから、索引の行 [kind, name, x, y] を作る。"""
    skip = {i for i, k in enumerate(kinds) if k in SKIP_KINDS}
    rows = sorted({(k, n, x, y) for k, n, x, y in places if n and k not in skip})
    out, seen = [], set()
    for k, n, x, y in rows:
        key = (k, n, x // CELL, y // CELL)
        if key in seen:
            continue
        seen.add(key)
        out.append((k, n, x, y))
    out.sort(key=lambda r: (r[1], r[0], r[2], r[3]))  # 名前（コードポイント順 = UTF-8 のバイト順）、種類、座標
    return out


def encode_index(entries, kinds):
    return gzip_bytes(_dumps({'v': INDEX_VERSION, 'kinds': list(kinds), 'places': [list(r) for r in entries]}))


def write_index(version_dir, places, kinds):
    """索引を書き、目録に書く項目 {file, bytes, sha256, count} を返す。"""
    entries = index_entries(places, kinds)
    data = encode_index(entries, kinds)
    (Path(version_dir) / INDEX_FILE).write_bytes(data)
    return {'file': INDEX_FILE, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'count': len(entries)}


def read_index(version_dir):
    """索引を読む。{'kinds': [...], 'places': [(kind, name, x, y)]}。"""
    import gzip
    t = json.loads(gzip.decompress((Path(version_dir) / INDEX_FILE).read_bytes()))
    if t.get('v') != INDEX_VERSION:
        raise ValueError(f'unsupported place index version: {t.get("v")}')
    return {'kinds': t['kinds'], 'places': [tuple(r) for r in t['places']]}


def places_of_tiles(version_dir, manifest, tile_relpath):
    """版のマスを全部読み、地名 (kind, name, x, y) を集める（古い版に索引を足すとき）。区間などは戻さない。"""
    import gzip
    out = []
    for x, y, *_ in manifest['tiles']:
        t = json.loads(gzip.decompress((Path(version_dir) / tile_relpath(x, y)).read_bytes()))
        names, px, py = t['names'], 0, 0
        for kind, ni, dx, dy in t['places']:
            px += dx
            py += dy
            out.append((kind, names[ni], px, py))
    return out
