# SpaceClaim External Domain Imitation Design

## Goal

Add an optional external-domain imitation stage to CFD Agent. The user selects
a validated SpaceClaim fluid-domain file (`fluid_domain.scdoc`) or a STEP file.
SpaceClaim opens visibly, analyzes the reference fluid domain, reads its named
boundaries, and calculates the enclosure shape and six directional clearance
ratios around the reference object. CFD Agent then scales those ratios to the
new target CAD and rebuilds a matching external flow domain.

The feature imitates the enclosure strategy and boundary layout. It does not
copy the reference object's geometry or the reference fluid-domain topology.

## User Experience

The local web entry adds:

- An `External domain imitation` enable switch.
- A reference `scdoc`, `step`, or `stp` file picker.
- A read-only analysis preview showing the detected enclosure shape, object
  bounds, inlet and outlet directions, boundary mapping, and six clearance
  ratios.
- A manual flow-direction control that appears when inlet or outlet direction
  cannot be detected.

The feature works in both execution styles:

- Step-by-step: run `Domain imitation` before `SpaceClaim`.
- Full automatic: analyze the reference, scale the enclosure, create the fluid
  domain, and continue into meshing without stopping when detection succeeds.

All real reference analysis and domain creation runs use the existing foreground
execution setting. Dry-run generates plans and paths but does not launch
SpaceClaim.

## Pipeline

The stage order becomes:

```text
validate
solidworks
domain_imitation (optional)
spaceclaim
mesh_imitation (optional)
meshing
fluent_setup
solver
postprocess
report
```

When imitation is disabled, `domain_imitation` records a successful skipped
result and the existing domain settings remain unchanged.

When imitation is enabled:

1. Validate the reference file extension and existence.
2. Launch SpaceClaim in the foreground and open or import the reference domain.
3. Locate the fluid-domain body and the object-wall faces.
4. Read named selections and identify inlet, outlet, farfield, and object wall.
5. Determine the inlet-to-outlet flow direction.
6. Calculate the reference object bounds, enclosure bounds, enclosure shape,
   and six directional clearances.
7. Normalize each clearance by the reference object's characteristic length.
8. Calculate the new target object's characteristic length.
9. Scale the enclosure settings and pass the effective domain configuration to
   the normal SpaceClaim external-domain stage.
10. Rebuild the enclosure, subtract the target CAD, create named selections,
    and write a comparison report.

## Data Model

Add an optional configuration object to `SimulationTask`:

```json
{
  "domain_imitation": {
    "enabled": true,
    "reference_file": "D:/reference/fluid_domain.scdoc",
    "manual_flow_direction": null
  }
}
```

`manual_flow_direction` is a fallback vector supplied by the user only when the
reference inlet or outlet direction cannot be detected. The vector must contain
three finite values and must not have zero magnitude.

The original task domain settings remain unchanged. The imitation stage
produces an effective domain configuration for the SpaceClaim stage, preserving
the original input for auditability.

## Reference Profile

The analysis output is saved as:

```text
outputs/<case>/domain_imitation/
  domain_reference_profile.json
  scaled_domain_settings.json
  domain_imitation_comparison.json
  spaceclaim_reference_analysis.log
```

`domain_reference_profile.json` contains:

- Reference file path and SpaceClaim version.
- Detected enclosure shape.
- Fluid-domain and object bounding boxes.
- Reference object characteristic length and detection method.
- Inlet-to-outlet flow direction.
- Six normalized clearances: upstream, downstream, left, right, top, and
  bottom.
- Named-selection names, detected boundary roles, and supported boundary types.
- Detection confidence and warnings.

`scaled_domain_settings.json` contains the effective enclosure dimensions,
clearances, flow direction, and boundary mapping used to create the new domain.

## Enclosure And Scaling Rules

The first version supports enclosure shapes that can be rebuilt reliably with
the existing SpaceClaim automation:

- Rectangular box.
- Cylinder aligned with the detected flow direction.

For supported shapes, preserve the reference shape and scale all directional
clearances by:

```text
scale_ratio = new_characteristic_length / reference_characteristic_length
```

The six normalized clearances remain dimensionless. The new absolute clearance
in each direction equals its reference ratio multiplied by the new target
characteristic length.

For an unsupported or ambiguous enclosure shape, use a rectangular box matching
the analyzed enclosure bounds and preserve all six directional clearance
ratios. Record the fallback in the profile and comparison report.

## Boundary Detection And Naming

Boundary roles are detected from SpaceClaim named selections:

- Inlet
- Outlet
- Farfield
- Object wall

The analyzer first uses recognized names and supported metadata. It then checks
face location and normal direction against the enclosure and flow direction.

The generated domain preserves reference boundary names and types when they are
valid and unambiguous. Unrecognized or missing names use the standard mapping:

- `velocity_inlet`
- `pressure_outlet`
- `farfield`
- `object_wall`

If inlet or outlet named selections are missing or do not identify a reliable
flow direction, the imitation stage stops before domain creation unless the
user supplied `manual_flow_direction`. STEP files do not reliably preserve
SpaceClaim named selections, so they commonly require the manual fallback.

## SpaceClaim Analysis

Use a dedicated SpaceClaim scripting runner instead of directly parsing
`scdoc` internals. This keeps the Agent compatible with SpaceClaim's supported
geometry and named-selection APIs.

The runner:

- Opens SpaceClaim visibly when `CFD_AGENT_FOREGROUND=true`.
- Opens `scdoc` references or imports STEP references.
- Inspects bodies, faces, bounding boxes, named selections, and face normals.
- Identifies the likely fluid-domain body and object-wall faces.
- Writes structured JSON and a transcript.
- Leaves actionable diagnostic information when detection fails.
- Closes the reference analysis session after completion.

Reference analysis must not modify or overwrite the selected reference file.

## Failure Handling

The imitation stage fails before new SpaceClaim domain creation when:

- The reference file does not exist or has an unsupported extension.
- SpaceClaim cannot open or import the reference.
- A fluid-domain body or object wall cannot be identified.
- Inlet or outlet direction cannot be detected and no manual flow direction is
  supplied.
- The reference characteristic length is zero or invalid.
- The calculated clearances are zero, negative, or geometrically inconsistent.

Warnings do not block execution when a documented fallback is available. For
example, an unsupported enclosure shape falls back to a rectangular box while
preserving its six clearance ratios.

The web UI displays actionable errors and preserves the SpaceClaim analysis log.
The user can supply a manual flow direction and rerun the stage.

## Comparison And Acceptance

After target-domain creation, `domain_imitation_comparison.json` compares:

- Reference and generated enclosure shapes.
- Reference and generated object characteristic lengths.
- Scale ratio.
- Requested and achieved six directional clearances.
- Reference and generated boundary names and roles.
- Flow direction.
- Any applied fallbacks or warnings.

The first MVP is accepted when:

1. The web app accepts `scdoc`, `step`, and `stp` reference domains.
2. SpaceClaim analyzes the reference in a visible foreground window.
3. The validated reference sphere domain is detected as a rectangular box with
   correct object bounds and six clearance ratios.
4. Inlet, outlet, farfield, and object-wall roles are detected from named
   selections.
5. A different-sized target sphere receives the scaled enclosure shape and
   directional clearances.
6. The generated named selections preserve valid reference names or use the
   standard fallback names.
7. All four output artifacts are generated.
8. The generated `fluid_domain.scdoc` and `fluid_domain.step` can continue into
   native Fluent Meshing.
9. Existing non-imitation workflows, mesh imitation, and dry-runs continue to
   pass.

## Testing

Unit tests cover:

- Reference configuration validation.
- Manual flow-direction validation.
- Boundary-role mapping and fallback names.
- Flow-direction detection.
- Six-direction clearance calculation and scaling.
- Supported-shape selection and unsupported-shape fallback.
- Stage ordering and disabled-stage compatibility.
- Web payload parsing and artifact discovery.

Integration validation uses the existing successful sphere fluid domain as the
reference, creates a sphere with a different diameter, runs SpaceClaim analysis
and target-domain generation in the foreground, and verifies the scaled
settings, named selections, output geometry, and comparison report. A dry-run
integration test verifies the full pipeline without launching SpaceClaim.

## Out Of Scope

- Copying or morphing the reference fluid-domain topology.
- Reusing the reference object's CAD geometry.
- Internal-flow-domain imitation.
- Image-based domain imitation.
- Automatic inference of reliable boundary roles from STEP alone when named
  selections are unavailable.
- Exact reproduction of unsupported arbitrary enclosure shapes.
