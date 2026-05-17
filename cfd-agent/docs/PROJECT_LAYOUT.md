# Project Layout

```text
cfd-agent/
  src/cfd_agent/              Python package
    core/                     data models, validation, orchestration, physics helpers
    tools/                    SolidWorks, SpaceClaim, Meshing, Fluent, postprocess tools
    templates/                active script/journal/report templates
    examples/                 input SimulationTask JSON examples
    web_app.py                local browser entry
  configs/                    default workflow config files
  docs/
    prompts/                  preserved project prompts/specs
    templates/                documentation copy of runtime templates
  tests/                      pytest suite
  validation_cases/sphere_001 curated successful real-run case
  CFD_Agent_Web.bat           Windows double-click web launcher
  start_cfd_agent_web.ps1     PowerShell launcher used by the BAT file
  ENVIRONMENT.md              local setup and executable paths
  README.md                   user-facing guide
```

Ignored local runtime output:

```text
outputs/
fluent-*.trn
cleanup-fluent-*.bat
FM_DESKTOP-*/
__pycache__/
.pytest_cache/
```
