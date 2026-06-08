# CFD Agent Environment

This project was validated on Windows with commercial CAD/CFD tools installed locally.

## Validated Machine Paths

```text
SpaceClaim: D:\Program Files\ANSYS Inc\v221\scdm\SpaceClaim.exe
Fluent:     D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe
Python:     py launcher, with pywin32 available for SolidWorks COM automation
```

SolidWorks was validated through COM automation with `win32com.client`.

## Required Environment Variables

For a real run:

```powershell
$env:SOLIDWORKS_ENABLED = "true"
$env:SPACECLAIM_ENABLED = "true"
$env:SPACECLAIM_EXECUTABLE = "D:\Program Files\ANSYS Inc\v221\scdm\SpaceClaim.exe"
$env:FLUENT_EXECUTABLE = "D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe"
$env:FLUENT_MESHING_ENABLED = "true"
$env:FLUENT_SOLVER_ENABLED = "true"
$env:CFD_AGENT_FOREGROUND = "true"
```

Fluent Meshing uses the ANSYS 2022 R1 Watertight Workflow through the pinned
`ansys-fluent-core==0.12.5` compatibility runner. The runner maps the 22.2
PyFluent data model to the installed 22.1 Fluent executable and directly
addresses the 22.1 task nodes.

For a dry run, omit the variables and pass `--dry-run`.

`CFD_AGENT_FOREGROUND=true` is the default. It keeps SolidWorks, SpaceClaim,
Fluent Meshing, and Fluent Solver visible while each real stage runs. Set it to
`false` only for unattended/headless execution.

Reference mesh imitation supports Fluent `msh`, `msh.h5`, `cas`, and `cas.h5`
files. Automatic wall bounding-box detection is strongest for HDF5 references.
Legacy non-HDF5 references may require a manually supplied reference
characteristic length.

Reference external-domain imitation supports SpaceClaim `scdoc` and STEP
reference fluid domains. SpaceClaim is launched visibly for real reference
analysis. The reference analyzer expects named face groups for inlet, outlet,
farfield, and object wall; STEP references may lose those names and require a
manual flow direction such as `1,0,0`.

Domain imitation outputs are written under:

```text
outputs/<case>/domain_imitation/
```

Expected files:

```text
domain_reference_profile.json
scaled_domain_settings.json
domain_imitation_comparison.json
spaceclaim_reference_analysis.log
```

If reference shape detection is ambiguous, the workflow records a warning and
uses a box enclosure with the recovered six clearance ratios.

## Custom CAD Files

Direct CAD import supports `.step`, `.stp`, `.x_t`, `.x_b`, and `.sldprt`.
SpaceClaim must be able to open the selected format. Use an absolute CAD path
and provide `geometry.parameters.characteristic_length` in meters.

## Local Web Entry

Run:

```powershell
.\CFD_Agent_Web.bat
```

Then open:

```text
http://127.0.0.1:8765/
```

The web UI can run the full chain or a segmented range such as `solidworks -> meshing` or `fluent_setup -> report`.

## Software Smoke Check

After configuring the executable paths in the web one-click deployment area,
run **Run software smoke check**. It performs minimal real startup checks for
SolidWorks, SpaceClaim, Fluent Meshing, and Fluent Solver, then writes:

```text
outputs/deployment_check/software_smoke_check.json
outputs/deployment_check/software_smoke_check.md
outputs/deployment_check/solidworks_smoke.log
outputs/deployment_check/spaceclaim_smoke.log
outputs/deployment_check/fluent_meshing_smoke.log
outputs/deployment_check/fluent_solver_smoke.log
```

This check confirms that the new machine can launch the external software
before running the full CFD pipeline.

## Validation Case

The validated sphere case is stored at:

```text
validated_cases/sphere_001/
```

It contains the input JSON, generated CAD/domain handoff files, mesh/case/data files, residual and force CSVs, and final report.
