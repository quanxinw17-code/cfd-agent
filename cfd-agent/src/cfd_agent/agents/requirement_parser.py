from __future__ import annotations

import re


NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
LENGTH_UNIT = r"(mm|毫米|cm|厘米|m|米)?"


def parse_requirement(text: str) -> dict:
    """Parse a concise Chinese or English CFD request into a SimulationTask payload."""
    normalized = " ".join(text.strip().split())
    geometry_type = _detect_geometry_type(normalized)
    parameters: dict[str, float] = {}
    missing_fields: list[str] = []
    assumptions = [
        "默认采用空气、外流场、稳态压力基求解器和 k-omega SST 湍流模型。",
        "未指定的网格、流体域尺寸和收敛参数使用项目默认值。",
    ]

    if geometry_type == "custom_cad":
        characteristic_length = _length_value(normalized, ["特征长度", "参考长度", "characteristic length"])
        if characteristic_length is not None:
            parameters["characteristic_length"] = characteristic_length
        else:
            missing_fields.append("CAD 特征长度")
    elif geometry_type == "sphere":
        diameter = _length_value(normalized, ["直径", "diameter"])
        radius = _length_value(normalized, ["半径", "radius"])
        if diameter is None and radius is not None:
            diameter = radius * 2
        if diameter is not None:
            parameters["diameter"] = diameter
        else:
            missing_fields.append("球体直径")
    elif geometry_type == "cylinder":
        diameter = _length_value(normalized, ["直径", "diameter"])
        length = _length_value(normalized, ["长度", "长", "length", "height"])
        if diameter is not None:
            parameters["diameter"] = diameter
        else:
            missing_fields.append("圆柱直径")
        if length is not None:
            parameters["length"] = length
        else:
            missing_fields.append("圆柱长度")
    elif geometry_type == "box":
        dimensions = _box_dimensions(normalized)
        parameters.update(dimensions)
        for name, label in [("length", "长方体长度"), ("width", "长方体宽度"), ("height", "长方体高度")]:
            if name not in parameters:
                missing_fields.append(label)
    elif geometry_type is None:
        missing_fields.append("模型类型（球体、圆柱或长方体）")

    velocity = _velocity_value(normalized)
    if velocity is None:
        missing_fields.append("入口速度")

    attack_angle = _number_after(normalized, ["攻角", "迎角", "attack angle", "aoa"]) or 0.0
    max_iterations = int(_number_after(normalized, ["迭代次数", "最大迭代", "iterations", "max iterations"]) or 1000)

    task = {}
    if not missing_fields and geometry_type and velocity is not None:
        task = {
            "task_id": "natural_language_task",
            "geometry": {"type": geometry_type, "unit": "m", "parameters": parameters},
            "motion": {"type": "stationary", "inlet_velocity": velocity, "attack_angle_deg": attack_angle},
            "solver": {"max_iterations": max_iterations},
        }

    return {
        "task": task,
        "missing_fields": missing_fields,
        "assumptions": assumptions,
        "normalized_text": normalized,
        "parsed_values": {
            "geometry_type": geometry_type,
            "parameters": parameters,
            "inlet_velocity": velocity,
            "attack_angle_deg": attack_angle,
            "max_iterations": max_iterations,
        },
    }


def _detect_geometry_type(text: str) -> str | None:
    lowered = text.lower()
    if any(token in lowered for token in ["custom cad", "cad 文件", "cad模型", "自定义模型", "导入模型"]):
        return "custom_cad"
    if any(token in lowered for token in ["sphere", "球体", "球形", "球"]):
        return "sphere"
    if any(token in lowered for token in ["cylinder", "圆柱", "圓柱"]):
        return "cylinder"
    if any(token in lowered for token in ["box", "长方体", "矩形体", "立方体"]):
        return "box"
    return None


def _length_value(text: str, labels: list[str]) -> float | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*(?:为|是|=|:|：)?\s*{NUMBER}\s*{LENGTH_UNIT}", text, re.IGNORECASE)
        if match:
            return _to_meters(float(match.group(1)), match.group(2))
    return None


def _box_dimensions(text: str) -> dict[str, float]:
    match = re.search(
        rf"{NUMBER}\s*{LENGTH_UNIT}\s*[xX×*]\s*{NUMBER}\s*{LENGTH_UNIT}\s*[xX×*]\s*{NUMBER}\s*{LENGTH_UNIT}",
        text,
    )
    if match:
        common_unit = match.group(2) or match.group(4) or match.group(6)
        return {
            "length": _to_meters(float(match.group(1)), match.group(2) or common_unit),
            "width": _to_meters(float(match.group(3)), match.group(4) or common_unit),
            "height": _to_meters(float(match.group(5)), match.group(6) or common_unit),
        }
    values = {}
    for key, labels in [("length", ["长度", "长", "length"]), ("width", ["宽度", "宽", "width"]), ("height", ["高度", "高", "height"])]:
        value = _length_value(text, labels)
        if value is not None:
            values[key] = value
    return values


def _velocity_value(text: str) -> float | None:
    match = re.search(
        rf"(?:入口速度|来流速度|风速|速度|velocity|speed)\s*(?:为|是|=|:|：)?\s*{NUMBER}\s*(m\s*/\s*s|mps|米每秒|km\s*/\s*h|公里每小时)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(rf"{NUMBER}\s*(m\s*/\s*s|mps|米每秒|km\s*/\s*h|公里每小时)", text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "m/s").lower().replace(" ", "")
    return value / 3.6 if unit in {"km/h", "公里每小时"} else value


def _number_after(text: str, labels: list[str]) -> float | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*(?:为|是|=|:|：)?\s*{NUMBER}", text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _to_meters(value: float, unit: str | None) -> float:
    normalized = (unit or "m").lower()
    if normalized in {"mm", "毫米"}:
        return value / 1000
    if normalized in {"cm", "厘米"}:
        return value / 100
    return value
