# 需求分析垂直链路低耦合拆分设计

## 背景

Phase 0/1 已经把 Application 与 Adapter 的直接依赖切换到组合根，但
`WebFacade` 仍同时承担 HTTP 兼容入口、需求状态编排、SQLite 写入、增量任务
提交和 LLM 配置解析。下一步如果直接把整个 `WebFacade` 或
`requirements_workbench.py` 搬成“大服务”，只会改变文件位置，不能真正降低
耦合，也会扩大回归范围。

本次只处理一条可独立验证的业务链路：

`上传/合并需求 -> 建立 accepted 基线 -> 保存工作台 -> 提交增量分析任务 -> 保存任务状态`

## 目标与非目标

目标：

- 将需求分析及增量任务编排从 `WebFacade` 移到一个窄职责应用服务。
- 让这个服务接收显式、最小化的依赖，而不是继续扩大对全局依赖注册表的使用。
- 保持现有 `WebFacade.analyze_requirements(...)` 签名、事件名、工作区目录、
  工作台 JSON 结构、任务状态和错误类型不变。
- 为服务增加假仓储、假任务服务和假模型测试，验证调用顺序与持久化结果。

非目标：

- 本次不拆 `requirements_workbench.py` 的纯状态转换函数。
- 本次不改变 LLM prompt、生成结果 schema、MBSE 语义或 UI 文案。
- 本次不重写 `JobService`，不引入队列、数据库或微服务。
- 本次不处理项目扫描/测试验证链路；该链路作为下一条垂直切片。

## 设计

新增 `src/rflp_lite/application/use_cases/requirements_analysis.py`，提供
`RequirementsAnalysisService`。服务只负责边界编排，纯状态转换仍由现有
`requirements_workbench` 函数完成。

```python
from pathlib import Path
from collections.abc import Callable

from rflp_lite.application.intelligence.enrichment_jobs import EnrichmentJobRunner
from rflp_lite.ports.generative_model import GenerativeModel


@dataclass(frozen=True, slots=True)
class RequirementsAnalysisDependencies:
    repository_factory: RepositoryFactory
    job_service_factory: JobServiceFactory
    enrichment_runner_factory: Callable[[Path], EnrichmentJobRunner]
    analyze_artifact: Callable[[str, bytes], dict[str, object]]
    merge_artifact: Callable[[dict[str, object], str, bytes], dict[str, object]]


class RequirementsAnalysisService:
    def analyze(
        self,
        workspace: WorkspaceRef,
        filename: str,
        content: bytes,
        *,
        merge: bool = True,
        model: GenerativeModel | None = None,
    ) -> dict[str, object]: ...

    def retry(
        self,
        workspace: WorkspaceRef,
        job_id: str,
        *,
        model: GenerativeModel | None = None,
    ) -> dict[str, object]: ...
```

第一步会把当前 `analyze_requirements` 的逻辑原样迁移到 `analyze`，包括：

1. 规范化文件名和合并/新建工作台。
2. 绑定工作区、标准化分析配置、生成草稿并接受明确基线。
3. 写入 `inputs/<sha256前缀>-<文件名>`。
4. 在一个事务中保存工作台、审计事件和需求记录。
5. 接收 facade 已按当前 LLM 配置创建的模型，提交由
   `enrichment_runner_factory` 创建的 `EnrichmentJobRunner`。
6. 根据任务返回状态保存 `requirements.enrichment_queued` 或
   `requirements.enrichment_finished`。

`WebFacade` 保留原方法，但只负责解析 `WorkspaceRef`、读取当前 LLM 配置、
调用 `RequirementsAnalysisService.analyze`，并返回结果。重试入口也改为调用
同一个服务。其他审核、生成、场景、项目接入方法在本次保持原状。

## 依赖收紧策略

`ApplicationDependencies` 继续作为 Phase 1 的兼容装配对象，但新服务只接收
`RequirementsAnalysisDependencies`。其中 `analyze_artifact`、`merge_artifact`
和 `enrichment_runner_factory` 由组合根预先绑定底层端口；这样新服务不会把
文档解析、渲染、追踪、测试执行等无关能力一起带入需求分析用例。

现有 `require_dependencies()` 仅保留给尚未迁移的兼容函数；本次迁移的分析链路
不得在服务内部调用它。CLI/Web 通过组合根构造窄依赖，旧的直接函数调用仍由
测试兼容配置支撑，待下一条垂直切片完成后再移除全局兜底。

## 错误与事务

- 继续沿用 `ContractViolation`、`AdapterFailure` 和
  `InvariantViolation`，不新增跨层异常。
- 工作台、审计和需求记录仍在同一个 SQLite 事务内保存。
- 任务提交失败时保留已保存的 accepted 基线，不能回滚用户输入文件。
- 任务状态的现有 `queued`、`running`、`degraded`、`completed` 和
  `failed` 含义不变。
- 任何不满足旧行为的结果都通过兼容 facade 回退到原函数，而不是静默改变
  工作台状态。

## 测试与验收

新增测试覆盖：

- 新建需求时保存 `requirements.analyzed`，并生成基线与需求记录。
- 合并需求时保存 `requirements.merged`，不丢失既有审核状态。
- 无模型时仍保存 accepted 基线并产生降级任务状态。
- 任务排队和任务立即完成两条分支分别保存正确事件。
- 假仓储记录事务边界、审计顺序和 `save_requirement_records` 参数。
- `WebFacade.analyze_requirements` 的旧调用路径返回值与服务一致。

验证门：

```bash
.venv/bin/python -m pytest -q tests/application/test_requirements_analysis_service.py tests/application/test_web_facade.py
.venv/bin/python -m pytest -q
.venv/bin/lint-imports
.venv/bin/python -m compileall -q src tests
```

若任一兼容测试失败，停止继续拆分，保留服务接口但回退 facade 调用，先修复
行为差异再进入项目接入垂直切片。

## 回滚点

本次变更限制在新增服务、组合根 wiring、`WebFacade` 两个入口和新增测试。若
回归失败，可以只撤回 facade 的服务调用和 container wiring，保留无行为影响的
依赖协议与测试，不需要修改数据库 schema 或工作区数据。
