# CFD Agent Report

## Task Summary

- Task ID: `sphere_external_flow_001`
- Status: `success`
- Stage: `POSTPROCESSED`
- Dry run: `False`

## Geometry Settings

- Type: `sphere`
- Unit: `m`
- Parameters: `{'diameter': 0.1}`

## SolidWorks Target Model

- Script: `outputs\sphere_001\solidworks\create_model.py`
- Native part: `outputs\sphere_001\solidworks\part.sldprt`
- STEP geometry: `outputs\sphere_001\solidworks\geometry.step`
- Parasolid: `outputs\sphere_001\solidworks\geometry.x_t`
- Metadata: `outputs\sphere_001\solidworks\geometry_metadata.json`

## SpaceClaim External Domain

- Script: `outputs\sphere_001\spaceclaim\create_external_domain.py`
- Fluid domain STEP: `outputs\sphere_001\spaceclaim\fluid_domain.step`
- Named selections: `outputs\sphere_001\spaceclaim\named_selections.json`

## Fluid Parameters

- Fluid: `air`
- Density: `1.225 kg/m^3`
- Viscosity: `1.789e-05 Pa.s`
- Temperature: `288.15 K`
- Pressure: `101325.0 Pa`

## Physics Summary

- Reynolds number: `205422`
- Mach number: `0.0882353`
- Flow regime: `turbulent`
- Compressibility: `incompressible`
- Recommended solver: `pressure_based`
- Recommended turbulence model: `k_omega_sst`

## Mesh Settings

- Meshing route: `Fluent Meshing Watertight Geometry Workflow`
- Journal: `outputs\sphere_001\meshing\fluent_meshing_watertight.jou`
- Mesh file: `outputs\sphere_001\meshing\mesh.msh.h5`
- Mesh case: `outputs\sphere_001\meshing\mesh_case.cas.h5`
- Quality report: `outputs\sphere_001\meshing\mesh_quality_report.json`
- Boundary layer enabled: `True`
- Layers: `15`
- Growth rate: `1.2`
- Target y+: `1.0`

## Fluent Settings

- Solver type: `pressure_based`
- Steady: `True`
- Turbulence model: `k_omega_sst`
- Residual target: `1e-05`
- Max iterations: `1000`

## Solver Status

Solver execution status is reflected in the workflow status and logs.

## Results Summary

- Drag coefficient: `None`
- Lift coefficient: `None`

## Files

- solidworks_script: `outputs\sphere_001\solidworks\create_model.py`
- solidworks_native: `outputs\sphere_001\solidworks\part.sldprt`
- geometry: `outputs\sphere_001\solidworks\geometry.step`
- parasolid: `outputs\sphere_001\solidworks\geometry.x_t`
- geometry_metadata: `outputs\sphere_001\solidworks\geometry_metadata.json`
- spaceclaim_script: `outputs\sphere_001\spaceclaim\create_external_domain.py`
- fluid_domain: `outputs\sphere_001\spaceclaim\fluid_domain.step`
- named_selections: `outputs\sphere_001\spaceclaim\named_selections.json`
- mesh: `outputs\sphere_001\meshing\mesh.msh.h5`
- mesh_case: `outputs\sphere_001\meshing\mesh_case.cas.h5`
- fluent_meshing_journal: `outputs\sphere_001\meshing\fluent_meshing_watertight.jou`
- mesh_quality_report: `outputs\sphere_001\meshing\mesh_quality_report.json`
- fluent_setup_journal: `outputs\sphere_001\fluent\fluent_setup.jou`
- fluent_solve_journal: `outputs\sphere_001\fluent\fluent_solve.jou`
- case: `outputs\sphere_001\fluent\case.cas.h5`
- data: `outputs\sphere_001\fluent\data.dat.h5`
- fluent_log: `outputs\sphere_001\fluent\fluent.log`
- residuals: `outputs\sphere_001\postprocess\residuals.csv`
- forces: `outputs\sphere_001\postprocess\forces.csv`
- pressure_contour: `None`
- velocity_contour: `None`


## Errors And Warnings

- None

## Limitations

This MVP automates workflow preparation and dry-run validation. It does not replace CFD engineering judgement, does not fabricate simulation results, and requires external tools such as CadQuery, Gmsh, and Fluent for real geometry, meshing, and solving.