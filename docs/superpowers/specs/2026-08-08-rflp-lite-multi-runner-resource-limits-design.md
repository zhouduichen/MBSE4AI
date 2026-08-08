# RFLP-Lite 多运行器与资源上限设计

**日期：** 2026-08-08  
**状态：** 待实施  
**前置：** `2026-08-06-rflp-lite-test-execution-design.md`

## 目标

把当前固定 pytest 的本地测试执行沙箱扩展为可配置、可复现、受资源约束的运行器集合，同时保持现有 `Evidence → Delta → TaskContract → execution` 链路和既有 CLI/Web 调用兼容。

本轮直接落地四项能力：

1. 内置 `pytest` 与标准库 `unittest` 运行器；
2. 超时、输出、内存和文件句柄上限；
3. 以项目内容和执行配置为键的确定性结果缓存；
4. 多个已选择运行器的受控并行执行。

## 范围与非目标

### 本轮范围

- 运行器只能从代码内置的 allowlist 中选择：`pytest`、`unittest`。
- 运行器通过参数数组启动，不经过 shell，不接受任意命令字符串。
- `pytest` 使用现有 JUnit XML 结果；`unittest` 使用 `python -m unittest discover -v`，从稳定的 verbose 输出派生测试 Evidence。
- 资源限制在 POSIX 平台通过子进程 `resource.setrlimit` 应用；所有平台都保证墙钟超时、输出上限和临时产物清理。
- 缓存保存于工作区 `.rflp/test-cache/`，缓存内容只包括规范化运行结果和 Evidence，不保存可执行产物。
- 多运行器并行只并行独立的内置运行器任务；默认并行度为 1，必须显式传入 `jobs > 1` 才启用。
- CLI、Web、`assess` 和应用层 API 都能传入运行器和资源配置。

### 非目标

- 不支持任意 shell、任意外部命令、远程执行、容器或虚拟机隔离。
- 不引入 pytest-xdist、psutil、第三方任务队列或新的数据库。
- 不把测试通过/失败直接改写为 R/F 符号匹配结果；测试仍是独立客观 Evidence。
- 不实现跨机器共享缓存、缓存 TTL、缓存垃圾回收或复杂测试选择器。
- 不承诺 Windows 上的硬内存/文件句柄限制；Windows 仍获得超时、输出上限和结果报告，并明确标记资源限制未应用。

## 方案选择

### 方案 A：内置运行器注册表 + 受控配置（采用）

运行器由代码注册，外部只能选择名称；每个运行器负责生成 argv 和解析结果。这样能覆盖当前 pytest 和常见标准库 unittest，又不会把任意命令执行面暴露给 Web 或工作区文件。

### 方案 B：允许任意参数数组

灵活性更高，但需要处理解释器路径、工作目录、环境变量、输出格式和命令白名单，且很容易让本地 Web 变成任意代码执行入口。本轮不采用。

### 方案 C：插件式运行器

适合后续接入 tox、nox、npm 或 CI provider，但当前项目尚无插件生命周期、版本治理和权限边界。本轮先用内部注册表保留未来扩展点。

## 核心接口

在 `adapters/test_executor.py` 中新增不可变配置和结果结构：

```python
DEFAULT_TEST_TIMEOUT = 60
DEFAULT_MEMORY_MIB = 1024
DEFAULT_MAX_OPEN_FILES = 1024
DEFAULT_MAX_OUTPUT_BYTES = 5 * 1024 * 1024

@dataclass(frozen=True, slots=True)
class ResourceLimits:
    timeout_seconds: int = DEFAULT_TEST_TIMEOUT
    memory_bytes: int | None = DEFAULT_MEMORY_MIB * 1024 * 1024
    max_open_files: int | None = DEFAULT_MAX_OPEN_FILES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES

@dataclass(frozen=True, slots=True)
class RunnerResult:
    runner: str
    command: tuple[str, ...]
    returncode: int | None
    timed_out: bool
    junit_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    temp_dir: Path | None
    evidence: tuple[Evidence, ...]
    diagnostics: dict[str, object]
    resource_limits: dict[str, object]
    cache_hit: bool = False
```

`run_project_tests` 保留现有函数名作为兼容入口：

```python
def run_project_tests(
    project_dir: Path,
    timeout: int = DEFAULT_TEST_TIMEOUT,
    *,
    runner: str = "pytest",
    limits: ResourceLimits | None = None,
    cache_dir: Path | None = None,
) -> RunnerResult:
```

应用层使用新的批量入口：

```python
def run_project_test_matrix(
    project_dir: Path,
    runners: tuple[str, ...] = ("pytest",),
    limits: ResourceLimits | None = None,
    cache_dir: Path | None = None,
    jobs: int = 1,
) -> tuple[RunnerResult, ...]:
```

`runners` 去重后按名称排序；`jobs` 限制 `ThreadPoolExecutor` 中同时运行的子进程数。线程只负责等待独立子进程和汇总文件，不共享可变运行状态。

## 运行器行为

### pytest

- 优先使用 `shutil.which("pytest")`；不可用时回退到当前解释器的 `-m pytest`。
- argv 为 `[pytest, "--junitxml", <temporary>/junit.xml]`。
- JUnit 继续经过现有归一化流程，移除计时/主机元数据并稳定排序。

### unittest

- argv 为 `[sys.executable, "-m", "unittest", "discover", "-v"]`。
- cwd 仍是被分析项目目录，环境设置 `PYTHONDONTWRITEBYTECODE=1`。
- 新增 `read_unittest_output(path)`：只识别形如 `test_name (module.Class.test_name) ... ok|FAIL|ERROR` 的稳定 verbose 行；按完整测试标识排序；无法识别的输出只进入诊断，不伪造测试 Evidence。
- 运行摘要使用解析出的 passed/failed 数；解析不到但进程返回 0 时允许 `tests_passed=0`，并记录 `unparsed_output=true`。

所有运行器均沿用当前 stdout/stderr 有界泵流、临时目录和失败输出尾部诊断策略。

## 资源限制

### 配置与校验

- `timeout_seconds` 必须是 1–3600 的整数；非法值抛 `ContractViolation`，不再静默改回默认值。
- `memory_bytes` 可为 `None` 表示不设置硬内存上限，否则必须至少 64 MiB。
- `max_open_files` 可为 `None` 表示不设置，否则必须至少 16。
- `max_output_bytes` 必须是 8 KiB–64 MiB；文件写入超过上限时继续消费管道但丢弃后续字节，避免死锁。

### 应用方式

子进程启动前通过 `preexec_fn` 在 POSIX 下设置：

- `RLIMIT_AS`（若平台提供）对应 `memory_bytes`；
- `RLIMIT_NOFILE`（若平台提供）对应 `max_open_files`；
- `RLIMIT_CPU` 使用不超过墙钟 timeout 的整数秒作为额外 CPU 保护。

设置时不能超过平台 hard limit；无法设置的项目写入 `resource_limits.unsupported`，不能伪造为已应用。墙钟 timeout 仍由父进程 `wait(timeout)` 强制执行，超时杀死整个当前子进程并清理临时目录。

结果中保留确定性描述：

```json
{
  "requested": {"memory_bytes": 1073741824, "max_open_files": 1024},
  "applied": ["memory_bytes", "max_open_files"],
  "unsupported": []
}
```

## 缓存

缓存键为：

```text
canonical_hash({
  "project_fingerprint": sha256(all eligible file paths + bytes),
  "runner": runner_name,
  "limits": normalized_limits,
})
```

- 项目指纹复用扫描器的隐藏目录、符号链接、大小和文件数量边界；扫描失败不命中缓存。
- 缓存目录为 `<workspace>/.rflp/test-cache/<key>.json`，使用临时文件加 `os.replace` 原子写入。
- 缓存记录包含版本、命令、规范化 stdout/stderr 尾部、returncode、timed_out、资源状态和序列化 test Evidence。
- 缓存命中时从记录恢复 `evidence` 与 `diagnostics`，路径字段为 `None`，不伪造临时文件；未命中结果仍由临时文件解析后填充这些字段。
- 只缓存已启动且有明确 returncode 的结果；启动失败和超时不写入缓存。
- 缓存损坏、版本不兼容或字段校验失败时忽略该条记录并重新执行，不删除其他缓存。
- 命中缓存时不启动子进程，但仍重扫项目并把 `cache_hit=true` 写入运行摘要。

## 应用层数据流

`execute_tests_state` 改为：

1. 校验已批准 Baseline 和已有 TaskContract；
2. 解析 runner、limits、cache 和 jobs；
3. 计算项目指纹并按 runner 查缓存；
4. 对未命中的 runner 通过矩阵入口执行，按 `jobs` 控制并发；
5. 从各 `RunnerResult.evidence` 读取 JUnit 或 unittest verbose Evidence，按 `runner + evidence.id` 去重并稳定排序；
6. 扫描项目 ActualModel；
7. 重新计算 Delta、matches 和契约状态；
8. 生成兼容的 `summary.test_run`。

单运行器时保留现有字段：`returncode`、`timed_out`、`tests_passed`、`tests_failed`、`failed_tests`、`junit_evidence`。同时增加：

```json
{
  "runner": "pytest",
  "runners": [{"runner": "pytest", "cache_hit": false, "returncode": 0}],
  "jobs": 1,
  "cache_hit": false,
  "resource_limits": {"requested": {}, "applied": [], "unsupported": []}
}
```

多运行器时聚合结果：所有进程返回 0 且未超时才算整体通过；任一失败或超时都如实反映，其他 runner 的结果仍保留。测试 Evidence 继续不参与 R/F 匹配。

`cache_hit`、临时路径和诊断尾部属于运行观测元数据，不参与 `execution.hash`；哈希只覆盖 runner、规范化结果、Evidence、资源状态、Delta 和契约状态。这样实际执行与等价缓存命中不会产生伪差异。

## CLI 与 Web

CLI 的 `project test` 和 `assess` 新增：

```text
--runner {pytest,unittest}   可重复；默认 pytest
--jobs N                     默认 1
--memory-mib N               默认 1024，传 0 表示不设置
--max-open-files N           默认 1024，传 0 表示不设置
--output-mib N               默认 5
--no-cache                   禁用读取和写入缓存
```

保留 `--timeout`。CLI JSON 输出增加 runner、cache、resource 和每个 runner 的结果；旧字段保持不变。

Web 的项目接入测试表单增加 runner 下拉框、超时、内存、文件句柄、并行度和缓存开关；只渲染 allowlist 选项，服务端再次校验。执行面板显示每个 runner 的状态、缓存命中和资源限制是否应用。

## 错误与安全

- 未知 runner、非法资源值、`jobs < 1` 或 runner 重复配置抛 `ContractViolation`。
- pytest 不可用时，选择 pytest 的执行抛 `AdapterFailure`；选择 unittest 不受 pytest 安装状态影响。
- 任一运行器的进程失败不抛应用异常，而是返回非零 `returncode` 和诊断；只有无法启动、缓存结构错误以外的适配器错误才按现有错误映射报告。
- 不使用 `shell=True`，不接受 argv 外部字符串，不继承项目指定的命令或脚本配置。
- 不把 API Key、完整环境变量、临时目录绝对路径或未截断输出写入缓存、SQLite 或审计日志。
- 需求模型变更继续清空 baseline/project，因此旧执行结果和缓存不会被错误复用；项目内容指纹变化会使测试缓存失效。

## 测试与验收

新增或更新测试覆盖：

1. pytest 与 unittest 的 argv、成功/失败摘要和 Evidence 解析；
2. 非法 runner/limits/jobs、pytest 缺失、项目目录缺失；
3. POSIX 资源设置成功、平台不支持时的显式报告；
4. 超时、输出上限和临时目录清理；
5. 相同项目和配置命中缓存，文件内容或配置变化不命中，损坏缓存安全回退；
6. 两个 runner 的并行执行、`jobs=1` 确定性和任一失败时的聚合状态；
7. application、CLI、Web 的新参数、旧参数兼容、execution hash 确定性；
8. 全量 `pytest`、`lint-imports`、`python -m build`。

验收条件：

- 默认 `rflp project test` 行为与当前 pytest 单运行器结果兼容；
- 同一项目、runner、资源配置重复执行时，首次实际执行、后续缓存命中都产生相同规范化 execution hash；
- 运行器失败、超时、资源限制不支持时均如实呈现，不伪造 passed 或 resolved；
- 缓存和并行不改变 Delta、TaskContract 的实现符号语义。
