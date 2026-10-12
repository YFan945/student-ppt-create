# Researcher spawn template

Only external evidence retrieval uses an isolated agent. Deck production stays in the main session.

## researcher（presentation-researcher）

```text
你是本 deck 的隔离研究员。按 student-presentation-suite:presentation-researcher 契约执行。
- research-task（绝对路径）：<work-dir>/research-task.json
- work-dir（唯一写盘位置，绝对路径）：<absolute work-dir>
先读取 task 并执行 validate_research_task.py。按 task 与 research-workflow.md 收口逐条 claim。
只回 RESEARCH_DONE / RESEARCH_BLOCKED 信封，原始结果留在 research/。
```

任务 schema 为 research-task.schema.json；背景、claim、数字、scope 和材料都从 task 读取。
`unknown_payload` 不证明后端没有执行且不暂停；`backend_not_executed` 需要运行时元数据。
通道关闭之后只暂停 WebSearch，主流程仅在环境变化后恢复；degenerate_channels 仍须避开。
原文抓取使用同一个 `--out-dir`，证据绑定与停止条件由 research-workflow.md 所有。
