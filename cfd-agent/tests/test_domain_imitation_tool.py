from pathlib import Path
from collections import deque
import json
import subprocess

import pytest
from pydantic import ValidationError

from cfd_agent.core.models import DomainImitationConfig, SimulationTask
from cfd_agent.tools.domain_imitation_tool import (
    STANDARD_BOUNDARIES,
    _render_analysis_script,
    analyze_reference_domain,
    map_boundary_roles,
    scale_domain_profile,
    supported_domain_reference_file,
    write_domain_comparison,
)
from cfd_agent.tools.spaceclaim_tool import create_external_flow_domain


def test_supported_domain_reference_file_accepts_spaceclaim_and_step(tmp_path: Path) -> None:
    for name in ("fluid_domain.scdoc", "fluid_domain.step", "fluid_domain.stp"):
        assert supported_domain_reference_file(tmp_path / name)
    assert not supported_domain_reference_file(tmp_path / "fluid_domain.msh.h5")


def test_domain_imitation_config_defaults_to_disabled() -> None:
    config = DomainImitationConfig()

    assert config.enabled is False
    assert config.reference_file is None
    assert config.manual_flow_direction is None


@pytest.mark.parametrize(
    "direction",
    (
        [0, 0, 0],
        [1, 0],
        [1, 0, 0, 0],
        [float("inf"), 0, 0],
        [float("-inf"), 0, 0],
        [float("nan"), 0, 0],
    ),
)
def test_manual_flow_direction_rejects_invalid_vectors(direction: list[float]) -> None:
    with pytest.raises(ValidationError):
        DomainImitationConfig(enabled=True, reference_file="reference.step", manual_flow_direction=direction)


@pytest.mark.parametrize("direction", ([True, 0, 0], [1, False, 0]))
def test_manual_flow_direction_rejects_boolean_components(direction: list[object]) -> None:
    with pytest.raises(ValidationError):
        DomainImitationConfig(manual_flow_direction=direction)


@pytest.mark.parametrize(
    "direction_factory",
    (
        lambda: deque([True, 0, 0]),
        lambda: (component for component in [1, False, 0]),
    ),
)
def test_manual_flow_direction_rejects_boolean_components_from_iterables(direction_factory) -> None:
    with pytest.raises(ValidationError):
        DomainImitationConfig(manual_flow_direction=direction_factory())


def test_manual_flow_direction_normalizes_components_to_floats() -> None:
    config = DomainImitationConfig(manual_flow_direction=[1, 0, -2])

    assert config.manual_flow_direction == [1.0, 0.0, -2.0]


def test_standard_boundaries_define_expected_names_and_types() -> None:
    assert STANDARD_BOUNDARIES == {
        "inlet": {"name": "velocity_inlet", "type": "velocity-inlet"},
        "outlet": {"name": "pressure_outlet", "type": "pressure-outlet"},
        "farfield": {"name": "farfield", "type": "wall"},
        "object_wall": {"name": "object_wall", "type": "wall"},
    }


def test_map_boundary_roles_preserves_valid_reference_values_and_falls_back_per_field() -> None:
    mapped = map_boundary_roles(
        {
            "inlet": {"name": "air_in", "type": "mass-flow-inlet"},
            "outlet": {"name": "", "type": "pressure-outlet"},
            "farfield": {"name": 42, "type": None},
        }
    )

    assert mapped["inlet"] == {"name": "air_in", "type": "mass-flow-inlet"}
    assert mapped["outlet"] == {"name": "pressure_outlet", "type": "pressure-outlet"}
    assert mapped["farfield"] == {"name": "farfield", "type": "wall"}
    assert mapped["object_wall"] == {"name": "object_wall", "type": "wall"}


@pytest.mark.parametrize(
    ("role", "boundary_type"),
    (
        ("inlet", "velocity-inlet"),
        ("inlet", "mass-flow-inlet"),
        ("inlet", "pressure-inlet"),
        ("outlet", "pressure-outlet"),
        ("outlet", "outflow"),
        ("farfield", "wall"),
        ("farfield", "pressure-far-field"),
        ("farfield", "symmetry"),
        ("object_wall", "wall"),
    ),
)
def test_map_boundary_roles_preserves_supported_reference_type(role: str, boundary_type: str) -> None:
    mapped = map_boundary_roles({role: {"type": boundary_type}})

    assert mapped[role]["type"] == boundary_type


def test_map_boundary_roles_falls_back_incompatible_types_to_role_standard() -> None:
    mapped = map_boundary_roles(
        {
            "inlet": {"type": "pressure-outlet"},
            "outlet": {"type": "velocity-inlet"},
            "farfield": {"type": "outflow"},
            "object_wall": {"type": "pressure-outlet"},
        }
    )

    assert {role: value["type"] for role, value in mapped.items()} == {
        "inlet": "velocity-inlet",
        "outlet": "pressure-outlet",
        "farfield": "wall",
        "object_wall": "wall",
    }


@pytest.mark.parametrize("boundary_type", (["velocity-inlet"], {"type": "velocity-inlet"}))
def test_map_boundary_roles_falls_back_non_string_reference_type(boundary_type: object) -> None:
    mapped = map_boundary_roles({"inlet": {"type": boundary_type}})

    assert mapped["inlet"]["type"] == "velocity-inlet"


def test_map_boundary_roles_falls_back_later_duplicate_name_and_keeps_names_unique() -> None:
    mapped = map_boundary_roles(
        {
            "inlet": {"name": "shared_boundary"},
            "outlet": {"name": "shared_boundary"},
            "farfield": {"name": "shared_boundary"},
        }
    )

    names = [value["name"] for value in mapped.values()]
    assert names == ["shared_boundary", "pressure_outlet", "farfield", "object_wall"]
    assert len(names) == len(set(names))


def test_map_boundary_roles_reserves_each_standard_name_for_its_role() -> None:
    mapped = map_boundary_roles(
        {
            "inlet": {"name": "pressure_outlet"},
            "outlet": {"name": "farfield"},
            "farfield": {"name": "object_wall"},
            "object_wall": {"name": "velocity_inlet"},
        }
    )

    names = [value["name"] for value in mapped.values()]
    assert names == ["velocity_inlet", "pressure_outlet", "farfield", "object_wall"]
    assert len(names) == len(set(names))


def _domain_profile() -> dict:
    return {
        "reference_characteristic_length": 0.1,
        "enclosure_shape": "cylinder",
        "clearance_ratios": {
            "upstream": 5.0,
            "downstream": 15.0,
            "left": 4.0,
            "right": 6.0,
            "top": 7.0,
            "bottom": 3.0,
        },
        "flow_direction": [3.0, 4.0, 0.0],
        "boundary_roles": {
            "inlet": {"name": "air_in", "type": "velocity-inlet"},
            "outlet": {"name": "air_out", "type": "pressure-outlet"},
        },
    }


def _task(reference: Path | None = None, *, enabled: bool = True, manual_flow_direction=None) -> SimulationTask:
    return SimulationTask(
        task_id="domain-reference-analysis",
        geometry={"type": "box", "parameters": {"length": 2.0, "width": 1.0, "height": 0.5}},
        domain={"upstream_length_ratio": 4.0, "downstream_length_ratio": 12.0, "side_length_ratio": 6.0},
        motion={"inlet_velocity": 10.0},
        domain_imitation={
            "enabled": enabled,
            "reference_file": str(reference) if reference else None,
            "manual_flow_direction": manual_flow_direction,
        },
    )


def _solidworks_info(tmp_path: Path) -> dict:
    return {"planned_step_file": str(tmp_path / "body.step")}


@pytest.fixture(autouse=True)
def _skip_real_foreground_wait(monkeypatch):
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.bring_process_to_foreground", lambda _pid: False)


def test_analyze_reference_domain_disabled_returns_successful_skip_with_four_paths(tmp_path: Path) -> None:
    result = analyze_reference_domain(_task(enabled=False), tmp_path)

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["enabled"] is False
    assert result["profile_file"].endswith("domain_reference_profile.json")
    assert result["scaled_settings_file"].endswith("scaled_domain_settings.json")
    assert result["comparison_file"].endswith("domain_imitation_comparison.json")
    assert result["log_file"].endswith("spaceclaim_reference_analysis.log")


def test_create_external_flow_domain_dry_run_keeps_default_domain_settings(tmp_path: Path) -> None:
    result = create_external_flow_domain(_task(enabled=False), _solidworks_info(tmp_path), str(tmp_path / "output"), dry_run=True)

    script = Path(result["spaceclaim_script"]).read_text(encoding="utf-8")
    named = json.loads(Path(result["named_selections_file"]).read_text(encoding="utf-8"))
    assert result["success"] is True
    assert "ENCLOSURE_SHAPE = 'box'" in script
    assert "'upstream': 8.0" in script
    assert "'downstream': 24.0" in script
    assert "'left': 12.0" in script
    assert "FLOW_DIRECTION = [1.0, 0.0, 0.0]" in script
    assert "BOUNDARY_NAMES = {'inlet': 'velocity_inlet'" in script
    assert named == {
        "velocity_inlet": {"type": "velocity-inlet"},
        "pressure_outlet": {"type": "pressure-outlet"},
        "farfield": {"type": "wall"},
        "object_wall": {"type": "wall"},
        "symmetry": {"type": "symmetry", "optional": True},
    }


def test_create_external_flow_domain_dry_run_applies_effective_domain_settings(tmp_path: Path) -> None:
    imitation = {
        "effective_domain_settings": {
            "enclosure_shape": "box",
            "flow_direction": [0.0, -1.0, 0.0],
            "clearances": {
                "upstream": 1.25,
                "downstream": 2.5,
                "left": 0.4,
                "right": 0.6,
                "top": 0.8,
                "bottom": 0.2,
            },
            "boundary_names": {
                "inlet": "ref_inlet",
                "outlet": "ref_outlet",
                "farfield": "ref_farfield",
                "object_wall": "ref_wall",
            },
            "boundary_types": {
                "inlet": "mass-flow-inlet",
                "outlet": "outflow",
                "farfield": "pressure-far-field",
                "object_wall": "wall",
            },
        }
    }

    result = create_external_flow_domain(
        _task(enabled=False),
        _solidworks_info(tmp_path),
        str(tmp_path / "output"),
        dry_run=True,
        imitation_info=imitation,
    )

    script = Path(result["spaceclaim_script"]).read_text(encoding="utf-8")
    named = json.loads(Path(result["named_selections_file"]).read_text(encoding="utf-8"))
    assert "ENCLOSURE_SHAPE = 'box'" in script
    assert "FLOW_DIRECTION = [0.0, -1.0, 0.0]" in script
    assert "CLEARANCES = {'upstream': 1.25, 'downstream': 2.5, 'left': 0.4, 'right': 0.6, 'top': 0.8, 'bottom': 0.2}" in script
    assert "BOUNDARY_NAMES = {'inlet': 'ref_inlet', 'outlet': 'ref_outlet', 'farfield': 'ref_farfield', 'object_wall': 'ref_wall'}" in script
    assert "_flow_axis_and_sign" in script
    assert "_classify_box_faces" in script
    assert named == {
        "ref_inlet": {"type": "mass-flow-inlet"},
        "ref_outlet": {"type": "outflow"},
        "ref_farfield": {"type": "pressure-far-field"},
        "ref_wall": {"type": "wall"},
        "symmetry": {"type": "symmetry", "optional": True},
    }


def test_create_external_flow_domain_deep_merges_partial_effective_domain_settings(tmp_path: Path) -> None:
    imitation = {
        "effective_domain_settings": {
            "flow_direction": [0.1, 3.0, 1.0],
            "clearances": {"upstream": 1.25},
            "boundary_names": {"inlet": "partial_inlet"},
            "boundary_types": {"inlet": "mass-flow-inlet"},
        }
    }

    result = create_external_flow_domain(
        _task(enabled=False),
        _solidworks_info(tmp_path),
        str(tmp_path / "output"),
        dry_run=True,
        imitation_info=imitation,
    )

    script = Path(result["spaceclaim_script"]).read_text(encoding="utf-8")
    named = json.loads(Path(result["named_selections_file"]).read_text(encoding="utf-8"))
    assert result["success"] is True
    assert "ENCLOSURE_SHAPE = 'box'" in script
    assert "FLOW_DIRECTION = [0.0, 1.0, 0.0]" in script
    assert "CLEARANCES = {'upstream': 1.25, 'downstream': 24.0, 'left': 12.0, 'right': 12.0, 'top': 12.0, 'bottom': 12.0}" in script
    assert "BOUNDARY_NAMES = {'inlet': 'partial_inlet', 'outlet': 'pressure_outlet', 'farfield': 'farfield', 'object_wall': 'object_wall'}" in script
    assert named == {
        "partial_inlet": {"type": "mass-flow-inlet"},
        "pressure_outlet": {"type": "pressure-outlet"},
        "farfield": {"type": "wall"},
        "object_wall": {"type": "wall"},
        "symmetry": {"type": "symmetry", "optional": True},
    }


def test_create_external_flow_domain_falls_back_for_malformed_partial_effective_domain_settings(tmp_path: Path) -> None:
    imitation = {
        "effective_domain_settings": {
            "enclosure_shape": "capsule",
            "clearances": ["not", "a", "mapping"],
            "boundary_names": "not-a-mapping",
            "boundary_types": None,
        }
    }

    result = create_external_flow_domain(
        _task(enabled=False),
        _solidworks_info(tmp_path),
        str(tmp_path / "output"),
        dry_run=True,
        imitation_info=imitation,
    )

    script = Path(result["spaceclaim_script"]).read_text(encoding="utf-8")
    named = json.loads(Path(result["named_selections_file"]).read_text(encoding="utf-8"))
    assert result["success"] is True
    assert "ENCLOSURE_SHAPE = 'box'" in script
    assert "CLEARANCES = {'upstream': 8.0, 'downstream': 24.0, 'left': 12.0, 'right': 12.0, 'top': 12.0, 'bottom': 12.0}" in script
    assert "BOUNDARY_NAMES = {'inlet': 'velocity_inlet', 'outlet': 'pressure_outlet', 'farfield': 'farfield', 'object_wall': 'object_wall'}" in script
    assert named == {
        "velocity_inlet": {"type": "velocity-inlet"},
        "pressure_outlet": {"type": "pressure-outlet"},
        "farfield": {"type": "wall"},
        "object_wall": {"type": "wall"},
        "symmetry": {"type": "symmetry", "optional": True},
    }


@pytest.mark.parametrize("direction", ([0, 0, 0], [1, 0], [1, 0, 0, 0], [float("inf"), 0, 0], [True, 0, 0]))
def test_create_external_flow_domain_rejects_invalid_effective_flow_direction(
    tmp_path: Path, direction: list[object]
) -> None:
    imitation = {"effective_domain_settings": {"flow_direction": direction}}

    with pytest.raises(ValueError, match="flow_direction"):
        create_external_flow_domain(
            _task(enabled=False),
            _solidworks_info(tmp_path),
            str(tmp_path / "output"),
            dry_run=True,
            imitation_info=imitation,
        )


def test_create_external_flow_domain_cylinder_settings_render_conservative_branch(tmp_path: Path) -> None:
    imitation = {
        "effective_domain_settings": {
            "enclosure_shape": "cylinder",
            "flow_direction": [0.0, 0.0, 1.0],
            "clearances": {"upstream": 1.0, "downstream": 3.0, "left": 0.5, "right": 0.5, "top": 0.5, "bottom": 0.5},
            "boundary_names": {"inlet": "cyl_in", "outlet": "cyl_out", "farfield": "cyl_far", "object_wall": "cyl_wall"},
            "boundary_types": {"inlet": "velocity-inlet", "outlet": "pressure-outlet", "farfield": "wall", "object_wall": "wall"},
        }
    }

    result = create_external_flow_domain(
        _task(enabled=False),
        _solidworks_info(tmp_path),
        str(tmp_path / "output"),
        dry_run=True,
        imitation_info=imitation,
    )

    script = Path(result["spaceclaim_script"]).read_text(encoding="utf-8")
    assert "ENCLOSURE_SHAPE = 'cylinder'" in script
    assert "_create_cylinder_enclosure" in script
    assert "_classify_cylinder_faces" in script
    assert "_is_cylindrical_face" in script
    assert "if ENCLOSURE_SHAPE == \"cylinder\"" in script
    assert "_validate_cylinder_named_selections(inlet, outlet, farfield, wall)" in script
    assert "Cylinder domain classification failed before export" in script
    assert "not inlet or not outlet or not farfield or not wall" in script
    guard_call = script.rindex("_validate_cylinder_named_selections(inlet, outlet, farfield, wall)")
    assert guard_call < script.index("_create_group(part, BOUNDARY_NAMES")
    assert guard_call < script.index("part.Export")
    assert "CylinderBody.Create" in script
    assert "Cylinder domain generation requires axis-aligned flow direction" in script
    assert "cyl_in" in script and "cyl_out" in script and "cyl_far" in script and "cyl_wall" in script


class _CompletedSpaceClaimDomain:
    pid = 12345
    returncode = 0

    def __init__(self, root: Path, stdout: str = "", stderr: str = "") -> None:
        self.root = root
        self.stdout = stdout
        self.stderr = stderr

    def communicate(self):
        (self.root / "fluid_domain.step").write_text("step", encoding="utf-8")
        (self.root / "fluid_domain.scdoc").write_text("scdoc", encoding="utf-8")
        return self.stdout, self.stderr


def test_create_external_flow_domain_rejects_zero_count_named_selection_after_spaceclaim_run(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "body.step"
    source.write_text("body", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    output = tmp_path / "output"
    root = output / "spaceclaim"
    stdout = "\n".join(
        [
            "imported_bodies=1",
            "boolean_subtract=ok tool_bodies=1",
            "named_selection:velocity_inlet count=1",
            "named_selection:pressure_outlet count=1",
            "named_selection:farfield count=1",
            "named_selection:object_wall count=0",
            "exported_step=True",
            "saved_scdoc=True",
        ]
    )
    process = _CompletedSpaceClaimDomain(root, stdout=stdout)
    monkeypatch.setenv("SPACECLAIM_ENABLED", "true")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.spaceclaim_tool.subprocess.Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr("cfd_agent.tools.spaceclaim_tool.bring_process_to_foreground", lambda _pid: False)

    result = create_external_flow_domain(_task(enabled=False), {"step_file": str(source)}, str(output))

    assert result["success"] is False
    assert "object_wall" in result["error"]
    assert result["spaceclaim_checks"]["named_selection_counts"]["object_wall"] == 0


def test_create_external_flow_domain_requires_scdoc_and_step_after_spaceclaim_run(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "body.step"
    source.write_text("body", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    output = tmp_path / "output"
    root = output / "spaceclaim"

    class StepOnlySpaceClaim(_CompletedSpaceClaimDomain):
        def communicate(self):
            (root / "fluid_domain.step").write_text("step", encoding="utf-8")
            return (
                "\n".join(
                    [
                        "named_selection:velocity_inlet count=1",
                        "named_selection:pressure_outlet count=1",
                        "named_selection:farfield count=1",
                        "named_selection:object_wall count=1",
                    ]
                ),
                "",
            )

    monkeypatch.setenv("SPACECLAIM_ENABLED", "true")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.spaceclaim_tool.subprocess.Popen", lambda *args, **kwargs: StepOnlySpaceClaim(root))
    monkeypatch.setattr("cfd_agent.tools.spaceclaim_tool.bring_process_to_foreground", lambda _pid: False)

    result = create_external_flow_domain(_task(enabled=False), {"step_file": str(source)}, str(output))

    assert result["success"] is False
    assert "fluid_domain.scdoc" in result["error"]
    assert result["spaceclaim_checks"]["output_files_ok"] is False


@pytest.mark.parametrize(
    ("name", "error_text"),
    (("missing.step", "not found"), ("reference.iges", "unsupported")),
)
def test_analyze_reference_domain_rejects_missing_or_unsupported_reference(
    tmp_path: Path, name: str, error_text: str
) -> None:
    reference = tmp_path / name
    if error_text == "unsupported":
        reference.write_text("reference", encoding="utf-8")

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert result["skipped"] is False
    assert error_text in result["error"]


def test_analyze_reference_domain_dry_run_writes_planned_box_profile_and_scaled_settings(tmp_path: Path) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")

    result = analyze_reference_domain(_task(reference, manual_flow_direction=[0, 2, 0]), tmp_path / "output", dry_run=True)

    assert result["success"] is True
    assert result["profile"]["enclosure_shape"] == "box"
    assert result["profile"]["flow_direction"] == [0.0, 1.0, 0.0]
    assert result["profile"]["clearance_ratios"] == {
        "upstream": 4.0,
        "downstream": 12.0,
        "left": 6.0,
        "right": 6.0,
        "top": 6.0,
        "bottom": 6.0,
    }
    assert result["effective_domain_settings"]["flow_direction"] == pytest.approx([0.0, 1.0, 0.0])
    assert result["effective_domain_settings"]["clearances"] == pytest.approx(
        {"upstream": 8.0, "downstream": 24.0, "left": 12.0, "right": 12.0, "top": 12.0, "bottom": 12.0}
    )
    assert Path(result["profile_file"]).is_file()
    assert Path(result["scaled_settings_file"]).is_file()
    assert Path(result["log_file"]).is_file()


class _CompletedSpaceClaim:
    def __init__(self, returncode: int = 0, stdout: str = "stdout", stderr: str = "stderr") -> None:
        self.pid = 4321
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.killed = False
        self.terminated = False

    def communicate(self, timeout=None):
        return self.stdout, self.stderr

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _launch_with_result(tmp_path: Path, payload: dict | str):
    def launch(*args, **kwargs):
        result_file = tmp_path / "output" / "domain_imitation" / "spaceclaim_reference_analysis_result.json"
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return _CompletedSpaceClaim()

    return launch


def _successful_analysis_profile(flow_direction=None) -> dict:
    return {
        "success": True,
        "reference_characteristic_length": 1.0,
        "enclosure_shape": "box",
        "clearance_ratios": {
            "upstream": 5.0,
            "downstream": 10.0,
            "left": 4.0,
            "right": 4.0,
            "top": 4.0,
            "bottom": 4.0,
        },
        "flow_direction": flow_direction,
        "boundary_roles": {},
        "warnings": [],
    }


def test_analyze_reference_domain_deletes_stale_result_before_launch(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    output = tmp_path / "output"
    stale_result = output / "domain_imitation" / "spaceclaim_reference_analysis_result.json"
    stale_result.parent.mkdir(parents=True, exist_ok=True)
    stale_result.write_text(json.dumps(_successful_analysis_profile([1.0, 0.0, 0.0])), encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", lambda *args, **kwargs: _CompletedSpaceClaim())

    result = analyze_reference_domain(_task(reference), output)

    assert result["success"] is False
    assert "did not produce result JSON" in result["error"]
    assert not stale_result.exists()


def test_analyze_reference_domain_reports_missing_spaceclaim_executable(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    monkeypatch.delenv("SPACECLAIM_EXECUTABLE", raising=False)

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "set SPACECLAIM_EXECUTABLE" in result["error"]


def test_analyze_reference_domain_reports_popen_exception(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("launch denied")),
    )

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "could not launch" in result["error"]
    assert "launch denied" in result["error"]


def test_analyze_reference_domain_reports_damaged_result_json(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", _launch_with_result(tmp_path, "{damaged"))

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "result JSON could not be read" in result["error"]


def test_analyze_reference_domain_preserves_spaceclaim_failure_detail(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.subprocess.Popen",
        _launch_with_result(tmp_path, {"success": False, "error": "no valid fluid-domain body"}),
    )

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert result["error"] == "no valid fluid-domain body"


@pytest.mark.parametrize(
    ("payload", "error_text"),
    (
        ({"success": "true", "warnings": []}, "success must be a boolean"),
        ({"success": True, "warnings": "not-a-list"}, "warnings must be a list"),
        (["not", "an", "object"], "result JSON must be an object"),
    ),
)
def test_analyze_reference_domain_rejects_invalid_result_schema(
    tmp_path: Path, monkeypatch, payload: object, error_text: str
) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.subprocess.Popen",
        _launch_with_result(tmp_path, json.dumps(payload)),
    )

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert error_text in result["error"]


def test_analyze_reference_domain_reports_process_failure_and_captures_log(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.scdoc"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", lambda *args, **kwargs: _CompletedSpaceClaim(7))

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "exit code 7" in result["error"]
    assert Path(result["log_file"]).read_text(encoding="utf-8") == "stdout\nstderr"


def test_analyze_reference_domain_reports_missing_result_file(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", lambda *args, **kwargs: _CompletedSpaceClaim())

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "did not produce result JSON" in result["error"]


def test_analyze_reference_domain_uses_manual_direction_only_when_result_direction_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    profile = _successful_analysis_profile()
    profile["warnings"] = ["Flow direction could not be detected."]
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", _launch_with_result(tmp_path, profile))

    result = analyze_reference_domain(_task(reference, manual_flow_direction=[0, 0, -3]), tmp_path / "output")

    assert result["success"] is True
    assert result["profile"]["flow_direction"] == [0.0, 0.0, -1.0]
    assert result["effective_domain_settings"]["flow_direction"] == pytest.approx([0.0, 0.0, -1.0])
    assert any("manual_flow_direction" in warning for warning in result["profile"]["warnings"])


def test_analyze_reference_domain_manual_fallback_uses_axis_aligned_direction_and_warning(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    profile = _successful_analysis_profile()
    profile["warnings"] = ["Flow direction could not be detected."]
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", _launch_with_result(tmp_path, profile))

    result = analyze_reference_domain(_task(reference, manual_flow_direction=[1, 3, 2]), tmp_path / "output")

    assert result["success"] is True
    assert result["profile"]["flow_direction"] == [0.0, 1.0, 0.0]
    assert result["effective_domain_settings"]["flow_direction"] == [0.0, 1.0, 0.0]
    assert any("axis-aligned" in warning for warning in result["profile"]["warnings"])


def test_analyze_reference_domain_manual_direction_does_not_override_detected_direction(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.subprocess.Popen",
        _launch_with_result(tmp_path, _successful_analysis_profile([1.0, 0.0, 0.0])),
    )

    result = analyze_reference_domain(_task(reference, manual_flow_direction=[0, 0, -3]), tmp_path / "output")

    assert result["success"] is True
    assert result["profile"]["flow_direction"] == [1.0, 0.0, 0.0]
    assert result["effective_domain_settings"]["flow_direction"] == [1.0, 0.0, 0.0]
    assert not any("manual_flow_direction" in warning for warning in result["profile"]["warnings"])


def test_analyze_reference_domain_detected_diagonal_direction_is_axis_aligned_before_scaling(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.subprocess.Popen",
        _launch_with_result(tmp_path, _successful_analysis_profile([1.0, -4.0, 2.0])),
    )

    result = analyze_reference_domain(_task(reference, manual_flow_direction=[1, 0, 0]), tmp_path / "output")

    assert result["success"] is True
    assert result["profile"]["flow_direction"] == [0.0, -1.0, 0.0]
    assert result["effective_domain_settings"]["flow_direction"] == [0.0, -1.0, 0.0]
    assert any("axis-aligned" in warning for warning in result["profile"]["warnings"])


def test_rendered_spaceclaim_analysis_receives_manual_direction_and_contains_conservative_analysis_contract(
    tmp_path: Path,
) -> None:
    script = tmp_path / "analyze.py"

    _render_analysis_script(tmp_path / "reference.step", tmp_path / "result.json", script, [0.0, -2.0, 0.0])

    rendered = script.read_text(encoding="utf-8")
    assert "MANUAL_FLOW_DIRECTION = [0.0, -2.0, 0.0]" in rendered
    assert "_face_members" in rendered
    assert "_select_fluid_domain_body" in rendered
    assert "_object_wall_faces_for_domain" in rendered
    assert "_detect_enclosure_shape" in rendered
    assert "_window_groups" in rendered
    assert "window.Groups" in rendered
    assert "GetAllGroups" in rendered
    assert "used manual flow direction" in rendered.lower()
    assert "standard boundary roles" in rendered.lower()
    assert "flow_direction = _axis_direction_from_direction(MANUAL_FLOW_DIRECTION)" in rendered
    assert "member in all_faces" in rendered
    assert "sorted(bodies, key=_bbox_volume, reverse=True)" in rendered
    assert "if len(ranked) > 1" not in rendered
    assert "face in domain_faces" in rendered
    assert "GetAncestor" in rendered or ".Parent" in rendered
    assert "object_wall faces do not belong" in rendered
    assert "len(outer_faces) == 6 and len(planar_outer_faces) == 6" in rendered
    assert "def _is_cylindrical_face" in rendered
    assert "def _is_planar_cap_face" in rendered
    assert "def _detect_enclosure_shape(domain_faces, domain_bounds, flow_axis, warnings)" in rendered
    assert "len(cylindrical_outer_faces) >= 1 and len(planar_cap_faces) == 2" in rendered
    assert "Detected cylinder enclosure" in rendered
    assert "Cylinder enclosure detection is not implemented" not in rendered


def test_rendered_spaceclaim_analysis_uses_python_none_when_manual_direction_is_absent(tmp_path: Path) -> None:
    script = tmp_path / "analyze.py"

    _render_analysis_script(tmp_path / "reference.step", tmp_path / "result.json", script)

    rendered = script.read_text(encoding="utf-8")
    assert "MANUAL_FLOW_DIRECTION = None" in rendered
    assert "MANUAL_FLOW_DIRECTION = null" not in rendered


def test_analyze_reference_domain_reports_timeout_and_kills_process(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    process = _CompletedSpaceClaim()
    calls = 0

    def communicate(timeout=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired("SpaceClaim.exe", timeout)
        return "after kill", ""

    process.communicate = communicate
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setenv("SPACECLAIM_ANALYSIS_TIMEOUT", "0.01")
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", lambda *args, **kwargs: process)

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert process.terminated is True
    assert process.killed is False


def test_analyze_reference_domain_timeout_terminates_then_kills_if_process_stays_alive(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    process = _CompletedSpaceClaim()
    calls = []

    def communicate(timeout=None):
        calls.append(timeout)
        if len(calls) <= 2:
            raise subprocess.TimeoutExpired("SpaceClaim.exe", timeout)
        return "after kill", ""

    process.communicate = communicate
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setenv("SPACECLAIM_ANALYSIS_TIMEOUT", "0.01")
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", lambda *args, **kwargs: process)

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert process.terminated is True
    assert process.killed is True
    assert calls[0] == 0.01
    assert calls[1] == 5
    assert calls[2] == 5


def test_analyze_reference_domain_timeout_returns_failure_when_kill_communicate_also_times_out(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    process = _CompletedSpaceClaim()
    calls = []

    def communicate(timeout=None):
        calls.append(timeout)
        raise subprocess.TimeoutExpired("SpaceClaim.exe", timeout)

    process.communicate = communicate
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setenv("SPACECLAIM_ANALYSIS_TIMEOUT", "0.01")
    monkeypatch.setattr("cfd_agent.tools.domain_imitation_tool.subprocess.Popen", lambda *args, **kwargs: process)

    result = analyze_reference_domain(_task(reference), tmp_path / "output")

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert process.terminated is True
    assert process.killed is True
    assert calls == [0.01, 5, 5]


def test_scale_domain_profile_scales_six_directions_and_normalizes_flow_direction() -> None:
    scaled = scale_domain_profile(_domain_profile(), new_characteristic_length=0.2)

    assert scaled["scale_ratio"] == 2.0
    effective = scaled["effective_domain_settings"]
    assert effective["enclosure_shape"] == "cylinder"
    assert effective["flow_direction"] == [0.0, 1.0, 0.0]
    assert effective["clearances"] == pytest.approx(
        {"upstream": 1.0, "downstream": 3.0, "left": 0.8, "right": 1.2, "top": 1.4, "bottom": 0.6}
    )
    assert effective["clearance_ratios"] == {
        "upstream": 5.0,
        "downstream": 15.0,
        "left": 4.0,
        "right": 6.0,
        "top": 7.0,
        "bottom": 3.0,
    }
    assert effective["boundary_names"] == {
        "inlet": "air_in",
        "outlet": "air_out",
        "farfield": "farfield",
        "object_wall": "object_wall",
    }
    assert effective["boundary_types"] == {
        "inlet": "velocity-inlet",
        "outlet": "pressure-outlet",
        "farfield": "wall",
        "object_wall": "wall",
    }
    assert scaled["warnings"] == ["Flow direction was not axis-aligned; using dominant axis direction [0.0, 1.0, 0.0]."]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("reference_characteristic_length", 0),
        ("reference_characteristic_length", -1),
        ("reference_characteristic_length", float("inf")),
        ("reference_characteristic_length", float("nan")),
        ("reference_characteristic_length", True),
        ("new_characteristic_length", 0),
        ("new_characteristic_length", -1),
        ("new_characteristic_length", float("inf")),
        ("new_characteristic_length", float("nan")),
        ("new_characteristic_length", True),
    ),
)
def test_scale_domain_profile_rejects_non_positive_or_non_finite_lengths(field: str, value: float) -> None:
    profile = _domain_profile()
    new_length = 0.2
    if field == "reference_characteristic_length":
        profile[field] = value
    else:
        new_length = value

    with pytest.raises(ValueError, match="finite positive"):
        scale_domain_profile(profile, new_characteristic_length=new_length)


@pytest.mark.parametrize("ratio", (0, -1, float("inf"), float("nan")))
def test_scale_domain_profile_rejects_invalid_directional_ratio(ratio: float) -> None:
    profile = _domain_profile()
    profile["clearance_ratios"]["top"] = ratio

    with pytest.raises(ValueError, match="six finite positive"):
        scale_domain_profile(profile, new_characteristic_length=0.2)


def test_scale_domain_profile_rejects_boolean_directional_ratio() -> None:
    profile = _domain_profile()
    profile["clearance_ratios"]["top"] = True

    with pytest.raises(ValueError, match="six finite positive"):
        scale_domain_profile(profile, new_characteristic_length=0.2)


def test_scale_domain_profile_requires_exactly_six_directional_ratios() -> None:
    profile = _domain_profile()
    del profile["clearance_ratios"]["bottom"]

    with pytest.raises(ValueError, match="six finite positive"):
        scale_domain_profile(profile, new_characteristic_length=0.2)


def test_scale_domain_profile_rejects_non_finite_derived_scale_ratio() -> None:
    profile = _domain_profile()
    profile["reference_characteristic_length"] = 5e-324

    with pytest.raises(ValueError, match="scale_ratio must be finite"):
        scale_domain_profile(profile, new_characteristic_length=__import__("sys").float_info.max)


def test_scale_domain_profile_rejects_non_finite_derived_absolute_clearance() -> None:
    maximum = __import__("sys").float_info.max
    profile = _domain_profile()
    profile["reference_characteristic_length"] = maximum

    with pytest.raises(ValueError, match="absolute clearances must be finite"):
        scale_domain_profile(profile, new_characteristic_length=maximum)


@pytest.mark.parametrize(
    "direction",
    ([0, 0, 0], [1, 0], [1, 0, 0, 0], [float("inf"), 0, 0], [float("nan"), 0, 0]),
)
def test_scale_domain_profile_rejects_invalid_flow_direction(direction: list[float]) -> None:
    profile = _domain_profile()
    profile["flow_direction"] = direction

    with pytest.raises(ValueError, match="three-dimensional finite non-zero"):
        scale_domain_profile(profile, new_characteristic_length=0.2)


def test_scale_domain_profile_rejects_boolean_flow_direction_component() -> None:
    profile = _domain_profile()
    profile["flow_direction"] = [True, 0, 0]

    with pytest.raises(ValueError, match="three-dimensional finite non-zero"):
        scale_domain_profile(profile, new_characteristic_length=0.2)


@pytest.mark.parametrize("magnitude", (1e308, 1e-308))
def test_scale_domain_profile_stably_normalizes_extreme_finite_flow_direction(magnitude: float) -> None:
    profile = _domain_profile()
    profile["flow_direction"] = [magnitude, magnitude, 0.0]

    scaled = scale_domain_profile(profile, new_characteristic_length=0.2)

    direction = scaled["effective_domain_settings"]["flow_direction"]
    assert direction == [1.0, 0.0, 0.0]
    assert all(__import__("math").isfinite(component) for component in direction)
    assert scaled["warnings"] == ["Flow direction was not axis-aligned; using dominant axis direction [1.0, 0.0, 0.0]."]


def test_scale_domain_profile_stably_normalizes_multiple_max_float_components() -> None:
    profile = _domain_profile()
    maximum = __import__("sys").float_info.max
    profile["flow_direction"] = [maximum, maximum, 0.0]

    scaled = scale_domain_profile(profile, new_characteristic_length=0.2)

    direction = scaled["effective_domain_settings"]["flow_direction"]
    assert direction == [1.0, 0.0, 0.0]
    assert all(__import__("math").isfinite(component) for component in direction)
    assert scaled["warnings"] == ["Flow direction was not axis-aligned; using dominant axis direction [1.0, 0.0, 0.0]."]


def test_scale_domain_profile_falls_back_unknown_shape_and_records_warning() -> None:
    profile = _domain_profile()
    profile["enclosure_shape"] = "capsule"

    scaled = scale_domain_profile(profile, new_characteristic_length=0.2)

    assert scaled["effective_domain_settings"]["enclosure_shape"] == "box"
    assert scaled["warnings"] == [
        "Unknown enclosure shape 'capsule'; using 'box'.",
        "Flow direction was not axis-aligned; using dominant axis direction [0.0, 1.0, 0.0].",
    ]


@pytest.mark.parametrize("shape", (["capsule"], {"kind": "capsule"}))
def test_scale_domain_profile_falls_back_unhashable_unknown_shape_and_records_warning(shape: object) -> None:
    profile = _domain_profile()
    profile["enclosure_shape"] = shape

    scaled = scale_domain_profile(profile, new_characteristic_length=0.2)

    assert scaled["effective_domain_settings"]["enclosure_shape"] == "box"
    assert scaled["warnings"] == [
        f"Unknown enclosure shape {shape!r}; using 'box'.",
        "Flow direction was not axis-aligned; using dominant axis direction [0.0, 1.0, 0.0].",
    ]


def test_write_domain_comparison_records_reference_requested_generated_and_warnings(tmp_path: Path) -> None:
    imitation = {
        "success": True,
        "skipped": False,
        "profile": {"reference_file": "reference.scdoc", "enclosure_shape": "cylinder"},
        "scaled_settings": {"scale_ratio": 2.0, "warnings": ["shape warning"]},
        "effective_domain_settings": {"enclosure_shape": "box", "clearances": {"upstream": 1.0}},
    }
    domain = {
        "scdoc_file": "fluid_domain.scdoc",
        "step_file": "fluid_domain.step",
        "named_selections_file": "named_selections.json",
    }

    path = write_domain_comparison(imitation, domain, tmp_path)

    assert path == tmp_path / "domain_imitation" / "domain_imitation_comparison.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "reference": {"reference_file": "reference.scdoc", "enclosure_shape": "cylinder"},
        "scale_ratio": 2.0,
        "requested_effective_settings": {"enclosure_shape": "box", "clearances": {"upstream": 1.0}},
        "generated": {
            "scdoc_file": "fluid_domain.scdoc",
            "step_file": "fluid_domain.step",
            "named_selections_file": "named_selections.json",
        },
        "warnings": ["shape warning"],
    }


@pytest.mark.parametrize("imitation", ({"skipped": True}, {"success": False}))
def test_write_domain_comparison_returns_none_for_skipped_or_failed(imitation: dict, tmp_path: Path) -> None:
    assert write_domain_comparison(imitation, {}, tmp_path) is None
    assert not (tmp_path / "domain_imitation" / "domain_imitation_comparison.json").exists()
