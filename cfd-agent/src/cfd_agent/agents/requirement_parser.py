from __future__ import annotations

import re


def parse_requirement(text: str) -> dict:
    """Small deterministic parser for MVP demos; it does not run simulations."""
    assumptions: list[str] = []
    missing_fields: list[str] = []
    normalized = text.strip()
    geometry_type = _detect_geometry_type(normalized)
    diameter_match = re.search(r"(?:直径|diameter)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(mm|m)?", normalized, re.IGNORECASE)
    velocity_match = re.search(r"(?:速度|velocity)?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m\s*/\s*s|mps|米/秒)", normalized, re.IGNORECASE)

    if geometry_type is None:
        missing_fields.append("geometry.type")
    if diameter_match is None:
        missing_fields.append("geometry.parameters.diameter")
    if velocity_match is None:
        missing_fields.append("motion.inlet_velocity")

    task = {}
    if geometry_type and diameter_match and velocity_match:
        task = {
            "task_id": "parsed_task_001",
            "geometry": {"type": geometry_type, "unit": diameter_match.group(2) or "m", "parameters": {"diameter": float(diameter_match.group(1))}},
            "motion": {"type": "stationary", "inlet_velocity": float(velocity_match.group(1)), "attack_angle_deg": 0.0},
        }
        assumptions.append("External steady incompressible air flow is assumed for MVP parsing.")

    return {"task": task, "missing_fields": missing_fields, "assumptions": assumptions}


def _detect_geometry_type(text: str) -> str | None:
    lowered = text.lower()
    if "sphere" in lowered or "球" in text:
        return "sphere"
    if "cylinder" in lowered or "圆柱" in text or "圓柱" in text:
        return "cylinder"
    if "box" in lowered or "长方体" in text or "立方体" in text:
        return "box"
    return None
