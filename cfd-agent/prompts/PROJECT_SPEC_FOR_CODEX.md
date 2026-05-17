# CFD 全流程仿真 Agent 项目说明书（给 Codex 使用）

> 文件用途：将本文件交给 Codex / 编程 Agent，用于生成一个“从建模 → 网格 → Fluent 仿真 → 后处理 → 报告”的自动化 CFD Agent 项目。
>
> 目标读者：Codex、后端开发者、仿真工程师。
>
> 当前阶段建议：先实现 MVP，支持简单外流场稳态不可压缩绕流，再逐步扩展到复杂 CAD、瞬态、旋转运动、动网格和六自由度。

---

## 1. 项目目标

请实现一个 CFD 全流程仿真 Agent，能够根据用户输入的：

1. 模型信息
2. 流场环境
3. 运动状态

自动完成：

1. 几何建模
2. 计算域生成
3. 边界命名
4. 网格划分
5. Fluent case 设置
6. Fluent 求解
7. 结果后处理
8. 报告生成

最终输出：

1. 几何模型文件
2. 网格文件
3. Fluent case/data 文件
4. 仿真结果数据
5. 云图/曲线图片
6. PDF 或 Markdown 报告

---

## 2. 开发原则

请遵循以下原则：

1. Agent 只负责理解、规划、调度和解释。
2. 实际建模、网格、Fluent、后处理由工具函数或脚本完成。
3. 所有输入必须先转为结构化 `SimulationTask`。
4. 不允许编造仿真结果。
5. 如果某一步失败，需要返回明确错误信息和建议修复方案。
6. 每个阶段都要保存日志和中间文件。
7. 代码优先保证可调试、可扩展，而不是一开始追求复杂智能。
8. MVP 先支持简单几何，复杂功能后续扩展。

---

## 3. MVP 功能范围

第一版只需要支持以下能力：

### 3.1 几何类型

支持：

1. sphere：球
2. cylinder：圆柱
3. box：长方体
4. airfoil_2d：二维翼型，后续可选

第一版优先实现：

1. sphere
2. cylinder

### 3.2 流动类型

支持：

1. 外流场绕流
2. 稳态
3. 不可压缩
4. 单相流
5. 等温流
6. 静止刚体，使用入口速度等效运动

暂不实现：

1. 动网格
2. 六自由度
3. 多相流
4. 燃烧
5. 传热
6. 可压缩高速流
7. 复杂 CAD 修复

### 3.3 Fluent 设置

默认使用：

1. Pressure-Based Solver
2. Steady
3. SIMPLE
4. k-omega SST 湍流模型
5. Second Order Upwind
6. 残差目标：1e-5
7. 最大迭代步：1000

### 3.4 输出

MVP 输出：

1. `geometry.step`
2. `mesh.msh`
3. `case.cas.h5`
4. `data.dat.h5`
5. `residuals.csv`
6. `forces.csv`
7. `pressure_contour.png`
8. `velocity_contour.png`
9. `report.md`

---

## 4. 推荐技术栈

请优先使用 Python 实现主流程。

### 4.1 主语言

```text
Python 3.10+
```

### 4.2 几何建模

本项目指定使用以下路线：

1. SolidWorks：负责目标物体的参数化建模，例如球、圆柱、翼型、弹体、飞行器部件等。
2. SpaceClaim：负责外流场计算域建模、布尔运算、流体域抽取、边界命名和几何清理。
3. 不使用 CadQuery / FreeCAD 作为主建模路线，除非仅用于无商业软件环境下的 mock 或 dry-run 占位。

SolidWorks 输出建议：

```text
part.sldprt
geometry.step
geometry.x_t
```

SpaceClaim 输出建议：

```text
fluid_domain.scdoc
fluid_domain.pmdb
fluid_domain.step
named_selections.json
```

### 4.3 外流场建模

外流场计算域必须由 SpaceClaim 脚本生成或处理。

SpaceClaim 负责：

1. 导入 SolidWorks 导出的目标模型。
2. 根据特征长度 L 自动创建外流场包围域。
3. 进行布尔减操作，得到流体域。
4. 创建入口、出口、远场、对称面、物体壁面等 named selections。
5. 导出供 Fluent Meshing 读取的几何文件。

默认外流场尺寸：

```text
入口距离：5L
出口距离：15L
侧向距离：5L
上/下距离：5L
```

### 4.4 网格

本项目指定使用 Fluent Meshing。

Fluent Meshing 负责：

1. 读取 SpaceClaim 导出的流体域几何。
2. 使用 Watertight Geometry Workflow。
3. 生成 surface mesh。
4. 描述边界层 inflation。
5. 生成 volume mesh。
6. 检查网格质量。
7. 导出 Fluent mesh/case。

不使用 Gmsh 作为主网格路线。Gmsh 只能作为 dry-run 或开源替代路线的占位，不进入主流程。

### 4.5 Fluent

优先级：

1. PyFluent
2. Fluent journal `.jou`
3. 命令行调用 Fluent

请设计为可配置：

```text
USE_PYFLUENT=true/false
FLUENT_EXECUTABLE=/path/to/fluent
```

### 4.6 后处理

优先级：

1. PyFluent
2. Fluent journal 导出数据
3. ParaView Python
4. matplotlib

### 4.7 报告

优先输出 Markdown，后续再转 PDF。

---

## 5. 推荐项目结构

请生成如下项目结构：

```text
cfd-agent/
  README.md
  PROJECT_SPEC_FOR_CODEX.md
  requirements.txt
  .env.example

  configs/
    default.yaml
    fluent.yaml
    meshing.yaml

  src/
    cfd_agent/
      __init__.py
      main.py

      core/
        models.py
        validators.py
        physics.py
        orchestrator.py
        state.py
        errors.py
        logging_config.py

      agents/
        requirement_parser.py
        parameter_checker.py
        geometry_agent.py
        mesh_agent.py
        fluent_agent.py
        solver_monitor_agent.py
        postprocess_agent.py
        report_agent.py

      tools/
        solidworks_tool.py
        spaceclaim_tool.py
        fluent_meshing_tool.py
        fluent_setup_tool.py
        solver_tool.py
        postprocess_tool.py
        report_tool.py
        file_tool.py

      templates/
        solidworks_model.py.j2
        spaceclaim_external_domain.py.j2
        fluent_meshing_watertight.jou.j2
        fluent_setup.jou.j2
        fluent_solve.jou.j2
        fluent_postprocess.jou.j2
        report.md.j2

      examples/
        sphere_external_flow.json
        cylinder_external_flow.json

  outputs/
    .gitkeep

  tests/
    test_models.py
    test_physics.py
    test_validators.py
    test_orchestrator.py
```

---

## 6. 核心数据结构

请在 `src/cfd_agent/core/models.py` 中定义 Pydantic 模型。

```python
from typing import Literal, Optional, List, Dict
from pydantic import BaseModel, Field


class GeometryConfig(BaseModel):
    type: Literal["sphere", "cylinder", "box", "custom_cad"]
    unit: Literal["m", "mm"] = "m"
    parameters: Dict[str, float]
    cad_file: Optional[str] = None


class DomainConfig(BaseModel):
    type: Literal["external", "internal"] = "external"
    upstream_length_ratio: float = 5.0
    downstream_length_ratio: float = 15.0
    side_length_ratio: float = 5.0


class FluidConfig(BaseModel):
    name: str = "air"
    density: float = 1.225
    viscosity: float = 1.789e-5
    temperature: float = 288.15
    pressure: float = 101325.0


class MotionConfig(BaseModel):
    type: Literal["stationary", "uniform_translation", "rotation"] = "stationary"
    inlet_velocity: float
    attack_angle_deg: float = 0.0
    angular_velocity_rad_s: Optional[float] = None


class MeshConfig(BaseModel):
    global_size: Optional[float] = None
    near_body_size: Optional[float] = None
    boundary_layer_enabled: bool = True
    target_y_plus: float = 1.0
    first_layer_height: Optional[float] = None
    layers: int = 15
    growth_rate: float = 1.2
    max_skewness: float = 0.85
    min_orthogonal_quality: float = 0.15


class SolverConfig(BaseModel):
    steady: bool = True
    solver_type: Literal["pressure_based", "density_based"] = "pressure_based"
    turbulence_model: Literal["laminar", "k_epsilon", "k_omega_sst"] = "k_omega_sst"
    residual_target: float = 1e-5
    max_iterations: int = 1000


class OutputConfig(BaseModel):
    requested: List[str] = Field(default_factory=lambda: [
        "drag_coefficient",
        "lift_coefficient",
        "pressure_contour",
        "velocity_contour",
        "residuals",
        "report"
    ])


class SimulationTask(BaseModel):
    task_id: str
    geometry: GeometryConfig
    domain: DomainConfig = Field(default_factory=DomainConfig)
    fluid: FluidConfig = Field(default_factory=FluidConfig)
    motion: MotionConfig
    mesh: MeshConfig = Field(default_factory=MeshConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    outputs: OutputConfig = Field(default_factory=OutputConfig)
```

---

## 7. 物理判断模块

请在 `src/cfd_agent/core/physics.py` 中实现以下函数。

```python
def get_characteristic_length(task: SimulationTask) -> float:
    """
    sphere: diameter
    cylinder: diameter
    box: max(length, width, height)
    custom_cad: 如果没有用户输入，则报错
    """


def calculate_reynolds_number(rho: float, velocity: float, length: float, mu: float) -> float:
    return rho * velocity * length / mu


def calculate_mach_number(velocity: float, speed_of_sound: float = 340.0) -> float:
    return velocity / speed_of_sound


def classify_flow(reynolds_number: float, mach_number: float) -> dict:
    """
    返回：
    {
      "compressibility": "incompressible" or "compressible",
      "regime": "laminar" or "turbulent",
      "recommended_solver": "pressure_based" or "density_based",
      "recommended_turbulence_model": "laminar" or "k_omega_sst"
    }
    """
```

规则：

```text
Mach < 0.3: incompressible
Mach >= 0.3: compressible

Re < 2300: laminar
Re >= 2300: turbulent

外流场绕流默认湍流模型：k_omega_sst
```

---

## 8. 参数校验

请在 `src/cfd_agent/core/validators.py` 中实现：

```python
def validate_simulation_task(task: SimulationTask) -> list[str]:
    """
    返回错误列表。
    如果为空，说明任务有效。
    """
```

需要检查：

1. 几何尺寸是否存在
2. 尺寸是否大于 0
3. 速度是否大于 0
4. 密度是否大于 0
5. 黏度是否大于 0
6. 网格层数是否合理
7. 增长率是否在 1.0 到 1.5 之间
8. 如果是 custom_cad，必须提供 cad_file
9. 如果是 sphere，必须有 diameter
10. 如果是 cylinder，必须有 diameter 和 length

---

## 9. Orchestrator 编排逻辑

请在 `src/cfd_agent/core/orchestrator.py` 中实现主流程。

```python
def run_simulation(task: SimulationTask, output_dir: str, dry_run: bool = False) -> dict:
    """
    执行完整 CFD 工作流。
    返回执行状态、文件路径、关键结果和错误信息。
    """
```

流程：

```text
1. 创建任务输出目录
2. 校验输入参数
3. 计算 Re、Mach 和推荐求解设置
4. 调用 SolidWorks 生成目标物体模型
5. 调用 SpaceClaim 生成外流场流体域
6. 调用 Fluent Meshing 生成 surface mesh、boundary layer 和 volume mesh
7. 检查网格质量
8. 生成 Fluent case / journal
9. 运行 Fluent
10. 监控收敛
11. 后处理
12. 生成报告
13. 返回结果
```

返回格式：

```python
{
    "task_id": "cfd_001",
    "status": "success",
    "stage": "completed",
    "physics_summary": {
        "reynolds_number": 205700,
        "mach_number": 0.087,
        "flow_regime": "turbulent",
        "compressibility": "incompressible"
    },
    "files": {
        "geometry": ".../geometry.step",
        "mesh": ".../mesh.msh",
        "case": ".../case.cas.h5",
        "data": ".../data.dat.h5",
        "report": ".../report.md"
    },
    "results": {
        "drag_coefficient": None,
        "lift_coefficient": None
    },
    "errors": []
}
```

---

## 10. 工具函数接口

### 10.1 SolidWorks Tool

文件：`src/cfd_agent/tools/solidworks_tool.py`

```python
def create_solidworks_model(task: SimulationTask, output_dir: str, dry_run: bool = False) -> dict:
    """
    使用 SolidWorks API / 宏 / Python COM 自动生成目标物体模型。

    返回：
    {
      "native_file": ".../solidworks/part.sldprt",
      "step_file": ".../solidworks/geometry.step",
      "parasolid_file": ".../solidworks/geometry.x_t",
      "metadata_file": ".../solidworks/geometry_metadata.json",
      "success": true,
      "error": null
    }
    """
```

SolidWorks 负责：

1. 根据 `SimulationTask.geometry` 创建目标物体。
2. 支持 sphere、cylinder、box 等基础几何。
3. 后续支持自定义参数化模型。
4. 导出 STEP 或 Parasolid，供 SpaceClaim 使用。
5. 保存几何元数据，例如特征长度、参考面积、参考体积。

要求：

1. Windows 环境下优先使用 SolidWorks COM API。
2. 支持 dry-run：只生成脚本和 metadata，不启动 SolidWorks。
3. 如果 SolidWorks 不存在，必须返回明确错误，不允许伪造几何文件。
4. 所有 SolidWorks 宏或脚本应保存到输出目录，便于人工复现。

建议输出目录：

```text
outputs/<task_id>/solidworks/
  create_model.py
  create_model.log
  part.sldprt
  geometry.step
  geometry.x_t
  geometry_metadata.json
```

---

### 10.2 SpaceClaim Tool

文件：`src/cfd_agent/tools/spaceclaim_tool.py`

```python
def create_external_flow_domain(task: SimulationTask, solidworks_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    """
    使用 SpaceClaim 脚本创建外流场计算域，并完成布尔减、边界命名和几何清理。

    返回：
    {
      "spaceclaim_script": ".../spaceclaim/create_external_domain.py",
      "scdoc_file": ".../spaceclaim/fluid_domain.scdoc",
      "pmdb_file": ".../spaceclaim/fluid_domain.pmdb",
      "step_file": ".../spaceclaim/fluid_domain.step",
      "named_selections_file": ".../spaceclaim/named_selections.json",
      "success": true,
      "error": null
    }
    """
```

SpaceClaim 负责：

1. 导入 SolidWorks 输出的 `geometry.step` 或 `geometry.x_t`。
2. 识别特征长度 L。
3. 创建外流场包围域。
4. 从包围域中扣除目标物体，得到流体域。
5. 命名边界：
   - `velocity_inlet`
   - `pressure_outlet`
   - `farfield`
   - `object_wall`
   - 可选：`symmetry`
6. 修复小面、小边、缝隙等几何问题。
7. 导出 Fluent Meshing 可读取的几何文件。

默认外流场域：

```text
x_min = -5L
x_max = 15L
y_min = -5L
y_max = 5L
z_min = -5L
z_max = 5L
```

要求：

1. SpaceClaim 脚本必须可保存、可复现。
2. 支持 dry-run：生成 SpaceClaim 脚本和 named selection 计划，但不启动 SpaceClaim。
3. 如果 SpaceClaim 执行失败，需要返回失败阶段和日志路径。
4. 不允许跳过布尔减直接进入网格。

建议输出目录：

```text
outputs/<task_id>/spaceclaim/
  create_external_domain.py
  spaceclaim.log
  fluid_domain.scdoc
  fluid_domain.pmdb
  fluid_domain.step
  named_selections.json
```

---

### 10.3 Fluent Meshing Tool

文件：`src/cfd_agent/tools/fluent_meshing_tool.py`

```python
def generate_mesh_with_fluent_meshing(task: SimulationTask, domain_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    """
    使用 Fluent Meshing Watertight Geometry Workflow 生成网格。

    返回：
    {
      "meshing_journal": ".../meshing/fluent_meshing_watertight.jou",
      "mesh_file": ".../meshing/mesh.msh.h5",
      "case_file": ".../meshing/mesh_case.cas.h5",
      "quality_report": {
        "cell_count": null,
        "max_skewness": null,
        "min_orthogonal_quality": null,
        "passed": null
      },
      "success": true,
      "error": null
    }
    """
```

Fluent Meshing 负责：

1. 读取 SpaceClaim 导出的流体域几何。
2. 启动 Watertight Geometry Workflow。
3. 设置长度单位。
4. 描述边界类型。
5. 生成 surface mesh。
6. 检查 surface mesh。
7. 设置边界层：
   - first layer height
   - layer count
   - growth rate
   - target y+
8. 生成 volume mesh。
9. 检查网格质量。
10. 导出 `mesh.msh.h5` 或 `mesh_case.cas.h5`。

网格质量标准：

```text
max_skewness <= 0.85
min_orthogonal_quality >= 0.15
```

要求：

1. 主流程必须使用 Fluent Meshing，不使用 Gmsh。
2. 支持 dry-run：只生成 Fluent Meshing journal，不启动 Fluent Meshing。
3. 如果 Fluent Meshing 不存在，必须返回明确错误。
4. 不允许伪造 cell count、skewness、orthogonal quality。
5. 如果没有真实网格质量数据，对应字段必须为 null。

建议输出目录：

```text
outputs/<task_id>/meshing/
  fluent_meshing_watertight.jou
  fluent_meshing.log
  mesh.msh.h5
  mesh_case.cas.h5
  mesh_quality_report.json
```

---

### 10.4 Fluent Setup Tool

文件：`src/cfd_agent/tools/fluent_setup_tool.py`

```python
def create_fluent_journal(task: SimulationTask, mesh_info: dict, output_dir: str) -> dict:
    """
    生成 Fluent 求解 journal。
    返回：
    {
      "setup_journal": ".../fluent/fluent_setup.jou",
      "solve_journal": ".../fluent/fluent_solve.jou"
    }
    """
```

journal 内容应包括：

1. 读取 Fluent Meshing 输出的 mesh/case。
2. 检查网格。
3. 设置 solver。
4. 设置材料。
5. 设置湍流模型。
6. 设置边界条件。
7. 初始化。
8. 迭代。
9. 保存 case/data。
10. 导出残差和力系数。

---

### 10.5 Solver Tool

文件：`src/cfd_agent/tools/solver_tool.py`

```python
def run_fluent(journal_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    """
    调用 Fluent 运行。
    返回：
    {
      "case_file": ".../fluent/case.cas.h5",
      "data_file": ".../fluent/data.dat.h5",
      "log_file": ".../fluent/fluent.log",
      "success": true,
      "error": null
    }
    """
```

要求：

1. 从环境变量读取 Fluent 路径。
2. 支持 dry-run 模式。
3. 如果 Fluent 不存在，不要报系统崩溃，返回失败信息。
4. 保存 Fluent 控制台输出到 log 文件。

---

### 10.6 Postprocess Tool

文件：`src/cfd_agent/tools/postprocess_tool.py`

```python
def postprocess_results(task: SimulationTask, solver_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    """
    后处理结果。
    返回：
    {
      "residuals_csv": ".../postprocess/residuals.csv",
      "forces_csv": ".../postprocess/forces.csv",
      "figures": {
        "pressure_contour": ".../postprocess/pressure_contour.png",
        "velocity_contour": ".../postprocess/velocity_contour.png"
      },
      "metrics": {
        "drag_coefficient": null,
        "lift_coefficient": null
      }
    }
    """
```

MVP：

1. 如果 Fluent 输出 CSV，则读取并画图。
2. 如果没有真实数据，返回 null，不允许生成假数据。

---

### 10.7 Report Tool

文件：`src/cfd_agent/tools/report_tool.py`

```python
def generate_report(task: SimulationTask, workflow_result: dict, output_dir: str) -> dict:
    """
    生成 Markdown 报告。
    返回：
    {
      "report_file": ".../report/report.md"
    }
    """
```

报告必须包含：

1. 任务摘要。
2. SolidWorks 目标模型设置。
3. SpaceClaim 外流场设置。
4. 流体参数。
5. Re 和 Mach。
6. Fluent Meshing 网格设置和质量。
7. Fluent 求解设置。
8. 求解状态。
9. 结果摘要。
10. 文件清单。
11. 错误或警告。


## 11. Agent 层设计

### 11.1 Requirement Parser Agent

文件：`src/cfd_agent/agents/requirement_parser.py`

作用：

把用户自然语言转成 `SimulationTask JSON`。

输入示例：

```text
模拟一个直径 0.1m 的球在 30m/s 空气中的绕流，求阻力系数和压力云图。
```

输出示例：

```json
{
  "task_id": "sphere_001",
  "geometry": {
    "type": "sphere",
    "unit": "m",
    "parameters": {
      "diameter": 0.1
    }
  },
  "motion": {
    "type": "stationary",
    "inlet_velocity": 30,
    "attack_angle_deg": 0
  }
}
```

要求：

1. 能处理中文自然语言
2. 缺参数时返回 `missing_fields`
3. 不确定时返回 `assumptions`
4. 不要直接运行仿真

---

### 11.2 Parameter Checker Agent

文件：`src/cfd_agent/agents/parameter_checker.py`

作用：

1. 调用 validators
2. 调用 physics
3. 给出推荐求解设置
4. 给出警告

---

### 11.3 其他子 Agent

Geometry / Mesh / Fluent / Solver / Postprocess / Report Agent 本质上是工具包装器：

1. 接收上一步结果
2. 调用对应 tool
3. 检查返回值
4. 把结果写入 workflow state

---

## 12. 状态机设计

请实现一个简单状态机，不必第一版引入复杂框架。

状态包括：

```text
CREATED
VALIDATED
SOLIDWORKS_MODEL_CREATED
SPACECLAIM_DOMAIN_CREATED
FLUENT_MESH_CREATED
CASE_CREATED
SOLVER_RUNNING
SOLVER_COMPLETED
POSTPROCESSED
REPORT_CREATED
FAILED
```

每一步失败时：

1. 设置状态为 FAILED
2. 记录失败阶段
3. 记录错误信息
4. 返回给用户

---

## 13. 示例输入文件

请在 `src/cfd_agent/examples/sphere_external_flow.json` 中创建：

```json
{
  "task_id": "sphere_external_flow_001",
  "geometry": {
    "type": "sphere",
    "unit": "m",
    "parameters": {
      "diameter": 0.1
    }
  },
  "domain": {
    "type": "external",
    "upstream_length_ratio": 5.0,
    "downstream_length_ratio": 15.0,
    "side_length_ratio": 5.0
  },
  "fluid": {
    "name": "air",
    "density": 1.225,
    "viscosity": 1.789e-5,
    "temperature": 288.15,
    "pressure": 101325.0
  },
  "motion": {
    "type": "stationary",
    "inlet_velocity": 30.0,
    "attack_angle_deg": 0.0
  },
  "mesh": {
    "boundary_layer_enabled": true,
    "target_y_plus": 1.0,
    "layers": 15,
    "growth_rate": 1.2,
    "max_skewness": 0.85,
    "min_orthogonal_quality": 0.15
  },
  "solver": {
    "steady": true,
    "solver_type": "pressure_based",
    "turbulence_model": "k_omega_sst",
    "residual_target": 1e-5,
    "max_iterations": 1000
  },
  "outputs": {
    "requested": [
      "drag_coefficient",
      "pressure_contour",
      "velocity_contour",
      "residuals",
      "report"
    ]
  }
}
```

---

## 14. CLI 接口

请实现命令行入口：

```bash
python -m cfd_agent.main run --input src/cfd_agent/examples/sphere_external_flow.json --output outputs/sphere_001
```

返回：

```text
Task ID: sphere_external_flow_001
Status: success/failed
Stage: ...
Report: outputs/sphere_001/report.md
```

也支持 dry-run：

```bash
python -m cfd_agent.main run --input src/cfd_agent/examples/sphere_external_flow.json --output outputs/sphere_001 --dry-run
```

dry-run 模式只做：

1. 参数校验
2. Re/Mach 计算
3. 生成计划
4. 生成 journal
5. 不真正调用 Fluent

---

## 15. README 要求

请生成 `README.md`，内容包括：

1. 项目简介
2. 支持功能
3. 安装方式
4. 环境变量
5. 示例运行
6. 输出文件说明
7. 当前限制
8. 后续开发计划

---


README 还必须说明以下环境变量：

```text
SOLIDWORKS_ENABLED=true/false
SPACECLAIM_ENABLED=true/false
FLUENT_MESHING_ENABLED=true/false
FLUENT_SOLVER_ENABLED=true/false

SOLIDWORKS_EXECUTABLE=C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe
SPACECLAIM_EXECUTABLE=C:/Program Files/ANSYS Inc/vXXX/scdm/SpaceClaim.exe
FLUENT_EXECUTABLE=C:/Program Files/ANSYS Inc/vXXX/fluent/ntbin/win64/fluent.exe
ANSYS_VERSION=XXX
```

主流程说明必须写成：

```text
用户输入
→ SimulationTask
→ SolidWorks 目标物体建模
→ SpaceClaim 外流场流体域建模
→ Fluent Meshing 网格生成
→ Fluent Solver 求解
→ 后处理
→ 报告
```


## 16. 测试要求

请实现最少以下测试：

### 16.1 test_physics.py

测试：

1. Re 计算正确
2. Mach 计算正确
3. 低 Mach 判断为不可压缩
4. 高 Re 判断为湍流

### 16.2 test_validators.py

测试：

1. sphere 缺 diameter 报错
2. cylinder 缺 length 报错
3. 负速度报错
4. 黏度为 0 报错

### 16.3 test_orchestrator.py

测试：

1. dry-run 能完整执行
2. 非法输入会失败
3. 输出目录会被创建
4. 返回结构包含 status、stage、files、errors

---

## 17. 错误处理要求

请定义统一异常：

文件：`src/cfd_agent/core/errors.py`

```python
class CFDAgentError(Exception):
    pass

class GeometryError(CFDAgentError):
    pass

class MeshError(CFDAgentError):
    pass

class FluentSetupError(CFDAgentError):
    pass

class SolverError(CFDAgentError):
    pass

class PostprocessError(CFDAgentError):
    pass

class ReportError(CFDAgentError):
    pass
```

工具函数不要直接让程序崩溃，应返回结构化错误。

---

## 18. 日志要求

请使用 Python logging。

每个任务输出目录下保存：

```text
workflow.log
geometry.log
mesh.log
fluent.log
postprocess.log
```

日志至少包含：

1. 当前阶段
2. 输入参数摘要
3. 输出文件路径
4. 外部程序命令
5. 错误堆栈
6. 耗时

---

## 19. Fluent Journal 模板要求

请在 `templates/fluent_setup.jou.j2` 中生成 Fluent journal 模板。

模板变量包括：

```text
mesh_file
case_file
data_file
velocity
density
viscosity
turbulence_model
residual_target
max_iterations
```

journal 需要尽可能保持简单，并用注释说明每一步。

---

## 20. 第一阶段开发任务清单

请 Codex 按以下顺序实现，不要跳步：

### Task 1：创建项目骨架

1. 创建目录结构
2. 创建 requirements.txt
3. 创建 README.md 初稿
4. 创建 .env.example

### Task 2：实现 Pydantic 数据模型

1. 实现 models.py
2. 加载 JSON 输入
3. 写模型测试

### Task 3：实现物理计算和参数校验

1. 实现 physics.py
2. 实现 validators.py
3. 写单元测试

### Task 4：实现 dry-run orchestrator

1. 创建输出目录
2. 校验参数
3. 计算 Re/Mach
4. 生成 workflow_result
5. 不调用外部软件

### Task 5：实现 report_tool

1. 使用 Jinja2 或普通字符串生成 report.md
2. dry-run 下也能生成报告

### Task 6：实现 Fluent journal 生成

1. 生成 setup journal
2. 生成 solve journal
3. 不要求立即能跑 Fluent

### Task 7：实现 solidworks_tool MVP

1. 先支持 sphere 和 cylinder 的参数化模型脚本生成。
2. 输出 SolidWorks 宏 / Python COM 脚本。
3. 如果环境可用，则调用 SolidWorks 导出 SLDPRT、STEP、Parasolid。
4. 如果 SolidWorks 不可用，dry-run 只生成脚本；非 dry-run 返回明确错误。
5. 不伪造真实 CAD 文件。

### Task 8：实现 spaceclaim_tool MVP

1. 生成 SpaceClaim 外流场建模脚本。
2. 导入 SolidWorks 输出几何。
3. 创建外流场计算域。
4. 执行布尔减，抽取流体域。
5. 创建 named selections。
6. 支持 dry-run。
7. 不伪造真实 SpaceClaim 几何结果。

### Task 9：实现 fluent_meshing_tool MVP

1. 生成 Fluent Meshing Watertight Workflow journal。
2. 设置 surface mesh、boundary layer 和 volume mesh。
3. 支持 dry-run。
4. 非 dry-run 下调用 Fluent Meshing。
5. 不伪造真实 mesh 或网格质量结果。

### Task 10：实现 solver_tool

1. 读取环境变量 FLUENT_EXECUTABLE。
2. 构造命令。
3. 保存日志。
4. 支持 dry-run。

### Task 11：补充端到端示例

1. 添加 sphere example
2. README 写明运行方式
3. 确保 pytest 通过

---

## 21. 后续扩展方向

完成 MVP 后再扩展：

1. 支持复杂 CAD 上传
2. 支持 Fluent Meshing Watertight Workflow
3. 支持 PyFluent 完整控制
4. 支持瞬态仿真
5. 支持旋转域 MRF
6. 支持滑移网格
7. 支持动网格
8. 支持六自由度
9. 支持自动网格无关性分析
10. 支持多算例批量运行
11. 支持 Web UI
12. 支持任务队列 Celery/Redis
13. 支持仿真结果数据库
14. 支持自动报告 PDF 导出

---

## 22. 重要限制声明

请在代码和 README 中明确：

1. 本系统不会替代 CFD 工程师判断。
2. 第一版只做自动化流程，不保证所有设置物理上最优。
3. 对高雷诺数、分离流、非定常流、压缩流，需要人工复核。
4. 如果外部软件缺失，例如 Fluent/Gmsh/CadQuery，程序必须清楚提示，而不是静默失败。
5. 不允许输出虚假的仿真结果或伪造收敛数据。

---

## 23. 期望 Codex 输出

请 Codex 最终提交：

1. 完整项目代码
2. 可运行 dry-run 示例
3. 单元测试
4. README
5. 示例输入 JSON
6. 示例输出 report.md

验收标准：

```bash
pip install -r requirements.txt
pytest
python -m cfd_agent.main run --input src/cfd_agent/examples/sphere_external_flow.json --output outputs/sphere_001 --dry-run
```

应能成功生成：

```text
outputs/sphere_001/workflow.log
outputs/sphere_001/report/report.md
outputs/sphere_001/solidworks/create_model.py
outputs/sphere_001/spaceclaim/create_external_domain.py
outputs/sphere_001/meshing/fluent_meshing_watertight.jou
outputs/sphere_001/fluent/fluent_setup.jou
outputs/sphere_001/fluent/fluent_solve.jou
```

---

## 24. 给 Codex 的最终指令

请从 Task 1 开始实现该项目。

要求：

1. 先实现 dry-run 全链路。
2. 不要一开始依赖真实 Fluent 环境。
3. 所有外部软件调用都必须可配置、可跳过、可记录日志。
4. 所有结果都必须来自真实计算或明确标注为未计算。
5. 代码要模块化，但主流程必须固定为 SolidWorks → SpaceClaim → Fluent Meshing → Fluent Solver。
6. 每完成一个 Task，请运行测试并修复错误。
7. 不要删除本说明文件。
