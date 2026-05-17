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
$env:FLUENT_SOLVER_ENABLED = "true"
$env:CFD_AGENT_GMSH_FALLBACK = "true"

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
validate, solidworks, spaceclaim, meshing, fluent_setup, solver, postprocess, report
```

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
- The validated ANSYS 2022 R1 route uses a Gmsh tetra volume mesh converted by Fluent to `.msh.h5` and `.cas.h5`; Fluent Meshing Watertight automation remains version-sensitive.
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
