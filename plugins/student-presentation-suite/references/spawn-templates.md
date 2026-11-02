# Researcher spawn and continuation

Only external evidence retrieval uses an isolated researcher; page production stays in the main session.

## researcher

```text
你是本 deck 的隔离研究员，执行 student-presentation-suite:presentation-researcher。
- research-task: <absolute work-dir>/research-task.json
- work-dir: <absolute work-dir>
先读取任务和已有进度，按 research-workflow.md 只补当前缺口。
默认回 RESEARCH_DONE/RESEARCH_BLOCKED 路径与状态；资料留 research/。
```

## researcher-resume

任务中断、内容修复和定向补检均可继续。优先宿主 resume；旧研究员已结束时允许顺序重新派发，禁止同一任务并发重复执行。
需要时主流程运行 research_control.py --resume --reason <本次具体目标>，不要求 recovered_from: crash 前缀或恢复次数。

```text
继续相同研究任务：
- research-task: <absolute work-dir>/research-task.json
- work-dir: <absolute work-dir>
保留已完成证据，仅修复校验指出的实际内容问题并补明确缺口。
普通 source-backed-v1 不要求重建 sha256/fetch回执链；读取PDF、OCR和表格均可。
遇到疑点可回传少量关键摘录，默认信封和路径。
```

scope 和具体证据规则由 research-workflow.md 所有；任务修改不需要重抄背景或数字。

研究任务的验收条件来自用户要求，不能把代理自定的精确分布变成核心缺口。研究员结束后以当前交接为准；迟到完成通知指向相同产物时不再次研究或触发PPT重建。具体恢复与收口规则见research-workflow.md。
