# Operational 9-Task Acceptance

## Frozen execution conditions

- Harness production baseline: `b1f8aaf4b6fc8ed79871ed213f41b49db4a23ffb`
- Probe driver baseline: `e5a4fc9` (`scripts/pr09_relation_policy_probe.py`)
- Provider: Windows 5080 Ollama
- Model: `qwen3.5:9b-q8_0`
- Temperature: `0.0`
- Seed: unset
- Context budget: `2000`
- Prompt reserve: `256`
- `max_output_tokens`: `4000`
- Input fixture: `tests/e2e/fixtures/campus_delivery_robot.json`

The final five runs used identical prompt and TaskSpec hashes:

| Task | Prompt hash | TaskSpec hash |
| --- | --- | --- |
| `system_definition` | `7c7efe08d7f5888224d3e102c8c9c3da919c339b8b2666d3d8d13600545da01c` | `95c66b19b1c2623299f014d7b63fb8c1360d42a2c8062790884c83ca8de0b0f9` |
| `stakeholder_analysis` | `fa9dc42502ec6ae7acb1b22689b7e41c6c9112b68b82b2b893a68f3b0a69ccf9` | `a777d6fac6eaa9073969892a92e5edbb2959bff8983831b7bd33c08dded3c970` |
| `stakeholder_requirements` | `887cc5516797234f59a086220c85944fbdd651ad5a3c344e6b854d93b257e0ae` | `e96e548e188453aa16050f908a6cf8e71e34c165fa3570d7d938aa184c9c19c7` |
| `lifecycle_analysis` | `26fd450188e7330cc3a6a934a76db88684969e3df8403e68d716c72e8de6186f` | `389372a54be3af7d2020407877f517f6821c9d6930d53d79a33e26609a2616ee` |
| `scenario_exploration` | `e777147f36c078e037032f64f4e2c91af82fcb46a967253e3797d000eced130e` | `295915656efb1ea798c229a6b8e0fef3b71a0f4fc909f2191f749c8dd62d7401` |
| `use_case_analysis` | `3e6b2ae9fd3b74b6375049173c172ab1c682927875ae4fd12b561a36c82ca7b2` | `31272be969e2a81256fd92279aec7991ea424711fc61263f66c31c1d35fbdb20` |
| `operational_scenario` | `e42a3352affbec1905bd1cfeb278b8f88aaa5dd320da52570f991d5e9c4f3d03` | `b18023911293fe42ce66dc34939ac2ec388a525a025e6324f93e19f806b52b82` |
| `activity_analysis` | `5b09160bc08ea64f0128b1c7b0759f287c805c0128c531bb686ac552064541bd` | `a003d6acf2d1c62e2e337554e6830e29486ffe1889bf6e3ae71a8f431d579d28` |
| `system_requirement_derivation` | `3918cba63a1bde3df61b77c716ff4eb7c27b56119ce3ab229de1c4c76e13cd48` | `4b9db992083995cb9d4ada5e83797ba6656866f0a12aa9dca58ff95594fda94f` |

## Execution results

| Run | Result | Provider calls | Terminal failures | Revision delta |
| --- | --- | ---: | --- | ---: |
| 9-task ×1, before relation-direction fix | 7/9 completed; `scenario_exploration` and `operational_scenario` degraded | 9 | 2 semantic endpoint failures | `+7` |
| 9-task ×1, after relation-direction fix | 9/9 completed | 10 | 1 transient transport error, recovered by retry | `+9` |
| 9-task ×5, stability | 45/45 completed; 5/5 runs completed | 45 | 0 | `+9` each run |

The final stability run had 45/45 `finish_reason=stop`, zero structural,
compiler, transport, semantic, or identity failures, zero duplicate
`local_ref`, zero failed/blocked task with a patch, and no structural retry.
Revision increments matched the number of committed task patches in every
run.

## Operational Gate and trace inspection

The current `O-Gate` implementation passed 5/5. Its current contract checks
presence of stakeholder, lifecycle, scenario, use-case, and requirement kinds;
it does not yet require the full cross-task provenance chain.

The final graph was structurally valid with zero invalid relation endpoints.
Representative relation counts in each of the five final repositories were:

- `Stakeholder --hasConcern--> Concern`: 2
- `Requirement --derivedFrom--> Concern`: 3
- `UseCase --derivedFrom--> Stakeholder`: 4
- `OperationalScenario --derivedFrom--> UseCase`: 5
- `Stakeholder --participatesIn--> OperationalScenario`: 5
- `Requirement --derivedFrom--> Activity`: 1

The following gaps remain visible in the explicit relation graph:

- `ScenarioHypothesis` has no outgoing provenance relation to Stakeholder,
  Concern, or LifecycleStage.
- `Activity` has no outgoing relation to its source
  `OperationalScenario`.
- `UseCase` is linked to Stakeholder, but not explicitly to
  `ScenarioHypothesis`.
- Several generated entities carry source IDs inside payload fields; those
  fields are not equivalent to typed ModelGraph relations for trace analysis.

Therefore the correct status is:

```text
Operational execution stability       PASS (45/45)
Operational Gate implementation       PASS (5/5)
Operational explicit trace completeness PARTIAL
Functional phase                      NOT STARTED
23-task lifecycle                     PENDING
```

Primary evidence:

- `relation-policy-operational-9-task-v2-20260913.json`
- `relation-policy-operational-9-task-stability-20260913.json`
