from pathlib import Path

from cfd_agent.tools.deployment_tool import (
    build_env_payload,
    deployment_check,
    load_project_env,
    parse_env_file,
    software_smoke_check,
    write_project_env,
)


def test_parse_env_file_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n# comment\nSPACECLAIM_ENABLED=true\nFLUENT_EXECUTABLE=D:/Fluent/fluent.exe\n",
        encoding="utf-8",
    )

    assert parse_env_file(env_file) == {
        "SPACECLAIM_ENABLED": "true",
        "FLUENT_EXECUTABLE": "D:/Fluent/fluent.exe",
    }


def test_write_project_env_writes_expected_keys(tmp_path: Path) -> None:
    env_file = write_project_env(
        {
            "spaceclaim_executable": "D:/ANSYS/scdm/SpaceClaim.exe",
            "fluent_executable": "D:/ANSYS/fluent.exe",
            "foreground": True,
            "solidworks_enabled": True,
            "spaceclaim_enabled": True,
            "fluent_meshing_enabled": True,
            "fluent_solver_enabled": False,
        },
        tmp_path,
    )

    values = parse_env_file(env_file)

    assert values["SPACECLAIM_EXECUTABLE"] == str(Path("D:/ANSYS/scdm/SpaceClaim.exe"))
    assert values["FLUENT_EXECUTABLE"] == str(Path("D:/ANSYS/fluent.exe"))
    assert values["CFD_AGENT_FOREGROUND"] == "true"
    assert values["FLUENT_SOLVER_ENABLED"] == "false"


def test_load_project_env_sets_missing_values_without_overwriting(tmp_path: Path, monkeypatch) -> None:
    write_project_env({"spaceclaim_executable": "D:/SpaceClaim.exe", "fluent_executable": "D:/fluent.exe"}, tmp_path)
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", "manual.exe")

    loaded = load_project_env(tmp_path)

    assert loaded["SPACECLAIM_EXECUTABLE"] == "manual.exe"
    assert loaded["FLUENT_EXECUTABLE"] == str(Path("D:/fluent.exe"))


def test_build_env_payload_prefers_explicit_values(tmp_path: Path) -> None:
    spaceclaim = tmp_path / "SpaceClaim.exe"
    fluent = tmp_path / "fluent.exe"
    spaceclaim.write_text("", encoding="utf-8")
    fluent.write_text("", encoding="utf-8")

    payload = build_env_payload(
        {
            "spaceclaim_executable": str(spaceclaim),
            "fluent_executable": str(fluent),
            "foreground": False,
        }
    )

    assert payload["SPACECLAIM_EXECUTABLE"] == str(spaceclaim.resolve())
    assert payload["FLUENT_EXECUTABLE"] == str(fluent.resolve())
    assert payload["CFD_AGENT_FOREGROUND"] == "false"


def test_deployment_check_reports_existing_configured_paths(tmp_path: Path) -> None:
    spaceclaim = tmp_path / "SpaceClaim.exe"
    fluent = tmp_path / "fluent.exe"
    spaceclaim.write_text("", encoding="utf-8")
    fluent.write_text("", encoding="utf-8")
    write_project_env({"spaceclaim_executable": str(spaceclaim), "fluent_executable": str(fluent)}, tmp_path)

    report = deployment_check(tmp_path)

    assert report["checks"]["spaceclaim"]["ok"] is True
    assert report["checks"]["fluent"]["ok"] is True
    assert (tmp_path / "outputs" / "deployment_check" / "environment_check.json").exists()
    assert (tmp_path / "outputs" / "deployment_check" / "environment_check.md").exists()


def test_software_smoke_check_writes_reports_and_logs_for_missing_tools(tmp_path: Path) -> None:
    write_project_env(
        {
            "spaceclaim_executable": str(tmp_path / "missing_spaceclaim.exe"),
            "fluent_executable": str(tmp_path / "missing_fluent.exe"),
            "solidworks_enabled": True,
        },
        tmp_path,
    )

    report = software_smoke_check(tmp_path, timeout=1)

    assert report["checks"]["spaceclaim"]["ok"] is False
    assert report["checks"]["fluent_meshing"]["ok"] is False
    assert report["checks"]["fluent_solver"]["ok"] is False
    assert (tmp_path / "outputs" / "deployment_check" / "software_smoke_check.json").exists()
    assert (tmp_path / "outputs" / "deployment_check" / "software_smoke_check.md").exists()
    assert (tmp_path / "outputs" / "deployment_check" / "spaceclaim_smoke.log").exists()
    assert (tmp_path / "outputs" / "deployment_check" / "fluent_meshing_smoke.log").exists()
    assert (tmp_path / "outputs" / "deployment_check" / "fluent_solver_smoke.log").exists()


def test_software_smoke_check_runs_configured_executables(tmp_path: Path, monkeypatch) -> None:
    spaceclaim = tmp_path / "SpaceClaim.exe"
    fluent = tmp_path / "fluent.exe"
    spaceclaim.write_text("", encoding="utf-8")
    fluent.write_text("", encoding="utf-8")
    write_project_env({"spaceclaim_executable": str(spaceclaim), "fluent_executable": str(fluent)}, tmp_path)
    calls = []

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        marker = kwargs["cwd"] / "spaceclaim_smoke_marker.txt"
        if "SpaceClaim" in str(command[0]):
            marker.write_text("ok", encoding="utf-8")
        return Completed()

    monkeypatch.setattr("cfd_agent.tools.deployment_tool.subprocess.run", fake_run)
    monkeypatch.setattr("cfd_agent.tools.deployment_tool._solidworks_smoke_check", lambda output, timeout: {"ok": True, "message": "COM OK", "log_file": str(output / "solidworks_smoke.log")})

    report = software_smoke_check(tmp_path, timeout=3)

    assert report["ok"] is True
    assert report["checks"]["spaceclaim"]["ok"] is True
    assert report["checks"]["fluent_meshing"]["ok"] is True
    assert report["checks"]["fluent_solver"]["ok"] is True
    assert any("-meshing" in command for command in calls)
    assert any("-r" in command for command in calls)
