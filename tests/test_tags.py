from roadtile.tags import (F_BRIDGE, F_MOTOR_ONLY, F_NO_ACCESS, F_ONEWAY, F_ONEWAY_REV, F_TUNNEL, KIND_CODE,
                           PLACE_CODE, place_kind, road_attrs)


def flags(**tags):
    return road_attrs(tags)[1]


def test_road_kinds_and_exclusions():
    assert road_attrs({'highway': 'residential'})[0] == KIND_CODE['residential']
    assert road_attrs({'highway': 'steps'})[0] == KIND_CODE['steps']
    assert road_attrs({'highway': 'path', 'name': '吉田ルート', 'ref': '1'}) == (KIND_CODE['path'], 0, '吉田ルート', '1')
    for hw in ('construction', 'proposed', 'platform', 'raceway', 'bus_guideway', 'elevator', 'corridor', 'services'):
        assert road_attrs({'highway': hw}) is None, hw
    assert road_attrs({'highway': 'pedestrian', 'area': 'yes'}) is None
    assert road_attrs({'name': 'no highway'}) is None


def test_bridge_tunnel():
    assert flags(highway='primary', bridge='viaduct') == F_BRIDGE
    assert flags(highway='primary', bridge='no') == 0
    assert flags(highway='footway', tunnel='building_passage') == F_TUNNEL
    assert flags(highway='trunk', bridge='yes', tunnel='yes') == F_BRIDGE | F_TUNNEL


def test_oneway():
    assert flags(highway='secondary', oneway='yes') == F_ONEWAY
    assert flags(highway='secondary', oneway='-1') == F_ONEWAY_REV
    assert flags(highway='secondary', oneway='no') == 0
    assert flags(highway='tertiary', junction='roundabout') == F_ONEWAY
    assert flags(highway='tertiary', junction='roundabout', oneway='no') == 0
    assert flags(highway='motorway') == F_ONEWAY | F_MOTOR_ONLY


def test_access_and_motor_only():
    assert flags(highway='trunk', foot='no') == F_NO_ACCESS
    assert flags(highway='service', access='private') == F_NO_ACCESS
    assert flags(highway='service', access='private', foot='yes') == 0
    assert flags(highway='track', access='no', foot='designated') == 0
    assert flags(highway='trunk', motorroad='yes') == F_MOTOR_ONLY
    assert flags(highway='motorway_link') == F_MOTOR_ONLY


def test_place_kinds():
    assert place_kind({'place': 'town', 'name': '富士吉田'}) == PLACE_CODE['town']
    assert place_kind({'place': 'town'}) is None  # 名前がない
    assert place_kind({'railway': 'station', 'name': '箱根湯本'}) == PLACE_CODE['station']
    assert place_kind({'natural': 'volcano', 'name': '富士山'}) == PLACE_CODE['peak']
    assert place_kind({'mountain_pass': 'yes', 'name': '箱根峠'}) == PLACE_CODE['saddle']
    assert place_kind({'highway': 'traffic_signals', 'name': '金鳥居'}) == PLACE_CODE['junction']
    assert place_kind({'highway': 'traffic_signals', 'name': '金鳥居'}, node=False) is None
    assert place_kind({'amenity': 'school', 'name': '第一小学校'}, node=False) == PLACE_CODE['school']
    assert place_kind({'highway': 'services', 'name': '道の駅'}, node=False) == PLACE_CODE['rest_area']
    # 地名が施設より先
    assert place_kind({'place': 'village', 'amenity': 'townhall', 'name': '村'}) == PLACE_CODE['village']
    assert place_kind({'amenity': 'cafe', 'name': 'カフェ'}) is None
