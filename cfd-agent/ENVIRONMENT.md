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
$env:FLUENT_SOLVER_ENABLED = "true"
$env:CFD_AGENT_GMSH_FALLBACK = "true"
```

`FLUENT_MESHING_ENABLED` is optional. The validated route uses a Gmsh-generated tetra volume mesh converted by Fluent to `.msh.h5` and `.cas.h5` because Fluent Meshing Watertight automation was unstable in ANSYS 2022 R1.

For a dry run, omit the variables and pass `--dry-run`.

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

## Validation Case

The validated sphere case is stored at:

```text
validation_cases/sphere_001/
```

It contains the input JSON, generated CAD/domain handoff files, mesh/case/data files, residual and force CSVs, and final report.
