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

## researcher-resume（基础设施故障恢复）

仅当研究员因 API 错误等非内容原因在写出可解析 pack 前终止、且检索证据已落盘时使用；
同一会话恰好恢复一次。这是宿主 Agent 工具的 resume 能力，不是重新 spawn，spawn 一次的
限制不变。unknown_payload 或校验失败的 pack 不恢复——记 blocked，等待用户明确补检指令。

```text
你是本 deck 的隔离研究员，恢复被基础设施故障（API 错误）中断的同一次研究任务。
按 student-presentation-suite:presentation-researcher 契约执行。
- research-task（绝对路径，沿用原任务文件，不得改动）：<work-dir>/research-task.json
- work-dir（唯一写盘位置，绝对路径）：<absolute work-dir>
检索证据已在 research/ 落盘：只基于已收集证据写出/补全 Research Pack，不得重新检索、
不得新增来源；引用逐字绑定既有 text_path 与 sha256，不凭记忆重写摘录。
先写 pack 再执行 validate_research_pack.py；输出信封与校验契约不变，只回
RESEARCH_DONE / RESEARCH_BLOCKED 信封，原始结果留在 research/。
```

恢复前主流程先运行 `research_control.py --work-dir <wd> --resume --reason "recovered_from: crash: <具体错误>"`
记入研究轨迹；信封与 pack 校验按首发同一契约收口。
