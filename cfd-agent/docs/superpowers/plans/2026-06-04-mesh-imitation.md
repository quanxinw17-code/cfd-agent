# Reference Mesh Imitation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native-Fluent reference mesh analysis stage that scales reusable mesh controls by characteristic length and applies them to a new Fluent Meshing run.

**Architecture:** A focused `mesh_imitation_tool` owns validation, profile normalization, scaling, output files, and comparison. A standalone PyFluent runner reads reference mesh/case files in visible Fluent and returns structured measurements. The orchestrator inserts an optional `mesh_imitation` stage before meshing, while the web app supplies reference-file inputs and exposes generated artifacts.

**Tech Stack:** Python 3.11, Pydantic, PyFluent 0.12.5, Fluent 2022 R1, pytest, local HTML/JavaScript web entry.

---

### Task 1: Configuration And Scaling Core

**Files:**
- Modify: `src/cfd_agent/core/models.py`
- Modify: `src/cfd_agent/core/validators.py`
- Create: `src/cfd_agent/tools/mesh_imitation_tool.py`
- Create: `tests/test_mesh_imitation_tool.py`
- Modify: `tests/test_validators.py`

- [ ] Write failing tests for reference configuration, scale-ratio calculation, dimensioned-value scaling, and manual characteristic-length fallback.
- [ ] Run `py -m pytest -q tests/test_mesh_imitation_tool.py tests/test_validators.py` and confirm failures describe missing mesh-imitation behavior.
- [ ] Add `MeshImitationConfig`, validation, profile normalization, and scaled-settings generation.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Fluent Reference Analysis Runner

**Files:**
- Create: `scripts/analyze_fluent_reference_mesh.py`
- Modify: `src/cfd_agent/tools/mesh_imitation_tool.py`
- Modify: `tests/test_mesh_imitation_tool.py`

- [ ] Write failing tests for supported reference extensions, command/config generation, dry-run outputs, and result handling.
- [ ] Run the focused test and confirm expected failures.
- [ ] Implement a foreground PyFluent runner that reads mesh/case files, finds `object_wall`, extracts vertices for a bounding box, runs mesh-size and quality reports, and writes structured JSON.
- [ ] Implement tool orchestration and the four required output artifacts.
- [ ] Re-run focused tests.

### Task 3: Pipeline And Native Meshing Application

**Files:**
- Modify: `src/cfd_agent/core/orchestrator.py`
- Modify: `src/cfd_agent/tools/fluent_meshing_tool.py`
- Modify: `scripts/run_fluent_meshing_221.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_fluent_meshing_tool.py`

- [ ] Write failing tests for optional stage ordering, segmented execution, and effective mesh settings passed to Fluent Meshing.
- [ ] Run focused tests and confirm failures.
- [ ] Insert `mesh_imitation`, persist its stage output, pass effective settings into meshing, and write the post-mesh comparison.
- [ ] Apply supported scaled surface-size and boundary-layer settings in the native Fluent workflow.
- [ ] Re-run focused tests.

### Task 4: Web Entry

**Files:**
- Modify: `src/cfd_agent/web_app.py`
- Modify: `tests/test_web_app.py`

- [ ] Write failing tests for the reference-file picker, payload conversion, stage listing, and artifact discovery.
- [ ] Run focused tests and confirm failures.
- [ ] Add the enable switch, file picker, automatic/manual length inputs, payload handling, and artifact links.
- [ ] Re-run focused tests.

### Task 5: Verification

**Files:**
- Modify: `README.md`
- Modify: `ENVIRONMENT.md`

- [ ] Document reference mesh imitation inputs, outputs, foreground behavior, and limitations.
- [ ] Run `py -m pytest -q`.
- [ ] Run `py -m compileall -q src scripts`.
- [ ] Run `git diff --check`.
- [ ] Restart `http://127.0.0.1:8765/` and verify the page and API.
- [ ] Run the existing sphere reference through Fluent analysis and verify generated profile/scaled/comparison artifacts.
