"""コマンドの入口: course3d-roadtile（または python -m roadtile）"""
import argparse
import sys

from . import __version__


def _bbox(s):
    v = [float(x) for x in s.split(',')]
    if len(v) != 4 or not (v[0] < v[2] and v[1] < v[3]):
        raise argparse.ArgumentTypeError('西経度,南緯度,東経度,北緯度 の順で4つ')
    return tuple(v)


def main(argv=None):
    p = argparse.ArgumentParser(prog='course3d-roadtile', description='OpenStreetMap から大会コース3D用の道路タイルを作る')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='cmd', required=True)

    f = sub.add_parser('fetch', help='Geofabrik から日本全体のファイルを取得する')
    f.add_argument('--dir', default='data', help='保存先（既定: data）')
    f.add_argument('--url', default=None, help='取得する URL（既定: 日本全体）')

    b = sub.add_parser('build', help='道路タイルを作る')
    b.add_argument('pbf', help='元ファイル（.osm.pbf）')
    b.add_argument('--out', default='tiles', help='出力先（既定: tiles）。この下に版の日付のフォルダを作る')
    b.add_argument('--date', default=None, help='版の日付 YYYY-MM-DD（既定: PBF の更新時刻）')
    b.add_argument('--bbox', type=_bbox, default=None, help='試し用: この範囲にかかるマスだけ書く（西,南,東,北）')
    b.add_argument('--node-store', default='flex_mem', help='ノード座標の置き場（osmium の指定。既定: flex_mem）')
    b.add_argument('--force', action='store_true', help='同じ日付の版があれば作り直す')

    v = sub.add_parser('verify', help='目録とファイルを照らし合わせる')
    v.add_argument('dir', help='版のフォルダ（tiles/2026-10-05 など）')
    v.add_argument('--deep', action='store_true', help='各マスを開いて中身も確かめる')

    i = sub.add_parser('info', help='版の概要を表示する')
    i.add_argument('dir')
    i.add_argument('--top', type=int, default=10, help='大きいマスを何枚表示するか')

    t = sub.add_parser('tile', help='経度・緯度が入るマスの番号と範囲を表示する')
    t.add_argument('lon', type=float)
    t.add_argument('lat', type=float)

    a = p.parse_args(argv)
    if a.cmd == 'fetch':
        from .fetch import GEOFABRIK_JAPAN, fetch
        fetch(a.dir, a.url or GEOFABRIK_JAPAN)
    elif a.cmd == 'build':
        from .build import build
        build(a.pbf, a.out, date=a.date, bbox=a.bbox, node_store=a.node_store, force=a.force)
    elif a.cmd == 'verify':
        from .reader import verify
        problems = verify(a.dir, deep=a.deep)
        for msg in problems:
            print(msg)
        print('問題なし' if not problems else f'問題 {len(problems)} 件')
        return 1 if problems else 0
    elif a.cmd == 'info':
        from .reader import load_manifest
        m = load_manifest(a.dir)
        c = m['counts']
        print(f'版 {m["dataVersion"]}（元 {m["source"]["file"]}、{m["source"]["timestamp"]}）')
        print(f'マス {c["tiles"]:,} 枚、{c["bytes"] / 1e6:,.1f} MB、区間 {c["edges"]:,}、地名 {c["places"]:,}')
        print('大きいマス:')
        for x, y, size, _h, ne, npl in sorted(m['tiles'], key=lambda r: -r[2])[:a.top]:
            print(f'  {x}/{y}  {size / 1e6:6.2f} MB  区間 {ne:,}  地名 {npl:,}')
    elif a.cmd == 'tile':
        from .tiles import tile_bounds, tile_of
        x, y = tile_of(a.lon, a.lat)
        w, s, e, n = tile_bounds(x, y)
        print(f'{x}/{y}  （経度 {w:.5f}〜{e:.5f}、緯度 {s:.5f}〜{n:.5f}）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
