# 通用自然语言 CAD Profile 设计

## 背景

当前详细设计切片已经能把支架/底座意图编译为 `add_rib`/`add_fillet`，但壳体、轴、齿轮只停留在目标识别和基础包络层。这样 3.1 的自然语言入口无法对常见零件类型形成真正的参数化建模链，也限制了 3.2 标注和 3.3 规则审查的特征证据。

## 目标

1. 在同一份设计意图契约下，为壳体、轴、齿轮生成可审查的参数化 CAD 操作。
2. Preview 与远程 FreeCAD 共享操作名称、参数、依赖和校验规则。
3. 参数缺失时继续生成澄清问题，不猜测关键工程尺寸。
4. 新特征进入既有 2D/3D 标注与 DFM/DFA 规则输入，保留候选/开发证据状态。
5. 不启动模型、服务器、SSH 或 FreeCAD；本轮只验证离线 preview 与生成脚本契约。

## 方案

采用有限 profile 编译器，不把自然语言直接转成 CAD/Python。规则入口识别目标零件和已知参数，产生 allowlist 操作：

| profile | 关键参数 | 操作结果 |
| --- | --- | --- |
| housing | length/width/height、wall_thickness、孔径 | 外壳、内腔、安装孔、材料 |
| shaft | diameter/length、step_diameter/step_length | 圆柱轴、阶梯段、圆角/材料 |
| gear | module、teeth、face_width、bore_diameter | 齿轮坯、中心孔、齿形候选特征 |

缺失 profile 必填参数时，计划仍保存为 `needs_clarification`，不会通过审批。Preview 对复杂特征输出确定性近似实体和完整特征参数；远程 FreeCAD 脚本使用相同参数构造真实几何。所有模型继续经过 preview → approval → execution，应用到 ModelGraph 前仍保留设计审查记录。

## 验收

- 三类自然语言输入分别识别为 `housing`、`shaft`、`gear`，并产生对应结构选项和澄清问题。
- 完整参数输入能生成至少一种非空、可校验的 profile 操作链；操作依赖、preview hash 和模型特征稳定。
- Preview payload、DrawingAnnotation 和 DFM/DFA review 能读取新特征，缺失材料/壁厚/工具可达性仍生成 finding。
- 旧支架/底座、需求→CAD 追溯、SysML/交付包和全量离线验证不回归。
