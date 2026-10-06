# 加工の手順

`course3d-roadtile build` が何をしているかの説明です。形式そのものは [FORMAT.md](FORMAT.md) が正本です。

## 流れ

| 段 | 読むもの | すること |
| --- | --- | --- |
| 1 | 道 | 対象の道のノード ID を集めて並べ替え、区切り点（2回以上出てくる ID）を決める。面の施設の頂点の ID も集める |
| 2 | ノードと道 | 段1で集めた ID のノードだけ座標を覚え、道をもう一度読む。道を区切り点で区切り、区間をマスごとの一時ファイルに書く。面の施設は頂点の平均の位置を書く |
| 3 | ノード | 名前のある地名・駅・山頂・峠・交差点・施設を一時ファイルに書く |
| 4 | 一時ファイル | ズーム8 のまとまり（16×16 マス）ごとに読み、マスのファイルを書く。最後に目録を書く |

- 元ファイルは4回読みます（段1・2・3と、ハッシュの計算）。
- 段2の区切りと座標の計算は、50万頂点ずつ numpy でまとめて行います。
- 一時ファイルは出力先の `.<版の日付>.partial/.work/` に置き、終わったら消します。

## 対象にする道と種類

| 種類（`roadKinds`） | OpenStreetMap の `highway` |
| --- | --- |
| 自動車道路 | motorway, motorway_link, trunk, trunk_link |
| 主な道路 | primary, primary_link, secondary, secondary_link, tertiary, tertiary_link |
| 一般の道 | unclassified, residential, living_street, service, pedestrian, road |
| 歩く道 | track, path, footway, cycleway, bridleway, steps |

次のものは入れません：工事中・計画中（construction、proposed）、ホーム（platform）、エレベーター、建物内の通路（corridor）、`area=yes` の面、上の表にない値。

## 区間の印

| 印 | 値 | 決め方 |
| --- | --- | --- |
| 橋 | 1 | `bridge` があり、`no` でない |
| トンネル | 2 | `tunnel` があり、`no` でない（`building_passage` を含む） |
| 一方通行（u→v） | 4 | `oneway=yes`。`oneway` の指定がない motorway とロータリー（`junction=roundabout`） |
| 一方通行（v→u） | 8 | `oneway=-1` |
| 通行禁止 | 16 | `foot=no`・`private`、または `access=no`・`private` で `foot` が yes・designated・permissive でない |
| 自動車専用 | 32 | motorway、motorway_link、または `motorroad=yes` |

- 一方通行は車の決まりです。大会では逆向きに走ることもあるので、経路の計算で禁止するかは読む側が決めます。
- 自動車専用の道は、地図には出しますが、コースの経路には使いません（読む側で除く）。

## 地名の種類

`name` があるものだけを入れます。上から順に当てはめ、最初に合ったものにします。

| 種類（`placeKinds`） | 条件 |
| --- | --- |
| city 〜 locality | `place` が city, town, village, suburb, quarter, neighbourhood, hamlet, locality |
| station | `railway=station`・`halt` |
| peak | `natural=peak`・`volcano` |
| saddle | `natural=saddle`、`mountain_pass=yes` |
| junction | ノードだけ：`highway=traffic_signals`、`junction=yes`（交差点名） |
| school | `amenity=school`・`kindergarten`・`college`・`university` |
| townhall | `amenity=townhall` |
| worship | `amenity=place_of_worship` |
| park | `leisure=park` |
| sports | `leisure=stadium`・`sports_centre` |
| attraction | `tourism=attraction`・`viewpoint`・`museum` |
| rest_area | `highway=services`・`rest_area`（道の駅など） |

施設はノードか、閉じた道（面）で描かれたものを拾います。マルチポリゴン（リレーション）で描かれた大きな公園などは入りません。

## かかる時間とメモリ

この開発環境（2コア・メモリ 7GB の Linux）で、架空のデータ（ノード 300万、道 30万本、区間 182万）を加工すると、全体で約50秒、メモリの最大は約450MB でした。区間の数とマスの数がほぼ時間に比例します。

### 日本全体（実測）

2026-10-05 版の日本全体（約2.5GB）を、Windows の PC（Python 3.14）で加工した結果です。

| 段 | 時間 |
| --- | --- |
| 1 ノード ID を数える | 6分37秒 |
| 2 区間を区切ってマスに分ける | 8分59秒 |
| 3 地名・施設を拾う | 22秒 |
| 4 マスのファイルを書く | 5分02秒 |
| 合計 | **21分02秒** |

| 項目 | 値 |
| --- | --- |
| メモリの最大 | 6,445 MB（段1の終わりまでに達した） |
| 道路の道 | 10,614,507 本 |
| 区切り点 | 14,799,606 |
| 座標を覚えたノード | 74,597,020 |
| 区間 | 20,076,241（マスをまたぐもの 291,521 = 1.5%、座標がなく落としたもの 0） |
| 地名・施設 | ノード 416,819、面 138,593 |
| マス | 7,550 枚、合計 361.6 MB（1枚平均 約48KB） |
| いちばん大きいマス | 3638/1612（東京都心）1.38 MB、区間 119,913 |
| `verify --deep` | 問題なし |

メモリは 16GB 以上の PC を勧めます。

メモリが足りないときは `--node-store sparse_file_array,<ファイル名>` でノード座標をディスクに置けます（遅くなります）。

## 試すとき

`--bbox 西,南,東,北` を付けると、その範囲にかかるマスだけを書きます。区切り点の判定は全体で行うので、全体を作ったときと同じマスができます。

```bash
course3d-roadtile build data/japan-latest.osm.pbf --out tiles-test --bbox 138.6,35.3,138.9,35.6
```
