# RFLP-Lite 任务契约执行最小设计

**日期：** 2026-08-05
**状态：** 待实现
**前置：** Python 项目接入已完成（`2026-08-05-rflp-lite-project-bridge-design.md`）

## 目标

把「项目接入 → 分析出 MISSING/EXTRA → 派生 TaskContract」闭环为「执行验证 → 报告每条任务契约是否已满足」。用户对项目作出修改后，可重新扫描项目目录，对每条已派生的 TaskContract 给出确定性的 `RESOLVED` / `UNRESOLVED` 判定，并回写基线差异计数与审计事件。

## 定位与边界

本迭代的“执行”是**确定性重验证循环**，不是运行任意用户代码：

- 重新扫描项目目录（反映用户对代码/测试的改动），不执行任何子进程；
- 对已批准基线重新计算 Delta，据此判定每条既有 TaskContract 是否满足；
- 保持项目全程只读、不复制、不上传。

**不实现**：运行用户测试命令、沙箱执行器、写回代码、动态任务重排。真正运行测试命令需要一个独立的、带超时与隔离的执行器，留作下一步（见文档末尾）。

## 判定规则

- 对每条既有 TaskContract，取其首个 `target_id`（分析时派生自 Delta 项的 `MISSING` 基线元素或 `EXTRA` 实际元素）；
- 重新计算该批基线的 Delta，得到 `open_targets = {item.target_id for item in delta.items}`；
- `target_id ∉ open_targets` → `RESOLVED`（该差异项已消失：缺失义务补上了，或多余实现被移除）；
- 否则 → `UNRESOLVED`（差异仍在）。

## 领域与数据结构

不新增领域数据类（复用 `ActualModel`/`Evidence`/`Delta`）。应用层新增：

```python
@dataclass(frozen=True, slots=True)
class VerifyResult:
    model: ActualModel
    evidence: tuple[Evidence, ...]
    delta: Delta
    matches: tuple[dict, ...]
    statuses: tuple[dict, ...]   # [{"task_id","target","status"}, ...] 按 task_id 排序
    hash: str
```

`state["project"]["execution"]`（全部可 JSON 序列化，排序确定）：

```python
{
  "source": "<resolved 项目绝对路径>",
  "actual_model_id": str,
  "actual_model_hash": str,
  "contract_statuses": [{"task_id", "target", "status"}, ...],
  "summary": {
    "files_used", "matched", "missing", "extra",
    "tests_passed", "tests_failed",
    "resolved": int, "unresolved": int,
  },
  "hash": canonical_hash(该 execution 对象),   # 确定性
}
```

## 应用层（`application/project_bridge.py` 新增）

```python
def verify_contracts_state(state, source) -> tuple[dict, VerifyResult]:
    # 要求 state["baseline"] 存在，否则 ContractViolation("请先批准基线")
    # 要求 state["project"]["tasks"] 非空，否则 ContractViolation("请先在项目接入中分析项目并生成任务契约")
    # scan_project → evidence_from_actual → compare_baseline_with_actual
    # 逐条契约判定 RESOLVED/UNRESOLVED（按 task_id 排序）
    # 写 state["project"]["execution"]，返回 (state, VerifyResult)
```

`matched` 记为目标匹配记录数（`len(matches)`）。

## Facade（`application/web_facade.py` 新增）

```python
def verify_workspace_project(self, workspace_name, source) -> dict:
    # 空工作台 → ContractViolation
    # 事务内：save_workbench + save_evidence(verify.evidence)
    #         + record_audit("project.executed", {"source", "resolved", "unresolved", "missing", "extra"})
```

基线不改，无需重写 `save_baseline`。

## Web 接入

| 方法 | 路由 | 用途 |
|---|---|---|
| POST | `/w/{ws}/project/verify` | 表单字段 `source`，重验证任务契约 |

页面在“项目源码”面板的分析表单下方新增“执行验证”表单（`source` 输入框用 `state.project.source` 预填），并在 `state.project.execution` 非空时显示“任务契约执行验证”面板：metric-row 摘要（resolved/unresolved/missing/extra/测试）、按条契约的 `RESOLVED`/`UNRESOLVED` badge 列表。复用现有 `panel`/`metric-row`/`review-list`/`review-row`/`status-badge` 类；`RESOLVED` 用 `accent` 色、`UNRESOLVED` 用 `danger` 色（在 `app.css` 各加一行 modifier）。

## CLI（`interface/cli.py` 新增）

```text
rflp project verify --workspace <path> --source <dir>
```

成功输出规范化 JSON：`{"status":"ok","actual_model_id", "resolved", "unresolved", "missing", "extra"}`；失败沿用 stderr JSON + 退出码 1。

## 门禁与失效

- 执行验证要求已批准基线 + 已有任务契约；两者缺一即明确报错；
- 修改需求（review/accept/generate）会清空 `baseline` 与 `project`，因此也会清空 `execution`（随 `project` 一并失效）；
- 扫描仍受既有上限约束（400 文件 / 深度 6 / 单文件 1 MiB / 跳过隐藏与依赖目录）。

## 确定性

- 所有 id/哈希来自 `canonical_hash`；`contract_statuses` 按 `task_id` 排序；`summary` 计数来自排序后的重扫；
- 同一项目目录、同一批准基线重复验证产生字节一致的 `state["project"]["execution"]`；
- 不写入时间戳。

## 验证

新增测试：

1. `tests/application/test_project_bridge.py`：
   - 未批准基线 / 无任务契约时 verify 抛 `ContractViolation`；
   - 单条英文义务、初始未实现 → 2 条 MISSING 契约；往项目补符号后验证 → 全部 `RESOLVED`、`missing=0`；重复验证字节一致；
   - 验证后修改需求 → `execution` 随 `project` 清空。
2. `tests/interface/web/test_project.py`：无基线 verify 返回 422；分析后 verify → 页面显示执行面板与 `RESOLVED`/`UNRESOLVED`。
3. `tests/interface/test_cli.py`：`project verify` 成功 JSON 与缺前置条件的失败退出。

回归：`pytest` 全量、`lint-imports` 3 contracts、`python -m build`。

## 下一步（不在本迭代）

真正的“运行测试命令”执行器：配置化、带超时与隔离，把 JUnit 结果回填为 Evidence 再重算 Delta；需要独立的执行安全设计和资源上限。