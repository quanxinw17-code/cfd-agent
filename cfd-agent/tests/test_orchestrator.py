from pathlib import Path
import json

from cfd_agent.core.models import DomainImitationConfig, GeometryConfig, MeshImitationConfig, MotionConfig, SimulationTask
from cfd_agent.core.orchestrator import STAGE_ORDER, run_simulation
from cfd_agent.core.state import WorkflowState


def _valid_task() -> SimulationTask:
    return SimulationTask(
        task_id="dry_run_test",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )


def test_dry_run_executes_end_to_end(tmp_path: Path) -> None:
    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True)
    assert result["status"] == "success"
    assert result["stage"] == "completed"
    assert (tmp_path / "report" / "report.md").exists()
    assert (tmp_path / "solidworks" / "create_model.py").exists()
    assert (tmp_path / "spaceclaim" / "create_external_domain.py").exists()
    assert (tmp_path / "meshing" / "fluent_meshing_watertight.jou").exists()
    assert (tmp_path / "fluent" / "fluent_setup.jou").exists()
    assert (tmp_path / "fluent" / "fluent_solve.jou").exists()


def test_invalid_input_fails(tmp_path: Path) -> None:
    task = SimulationTask(task_id="invalid", geometry=GeometryConfig(type="sphere", parameters={}), motion=MotionConfig(inlet_velocity=30.0))
    result = run_simulation(task, str(tmp_path), dry_run=True)
    assert result["status"] == "failed"
    assert result["errors"]


def test_output_directory_is_created(tmp_path: Path) -> None:
    output = tmp_path / "new_output"
    result = run_simulation(_valid_task(), str(output), dry_run=True)
    assert result["status"] == "success"
    assert output.exists()


def test_result_shape(tmp_path: Path) -> None:
    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True)
    for key in ["status", "stage", "files", "errors"]:
        assert key in result


def test_segmented_run_stops_at_solidworks(tmp_path: Path) -> None:
    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, to_stage="solidworks")
    assert result["status"] == "success"
    assert result["stage"] == "SOLIDWORKS_MODEL_CREATED"
    assert (tmp_path / "solidworks" / "create_model.py").exists()
    assert not (tmp_path / "spaceclaim" / "create_external_domain.py").exists()
    assert (tmp_path / "pipeline_state.json").exists()


def test_segmented_run_can_resume_from_spaceclaim(tmp_path: Path) -> None:
    first = run_simulation(_valid_task(), str(tmp_path), dry_run=True, to_stage="solidworks")
    assert first["status"] == "success"

    second = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage="spaceclaim", to_stage="meshing")
    assert second["status"] == "success"
    assert second["stage"] == "FLUENT_MESH_CREATED"
    assert (tmp_path / "spaceclaim" / "create_external_domain.py").exists()
    assert (tmp_path / "meshing" / "fluent_meshing_watertight.jou").exists()


def test_domain_imitation_stage_is_between_solidworks_and_spaceclaim() -> None:
    assert WorkflowState.DOMAIN_IMITATION_ANALYZED.value == "DOMAIN_IMITATION_ANALYZED"
    assert STAGE_ORDER == (
        "validate",
        "solidworks",
        "domain_imitation",
        "spaceclaim",
        "mesh_imitation",
        "meshing",
        "fluent_setup",
        "solver",
        "postprocess",
        "report",
    )


def test_domain_imitation_stage_can_stop_after_analysis(tmp_path: Path, monkeypatch) -> None:
    analysis = {
        "success": True,
        "skipped": False,
        "profile_file": str(tmp_path / "profile.json"),
        "scaled_settings_file": str(tmp_path / "scaled.json"),
        "comparison_file": None,
        "effective_domain_settings": {"enclosure_shape": "box"},
    }
    monkeypatch.setattr("cfd_agent.core.orchestrator.analyze_reference_domain", lambda *args, **kwargs: analysis)

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, to_stage="domain_imitation")

    assert result["status"] == "success"
    assert result["stage"] == "DOMAIN_IMITATION_ANALYZED"
    assert result["stage_outputs"]["domain_imitation"] is analysis
    assert result["files"]["domain_reference_profile"] == str(tmp_path / "profile.json")
    assert result["files"]["scaled_domain_settings"] == str(tmp_path / "scaled.json")
    assert not (tmp_path / "spaceclaim" / "create_external_domain.py").exists()


def test_domain_imitation_failure_stops_workflow_before_spaceclaim(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cfd_agent.core.orchestrator.analyze_reference_domain",
        lambda *args, **kwargs: {"success": False, "error": "reference domain invalid"},
    )

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True)

    assert result["status"] == "failed"
    assert result["stage"] == "FAILED"
    assert result["errors"] == ["reference domain invalid"]
    assert "spaceclaim" not in result["stage_outputs"]


def test_spaceclaim_receives_domain_imitation_info_and_records_comparison(tmp_path: Path, monkeypatch) -> None:
    calls = {}
    analysis = {
        "success": True,
        "skipped": False,
        "profile_file": str(tmp_path / "profile.json"),
        "scaled_settings_file": str(tmp_path / "scaled.json"),
        "effective_domain_settings": {"enclosure_shape": "box", "flow_direction": [0.0, 1.0, 0.0]},
    }
    domain = {
        "success": True,
        "spaceclaim_script": str(tmp_path / "create_external_domain.py"),
        "planned_step_file": str(tmp_path / "fluid_domain.step"),
        "named_selections_file": str(tmp_path / "named_selections.json"),
    }
    comparison = tmp_path / "domain_imitation_comparison.json"

    def fake_spaceclaim(task, solidworks_info, output_dir, dry_run=False, imitation_info=None):
        calls["imitation_info"] = imitation_info
        return domain

    def fake_comparison(imitation_info, domain_info, output):
        calls["comparison_args"] = (imitation_info, domain_info, output)
        comparison.write_text("{}", encoding="utf-8")
        return comparison

    monkeypatch.setattr("cfd_agent.core.orchestrator.analyze_reference_domain", lambda *args, **kwargs: analysis)
    monkeypatch.setattr("cfd_agent.core.orchestrator.create_external_flow_domain", fake_spaceclaim)
    monkeypatch.setattr("cfd_agent.core.orchestrator.write_domain_comparison", fake_comparison)

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, to_stage="spaceclaim")

    assert result["status"] == "success"
    assert calls["imitation_info"] is analysis
    assert calls["comparison_args"] == (analysis, domain, tmp_path)
    assert result["stage_outputs"]["domain_imitation"]["comparison_file"] == str(comparison)
    assert result["files"]["domain_imitation_comparison"] == str(comparison)


def test_resume_from_spaceclaim_uses_prior_domain_imitation_output(tmp_path: Path, monkeypatch) -> None:
    prior_imitation = {"success": True, "skipped": False, "effective_domain_settings": {"enclosure_shape": "box"}}
    state = {
        "stage_outputs": {
            "solidworks": {"success": True, "planned_step_file": str(tmp_path / "body.step")},
            "domain_imitation": prior_imitation,
        }
    }
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")
    calls = {}

    def fake_spaceclaim(task, solidworks_info, output_dir, dry_run=False, imitation_info=None):
        calls["imitation_info"] = imitation_info
        return {"success": True, "planned_step_file": str(tmp_path / "fluid.step")}

    monkeypatch.setattr("cfd_agent.core.orchestrator.create_external_flow_domain", fake_spaceclaim)
    monkeypatch.setattr("cfd_agent.core.orchestrator.write_domain_comparison", lambda *args, **kwargs: None)

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage="spaceclaim", to_stage="spaceclaim")

    assert result["status"] == "success"
    assert calls["imitation_info"] == prior_imitation


def test_resume_from_spaceclaim_uses_disabled_domain_imitation_default_when_missing(tmp_path: Path, monkeypatch) -> None:
    state = {"stage_outputs": {"solidworks": {"success": True, "planned_step_file": str(tmp_path / "body.step")}}}
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")
    calls = {}

    def fake_spaceclaim(task, solidworks_info, output_dir, dry_run=False, imitation_info=None):
        calls["imitation_info"] = imitation_info
        return {"success": True, "planned_step_file": str(tmp_path / "fluid.step")}

    monkeypatch.setattr("cfd_agent.core.orchestrator.create_external_flow_domain", fake_spaceclaim)

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage="spaceclaim", to_stage="spaceclaim")

    assert result["status"] == "success"
    assert calls["imitation_info"] == {"success": True, "skipped": True, "enabled": False, "effective_domain_settings": {}}


def test_resume_prunes_stage_outputs_from_rerun_stage_forward(tmp_path: Path, monkeypatch) -> None:
    prior_domain_imitation = {"success": True, "skipped": False, "effective_domain_settings": {"enclosure_shape": "box"}}
    state = {
        "stage_outputs": {
            "validate": {"success": True, "physics_summary": {"flow_regime": "laminar"}},
            "solidworks": {"success": True, "planned_step_file": str(tmp_path / "body.step")},
            "domain_imitation": prior_domain_imitation,
            "spaceclaim": {"success": True, "old": "spaceclaim"},
            "mesh_imitation": {"success": True, "old": "mesh_imitation"},
            "meshing": {"success": True, "old": "meshing"},
            "fluent_setup": {"success": True, "old": "fluent_setup"},
            "solver": {"success": True, "old": "solver"},
            "postprocess": {"success": True, "old": "postprocess"},
            "report": {"success": True, "old": "report"},
        }
    }
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")

    def fake_spaceclaim(task, solidworks_info, output_dir, dry_run=False, imitation_info=None):
        return {"success": True, "new": "spaceclaim", "planned_step_file": str(tmp_path / "new_fluid.step")}

    monkeypatch.setattr("cfd_agent.core.orchestrator.create_external_flow_domain", fake_spaceclaim)
    monkeypatch.setattr("cfd_agent.core.orchestrator.write_domain_comparison", lambda *args, **kwargs: None)

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage="spaceclaim", to_stage="spaceclaim")

    assert result["status"] == "success"
    assert result["stage_outputs"]["validate"] == state["stage_outputs"]["validate"]
    assert result["stage_outputs"]["solidworks"] == state["stage_outputs"]["solidworks"]
    assert result["stage_outputs"]["domain_imitation"] == prior_domain_imitation
    assert result["stage_outputs"]["spaceclaim"] == {"success": True, "new": "spaceclaim", "planned_step_file": str(tmp_path / "new_fluid.step")}
    for stale_stage in ("mesh_imitation", "meshing", "fluent_setup", "solver", "postprocess", "report"):
        assert stale_stage not in result["stage_outputs"]


def test_resume_from_spaceclaim_requires_prior_domain_imitation_when_enabled(tmp_path: Path, monkeypatch) -> None:
    state = {"stage_outputs": {"solidworks": {"success": True, "planned_step_file": str(tmp_path / "body.step")}}}
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")
    task = _valid_task().model_copy(update={"domain_imitation": DomainImitationConfig(enabled=True, reference_file="reference.step")})
    monkeypatch.setattr(
        "cfd_agent.core.orchestrator.create_external_flow_domain",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spaceclaim should not run")),
    )

    result = run_simulation(task, str(tmp_path), dry_run=True, from_stage="spaceclaim", to_stage="spaceclaim")

    assert result["status"] == "failed"
    assert "domain_imitation" in result["errors"][0]
    assert "from_stage='domain_imitation'" in result["errors"][0]


def test_resume_from_meshing_requires_prior_mesh_imitation_when_enabled(tmp_path: Path, monkeypatch) -> None:
    state = {
        "stage_outputs": {
            "solidworks": {"success": True, "planned_step_file": str(tmp_path / "body.step")},
            "spaceclaim": {"success": True, "planned_step_file": str(tmp_path / "fluid.step")},
        }
    }
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")
    task = _valid_task().model_copy(
        update={"mesh_imitation": MeshImitationConfig(enabled=True, reference_file="reference.msh.h5")}
    )
    monkeypatch.setattr(
        "cfd_agent.core.orchestrator.generate_mesh_with_fluent_meshing",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("meshing should not run")),
    )

    result = run_simulation(task, str(tmp_path), dry_run=True, from_stage="meshing", to_stage="meshing")

    assert result["status"] == "failed"
    assert "mesh_imitation" in result["errors"][0]
    assert "from_stage='mesh_imitation'" in result["errors"][0]


def test_meshing_failure_does_not_write_mesh_comparison(tmp_path: Path, monkeypatch) -> None:
    state = {
        "stage_outputs": {
            "solidworks": {"success": True, "planned_step_file": str(tmp_path / "body.step")},
            "spaceclaim": {"success": True, "planned_step_file": str(tmp_path / "fluid.step")},
            "mesh_imitation": {"success": True, "skipped": False, "effective_mesh_settings": {"global_size": 0.01}},
        }
    }
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(
        "cfd_agent.core.orchestrator.generate_mesh_with_fluent_meshing",
        lambda *args, **kwargs: {"success": False, "error": "mesh failed"},
    )
    monkeypatch.setattr(
        "cfd_agent.core.orchestrator.write_mesh_comparison",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("comparison should not be written")),
    )

    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage="meshing", to_stage="meshing")

    assert result["status"] == "failed"
    assert result["errors"] == ["mesh failed"]
    assert "mesh_imitation_comparison" not in result["files"]


def test_custom_cad_dry_run_imports_file_and_generates_spaceclaim_script(tmp_path: Path) -> None:
    source = tmp_path / "source.step"
    source.write_text("test STEP payload", encoding="utf-8")
    output = tmp_path / "output"
    task = SimulationTask(
        task_id="custom_cad_test",
        geometry=GeometryConfig(
            type="custom_cad",
            parameters={"characteristic_length": 0.25},
            cad_file=str(source),
        ),
        motion=MotionConfig(inlet_velocity=20.0),
    )

    result = run_simulation(task, str(output), dry_run=True, to_stage="spaceclaim")

    imported = output / "custom_cad" / "imported_geometry.step"
    assert result["status"] == "success"
    assert imported.read_text(encoding="utf-8") == "test STEP payload"
    assert result["files"]["geometry"] == str(imported)
    script = (output / "spaceclaim" / "create_external_domain.py").read_text(encoding="utf-8")
    assert str(imported.resolve()) in script


def test_each_stage_can_run_one_at_a_time(tmp_path: Path) -> None:
    stages = [
        "validate",
        "solidworks",
        "domain_imitation",
        "spaceclaim",
        "mesh_imitation",
        "meshing",
        "fluent_setup",
        "solver",
        "postprocess",
        "report",
    ]
    assert stages == list(STAGE_ORDER)

    for stage in stages:
        result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage=stage, to_stage=stage)
        assert result["status"] == "success", f"{stage}: {result['errors']}"

    assert result["stage"] == "completed"
    assert (tmp_path / "report" / "report.md").exists()


def test_mesh_imitation_stage_is_before_meshing() -> None:
    assert STAGE_ORDER.index("mesh_imitation") + 1 == STAGE_ORDER.index("meshing")


def test_mesh_imitation_stage_generates_scaled_settings_in_dry_run(tmp_path: Path) -> None:
    reference = tmp_path / "reference.msh.h5"
    reference.write_text("mesh", encoding="utf-8")
    task = _valid_task().model_copy(
        update={
            "mesh_imitation": MeshImitationConfig(
                enabled=True,
                reference_file=str(reference),
                reference_characteristic_length=0.05,
            )
        }
    )

    result = run_simulation(task, str(tmp_path / "output"), dry_run=True, to_stage="mesh_imitation")

    assert result["status"] == "success"
    assert result["stage_outputs"]["mesh_imitation"]["effective_mesh_settings"]["global_size"] == 0.005
    assert (tmp_path / "output" / "mesh_imitation" / "scaled_mesh_settings.json").exists()
