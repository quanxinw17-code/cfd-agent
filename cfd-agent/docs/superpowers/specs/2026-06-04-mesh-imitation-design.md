# Fluent Reference Mesh Imitation Design

## Goal

Add an optional reference-mesh imitation stage to CFD Agent. The user selects an
existing Fluent `msh`, `msh.h5`, `cas`, or `cas.h5` file. Fluent opens visibly,
analyzes the reference mesh, estimates the characteristic length of
`object_wall`, and creates a reusable mesh profile. CFD Agent then scales
length-based mesh controls by the ratio between the new and reference
characteristic lengths before generating the new mesh.

The feature imitates mesh density and boundary-layer strategy. It does not copy
cells or topology from the reference geometry.

## User Experience

The local web entry adds:

- A `Reference mesh imitation` enable switch.
- A reference Fluent mesh/case file picker.
- A read-only analysis preview showing detected boundaries, reference
  characteristic length, cell count, quality, and recovered mesh controls.
- A manual reference characteristic-length input that appears only when
  automatic detection fails.

The feature works in both execution styles:

- Step-by-step: run `Mesh imitation` after `SpaceClaim` and before `Meshing`.
- Full automatic: analyze, scale, mesh, and compare without stopping when
  automatic detection succeeds.

All real Fluent analysis and meshing runs use the existing foreground execution
setting. Dry-run generates plans and paths but does not launch Fluent.

## Pipeline

The stage order becomes:

```text
validate
solidworks
spaceclaim
mesh_imitation (optional)
meshing
fluent_setup
solver
postprocess
report
```

When imitation is disabled, `mesh_imitation` records a successful skipped result
and the existing mesh settings remain unchanged.

When imitation is enabled:

1. Validate the reference file extension and existence.
2. Launch Fluent in the foreground and read the reference mesh or case.
3. Inspect zones and locate `object_wall`.
4. Estimate reference characteristic length from the `object_wall` bounding box.
5. Extract mesh statistics and recover supported mesh-control values.
6. Calculate the new geometry characteristic length using the existing physics
   helper.
7. Compute `scale_ratio = new_characteristic_length /
   reference_characteristic_length`.
8. Scale length-based controls and pass the resulting effective settings to
   Fluent Meshing.
9. Generate the new mesh and write a comparison report.

## Data Model

Add an optional configuration object to `SimulationTask`:

```json
{
  "mesh_imitation": {
    "enabled": true,
    "reference_file": "D:/reference/reference.msh.h5",
    "reference_characteristic_length": null,
    "scale_mode": "characteristic_length"
  }
}
```

`reference_characteristic_length` is a fallback supplied by the user only when
automatic `object_wall` detection or bounding-box estimation fails.

The original task mesh settings remain unchanged. The imitation stage produces
effective mesh settings for the meshing stage, preserving the original input
for auditability.

## Reference Profile

The analysis output is saved as:

```text
outputs/<case>/mesh_imitation/
  mesh_reference_profile.json
  scaled_mesh_settings.json
  mesh_imitation_comparison.json
  fluent_reference_analysis.log
```

`mesh_reference_profile.json` contains:

- Reference file path and Fluent version.
- Boundary and cell-zone names and types.
- Detected `object_wall` bounding box.
- Reference characteristic length and detection method.
- Cell count.
- Minimum orthogonal quality and maximum skewness when available.
- Estimated global surface size and near-wall size when available.
- Boundary-layer layer count, first-layer height, total thickness, and growth
  rate when available.
- Warnings for values Fluent could not recover reliably.

`scaled_mesh_settings.json` contains the effective controls used for the new
mesh and the scale ratio.

## Scaling Rules

Scale these length-based values by `scale_ratio` when the reference profile
provides them:

- `global_size`
- `near_body_size`
- `first_layer_height`
- Boundary-layer total thickness
- Any supported local size or curvature/proximity minimum length

Copy these dimensionless values without scaling:

- Boundary-layer enabled state
- Layer count
- Growth rate
- Target quality limits

The new geometry's existing explicit mesh values take precedence only when the
reference profile lacks a corresponding value. This makes imitation the active
strategy while retaining safe fallbacks.

## Fluent Analysis

Use a dedicated Python/PyFluent runner rather than parsing HDF5 internals
directly. This avoids coupling the Agent to Fluent's private file layout and
supports both mesh and case inputs.

The runner:

- Opens Fluent with `show_gui=True` when `CFD_AGENT_FOREGROUND=true`.
- Reads the selected reference file using Fluent.
- Queries mesh size, zones, bounding box, quality, and supported mesh metrics.
- Writes structured JSON and a transcript.
- Exits Fluent after analysis.

Mesh controls that cannot be reconstructed from the final mesh are marked as
estimated or unavailable. The Agent must not claim an unavailable value was
exactly recovered.

## Failure Handling

The imitation stage fails before new meshing when:

- The reference file does not exist or has an unsupported extension.
- Fluent cannot read the reference file.
- `object_wall` cannot be detected and no manual reference length is supplied.
- The reference characteristic length is zero or invalid.
- No usable mesh-density or boundary-layer information can be extracted.

The web UI displays the actionable error and preserves analysis logs. Automatic
execution may resume after the user supplies a manual reference characteristic
length and reruns the imitation stage.

Warnings do not block execution when sufficient fallback settings exist. For
example, missing first-layer height may fall back to the task's existing
`target_y_plus` strategy.

## Comparison And Acceptance

After new meshing, `mesh_imitation_comparison.json` compares:

- Reference and generated cell count.
- Cell-count ratio.
- Reference and generated quality metrics.
- Reference and generated boundary-zone names.
- Requested and applied scaled controls.
- Boundary-layer generation status.

The first MVP is accepted when:

1. The web app accepts Fluent `msh`, `msh.h5`, `cas`, and `cas.h5` references.
2. Fluent analyzes the reference in a visible foreground window.
3. `object_wall` characteristic length is detected automatically for the
   validated sphere case.
4. Length-based controls scale using the new/reference characteristic-length
   ratio.
5. The resulting settings are passed into the native Fluent Meshing workflow.
6. All four output artifacts are generated.
7. Existing non-imitation workflows and dry-runs continue to pass.

## Testing

Unit tests cover:

- Reference configuration validation.
- Scale-ratio calculation.
- Length-based versus dimensionless scaling.
- Automatic-length failure and manual fallback behavior.
- Stage ordering and disabled-stage compatibility.
- Web payload parsing and artifact discovery.

Integration validation uses the existing successful sphere mesh as the
reference, creates a sphere with a different diameter, runs Fluent analysis and
native Fluent Meshing in the foreground, and verifies the scaled settings and
comparison outputs.

## Out Of Scope

- Copying cell topology from one geometry to another.
- Image-based mesh imitation.
- Machine-learning-based mesh prediction.
- Exact recovery of unavailable Fluent Meshing workflow controls from a final
  mesh.
- Gmsh or other non-Fluent meshing fallbacks.
