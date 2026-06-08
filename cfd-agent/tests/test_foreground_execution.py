from pathlib import Path

from cfd_agent.tools.process_ui import foreground_enabled
from cfd_agent.tools.domain_imitation_tool import analyze_reference_domain
from cfd_agent.tools.solver_tool import _build_fluent_command
from tests.test_domain_imitation_tool import _CompletedSpaceClaim, _task


def test_foreground_execution_is_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CFD_AGENT_FOREGROUND", raising=False)

    assert foreground_enabled() is True


def test_solver_command_is_visible_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CFD_AGENT_FOREGROUND", raising=False)

    command = _build_fluent_command("fluent.exe", tmp_path / "solve.jou", "4")

    assert "-g" not in command


def test_solver_command_can_be_headless_when_explicitly_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CFD_AGENT_FOREGROUND", "false")

    command = _build_fluent_command("fluent.exe", tmp_path / "solve.jou", "4")

    assert "-g" in command


def test_spaceclaim_reference_analysis_uses_popen_and_brings_process_to_foreground(monkeypatch, tmp_path: Path) -> None:
    reference = tmp_path / "reference.step"
    reference.write_text("reference", encoding="utf-8")
    executable = tmp_path / "SpaceClaim.exe"
    executable.write_text("", encoding="utf-8")
    process = _CompletedSpaceClaim(returncode=9)
    popen_calls = []
    foreground_calls = []
    monkeypatch.setenv("SPACECLAIM_EXECUTABLE", str(executable))
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.subprocess.Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)) or process,
    )
    monkeypatch.setattr(
        "cfd_agent.tools.domain_imitation_tool.bring_process_to_foreground",
        lambda pid: foreground_calls.append(pid),
    )

    analyze_reference_domain(_task(reference), tmp_path / "output")

    command = popen_calls[0][0][0]
    assert command[0] == str(executable)
    assert "/ScriptAPI=22" in command
    assert any(part.startswith("/RunScript=") for part in command)
    assert foreground_calls == [process.pid]
