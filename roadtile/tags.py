"""OpenStreetMap のタグから、道の種類・印と、地名の種類を決める（入出力のない純粋な関数）。

ここで決めた番号は道路タイルの形式の一部です。番号を変えたら形式の版を上げます（docs/FORMAT.md）。
"""

# 道の種類。並び順が番号（0 始まり）。末尾に足すのはよいが、途中を変えてはいけない。
ROAD_KINDS = (
    'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link',
    'secondary', 'secondary_link', 'tertiary', 'tertiary_link', 'unclassified', 'residential',
    'living_street', 'service', 'pedestrian', 'road', 'track', 'path', 'footway', 'cycleway',
    'bridleway', 'steps',
)
KIND_CODE = {k: i for i, k in enumerate(ROAD_KINDS)}

# 区間の印（ビット）
F_BRIDGE = 1        # 橋
F_TUNNEL = 2        # トンネル
F_ONEWAY = 4        # 一方通行（u → v の向き）
F_ONEWAY_REV = 8    # 一方通行（v → u の向き）
F_NO_ACCESS = 16    # 通行禁止（歩行者が入れない、または私道）
F_MOTOR_ONLY = 32   # 自動車専用
FLAGS = {'bridge': F_BRIDGE, 'tunnel': F_TUNNEL, 'oneway': F_ONEWAY, 'onewayReverse': F_ONEWAY_REV,
         'noAccess': F_NO_ACCESS, 'motorOnly': F_MOTOR_ONLY}

# 地名の種類。並び順が番号。
PLACE_KINDS = (
    'city', 'town', 'village', 'suburb', 'quarter', 'neighbourhood', 'hamlet', 'locality',
    'station', 'peak', 'saddle', 'junction',
    'school', 'townhall', 'worship', 'park', 'sports', 'attraction', 'rest_area',
    'lake',  # 0.3.0 から。名前のある大きな水面（build.py の LAKE_MIN_M2 以上）
)
PLACE_CODE = {k: i for i, k in enumerate(PLACE_KINDS)}

# 鉄道の線の種類（地図に描くだけ。道路網には入れない）。並び順が番号。
RAIL_KINDS = ('rail', 'narrow_gauge', 'light_rail', 'subway', 'monorail', 'tram', 'funicular', 'aerialway')
RAIL_CODE = {k: i for i, k in enumerate(RAIL_KINDS)}
_RAIL_SERVICE_SKIP = frozenset(('yard', 'siding', 'spur', 'crossover'))

# 川の線の種類（地図に描くだけ）。並び順が番号。
RIVER_KINDS = ('river', 'canal', 'stream')
RIVER_CODE = {k: i for i, k in enumerate(RIVER_KINDS)}

# 水面の種類。並び順が番号。
WATER_KINDS = ('lake', 'reservoir', 'pond', 'river', 'canal', 'water')
WATER_CODE = {k: i for i, k in enumerate(WATER_KINDS)}
_WATER_OF = {
    'lake': 'lake', 'oxbow': 'lake', 'lagoon': 'lake',
    'reservoir': 'reservoir',
    'pond': 'pond', 'basin': 'pond', 'fishpond': 'pond',
    'river': 'river', 'stream_pool': 'river', 'rapids': 'river',
    'canal': 'canal', 'ditch': 'canal', 'drain': 'canal', 'stream': 'canal', 'moat': 'canal',
}
_WATER_SKIP = frozenset(('wastewater',))
F_INTERMITTENT = 1  # 川の線・水面の印：時期によって水がない

# 絞り込みに使うキー（このキーのどれかを持つものだけを読む）
WAY_KEYS = ('highway', 'amenity', 'leisure', 'tourism', 'place', 'railway', 'aerialway', 'natural', 'mountain_pass',
            'waterway')
NODE_KEYS = ('place', 'railway', 'natural', 'mountain_pass', 'highway', 'junction', 'amenity', 'leisure', 'tourism')

_NO = frozenset(('no', 'false', '0'))
_FOOT_OK = frozenset(('yes', 'designated', 'permissive'))
_PLACE_VALUES = frozenset(PLACE_KINDS[:8])


def road_attrs(tags):
    """道路として使うなら (種類, 印, 名前, 路線番号) を、使わないなら None を返す。

    tags は get(key) を持つもの（pyosmium の TagList か dict）。
    """
    hw = tags.get('highway')
    kind = KIND_CODE.get(hw)
    if kind is None or tags.get('area') == 'yes':
        return None
    f = 0
    v = tags.get('bridge')
    if v and v not in _NO:
        f |= F_BRIDGE
    v = tags.get('tunnel')
    if v and v not in _NO:
        f |= F_TUNNEL
    ow = tags.get('oneway')
    if ow in ('yes', 'true', '1'):
        f |= F_ONEWAY
    elif ow in ('-1', 'reverse'):
        f |= F_ONEWAY_REV
    elif ow is None and (hw == 'motorway' or tags.get('junction') in ('roundabout', 'circular')):
        f |= F_ONEWAY
    foot = tags.get('foot')
    if foot in ('no', 'private') or (tags.get('access') in ('no', 'private') and foot not in _FOOT_OK):
        f |= F_NO_ACCESS
    if hw in ('motorway', 'motorway_link') or tags.get('motorroad') == 'yes':
        f |= F_MOTOR_ONLY
    return kind, f, tags.get('name') or '', tags.get('ref') or ''


def place_kind(tags, node=True):
    """名前の候補に使う地点なら地名の種類の番号を、使わないなら None を返す。名前のないものは使わない。

    node=False は、閉じた道（面）として描かれた施設を調べるとき。交差点名はノードだけで使う。
    """
    if not tags.get('name'):
        return None
    v = tags.get('place')
    if v in _PLACE_VALUES:
        return PLACE_CODE[v]
    if tags.get('railway') in ('station', 'halt'):
        return PLACE_CODE['station']
    v = tags.get('natural')
    if v in ('peak', 'volcano'):
        return PLACE_CODE['peak']
    if v == 'saddle' or tags.get('mountain_pass') == 'yes':
        return PLACE_CODE['saddle']
    hw = tags.get('highway')
    if node and (hw == 'traffic_signals' or tags.get('junction') == 'yes'):
        return PLACE_CODE['junction']
    v = tags.get('amenity')
    if v in ('school', 'kindergarten', 'college', 'university'):
        return PLACE_CODE['school']
    if v == 'townhall':
        return PLACE_CODE['townhall']
    if v == 'place_of_worship':
        return PLACE_CODE['worship']
    v = tags.get('leisure')
    if v == 'park':
        return PLACE_CODE['park']
    if v in ('stadium', 'sports_centre'):
        return PLACE_CODE['sports']
    if tags.get('tourism') in ('attraction', 'viewpoint', 'museum'):
        return PLACE_CODE['attraction']
    if hw in ('services', 'rest_area'):
        return PLACE_CODE['rest_area']
    return None


def rail_attrs(tags):
    """地図に描く鉄道の線なら (種類, 印) を、そうでなければ None を返す。印は橋 1・トンネル 2 だけ。

    廃線・工事中・計画中、操車場や側線（service=yard・siding・spur・crossover）は入れない。
    ロープウェイ・ゴンドラ（aerialway=cable_car・gondola）は aerialway として入れる。
    """
    v = tags.get('railway')
    if v in RAIL_CODE and v != 'aerialway':
        kind = RAIL_CODE[v]
    elif tags.get('aerialway') in ('cable_car', 'gondola'):
        kind = RAIL_CODE['aerialway']
    else:
        return None
    if tags.get('service') in _RAIL_SERVICE_SKIP or tags.get('area') == 'yes':
        return None
    f = 0
    b = tags.get('bridge')
    if b and b not in _NO:
        f |= F_BRIDGE
    t = tags.get('tunnel')
    if t and t not in _NO:
        f |= F_TUNNEL
    return kind, f


def _intermittent(tags):
    return F_INTERMITTENT if tags.get('intermittent') == 'yes' else 0


def river_attrs(tags):
    """地図に描く川の線なら (種類, 印) を、そうでなければ None を返す。

    waterway=river・canal・stream。暗渠（tunnel が no 以外。culvert を含む）と area=yes は入れない。
    用水路・排水路（ditch・drain）は数が多く地図ではほとんど見えないので入れない。
    """
    kind = RIVER_CODE.get(tags.get('waterway'))
    if kind is None or tags.get('area') == 'yes':
        return None
    t = tags.get('tunnel')
    if t and t not in _NO:
        return None
    return kind, _intermittent(tags)


def water_attrs(tags):
    """水面（閉じた道・マルチポリゴンのリレーション）なら (種類, 印) を、そうでなければ None を返す。

    natural=water（water=wastewater を除く）と、古い書き方の waterway=riverbank。
    リレーションかどうか（type=multipolygon）は呼ぶ側で確かめる。
    """
    if tags.get('natural') == 'water':
        w = tags.get('water')
        if w in _WATER_SKIP:
            return None
        return WATER_CODE[_WATER_OF.get(w, 'water')], _intermittent(tags)
    if tags.get('waterway') == 'riverbank':
        return WATER_CODE['river'], _intermittent(tags)
    return None
