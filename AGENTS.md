# AGENTS.md — course3d-roadtile

このファイルは、このリポジトリで作業するすべてのエージェント（Claude Code、Codex など）の入口です。作業の前に必ず読んでください。

## このリポジトリは何か

OpenStreetMap の日本全体のデータ（Geofabrik）から、大会コース3D スタジオ（非公開の制作ツール）が読む道路タイルを作る加工スクリプトです。OpenStreetMap のライセンス（ODbL）の「作り方の提供」にあてるため公開しています。

## 文書

| 層 | 役割 | 場所 |
| --- | --- | --- |
| L0 | 作業のルール | `AGENTS.md`（このファイル）、`CLAUDE.md` |
| L1 | 道路タイルの形式（正本） | `docs/FORMAT.md` |
| L2 | 加工の手順、タグの扱い、時間とメモリ | `docs/PIPELINE.md` |
| L3 | 決定記録 | `docs/DECISIONS.md` |

アプリ側の要件（REQ-DATA-001〜004、REQ-DATA-008、REQ-LIC-002）は course3d-studio の REQUIREMENTS.md にあります。

## 作業のルール

1. **形式が先:** 出力の形を変えるときは、先に `docs/FORMAT.md` を直す。読めなくなる変更は `formatVersion` を上げる。
2. **決定は記録する:** 設計上の選択は `docs/DECISIONS.md` に1件追記する。
3. **三回で止まる:** 同じ問題に3回取り組んで解決しなければ、止めて状況を報告する。
4. **結果を決める:** 同じ元ファイルと同じ版のスクリプトからは、同じバイト列を作る。現在時刻や乱数を出力に入れない。
5. **純粋な部分を分ける:** `tags.py`・`tiles.py`・`encode.py` は入出力を持たない。テストはここと、小さな架空データでの全体の加工に対して書く。
6. **テストを通す:** `pytest` が通らない変更はコミットしない。
7. **データを入れない:** OpenStreetMap の元データ、作った道路タイルはこのリポジトリに入れない（`.gitignore` 済み）。テストのデータは手で作った架空のものだけ。

## よく使うコマンド

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
course3d-roadtile fetch                       # data/japan-latest.osm.pbf を取得
course3d-roadtile build data/japan-latest.osm.pbf --out tiles
course3d-roadtile verify tiles/<版の日付> --deep
```
