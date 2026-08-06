# RFLP-Lite Python 项目接入最小设计

**日期：** 2026-08-05
**状态：** 待实现
**前置：** 需求工作台已完成（`2026-08-04-rflp-lite-requirements-workbench-design.md`）

## 目标

把需求工作台产出的已批准 RFLP 模型与一个真实本地 Python 项目接通，补齐 `DEVELOPMENT_STATUS.md` 中标注为“下一独立子项目”的链路：

```text
已生成 RFLP（工作台）
→ Baseline（人工显式批准）
→ 本地 Python 项目目录扫描
→ ActualModel（模块 / 类 / 函数 / API 操作 / 测试用例）
→ Evidence（逐项观察证据）
→ Delta（MISSING / EXTRA）
→ TaskContract（修复契约，含依赖顺序）
```

完成后，用户可以从自己的需求出发，看到“应该有什么”（Baseline）与“实际有什么”（ActualModel）之间的确定性差异，并得到带验收条件的任务契约。

## 范围

首版只实现：

- 工作台 RFLP 的人工显式基线批准（独立按钮，审计事件记录）；
- 服务器本地目录扫描：Python AST、OpenAPI JSON、JUnit XML 三类制品；
- ActualModel 领域对象与确定性 Evidence 派生；
- Baseline 与 ActualModel 的名称关键词匹配、MISSING/EXTRA Delta；
- 复用现有 `build_task_contracts` 派生任务契约；
- 新页面 `/w/{workspace}/project`（项目接入）与三个 POST/GET 路由；
- CLI 子命令 `rflp project approve` 与 `rflp project analyze`；
- SQLite 持久化（workbench 状态 + baselines/evidence/tasks 表）与审计事件；
- 工作台 JSON 派生的确定性下载：baseline、actual-model、matches、delta、task-contracts、evidence、project 汇总。

不实现：拖拽编辑、远程仓库拉取（git clone）、测试实际执行（只解析已有 JUnit 结果）、Python 以外语言、相似度自动合并、LLM 参与匹配。

## 复用边界

继续使用现有 FastAPI、Jinja、SQLiteRepository、Workspace、`approve_baseline`、`build_task_contracts`、`Evidence`、`Delta`、`DeltaItem`、`canonical_hash/canonical_json`。不新增前端构建工具、数据库或第三方依赖（扫描与解析只用标准库 + 可选依赖 prance/junitparser 的现有用法）。

现有 `application/diff.py::calculate_delta` 与 `application/demo.py` 行为保持字节级不变；新链路是新增函数与新模块，不改写演示管线。

## 领域新增（`domain/models.py`）

```python
@dataclass(frozen=True, slots=True)
class ActualElement:
    id: str
    kind: str          # module | class | function | api-operation | test-case
    name: str
    source: str        # 相对路径:行号 或 openapi/junit 定位
    artifact_hash: str # 所在文件内容 sha256
    status: str = "observed"          # test-case 为 passed/failed
    details: tuple[KeyValue, ...] = ()

@dataclass(frozen=True, slots=True)
class ActualModel:
    id: str            # actualmodel-<hash[:12]>
    source_root: str   # 被扫描目录名（不存绝对路径，路径只进审计与工作台 source 字段）
    elements: tuple[ActualElement, ...]
    hash: str          # canonical_hash(elements)
```

领域层只增加数据类，不引入新依赖，保持 domain-independence 契约。

## 适配器新增（`adapters/project_scanner.py`）

```python
MAX_FILES = 400
MAX_DEPTH = 6
MAX_FILE_BYTES = 1024 * 1024
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".tox",
             ".mypy_cache", ".pytest_cache", ".hypothesis", "dist", "build",
             ".idea", ".vscode", "site-packages"}
SCAN_SUFFIXES = {".py", ".json", ".xml"}

def scan_project(root: Path) -> tuple[ActualModel, dict[str, object]]:
    """返回 ActualModel 与扫描摘要。摘要字段：
    files_seen, files_used, files_skipped_size, files_skipped_limit,
    parse_errors（排序后的 '相对路径: 原因' 列表）。"""
```

规则：

- `root` 必须 `expanduser().resolve()` 后存在且是目录，否则 `ContractViolation("项目目录不存在或不是目录")`；
- 手工递归遍历（不用 `os.walk` 的 followlinks），目录条目按名称排序，保证确定性；跳过 `SKIP_DIRS`、所有以 `.` 开头的目录、符号链接（目录与文件均跳过）；
- 深度超过 `MAX_DEPTH` 或已用文件数达到 `MAX_FILES` 后停止收录并计数 `files_skipped_limit`；
- 单文件超过 `MAX_FILE_BYTES` 计 `files_skipped_size` 并跳过；
- `.py`：`ast.parse` 得到 1 个 `module` 元素 + 每个 `ClassDef`/`FunctionDef`/`AsyncFunctionDef` 一个元素；解析失败计入 `parse_errors` 并跳过该文件；
- `.json`：`json.loads` 成功且顶层是 dict 且含 `openapi` 或 `swagger` 键时，按 `paths` × HTTP 方法生成 `api-operation` 元素（operationId 缺省用 `method-route`）；其余 JSON 静默跳过；
- `.xml`：先用 `xml.etree.ElementTree` 读根标签，仅当根为 `testsuites`/`testsuite` 时用 `junitparser` 解析为 `test-case` 元素（`status` 为 passed/failed）；其余 XML 静默跳过；
- 元素 id：`actual-{canonical_hash((相对posix路径, kind, name, line))[:12]}`；
  ActualModel id：`actualmodel-{canonical_hash(按id排序后的elements)[:12]}`；
- 没有任何可用元素时抛 `AdapterFailure("项目里没有可解析的 Python、OpenAPI 或 JUnit 制品")`。

## 应用层新增（`application/project_bridge.py`）

纯函数优先，事务与持久化留在 facade/CLI。

```python
def reconstruct_rflp(state) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]:
    """从 state["rflp"] 的 asdict 结构重建领域对象；
    attributes 列表还原为 tuple((str(k), v), ...)。"""

def approve_workbench_baseline(state) -> tuple[dict, Baseline]:
    """要求 state["rflp"] 非空，否则 ContractViolation("请先生成 RFLP 规划图")。
    调 domain.approve_baseline。返回新 state（写入 state["baseline"] =
    {"id","status","hash","elements","relations"}，并把 state["project"] 置 None）。"""

def analyze_project_state(state, source: str | Path) -> tuple[dict, BridgeArtifacts]:
    """要求 state["baseline"] 存在，否则 ContractViolation("请先批准基线")。
    scan_project → evidence_from_actual → compare_baseline_with_actual
    → build_task_contracts。写入 state["project"]（结构见下），返回
    BridgeArtifacts(baseline, actual, evidence, delta, tasks) 供持久化。"""

def evidence_from_actual(model: ActualModel) -> tuple[Evidence, ...]:
    """每个 ActualElement 派生一条 Evidence：
    kind 映射 module→python-module, class→python-class, function→python-function,
    api-operation→openapi-operation, test-case→test-case；
    target_id = element.id；artifact_hash = element.artifact_hash；
    details = element.details + (("name", element.name), ("actual_model_id", model.id))；
    id = evidence-{canonical_hash((model.hash, element.id))[:12]}；按 id 排序。"""
```

`state["project"]` 结构（全部可 JSON 序列化，排序确定）：

```python
{
  "source": "<resolved 绝对路径字符串>",
  "approved_baseline_id": str,
  "baseline_hash": str,
  "actual": {"id", "source_root", "elements": [...], "hash"},
  "matches": [{"baseline_id", "baseline_name", "layer", "actual_id",
               "actual_name", "actual_kind", "shared": [...]}],
  "delta": asdict(Delta),
  "tasks": [asdict(TaskContract), ...],
  "evidence": [asdict(Evidence), ...],
  "summary": {"files_seen", "files_used", "files_skipped_size",
              "files_skipped_limit", "parse_errors": [...],
              "elements_by_kind": {...}, "matched", "missing", "extra",
              "tests_passed", "tests_failed"},
}
```

## 匹配与 Delta（`application/diff.py` 新增，不改旧函数）

```python
def compare_baseline_with_actual(baseline, model) -> tuple[Delta, tuple[dict, ...]]:
    """返回 (delta, matches)。"""
```

- 分词 `_tokens(name)`：casefold；ASCII 侧用非字母数字切分，保留长度 ≥3 的词；CJK 侧提取连续 `一-鿿` 片段并保留长度 ≥2 的片段；
- 匹配只发生在 baseline 的 R/F 层元素与 actual 的 `class`/`function`/`api-operation` 元素之间；两边 token 集合交集非空即记一条 match（同一 baseline 元素可匹配多个 actual，全部记录，按 (baseline_id, actual_id) 排序）；
- MISSING：无 match 的 R/F baseline 元素，`DeltaItem(id=f"delta-missing-{element.id}", kind="MISSING", target_id=element.id, description=f"基线义务未找到实现证据：{element.name}")`；
- EXTRA：未匹配任何 R/F 的 class/function/api-operation actual 元素，`DeltaItem(id=f"delta-extra-{element.id}", kind="EXTRA", target_id=element.id, description=f"实际实现未对应基线义务：{element.name}")`；
- Delta id：`delta-{canonical_hash((baseline.hash, model.hash, ordered_items))[:12]}`，`baseline_hash=baseline.hash`；items 按 id 排序；
- `build_task_contracts(delta)` 原样复用（最多 3 条，链式依赖）。

## Web 接入

### Facade（`application/web_facade.py` 新增方法）

```python
def approve_requirements_baseline(self, workspace_name) -> dict:
    # 空工作台 → ContractViolation；事务内 save_workbench + save_baseline + record_audit("baseline.approved", {"baseline_hash": ...})

def analyze_workspace_project(self, workspace_name, source: str) -> dict:
    # 事务内 save_workbench + save_baseline + save_evidence + save_tasks + record_audit("project.analyzed", {"source": ..., "missing": n, "extra": n, "tasks": n})
```

事务内任何异常回滚（沿用 `repository.transaction()`）。

### 路由（`interface/web/routes.py` 新增）

| 方法 | 路由 | 用途 |
|---|---|---|
| GET | `/w/{ws}/project` | 项目接入页面 |
| POST | `/w/{ws}/project/approve-baseline` | 人工批准基线 |
| POST | `/w/{ws}/project/analyze` | 表单字段 `source`，扫描并生成 Delta |
| GET | `/w/{ws}/project/download/{filename}` | 白名单下载 |

下载白名单与内容来源（均为内存序列化，直接读工作台状态，不落盘新文件）：

| filename | 内容 |
|---|---|
| `baseline.json` | `state["baseline"]` |
| `actual-model.json` | `state["project"]["actual"]` |
| `matches.json` | `state["project"]["matches"]` |
| `delta.json` | `state["project"]["delta"]` |
| `task-contracts.json` | `state["project"]["tasks"]` |
| `evidence.json` | `state["project"]["evidence"]` |
| `project.json` | `state["project"]` 全量 |

缺少对应状态返回 404；非白名单文件名返回 404。错误处理沿用 `_run_error`。

### 导航与页面

`base.html` 的 Model 分组在“需求建模”后新增“项目接入”，沿用有/无工作区的链接与 muted 分支写法。

新模板 `templates/project-bridge.html`：

1. 未生成 RFLP：引导去需求建模；
2. 已生成未批准：显示元素/关系统计与“批准基线”按钮（`button primary`）；
3. 已批准：显示 baseline id、hash、批准标记；
4. 分析表单：单行输入框（本地目录路径）+“分析项目”按钮；
5. 有 `state.project` 时：metric-row 摘要（文件数、实现元素数、matched、MISSING、EXTRA、测试 passed/failed）、Delta 列表（status-badge 区分 MISSING/EXTRA）、matches `<details>` 列表、任务契约表（id/target/read/write/acceptance/depends）、下载链接组、证据按 kind 分组计数；
6. 复用现有 CSS 类：`panel`、`panel-head`、`eyebrow`、`count-badge`、`metric-row`、`status-badge`、`download-actions`、`mini-empty`；所有动态文本经 Jinja 自动转义。

## CLI 接入（`interface/cli.py`）

```text
rflp project approve --workspace <path>
rflp project analyze --workspace <path> --source <dir>
```

- 直接使用 `SQLiteRepository(<workspace>/.rflp/model.db)` + `load_workbench()`；空工作台报 `ContractViolation("需求工作台为空，请先在需求建模中生成 RFLP")`；
- 与 facade 相同的事务内容：`save_workbench` + `save_baseline`/`save_evidence`/`save_tasks` + `record_audit`；
- 成功输出单行规范化 JSON：approve → `{"status":"ok","baseline_id","baseline_hash"}`；analyze → `{"status":"ok","baseline_hash","actual_model_id","files_used","matched","missing","extra","tasks"}`；
- 失败沿用现有 stderr JSON + 退出码 1 的写法。

## 门禁与失效语义

- 基线只能由人工显式动作批准（页面按钮或 CLI 子命令）；任何 AI/自动化路径不得调用 `approve_workbench_baseline`（LLM 相关代码不新增对该函数的调用）；
- `review_item`、`accept_traceable`、`generate_model` 三处现有失效逻辑在清空 `rflp/coverage/svg` 的同时清空 `baseline` 与 `project`，避免陈旧差异继续展示；
- 读取旧工作台状态时所有新键用 `.get()`/Jinja 真值判断容错（既有数据库无新键）；
- 目录扫描只读不写；不跟随符号链接；被扫描项目内任何文件不复制到工作区。

## 确定性

- 所有 id 来自 `canonical_hash`；所有集合排序后落盘；摘要计数只依赖排序后的遍历；
- 同一目录、同一基线重复分析产生字节一致的 `state["project"]` 与各下载 JSON；
- 不在持久化内容中写入时间戳（审计事件自身的时间由 SQLite 序列表达，沿用现状）。

## 验证

新增测试（沿用现有目录约定）：

1. `tests/adapters/test_project_scanner.py`：扫描 `examples/versioned-content-service` 的元素构成；确定性；跳过规则（tmp 项目内建 `.git/`、超大文件、超限文件数）；空目录与无可用制品报错；坏 Python 文件计 `parse_errors` 不中断；
2. `tests/application/test_project_bridge.py`：工作台全链路（analyze→accept→generate→approve→analyze_project）对 `examples/versioned-content-service` 产出非空 matches/delta/tasks；重复执行字节一致；缺基线/缺 RFLP 的 ContractViolation；review 后 baseline/project 被清空；
3. Web 路由测试：页面 200 与引导文案、approve→analyze→下载白名单→404 分支；
4. CLI 测试：approve/analyze 成功 JSON 与失败退出码；
5. 回归：`pytest` 全量、`lint-imports` 3 contracts、`python -m build`。

## 完成标准

用户在本机浏览器中：从自己的需求生成 RFLP → 显式批准基线 → 指向一个本地 Python 项目目录 → 看到确定性的 MISSING/EXTRA 差异、匹配证据与任务契约，并可下载全部规范化 JSON。整条链不依赖演示 fixture，不依赖 LLM，不依赖网络。
