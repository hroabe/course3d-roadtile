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
)
PLACE_CODE = {k: i for i, k in enumerate(PLACE_KINDS)}

# 絞り込みに使うキー（このキーのどれかを持つものだけを読む）
WAY_KEYS = ('highway', 'amenity', 'leisure', 'tourism', 'place', 'railway', 'natural', 'mountain_pass')
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
