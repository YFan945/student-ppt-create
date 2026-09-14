# Presentation Brief

topic: 基于用户论文的答辩陈述
scenario: defense
audience: 答辩委员会
language: Chinese
duration_min: 10
slide_count: 12

## 检索限制（关键，scope = D）
- 仅可使用用户提供的材料，禁止任何联网检索。
- 所有 source 的 type 必须为 `user-file`，`queries` 必须为空数组。
- 若材料不足以支撑某 claim，写入 `unresolved` 并说明 impact，禁止联网补全。
- 这是 D 模式的硬契约：违反任一条即为研究失败，而非"降级通过"。

## 待证内容
- 论文的核心贡献点
- 实验设置与关键指标
- 与已有工作的差异

## 约束
- 不编造任何数字；材料中没有的指标不得出现。
- 输出语言：中文
