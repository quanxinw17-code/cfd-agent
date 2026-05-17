# Validation Case: sphere_001

This case validates the automated external-flow workflow for a sphere with diameter `0.1 m`.

## Route

```text
SimulationTask JSON
-> SolidWorks sphere model
-> STEP / Parasolid export
-> SpaceClaim external fluid domain
-> Fluent-readable volume mesh/case
-> Fluent Solver
-> residuals.csv / forces.csv / report.md
```

## Key Outputs

```text
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

`case.dat.h5` is intentionally included because Fluent GUI looks for a paired `case.dat.h5` when opening `case.cas.h5`.

## Solver Snapshot

- Solver: Fluent 2022 R1
- Model: k-omega SST
- Inlet velocity: `30 m/s`
- Material: air, density `1.225 kg/m^3`, viscosity about `1.789e-5 Pa.s`
- Iterations: `20`
- Drag X total from the successful run: see `postprocess/forces.csv`
- Lift Y total from the successful run: see `postprocess/forces.csv`

This is a pipeline validation case, not a mesh-independent production CFD result.
