from pathlib import Path

from cfd_agent.web_app import (
    INDEX_HTML,
    STAGES,
    _collect_artifacts,
    _deployment_payload_from_form,
    _parse_manual_flow_direction,
    _task_from_payload,
)


def test_web_page_has_output_and_cad_browse_buttons() -> None:
    assert "browsePath('directory', 'output', this)" in INDEX_HTML
    assert "browsePath('cad', 'cadFile', this)" in INDEX_HTML
    assert "browsePath('mesh', 'referenceMeshFile', this)" in INDEX_HTML
    assert "browsePath('domain', 'referenceDomainFile', this)" in INDEX_HTML
    assert 'id="meshImitationEnabled"' in INDEX_HTML
    assert 'id="domainImitationEnabled"' in INDEX_HTML
    assert 'id="oneClickDeployEnabled"' in INDEX_HTML
    assert "runDeploymentCheck()" in INDEX_HTML
    assert "saveDeploymentConfig()" in INDEX_HTML
    assert "runSoftwareSmokeCheck()" in INDEX_HTML
    assert "runDiagnostics()" in INDEX_HTML
    assert "/api/diagnose" in INDEX_HTML
    assert "refreshCases()" in INDEX_HTML
    assert "createCase()" in INDEX_HTML
    assert "/api/cases" in INDEX_HTML
    assert "/api/cases/create" in INDEX_HTML
    assert "parameterTaskPayload()" in INDEX_HTML
    assert "previewParameterTask()" in INDEX_HTML
    assert "saveParameterTask()" in INDEX_HTML
    assert "loadParameterTask()" in INDEX_HTML
    assert "/api/task/preview" in INDEX_HTML
    assert "/api/task/save" in INDEX_HTML
    assert "/api/task/load" in INDEX_HTML


def test_deployment_payload_from_form_maps_web_fields() -> None:
    payload = _deployment_payload_from_form(
        {
            "deploy_spaceclaim_executable": "D:/ANSYS/SpaceClaim.exe",
            "deploy_fluent_executable": "D:/ANSYS/fluent.exe",
            "deploy_foreground": False,
            "deploy_solidworks_enabled": True,
            "deploy_spaceclaim_enabled": True,
            "deploy_fluent_meshing_enabled": True,
            "deploy_fluent_solver_enabled": False,
        }
    )

    assert payload == {
        "spaceclaim_executable": "D:/ANSYS/SpaceClaim.exe",
        "fluent_executable": "D:/ANSYS/fluent.exe",
        "foreground": False,
        "solidworks_enabled": True,
        "spaceclaim_enabled": True,
        "fluent_meshing_enabled": True,
        "fluent_solver_enabled": False,
    }


def test_collect_artifacts_supports_absolute_output_outside_root(tmp_path: Path) -> None:
    report = tmp_path / "report" / "report.md"
    report.parent.mkdir()
    report.write_text("report", encoding="utf-8")

    artifacts = _collect_artifacts(tmp_path)

    assert artifacts[0]["path"] == str(report.resolve())
    assert artifacts[0]["url"].startswith("/files?path=")


def test_mesh_imitation_stage_is_available_in_web_entry() -> None:
    assert "mesh_imitation" in STAGES


def test_domain_imitation_stage_is_available_in_web_entry() -> None:
    assert STAGES.index("domain_imitation") + 1 == STAGES.index("spaceclaim")


def test_collect_artifacts_includes_mesh_imitation_outputs(tmp_path: Path) -> None:
    profile = tmp_path / "mesh_imitation" / "mesh_reference_profile.json"
    profile.parent.mkdir()
    profile.write_text("{}", encoding="utf-8")

    artifacts = _collect_artifacts(tmp_path)

    assert any(artifact["name"] == "mesh_reference_profile.json" for artifact in artifacts)


def test_collect_artifacts_includes_domain_imitation_outputs(tmp_path: Path) -> None:
    profile = tmp_path / "domain_imitation" / "domain_reference_profile.json"
    scaled = tmp_path / "domain_imitation" / "scaled_domain_settings.json"
    comparison = tmp_path / "domain_imitation" / "domain_imitation_comparison.json"
    log = tmp_path / "domain_imitation" / "spaceclaim_reference_analysis.log"
    profile.parent.mkdir()
    for file in (profile, scaled, comparison, log):
        file.write_text("{}", encoding="utf-8")

    artifacts = _collect_artifacts(tmp_path)
    names = {artifact["name"] for artifact in artifacts}

    assert {
        "domain_reference_profile.json",
        "scaled_domain_settings.json",
        "domain_imitation_comparison.json",
        "spaceclaim_reference_analysis.log",
    }.issubset(names)


def test_task_from_payload_adds_reference_mesh_configuration(tmp_path: Path) -> None:
    reference = tmp_path / "reference.msh.h5"
    reference.write_text("mesh", encoding="utf-8")

    task = _task_from_payload(
        {
            "description": "",
            "input": "examples/sphere_external_flow.json",
            "mesh_imitation_enabled": True,
            "reference_mesh_file": str(reference),
            "reference_characteristic_length": "0.1",
        }
    )

    assert task.mesh_imitation.enabled is True
    assert task.mesh_imitation.reference_file == str(reference.resolve())
    assert task.mesh_imitation.reference_characteristic_length == 0.1


def test_task_from_payload_adds_reference_domain_configuration(tmp_path: Path) -> None:
    reference = tmp_path / "fluid_domain.scdoc"
    reference.write_text("spaceclaim", encoding="utf-8")

    task = _task_from_payload(
        {
            "description": "",
            "input": "examples/sphere_external_flow.json",
            "domain_imitation_enabled": True,
            "reference_domain_file": str(reference),
            "manual_flow_direction": "1, 0, 0",
        }
    )

    assert task.domain_imitation.enabled is True
    assert task.domain_imitation.reference_file == str(reference.resolve())
    assert task.domain_imitation.manual_flow_direction == [1.0, 0.0, 0.0]


def test_parse_manual_flow_direction_accepts_empty_or_three_numbers() -> None:
    assert _parse_manual_flow_direction("") is None
    assert _parse_manual_flow_direction("0, 1, 0") == [0.0, 1.0, 0.0]


def test_parse_manual_flow_direction_rejects_invalid_text() -> None:
    try:
        _parse_manual_flow_direction("1,0")
    except ValueError as exc:
        assert "manual_flow_direction" in str(exc)
    else:
        raise AssertionError("expected invalid manual flow direction to fail")
