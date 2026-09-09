# public-real-v1 数据字典

本目录的 `historical_uav_public_facts.*` 是公开事实层；`fixed-wing-schemes-public-demo.*` 是为了当前 `fixed-wing-v1` 直接运行而建立的方案层。两者不可互相替代。

| 字段 | 中文含义 | 单位 | 使用模块 | 公开资料情况 | 当前 Demo 的缺失/语义处理 |
|---|---|---:|---|---|---|
| `mass_kg` | 非任务载荷质量代理；MQ-1B 为公开空重，其余多数行按 `public_mtow_kg - payload_kg` 计算 | kg | 2.1 检索、2.2 重量平衡/约束 | 空重通常不完整，MTOW 和任务载荷更常见 | 不得解释为官方 empty weight；用 `mass + payload` 回到公开 MTOW |
| `payload_kg` | 最大任务载荷 | kg | 2.1 检索、2.2 重量平衡 | 部分型号有官方/制造商公开值 | 保留来源；不把任务载荷和空重混为一列 |
| `wing_area_m2` | 机翼面积 | m² | 2.1 检索、2.2 气动 | 公开资料常缺失 | 使用显式 `demo_assumption`，通常为 `span² / assumed_AR` |
| `span_m` | 翼展 | m | 2.1 检索、2.2 气动/约束 | 通常可从公开规格得到 | 保留公开值和来源；不与机翼面积混淆 |
| `fuselage_length_m` | 机身长度 | m | 2.1 检索、2.2 重量平衡/布局 | 通常可从公开规格得到 | 保留公开值和来源 |
| `cruise_speed_mps` | 用于当前 Demo 的巡航/任务速度 | m/s | 2.1 检索、2.2 气动 | 公开来源有时只给 KTAS、km/h、范围或最大速度 | 做确定性单位换算；`public_speed_basis` 说明速度语义，不能把最大速度写成巡航速度 |
| `section_modulus_m3` | 截面模量占位参数 | m³ | 2.2 结构 | 通常不是公开型号级参数 | `demo_assumption`，按 `3.0e-5 * published_MTOW_kg`，不是飞机真实结构属性 |
| `allowable_stress_pa` | 当前低阶结构计算用的允许应力占位值 | Pa | 2.2 结构 | 飞机特定允许值不公开 | 由材料公开屈服强度确定性计算的测试值；不是适航允许值 |
| `cg_x_m` | 重心纵向位置占位值 | m | 2.2 重量平衡 | 通常缺少型号级公开 CG | `demo_assumption`，按 `0.30 * published fuselage length` |
| `air_density_kg_m3` | 空气密度 | kg/m³ | 2.2 气动 | 标准大气参考可公开 | 使用 NASA 公共标准大气海平面值 1.225；不是实测任务环境 |
| `cd0` | 零升阻力系数占位值 | 1 | 2.2 气动 | 通常不公开 | 使用 `fixed-wing-v1` 默认值 0.025；仅用于 development evaluator |
| `oswald_efficiency` | 奥斯瓦尔德效率因子占位值 | 1 | 2.2 气动 | 通常不公开 | 使用 `fixed-wing-v1` 默认值 0.8；仅用于 development evaluator |
| `load_factor` | 结构计算载荷因子 | 1 | 2.2 结构 | 任务/型号级值不一定公开 | 使用 `fixed-wing-v1` 默认值 3.5；不是认证载荷包线 |

字段来源和证据级别保存在方案的扩展字段（如 `*_provenance`、`source_url`、`data_status`）中。`demo_assumption` 仅用于软件功能演示，不是原型号真实内部设计参数。
