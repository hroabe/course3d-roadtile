# course3d-roadtile

OpenStreetMap の日本全体のデータから、大会コース3D スタジオ（駅伝・マラソン・トレイルのコースを3Dで見せるページを作る、自分用の制作ツール）が読む**道路タイル**を作る加工スクリプトです。

- 道を交差点で区切った区間を、約8km四方のマス（地図タイルのズーム12）に分けて保存します。
- 区間の両端には OpenStreetMap のノード ID が付いていて、マスの境目はその ID でつながります。
- 道の種類、名前・路線番号、橋・トンネル・一方通行・通行禁止・自動車専用の印と、ポイントの名前の候補（地名・駅・山頂・交差点名・施設）も入れます。
- 目録（manifest.json）に、版の日付とマスごとの大きさ・ハッシュを書きます。

形式の正本は [docs/FORMAT.md](docs/FORMAT.md)、加工の手順は [docs/PIPELINE.md](docs/PIPELINE.md) です。

## なぜ公開しているか

道路タイルは OpenStreetMap のデータから作った「派生データベース」で、Open Database License（ODbL 1.0）に従います。派生データベースを使って作ったものを公開するときは、派生データベースそのものか、**作り方**を提供する必要があります（ODbL 4.6）。このリポジトリは、その作り方の提供にあたります。

## 準備

- Python 3.10 以上
- メモリ 8GB 以上（日本全体なら 16GB を推奨）
- ディスクの空き 10GB ほど（元ファイル 2.4GB、出力と一時ファイル）

```bash
git clone https://github.com/hroabe/course3d-roadtile
cd course3d-roadtile
python -m venv .venv
. .venv/bin/activate            # Windows は .venv\Scripts\activate
pip install -e .
```

## 月1回の手順

```bash
course3d-roadtile fetch                                   # data/japan-latest.osm.pbf を取得（MD5 を確認）
course3d-roadtile build data/japan-latest.osm.pbf --out tiles
course3d-roadtile verify tiles/2026-10-05 --deep          # 目録とファイルを照らし合わせる
course3d-roadtile info tiles/2026-10-05                   # 大きさと、大きいマスの一覧
```

- 版のフォルダ名（`2026-10-05` など）は、元ファイルの更新日です。
- 範囲を絞って試すときは `--bbox 西,南,東,北` を付けます。
- `course3d-roadtile tile 138.75 35.40` で、その地点が入るマスの番号と範囲を表示します。

## 開発

```bash
pip install -e '.[dev]'
pytest
```

テストは、手で作った架空の小さなデータで、区切り方・マスへの分け方・つなぎ合わせ・結果が毎回同じになることなどを確かめます。

## ライセンス

- このリポジトリのコード：MIT（[LICENSE](LICENSE)）
- 作った道路タイル：ODbL 1.0。使うときは「© OpenStreetMap contributors」を表示してください。
- 元データ：© OpenStreetMap contributors。[Geofabrik](https://download.geofabrik.de/asia/japan.html) の抜き出しを使います。
