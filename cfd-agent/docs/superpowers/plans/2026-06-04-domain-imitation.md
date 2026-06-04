# SpaceClaim External Domain Imitation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional foreground SpaceClaim analysis stage that reads a reference external fluid domain and rebuilds its enclosure shape, directional clearances, flow direction, and boundary naming around a new target CAD model.

**Architecture:** A new `domain_imitation_tool` owns reference validation, pure scaling logic, SpaceClaim analyzer launch, and comparison output. It produces an immutable `effective_domain_settings` dictionary consumed by the existing SpaceClaim generation tool, while the original `SimulationTask.domain` remains unchanged. The orchestrator inserts `domain_imitation` between geometry creation and SpaceClaim domain creation, and the web entry exposes the reference file and manual flow-direction fallback.

**Tech Stack:** Python 3.10+, Pydantic, Jinja2, SpaceClaim API V22/IronPython, pytest, local HTTP web entry

---

## File Structure

- Create `src/cfd_agent/tools/domain_imitation_tool.py`: validate, normalize, scale, launch reference analysis, and write comparison artifacts.
- Create `templates/spaceclaim_analyze_reference_domain.py.j2`: foreground SpaceClaim script that inspects bodies, named selections, bounding boxes, and boundary faces.
- Create `tests/test_domain_imitation_tool.py`: pure logic and dry-run behavior tests.
- Modify `src/cfd_agent/core/models.py`: add `DomainImitationConfig` to `SimulationTask`.
- Modify `src/cfd_agent/core/state.py`: add the domain-imitation workflow state.
- Modify `src/cfd_agent/core/orchestrator.py`: insert and checkpoint the optional stage, pass its effective settings into SpaceClaim, and write comparison output.
- Modify `src/cfd_agent/tools/spaceclaim_tool.py`: accept effective domain settings and render them into the generation template.
- Modify `templates/spaceclaim_external_domain.py.j2`: build the selected enclosure shape and use effective boundary names.
- Modify `src/cfd_agent/web_app.py`: expose controls, payload parsing, stage status, and artifacts.
- Modify `tests/test_orchestrator.py`: verify ordering, dry-run chaining, and stage resume behavior.
- Modify `tests/test_web_app.py`: verify UI payload and artifact discovery.
- Modify `README.md` and `ENVIRONMENT.md`: document use and foreground SpaceClaim requirements.

### Task 1: Add Domain Imitation Configuration And Validation

**Files:**
- Modify: `src/cfd_agent/core/models.py`
- Modify: `src/cfd_agent/core/validators.py`
- Create: `tests/test_domain_imitation_tool.py`
- Modify: `tests/test_validators.py`

- [ ] **Step 1: Write failing model and validator tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from cfd_agent.core.models import DomainImitationConfig
from cfd_agent.tools.domain_imitation_tool import supported_domain_reference_file


def test_supported_domain_reference_file_accepts_spaceclaim_and_step(tmp_path: Path) -> None:
    for name in ("fluid_domain.scdoc", "fluid_domain.step", "fluid_domain.stp"):
        assert supported_domain_reference_file(tmp_path / name)
    assert not supported_domain_reference_file(tmp_path / "fluid_domain.msh.h5")


def test_manual_flow_direction_rejects_zero_vector() -> None:
    with pytest.raises(ValidationError):
        DomainImitationConfig(enabled=True, reference_file="reference.step", manual_flow_direction=[0, 0, 0])
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_domain_imitation_tool.py tests/test_validators.py -v`

Expected: FAIL because `DomainImitationConfig` and `domain_imitation_tool` do not exist.

- [ ] **Step 3: Add the configuration model**

Add to `src/cfd_agent/core/models.py`:

```python
from pydantic import BaseModel, Field, field_validator


class DomainImitationConfig(BaseModel):
    enabled: bool = False
    reference_file: Optional[str] = None
    manual_flow_direction: Optional[List[float]] = None

    @field_validator("manual_flow_direction")
    @classmethod
    def validate_manual_flow_direction(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return None
        if len(value) != 3 or sum(float(component) ** 2 for component in value) <= 0:
            raise ValueError("manual_flow_direction must be a non-zero three-component vector")
        return [float(component) for component in value]
```

Add `domain_imitation: DomainImitationConfig = Field(default_factory=DomainImitationConfig)` to `SimulationTask`.

- [ ] **Step 4: Add reference-file validation**

Create the initial `src/cfd_agent/tools/domain_imitation_tool.py`:

```python
from pathlib import Path

SUPPORTED_DOMAIN_REFERENCE_SUFFIXES = (".scdoc", ".step", ".stp")


def supported_domain_reference_file(path: str | Path) -> bool:
    return str(path).lower().endswith(SUPPORTED_DOMAIN_REFERENCE_SUFFIXES)
```

Update `validate_simulation_task` so enabled imitation requires a reference file and only accepts supported suffixes.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_domain_imitation_tool.py tests/test_validators.py -v`

Expected: PASS.

```powershell
git add src/cfd_agent/core/models.py src/cfd_agent/core/validators.py src/cfd_agent/tools/domain_imitation_tool.py tests/test_domain_imitation_tool.py tests/test_validators.py
git commit -m "feat: add domain imitation configuration"
```

### Task 2: Implement Directional Clearance Scaling And Boundary Mapping

**Files:**
- Modify: `src/cfd_agent/tools/domain_imitation_tool.py`
- Modify: `tests/test_domain_imitation_tool.py`

- [ ] **Step 1: Write failing pure-logic tests**

```python
from cfd_agent.tools.domain_imitation_tool import map_boundary_roles, scale_domain_profile, write_domain_comparison


def test_scale_domain_profile_preserves_six_ratios() -> None:
    profile = {
        "reference_characteristic_length": 0.1,
        "enclosure_shape": "box",
        "clearance_ratios": {
            "upstream": 5.0, "downstream": 15.0,
            "left": 4.0, "right": 6.0, "top": 7.0, "bottom": 3.0,
        },
        "flow_direction": [1.0, 0.0, 0.0],
        "boundary_roles": {
            "inlet": {"name": "air_in", "type": "velocity-inlet"},
            "outlet": {"name": "air_out", "type": "pressure-outlet"},
        },
    }
    scaled = scale_domain_profile(profile, new_characteristic_length=0.2)
    assert scaled["scale_ratio"] == 2.0
    assert scaled["effective_domain_settings"]["clearances"]["downstream"] == 3.0
    assert scaled["effective_domain_settings"]["boundary_names"]["inlet"] == "air_in"


def test_map_boundary_roles_uses_standard_fallback_names() -> None:
    mapped = map_boundary_roles({})
    assert mapped["inlet"]["name"] == "velocity_inlet"
    assert mapped["object_wall"]["name"] == "object_wall"


def test_write_domain_comparison_records_generated_outputs(tmp_path: Path) -> None:
    imitation = {
        "success": True,
        "skipped": False,
        "profile": {"reference_file": "reference.scdoc", "enclosure_shape": "box"},
        "scaled_settings": {"scale_ratio": 2.0},
        "effective_domain_settings": {"enclosure_shape": "box", "clearances": {"upstream": 1.0}},
    }
    path = write_domain_comparison(imitation, {"step_file": "fluid_domain.step"}, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scale_ratio"] == 2.0
    assert payload["generated"]["step_file"] == "fluid_domain.step"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_domain_imitation_tool.py -v`

Expected: FAIL because scaling and mapping functions do not exist.

- [ ] **Step 3: Implement minimal pure logic**

Implement:

```python
STANDARD_BOUNDARIES = {
    "inlet": {"name": "velocity_inlet", "type": "velocity-inlet"},
    "outlet": {"name": "pressure_outlet", "type": "pressure-outlet"},
    "farfield": {"name": "farfield", "type": "wall"},
    "object_wall": {"name": "object_wall", "type": "wall"},
}


def map_boundary_roles(roles: dict) -> dict:
    return {
        role: {
            "name": roles.get(role, {}).get("name") or fallback["name"],
            "type": roles.get(role, {}).get("type") or fallback["type"],
        }
        for role, fallback in STANDARD_BOUNDARIES.items()
    }


def scale_domain_profile(profile: dict, new_characteristic_length: float) -> dict:
    reference_length = float(profile.get("reference_characteristic_length") or 0)
    if reference_length <= 0 or new_characteristic_length <= 0:
        raise ValueError("reference and new characteristic lengths must be greater than 0")
    ratios = profile.get("clearance_ratios") or {}
    required = {"upstream", "downstream", "left", "right", "top", "bottom"}
    if set(ratios) != required or any(float(ratios[name]) <= 0 for name in required):
        raise ValueError("six positive directional clearance ratios are required")
    ratio = float(new_characteristic_length) / reference_length
    return {
        "scale_ratio": ratio,
        "reference_characteristic_length": reference_length,
        "new_characteristic_length": float(new_characteristic_length),
        "effective_domain_settings": {
            "enclosure_shape": profile.get("enclosure_shape", "box"),
            "flow_direction": profile["flow_direction"],
            "clearances": {name: float(value) * float(new_characteristic_length) for name, value in ratios.items()},
            "clearance_ratios": {name: float(value) for name, value in ratios.items()},
            "boundary_names": {role: value["name"] for role, value in map_boundary_roles(profile.get("boundary_roles", {})).items()},
            "boundary_types": {role: value["type"] for role, value in map_boundary_roles(profile.get("boundary_roles", {})).items()},
        },
    }
```

- [ ] **Step 4: Implement comparison output**

Implement `write_domain_comparison(imitation_info, domain_info, output_dir)` in
`domain_imitation_tool.py`. Return `None` for skipped or failed imitation.
Otherwise write `domain_imitation_comparison.json` containing the reference
file and shape, scale ratio, requested effective settings, generated SCDOC and
STEP paths, generated named-selection path, and analyzer warnings.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_domain_imitation_tool.py -v`

Expected: PASS.

```powershell
git add src/cfd_agent/tools/domain_imitation_tool.py tests/test_domain_imitation_tool.py
git commit -m "feat: scale reference external domains"
```

### Task 3: Add Foreground SpaceClaim Reference Analyzer

**Files:**
- Create: `templates/spaceclaim_analyze_reference_domain.py.j2`
- Modify: `src/cfd_agent/tools/domain_imitation_tool.py`
- Modify: `tests/test_domain_imitation_tool.py`
- Modify: `tests/test_foreground_execution.py`

- [ ] **Step 1: Write failing dry-run and launch-contract tests**

```python
def test_dry_run_domain_analysis_writes_planned_profile(tmp_path: Path) -> None:
    reference = tmp_path / "fluid_domain.scdoc"
    reference.write_text("reference", encoding="utf-8")
    task = valid_task(domain_imitation={"enabled": True, "reference_file": str(reference), "manual_flow_direction": [1, 0, 0]})
    result = analyze_reference_domain(task, str(tmp_path / "out"), dry_run=True)
    assert result["success"] is True
    assert result["effective_domain_settings"]["flow_direction"] == [1.0, 0.0, 0.0]
    assert result["effective_domain_settings"]["clearance_ratios"]["upstream"] == task.domain.upstream_length_ratio
    assert (tmp_path / "out" / "domain_imitation" / "domain_reference_profile.json").exists()
```

Add a foreground test that mocks `subprocess.Popen` and asserts
`bring_process_to_foreground(process.pid)` is called.

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_domain_imitation_tool.py tests/test_foreground_execution.py -v`

Expected: FAIL because `analyze_reference_domain` and its analyzer template do not exist.

- [ ] **Step 3: Implement the analyzer template**

The generated SpaceClaim script must:

1. Open `.scdoc` with `Document.Open` or import STEP with `ImportOptions.Create`.
2. Enumerate root-part bodies and choose the largest body bounding box as the fluid domain.
3. Enumerate groups and map recognized names to inlet, outlet, farfield, and object wall.
4. Calculate the enclosure bounding box and object-wall face bounding box.
5. Derive flow direction from inlet and outlet face centers; use the configured manual vector when either group is unavailable.
6. Calculate upstream, downstream, left, right, top, and bottom clearances in the flow-aligned basis.
7. Classify a six-planar-face enclosure as `box`; classify an axial curved enclosure as `cylinder`; otherwise record `box` with `unsupported_shape_box_fallback`.
8. Write `spaceclaim_reference_analysis_result.json` with `success`, profile fields, warnings, and an actionable `error`.

- [ ] **Step 4: Implement analyzer orchestration**

Add `analyze_reference_domain(task, output_dir, dry_run=False)` mirroring
`analyze_reference_mesh`:

```python
def analyze_reference_domain(task: SimulationTask, output_dir: str, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "domain_imitation")
    profile_file = root / "domain_reference_profile.json"
    scaled_file = root / "scaled_domain_settings.json"
    comparison_file = root / "domain_imitation_comparison.json"
    log_file = root / "spaceclaim_reference_analysis.log"
    # Validate, render the analyzer script, launch SpaceClaim visibly, read the
    # result JSON, apply manual direction only when required, scale, and write
    # profile/scaled artifacts.
```

Use the same SpaceClaim executable resolution and visible-process behavior as
`create_external_flow_domain`. Return `skipped=True` when disabled and preserve
the four artifact paths in every result. In dry-run, create a planned box
profile from `task.domain`: upstream and downstream use their dedicated ratios,
and left, right, top, and bottom use `side_length_ratio`; use the manual flow
direction when provided and `[1.0, 0.0, 0.0]` otherwise.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_domain_imitation_tool.py tests/test_foreground_execution.py -v`

Expected: PASS.

```powershell
git add templates/spaceclaim_analyze_reference_domain.py.j2 src/cfd_agent/tools/domain_imitation_tool.py tests/test_domain_imitation_tool.py tests/test_foreground_execution.py
git commit -m "feat: analyze reference domains with SpaceClaim"
```

### Task 4: Apply Effective Domain Settings During SpaceClaim Generation

**Files:**
- Modify: `src/cfd_agent/tools/spaceclaim_tool.py`
- Modify: `templates/spaceclaim_external_domain.py.j2`
- Modify: `tests/test_domain_imitation_tool.py`

- [ ] **Step 1: Write failing rendering tests**

```python
def test_spaceclaim_script_uses_effective_domain_settings(tmp_path: Path) -> None:
    imitation_info = {
        "effective_domain_settings": {
            "enclosure_shape": "box",
            "flow_direction": [1.0, 0.0, 0.0],
            "clearances": {"upstream": 0.5, "downstream": 1.5, "left": 0.4, "right": 0.6, "top": 0.7, "bottom": 0.3},
            "boundary_names": {"inlet": "air_in", "outlet": "air_out", "farfield": "outer", "object_wall": "vehicle"},
        }
    }
    result = create_external_flow_domain(valid_task(), valid_geometry_info(tmp_path), str(tmp_path / "out"), dry_run=True, imitation_info=imitation_info)
    script = Path(result["spaceclaim_script"]).read_text(encoding="utf-8")
    assert 'INLET_NAME = "air_in"' in script
    assert "UPSTREAM_CLEARANCE = 0.5" in script
```

- [ ] **Step 2: Run test and verify it fails**

Run: `pytest tests/test_domain_imitation_tool.py::test_spaceclaim_script_uses_effective_domain_settings -v`

Expected: FAIL because `create_external_flow_domain` does not accept `imitation_info`.

- [ ] **Step 3: Pass effective settings into the template**

Change the tool signature to:

```python
def create_external_flow_domain(
    task: SimulationTask,
    solidworks_info: dict,
    output_dir: str,
    dry_run: bool = False,
    imitation_info: dict | None = None,
) -> dict:
```

Build default effective settings from the current domain ratios, then overlay
`imitation_info["effective_domain_settings"]`. Pass this dictionary to the
template as `domain_settings`.

- [ ] **Step 4: Update the generation template**

Replace fixed X/Y/Z ratios with explicit effective clearances and boundary
names. Keep the current box path for `enclosure_shape == "box"`. Add the
SpaceClaim V22 cylinder-body creation path for `enclosure_shape == "cylinder"`,
aligned to `flow_direction`. Classify faces in the same flow-aligned coordinate
basis used by the analyzer and create groups using the effective names.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_domain_imitation_tool.py tests/test_foreground_execution.py -v`

Expected: PASS.

```powershell
git add src/cfd_agent/tools/spaceclaim_tool.py templates/spaceclaim_external_domain.py.j2 tests/test_domain_imitation_tool.py
git commit -m "feat: rebuild imitated SpaceClaim domains"
```

### Task 5: Insert Domain Imitation Into The Orchestrator

**Files:**
- Modify: `src/cfd_agent/core/state.py`
- Modify: `src/cfd_agent/core/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing stage-order and chaining tests**

```python
def test_domain_imitation_stage_is_before_spaceclaim() -> None:
    assert STAGE_ORDER.index("domain_imitation") + 1 == STAGE_ORDER.index("spaceclaim")


def test_domain_imitation_dry_run_chains_into_spaceclaim(tmp_path: Path) -> None:
    reference = tmp_path / "reference.scdoc"
    reference.write_text("reference", encoding="utf-8")
    task = _valid_task().model_copy(update={
        "domain_imitation": DomainImitationConfig(
            enabled=True,
            reference_file=str(reference),
            manual_flow_direction=[1, 0, 0],
        )
    })
    result = run_simulation(task, str(tmp_path / "out"), dry_run=True, to_stage="spaceclaim")
    assert result["status"] == "success"
    assert result["stage_outputs"]["domain_imitation"]["effective_domain_settings"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_orchestrator.py -v`

Expected: FAIL because the stage is not registered.

- [ ] **Step 3: Add orchestration and checkpointing**

Add `DOMAIN_IMITATION_ANALYZED` to `WorkflowState`. Change stage order to:

```python
STAGE_ORDER = (
    "validate", "solidworks", "domain_imitation", "spaceclaim",
    "mesh_imitation", "meshing", "fluent_setup", "solver",
    "postprocess", "report",
)
```

After SolidWorks, call `analyze_reference_domain`; fail on unsuccessful
analysis; checkpoint the new state; then pass `domain_imitation_info` to
`create_external_flow_domain`. After SpaceClaim succeeds, call
`write_domain_comparison` and expose the profile, scaled settings, comparison,
and analysis log in `files`.

- [ ] **Step 4: Run orchestrator tests and commit**

Run: `pytest tests/test_orchestrator.py -v`

Expected: PASS, including each-stage and resume tests.

```powershell
git add src/cfd_agent/core/state.py src/cfd_agent/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrate external domain imitation"
```

### Task 6: Add Web Controls And Artifact Discovery

**Files:**
- Modify: `src/cfd_agent/web_app.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write failing web tests**

```python
def test_domain_imitation_stage_is_available_in_web_entry() -> None:
    assert "domain_imitation" in STAGES
    assert "browsePath('domain', 'referenceDomainFile', this)" in INDEX_HTML


def test_task_from_payload_adds_domain_imitation_configuration(tmp_path: Path) -> None:
    reference = tmp_path / "fluid_domain.scdoc"
    reference.write_text("reference", encoding="utf-8")
    task = _task_from_payload({
        **valid_payload(tmp_path),
        "domain_imitation_enabled": True,
        "reference_domain_file": str(reference),
        "manual_flow_direction": "1,0,0",
    })
    assert task.domain_imitation.enabled is True
    assert task.domain_imitation.manual_flow_direction == [1.0, 0.0, 0.0]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_web_app.py -v`

Expected: FAIL because the stage and payload fields are absent.

- [ ] **Step 3: Add UI and payload parsing**

Add the stage between SolidWorks and SpaceClaim. Add an enable checkbox,
reference-domain file picker, and manual flow-direction input. Extend the
existing browse endpoint with a `domain` mode accepting `.scdoc`, `.step`, and
`.stp`. Parse comma-separated manual direction into three floats and pass a
`DomainImitationConfig` to the task.

- [ ] **Step 4: Add artifact discovery**

Add:

```python
output_dir / "domain_imitation" / "domain_reference_profile.json"
output_dir / "domain_imitation" / "scaled_domain_settings.json"
output_dir / "domain_imitation" / "domain_imitation_comparison.json"
output_dir / "domain_imitation" / "spaceclaim_reference_analysis.log"
```

- [ ] **Step 5: Run web tests and commit**

Run: `pytest tests/test_web_app.py -v`

Expected: PASS.

```powershell
git add src/cfd_agent/web_app.py tests/test_web_app.py
git commit -m "feat: expose external domain imitation in web app"
```

### Task 7: Document And Verify The Complete Feature

**Files:**
- Modify: `README.md`
- Modify: `ENVIRONMENT.md`
- Create during validation: `outputs/domain_imitation_validation/domain_imitation/*`
- Create during validation: `outputs/domain_imitation_validation/spaceclaim/*`

- [ ] **Step 1: Document operation and failure recovery**

Document the step-by-step and full-auto use paths, supported reference formats,
foreground SpaceClaim requirement, manual flow-direction format, output
artifacts, STEP named-selection limitation, and box fallback for unsupported
shapes.

- [ ] **Step 2: Run the complete automated test suite**

Run: `pytest -q`

Expected: all tests pass.

Run: `python -m compileall src scripts`

Expected: compilation succeeds without errors.

- [ ] **Step 3: Run dry-run full-pipeline validation**

Run a domain-imitation task from `validate` through `report` with `--dry-run`.

Expected: `pipeline_state.json` contains successful `domain_imitation`,
`spaceclaim`, `mesh_imitation`, and later stage outputs, with no missing prior
stage errors.

- [ ] **Step 4: Run real foreground sphere validation**

Use the existing validated sphere `fluid_domain.scdoc` as reference and a
different-diameter target sphere. Run through `domain_imitation` and
`spaceclaim` with `SPACECLAIM_ENABLED=true` and
`CFD_AGENT_FOREGROUND=true`.

Expected:

- SpaceClaim opens visibly for reference analysis and target-domain creation.
- `domain_reference_profile.json` identifies box shape, flow direction, named
  boundary roles, and six positive ratios.
- `scaled_domain_settings.json` contains the correct characteristic-length
  scale ratio.
- `fluid_domain.scdoc`, `fluid_domain.step`, and `named_selections.json` exist.
- `domain_imitation_comparison.json` reports achieved clearances and preserved
  or fallback boundary names.

- [ ] **Step 5: Verify the generated domain enters Fluent Meshing**

Run native Fluent Meshing on the generated target domain.

Expected: geometry imports, boundary zones are present, and a volume mesh is
generated without changing the external-domain imitation artifacts.

- [ ] **Step 6: Verify the local web entry**

Restart the web server, open `http://127.0.0.1:8765/`, and verify with the
in-app browser that the new controls render, reference browsing works, the
stage can run independently, and all four artifacts appear.

- [ ] **Step 7: Commit documentation and validation metadata**

```powershell
git add README.md ENVIRONMENT.md
git commit -m "docs: document external domain imitation"
```

Do not commit large generated CAD, mesh, case, or data files unless the user
explicitly requests them.
