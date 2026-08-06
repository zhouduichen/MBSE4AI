# RFLP-Lite 测试执行沙箱最小设计

**日期：** 2026-08-06
**状态：** 待实现
**前置：** 任务契约执行已完成（`2026-08-05-rflp-lite-contract-execution-design.md`）

## 目标

在“任务契约执行（resolve/unresolved 重验证）”之上，增加真正运行项目测试的沙箱：配置化、带超时与隔离地运行 `pytest`，把 JUnit 结果归一化后回填为客观 Evidence，再重算与已批准基线的差异，并在执行面板报告测试通过/失败与证据计数。

## 定位与安全边界

这是本地工具中唯一执行子进程的边界，因此刻意收紧：

- **命令固定**为 `pytest --junitxml <临时目录>/junit.xml`，不接收任意 shell/命令字符串（没有任何注入面）；`pytest` 通过 `shutil.which` 解析，找不到即明确报错；
- **强制超时**（默认 60s，CLI 可 `--timeout`），超时即 `kill` 并标记 `timed_out`；
- **隔离**：cwd 为被分析项目目录，但所有输出（junit/stdout/stderr）写入全新临时目录，不污染项目；`PYTHONDONTWRITEBYTECODE=1` 避免写 `__pycache__`；结束后清理临时目录；
- **确定性**：归一化 JUnit（去掉 `time` / `timestamp` / `hostname` / `id`，按 `classname+name` 排序 testcase），使同一项目、同一测试结果产生字节一致的 Evidence 与输出；测试结果本身取决于项目，属客观事实而非伪造；
- 运行 pytest 会执行项目自身测试代码——这是本地单用户工具的有意行为，等同用户自己在终端跑测试；文档明确标识。

## 适配器（`adapters/test_executor.py` 新增）

```python
DEFAULT_TEST_TIMEOUT = 60

@dataclass(frozen=True, slots=True)
class TestRun:
    junit_path: Path | None
    stdout_path: Path
    stderr_path: Path
    temp_dir: Path
    returncode: int | None
    timed_out: bool

def run_project_tests(project_dir: Path, timeout: int = DEFAULT_TEST_TIMEOUT) -> TestRun:
    # resolve 后必须是目录，否则 ContractViolation("项目目录不存在或不是目录")
    # shutil.which("pytest") 为 None → AdapterFailure("未找到 pytest，无法运行项目测试")
    # 临时目录 mkdtemp；[pytest, "--junitxml", junit] 以 cwd=project_dir 运行
    # Popen + wait(timeout)；TimeoutExpired → kill + timed_out=True
    # junit 存在则 _normalize_junit(junit)；返回 TestRun

def _normalize_junit(path: Path) -> None:
    # ElementTree 解析；对 testsuite/testcase 移除 time/timestamp/hostname/id；
    # 移除 system-out/system-err；testcase 按(classname,name)排序；写回原临时文件
```

适配器只依赖标准库（`subprocess`,`tempfile`,`shutil`,`os`,`xml.etree`），不新增依赖。`read_junit`（`evidence_readers.py`）原样复用，因为归一化后的 junit 已无计时字段，`artifact_hash` 与 `details.duration` 都确定。

## 应用层（`application/project_bridge.py`）

把 `verify_contracts_state` 的重扫部分提取为共享内部函数，保持其对外行为不变：

```python
def _build_execution(state, baseline, model, evidence, extra_summary=None) -> tuple[dict, VerifyResult]:
    # compare_baseline_with_actual → 逐条契约 RESOLVED/UNRESOLVED
    # 组装 state["project"]["execution"]（含可选 extra_summary），hash = canonical_hash(execution)

def verify_contracts_state(state, source):
    # 要求 baseline + 现有 tasks；scan → evidence_from_actual → _build_execution

def execute_tests_state(state, project_dir: str | Path, timeout=DEFAULT_TEST_TIMEOUT) -> tuple[dict, VerifyResult]:
    # 要求 baseline + 现有 tasks（缺一即 ContractViolation，文案同 verify）
    # run_project_tests(resolved, timeout)
    # scan_project(resolved) → implementation evidence
    # junit 存在 → read_junit(junit_path) → test evidence
    # evidence = sorted(impl + test)
    # extra_summary = {"test_run": {returncode, timed_out, tests_passed, tests_failed, junit_evidence}}
    # _build_execution(..., extra_summary)
    # finally 清理 run.temp_dir
```

`read_junit` 的 Evidence `status` 为 passed/failed，`target_id=verification-<case>`；测试证据不参与 R/F 匹配（`compare_baseline_with_actual` 只匹配 class/function/api-operation），因此**测试结果不改变契约 RESOLVED/UNRESOLVED**——它作为独立的客观验证证据存在，与实现符号层面的差异分开呈现。

## Facade（`application/web_facade.py`）

```python
def test_workspace_project(self, workspace_name, timeout=DEFAULT_TEST_TIMEOUT) -> dict:
    # 空工作台 → ContractViolation
    # 取 state["project"]["source"] 作为项目目录（复用已分析项目），无则 ContractViolation
    # 事务内 save_workbench + save_evidence + record_audit("project.tested", {"source","returncode","timed_out","tests_passed","tests_failed"})
```

## Web 接入

| 方法 | 路由 | 用途 |
|---|---|---|
| POST | `/w/{ws}/project/test` | 用已分析项目的 source 运行 pytest 沙箱 |

页面在“项目源码”面板新增“运行项目测试（pytest，默认 60s 超时）”按钮（复用 `state.project.source`，无需手动输入路径）；在“任务契约执行验证”面板内，当 `execution.summary.test_run` 存在时显示测试运行子块：returncode、是否超时、passed/failed、证据数。复用现有 `panel`/`metric-row`/`status-badge` 类。

## CLI（`interface/cli.py`）

```text
rflp project test --workspace <path> --source <dir> [--timeout 60]
```

成功输出规范化 JSON：`{"status":"ok","actual_model_id","returncode","timed_out","tests_passed","tests_failed","resolved","unresolved"}`；失败沿用 stderr JSON + 退出码 1。

## 门禁与失效

- 未批准基线 / 无任务契约 → 明确报错（同 verify）；
- 项目目录不存在 → ContractViolation；找不到 pytest → AdapterFailure；
- 修改需求（review/accept/generate）仍清空 `baseline` 与 `project` → 连执行结果一并失效；
- 测试超时/失败不伪造结果：`timed_out` 与 `returncode` 如实记录，无 junit 产出的运行在 `test_run` 中记 `junit_evidence=0`。

## 确定性

- 归一化 junit 后 `read_junit` 的 `artifact_hash` 与 `details` 确定；`execution` 的 `hash` 来自 `canonical_hash`；
- 同一项目目录、同一测试结果重复运行产生字节级一致的 `state["project"]["execution"]`；
- 不写入时间戳。

## 验证

新增测试：

1. `tests/adapters/test_test_executor.py`：构造最小 pytest 项目（含一个通过测试），`run_project_tests` 返回 returncode 0、junit 存在且已归一化（无 time 属性、testcase 排序确定）；无 pytest 时（monkeypatch `shutil.which`）抛 AdapterFailure；不存在目录抛 ContractViolation；超时（monkeypatch timeout 极小 + 睡眠测试）`timed_out=True`；归一化后重复运行 junit 字节一致。
2. `tests/application/test_project_bridge.py`：未批准基线 / 无任务契约时 `execute_tests_state` 抛 ContractViolation；对含通过测试的项目执行后 `test_run` 记录 returncode/passed；重复执行 `execution` 字节一致。
3. `tests/interface/web/test_project.py`：无基线 `POST /project/test` 返回 422；批准+分析后执行 → 页面显示测试运行子块。
4. `tests/interface/test_cli.py`：`rflp project test` 成功 JSON 与缺前置退出码。

回归：`pytest` 全量、`lint-imports` 3 contracts、`python -m build`。

## 下一步（不在本迭代）

多运行器配置（非 pytest）、资源上限（内存/文件句柄）、结果缓存与并行执行、把测试证据纳入契约验收判定。