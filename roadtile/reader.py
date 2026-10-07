"""道路タイルの読み込み・つなぎ合わせ・検査（アプリ側の読み方の見本を兼ねる）。"""
import hashlib
import json
from pathlib import Path

from .build import FORMAT_NAME, tile_relpath
from .encode import FORMAT_VERSION, decode_tile
from .tiles import tiles_in_bbox


def load_manifest(version_dir):
    m = json.loads((Path(version_dir) / 'manifest.json').read_text(encoding='utf-8'))
    if m.get('format') != FORMAT_NAME or m.get('formatVersion') != FORMAT_VERSION:
        raise ValueError(f'unsupported manifest: {m.get("format")} v{m.get("formatVersion")}')
    return m


def read_tile(version_dir, x, y):
    return decode_tile((Path(version_dir) / tile_relpath(x, y)).read_bytes())


def load_area(version_dir, bbox=None):
    """範囲にかかるマスを読み、ノード ID でつなぎ合わせる。

    返り値: {'nodes': {id: (x, y)}, 'edges': {(way, seg): edge}, 'places': [...], 'rails': {(way, part): rail},
             'rivers': {(way, part): river}, 'water': [(マス x, マス y, kind, flags, src, xs, ys)], 'tiles': [(x, y)]}
    同じ区間・同じ鉄道や川の線が複数のマスに入っているときは1つにまとめる（中身が違えば ValueError）。
    水面はマスごとに切り取ってあるので、まとめずに並べる。
    """
    m = load_manifest(version_dir)
    rng = tiles_in_bbox(*bbox) if bbox else None
    nodes, edges, places, rails, rivers, water, used = {}, {}, [], {}, {}, [], []
    for x, y, *_ in m['tiles']:
        if rng and not (rng[0] <= x <= rng[2] and rng[1] <= y <= rng[3]):
            continue
        t = read_tile(version_dir, x, y)
        used.append((x, y))
        for nid, xy in t['nodes'].items():
            old = nodes.setdefault(nid, xy)
            if old != xy:
                raise ValueError(f'node {nid} has different coordinates in tile {x}/{y}')
        for e in t['edges']:
            key = (e[0], e[1])
            old = edges.setdefault(key, e)
            if old != e:
                raise ValueError(f'edge {key} differs in tile {x}/{y}')
        places += t['places']
        for name, store in (('rail', rails), ('river', rivers)):
            for r in t[name + 's']:
                old = store.setdefault((r[0], r[1]), r)
                if old != r:
                    raise ValueError(f'{name} {(r[0], r[1])} differs in tile {x}/{y}')
        water += [(x, y) + w for w in t['water']]
    return {'nodes': nodes, 'edges': edges, 'places': places, 'rails': rails, 'rivers': rivers, 'water': water,
            'tiles': used}


def verify(version_dir, deep=False):
    """目録とファイルを照らし合わせ、問題の一覧を返す（空なら問題なし）。"""
    version_dir = Path(version_dir)
    problems = []
    try:
        m = load_manifest(version_dir)
    except (OSError, ValueError) as e:
        return [f'manifest: {e}']
    listed = set()
    for x, y, size, digest, n_edges, n_places in m['tiles']:
        rel = tile_relpath(x, y)
        listed.add(rel)
        p = version_dir / rel
        if not p.is_file():
            problems.append(f'{rel}: ファイルがない')
            continue
        data = p.read_bytes()
        if len(data) != size:
            problems.append(f'{rel}: 大きさが違う（目録 {size}、実際 {len(data)}）')
        if hashlib.sha256(data).hexdigest() != digest:
            problems.append(f'{rel}: ハッシュが違う')
            continue
        if deep:
            try:
                t = decode_tile(data)
            except Exception as e:  # 壊れたファイル
                problems.append(f'{rel}: 読めない（{e}）')
                continue
            if (t['x'], t['y']) != (x, y):
                problems.append(f'{rel}: 中のマス番号が違う')
            if len(t['edges']) != n_edges or len(t['places']) != n_places:
                problems.append(f'{rel}: 区間・地名の数が目録と違う')
            for e in t['edges']:
                if e[4] >= len(m['roadKinds']):
                    problems.append(f'{rel}: 道の種類の番号が範囲外（way {e[0]}）')
                    break
            for r in t['rails']:
                if r[2] >= len(m.get('railKinds', [])) or len(r[4]) < 2:
                    problems.append(f'{rel}: 鉄道の線がおかしい（way {r[0]}）')
                    break
            for r in t['rivers']:
                if r[2] >= len(m.get('riverKinds', [])) or len(r[4]) < 2:
                    problems.append(f'{rel}: 川の線がおかしい（way {r[0]}）')
                    break
            for w in t['water']:
                if w[0] >= len(m.get('waterKinds', [])) or len(w[3]) < 3:
                    problems.append(f'{rel}: 水面の輪がおかしい（src {w[2]}）')
                    break
    for p in sorted((version_dir / str(m['zoom'])).rglob('*.json.gz')):
        rel = p.relative_to(version_dir).as_posix()
        if rel not in listed:
            problems.append(f'{rel}: 目録にないファイル')
    return problems
