# CFD Agent

CFD Agent automates a validated external-flow CFD workflow for simple bodies, with both CLI and local web entry points.

The current validated chain is:

```text
SimulationTask JSON
-> SolidWorks target-body model
-> SpaceClaim external fluid domain
-> Fluent-readable volume mesh/case
-> Fluent Solver
-> postprocess CSVs
-> Markdown report
```

## Quick Start

Install Python dependencies:

```powershell
py -m pip install -r requirements.txt
```

Run the local web entry:

```powershell
.\CFD_Agent_Web.bat
```

Open:

```text
http://127.0.0.1:8765/
```

The web page can run the full workflow or a segmented range such as `solidworks -> meshing` or `fluent_setup -> report`.

## GitHub Pages Entry

The repository includes a first-version static website under `docs/`.
After pushing to GitHub, enable Pages with:

```text
Settings -> Pages -> Deploy from a branch -> /docs
```

The public entry will be:

```text
https://quanxinw17-code.github.io/cfd-agent/
```

GitHub Pages is only a download and startup guide. The Agent itself still runs
locally at:

```text
http://127.0.0.1:8765/
```

The primary web input is a natural-language task description. Example:

```text
分析一个直径 0.1 米的球体外流场，入口速度 30 m/s，攻角 0 度
```

Select **解析任务** to preview the structured task before starting. The
advanced JSON input remains available when exact configuration or repeatable
case files are required.

Use the folder button beside the output path to select an existing output
directory. Use the file button beside the custom CAD path to select a STEP,
Parasolid, or SolidWorks part file.

## One-Click Deployment Check

The web entry includes a one-click deployment area for moving the agent to a
new Windows workstation. Use **Check environment** first to verify Python,
required packages, and configured executable paths. Then use **Run software
smoke check** to start the configured tools with minimal scripts:

- SolidWorks COM startup
- SpaceClaim foreground script execution
- Fluent Meshing startup journal
- Fluent Solver startup journal

Smoke-check reports are written to:

```text
outputs/deployment_check/software_smoke_check.json
outputs/deployment_check/software_smoke_check.md
outputs/deployment_check/*_smoke.log
```

The web entry provides three execution modes:

- **Full automatic run**: runs all stages from validation through report.
- **Run selected range**: runs the selected start and end stages.
- **Run one stage at a time**: runs each stage separately and resumes from
  `pipeline_state.json` in the same output directory.

For one-stage execution, run the stages in order and keep the input and output
paths unchanged between steps.

## External Domain Imitation

The web entry can imitate a validated SpaceClaim external-flow fluid domain.
Enable **External domain imitation**, select a reference `fluid_domain.scdoc`,
`.step`, or `.stp` file, and run either the single `domain_imitation` stage or
the full workflow. The stage runs before SpaceClaim domain creation.

The analyzer opens SpaceClaim in the foreground when `CFD_AGENT_FOREGROUND=true`
and writes:

```text
outputs/<case>/domain_imitation/domain_reference_profile.json
outputs/<case>/domain_imitation/scaled_domain_settings.json
outputs/<case>/domain_imitation/domain_imitation_comparison.json
outputs/<case>/domain_imitation/spaceclaim_reference_analysis.log
```

The reference should contain named face groups for inlet, outlet, farfield, and
object wall. Valid reference names and boundary types are preserved. Missing or
unrecognized values fall back to the standard names:

```text
velocity_inlet, pressure_outlet, farfield, object_wall
```

If inlet/outlet direction cannot be detected, enter a manual flow direction in
the web UI as comma-separated components, for example `1,0,0`. STEP files may
not preserve SpaceClaim named selections reliably, so they often need this
manual fallback.

The first version supports rectangular box and conservatively detected cylinder
enclosures. Unsupported or ambiguous shapes fall back to a box with the same
six clearance ratios and a warning in the profile.

## CLI Usage

Dry run:

```powershell
$env:PYTHONPATH = "src"
py -m cfd_agent.main run --input examples\sphere_external_flow.json --output outputs\sphere_001 --dry-run
```

Real run on the validated machine:

```powershell
$env:PYTHONPATH = "src"
$env:SOLIDWORKS_ENABLED = "true"
$env:SPACECLAIM_ENABLED = "true"
$env:SPACECLAIM_EXECUTABLE = "D:\Program Files\ANSYS Inc\v221\scdm\SpaceClaim.exe"
$env:FLUENT_EXECUTABLE = "D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe"
$env:FLUENT_MESHING_ENABLED = "true"
$env:FLUENT_SOLVER_ENABLED = "true"
$env:CFD_AGENT_FOREGROUND = "true"

## Reference mesh imitation

The web entry can imitate an existing Fluent `msh`, `msh.h5`, `cas`, or
`cas.h5` reference. Enable **Reference mesh imitation**, select the reference
file, and leave the reference characteristic length empty for automatic
`object_wall` detection. Length-based mesh controls are scaled by the ratio
between the new and reference characteristic lengths.

Outputs are written under `outputs/<case>/mesh_imitation/`:

- `mesh_reference_profile.json`
- `scaled_mesh_settings.json`
- `mesh_imitation_comparison.json`
- `fluent_reference_analysis.log`

For Fluent 2022 R1, the field-data service may not expose surface vertices. In
that case the analyzer uses Fluent HDF5 zone connectivity to identify the
smallest wall-zone bounding box and records the fallback in the profile.

py -m cfd_agent.main run --input examples\sphere_external_flow.json --output outputs\sphere_001 --json
```

Segmented run:

```powershell
py -m cfd_agent.main run --input examples\sphere_external_flow.json --output outputs\sphere_001 --to-stage solidworks
py -m cfd_agent.main run --input examples\sphere_external_flow.json --output outputs\sphere_001 --from-stage spaceclaim --to-stage meshing
py -m cfd_agent.main run --input examples\sphere_external_flow.json --output outputs\sphere_001 --from-stage fluent_setup
```

Supported stages:

```text
validate, solidworks, domain_imitation, spaceclaim, mesh_imitation, meshing, fluent_setup, solver, postprocess, report
```

## Custom CAD Import

Custom external-flow bodies can be imported directly from `.step`, `.stp`,
`.x_t`, `.x_b`, or `.sldprt` files. The geometry stage copies the source CAD
into the task output and skips SolidWorks model generation.

Use `examples/custom_cad_external_flow.json` and set:

```json
"geometry": {
  "type": "custom_cad",
  "unit": "m",
  "parameters": {
    "characteristic_length": 0.1
  },
  "cad_file": "D:/models/body.step"
}
```

`characteristic_length` controls enclosure sizing and Reynolds-number
calculation. In the web entry, a CAD path and characteristic length can
override the geometry in the selected input JSON.

## Validated Case

A successful real-run case is preserved in:

```text
validated_cases/sphere_001/
```

It includes:

```text
input/sphere_external_flow.json
solidworks/geometry.step
solidworks/geometry.x_t
solidworks/part.SLDPRT
spaceclaim/fluid_domain.scdoc
spaceclaim/fluid_domain.step
meshing/mesh.msh.h5
meshing/mesh_case.cas.h5
fluent/case.cas.h5
fluent/case.dat.h5
fluent/data.dat.h5
postprocess/residuals.csv
postprocess/forces.csv
report/report.md
```

## Important Notes

- `case.dat.h5` is generated alongside `case.cas.h5` because Fluent GUI expects the paired data filename when opening the case interactively.
- The ANSYS 2022 R1 route uses Fluent Meshing Watertight Workflow directly.
- Meshing succeeds only after mesh/case files, workflow task states, named
  boundaries, boundary layers, cell count, and quality limits are verified.
- The included sphere run is a pipeline validation case, not a mesh-independent production CFD result.

## Development

Run tests:

```powershell
$env:PYTHONPATH = "src"
py -m pytest -q
```

## Project Layout

```text
cfd-agent/
  README.md
  ENVIRONMENT.md
  requirements.txt
  .env.example
  prompts/
  configs/
  src/
  templates/
  examples/
  validated_cases/
```

Machine setup and environment variables are documented in:

```text
ENVIRONMENT.md
```
