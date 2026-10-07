# 加工の手順

`course3d-roadtile build` が何をしているかの説明です。形式そのものは [FORMAT.md](FORMAT.md) が正本です。

## 流れ

| 段 | 読むもの | すること |
| --- | --- | --- |
| 1 | リレーションと道 | 水面のマルチポリゴンを読み、部品の道の ID を覚える。対象の道のノード ID を集めて並べ替え、区切り点（2回以上出てくる ID）を決める。面の施設・鉄道・川・水面の頂点の ID と、マルチポリゴンの部品の道の頂点の ID も集める |
| 2 | ノードと道 | 段1で集めた ID のノードだけ座標を覚え、道をもう一度読む。道を区切り点で区切り、区間をマスごとの一時ファイルに書く。面の施設は頂点の平均の位置を書く。鉄道・川の線は64頂点ずつに分けて書く。閉じた道の水面は、間引いて向きをそろえ、マスの四角で切り取って書く。最後にマルチポリゴンの部品の道だけを読み、輪を組み立てて同じように書く |
| 3 | ノード | 名前のある地名・駅・山頂・峠・交差点・施設を一時ファイルに書く |
| 4 | 一時ファイル | ズーム8 のまとまり（16×16 マス）ごとに読み、マスのファイルを書く。地名の索引（places.json.gz）と目録を書く |

- 元ファイルは7回読みます（段1でリレーション・道・部品の道、段2で道・部品の道、段3、ハッシュの計算）。リレーションだけ・部品の道だけを読む回は、osmium が中で読み飛ばすので短く済みます。
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

## 鉄道の線

地図に描くための線で、道路網には入れません（踏切で道路を区切らない）。

| 種類（`railKinds`） | 条件 |
| --- | --- |
| rail、narrow_gauge、light_rail、subway、monorail、tram、funicular | `railway` がその値 |
| aerialway | `aerialway=cable_car`・`gondola`（ロープウェイ・ゴンドラ） |

入れないもの：廃線・工事中・計画中など上の表にない値、`service=yard`・`siding`・`spur`・`crossover`（操車場・側線）、`area=yes`。印は橋とトンネルだけです。

## 川の線と水面（0.3.0 から）

地図に描くためのもので、道路網には入れません。

| 種類（`riverKinds`） | 条件 |
| --- | --- |
| river、canal、stream | `waterway` がその値 |

入れないもの：用水路・排水路（`ditch`・`drain`。日本で22万本あり、地図ではほとんど見えない）、暗渠（`tunnel` が no 以外。`culvert` を含む）、`area=yes`。印は「時期によって水がない」（`intermittent=yes`）だけです。

| 種類（`waterKinds`） | 条件 |
| --- | --- |
| lake | `natural=water` で `water=lake`・`oxbow`・`lagoon` |
| reservoir | `water=reservoir` |
| pond | `water=pond`・`basin`・`fishpond` |
| river | `water=river`・`stream_pool`・`rapids`、または古い書き方の `waterway=riverbank` |
| canal | `water=canal`・`ditch`・`drain`・`stream`・`moat` |
| water | そのほかの `natural=water`（`water` の指定なしを含む） |

- 入れないもの：`water=wastewater`（下水処理の池）。
- 水面は、閉じた道と、`type=multipolygon` のリレーションから作ります。リレーションは、外側（role が inner 以外）と内側（inner）の道をそれぞれ並び順につなぎ、閉じた輪にします。閉じられなかった輪（部品の道がファイルにないなど）は入れず、目録の `counts.waterRingsBroken` に数えます。
- リレーションの外側の部品になっている閉じた道は、道としては描きません（古い書き方で道にも `natural=water` があると、穴の部分が塗られてしまうため）。内側の部品になっている閉じた道（川の面の中の池など）は、道としても描きます。
- 輪は、外側を反時計回り・内側を時計回りにそろえ、ずれ約2m で点を間引いてから、マスの四角で切り取ります（FORMAT.md「川の線と水面」）。
- 名前のある水面（lake・reservoir・pond・water）で、広さ（外側 − 内側）が約10ha 以上（1e7 倍の座標で 1,000,000,000 以上。北緯35度で約10ha）のものは、地名の `lake` として、いちばん大きい外側の輪の重心に入れます。

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
| lake | 名前のある約10ha 以上の水面（上の「川の線と水面」。0.3.0 から） |

施設はノードか、閉じた道（面）で描かれたものを拾います。マルチポリゴン（リレーション）で描かれた大きな公園などは入りません。

## かかる時間とメモリ

この開発環境（2コア・メモリ 7GB の Linux）で、架空のデータ（ノード 300万、道 30万本、区間 182万）を加工すると、全体で約50秒、メモリの最大は約450MB でした。区間の数とマスの数がほぼ時間に比例します。

### 日本全体（実測）

2026-10-05 版の日本全体（約2.5GB）を、Windows の PC（Python 3.14）で加工した結果です。0.1.0 は道路と地名だけ、0.3.0 は鉄道・川・水面を足した版です。

| 段 | 0.1.0 | 0.3.0 |
| --- | --- | --- |
| 1 ノード ID を数える（0.3.0 は水面のリレーションと部品の道を読む回を含む） | 6分37秒 | 6分03秒 |
| 2 区間を区切ってマスに分ける（0.3.0 は鉄道・川・水面を含む） | 8分59秒 | 9分49秒 |
| 3 地名・施設を拾う | 22秒 | 21秒 |
| 4 マスのファイルを書く | 5分02秒 | 5分23秒 |
| 合計 | **21分02秒** | **21分37秒** |

| 項目 | 0.1.0 | 0.3.0 |
| --- | --- | --- |
| メモリの最大（どちらも段1の終わりまでに達した） | 6,445 MB | 8,361 MB |
| 道路の道 | 10,614,507 本 | 同じ |
| 区切り点 | 14,799,606 | 同じ |
| 座標を覚えたノード | 74,597,020 | 97,186,061 |
| 区間 | 20,076,241（マスをまたぐもの 291,521 = 1.5%、座標がなく落としたもの 0） | 同じ |
| 地名・施設 | ノード 416,819、面 138,593 | 同じ＋湖 1,047 |
| 鉄道の線（64頂点ずつ） | — | 98,957 |
| 川の線（64頂点ずつ） | — | 511,567 |
| 水面のマルチポリゴン | — | 5,814（部品の道 25,472 本、組み立てられなかった輪 3） |
| 水面の輪 | — | 191,768（マスで切った部分 199,878） |
| マス | 7,550 枚、合計 361.6 MB（1枚平均 約48KB） | 7,558 枚、合計 406.5 MB（+12%、1枚平均 約54KB） |
| いちばん大きいマス | 3638/1612（東京都心）1.38 MB、区間 119,913 | — |
| `verify --deep` | 問題なし | 問題なし |
| 地名の索引（0.4.0 の `index` で足したもの） | — | 470,351 件、6.3 MB |

- 川・水面を足しても、時間は35秒しか増えませんでした。メモリの最大は約1.9GB 増えました。座標を覚えるノードが2,260万増え、段1の終わりで ID の一覧をまとめるところで増えたとみられます。
- 開発環境の架空のデータでは、川・水面の1頂点あたり約8µs でした（沢 4万本・池 2万・細長い川の面 50）。

メモリは 16GB 以上の PC を勧めます。

メモリが足りないときは `--node-store sparse_file_array,<ファイル名>` でノード座標をディスクに置けます（遅くなります）。

## 試すとき

`--bbox 西,南,東,北` を付けると、その範囲にかかるマスだけを書きます。区切り点の判定は全体で行うので、全体を作ったときと同じマスができます。

```bash
course3d-roadtile build data/japan-latest.osm.pbf --out tiles-test --bbox 138.6,35.3,138.9,35.6
```
