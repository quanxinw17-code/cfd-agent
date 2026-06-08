from cfd_agent.agents.requirement_parser import parse_requirement


def test_parse_chinese_sphere_request() -> None:
    parsed = parse_requirement("分析一个直径 100 mm 的球体外流场，入口速度 30 m/s，攻角 5 度")

    assert parsed["missing_fields"] == []
    assert parsed["task"]["geometry"]["type"] == "sphere"
    assert parsed["task"]["geometry"]["parameters"]["diameter"] == 0.1
    assert parsed["task"]["motion"]["inlet_velocity"] == 30.0
    assert parsed["task"]["motion"]["attack_angle_deg"] == 5.0


def test_parse_chinese_cylinder_request() -> None:
    parsed = parse_requirement("圆柱直径 50 毫米，长度 0.2 米，来流速度 20 米每秒")

    assert parsed["missing_fields"] == []
    assert parsed["task"]["geometry"]["type"] == "cylinder"
    assert parsed["task"]["geometry"]["parameters"] == {"diameter": 0.05, "length": 0.2}


def test_parse_box_dimensions() -> None:
    parsed = parse_requirement("长方体 1m x 0.5m x 0.25m，风速 10 m/s")

    assert parsed["missing_fields"] == []
    assert parsed["task"]["geometry"]["parameters"] == {"length": 1.0, "width": 0.5, "height": 0.25}


def test_parse_reports_missing_fields() -> None:
    parsed = parse_requirement("分析一个球体")

    assert "球体直径" in parsed["missing_fields"]
    assert "入口速度" in parsed["missing_fields"]


def test_parse_custom_cad_request() -> None:
    parsed = parse_requirement("导入模型做外流场分析，特征长度 0.8 米，速度 50 m/s")

    assert parsed["missing_fields"] == []
    assert parsed["task"]["geometry"]["type"] == "custom_cad"
    assert parsed["task"]["geometry"]["parameters"]["characteristic_length"] == 0.8
