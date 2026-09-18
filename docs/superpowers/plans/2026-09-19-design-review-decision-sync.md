# 设计审查决策同步实施计划

## 目标

让 3.3 的人工审查决策成为 ModelGraph 和交付包中的唯一最新事实。

## 步骤

1. 为 Review finding 决策增加已应用 CAD `PhysicalBlock` 定位和 CAS Patch 回写。
2. 对锁定 PhysicalBlock 保持写保护，不能通过审查接口绕过锁定。
3. 增加 API/应用/E2E 验收，检查 Review、ModelGraph、SysML 和交付包一致。
4. 运行全量离线门禁，更新能力文档，提交并推送。

## 非目标

本次不改变 DFM/DFA 规则算法、不自动修改几何、不把开发期规则结果升级为正式制造结论，也不连接远程模型或 FreeCAD。
