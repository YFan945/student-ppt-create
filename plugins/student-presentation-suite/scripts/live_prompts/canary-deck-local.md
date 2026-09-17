/student-presentation-suite:sp-deck

这是固定的 Live E2E 成本 canary：请创建一份 **6 页中文课程汇报 PPTX**，主题是“操作系统 CPU 调度算法入门”。

使用 work-id：`canary-deck-local`。
研究范围：**C（仅使用本消息提供的事实，不进行 WebSearch/WebFetch）**。
听众：本科操作系统课程同学；时长约 6 分钟；16:9；风格简洁、清晰、适合课堂展示。

必须覆盖以下事实，不要扩展成需要外部检索的新事实：
- FCFS：按到达顺序执行，简单，但长作业可能导致 convoy effect。
- SJF：优先选择预计 CPU burst 较短的作业；若能准确估计 burst，可降低平均等待时间，但长作业可能饥饿。
- Round Robin：每个就绪进程获得固定时间片；时间片过大时趋近 FCFS，过小时上下文切换开销增加。
- HRRN：响应比 R = (等待时间 + 服务时间) / 服务时间 = 1 + 等待时间 / 服务时间；等待时间增长会逐步提高长作业优先级。
- 调度算法没有脱离工作负载的绝对最优解，比较时至少关注响应时间、等待时间、公平性和切换开销。

建议结构：封面；调度问题与评价指标；FCFS/SJF；Round Robin；HRRN；比较与结论。

**本回合只执行到 Production Summary。** 请生成并持久化 intake 所需文件，展示 Production Summary 后停止，等待下一条用户消息确认。不要提前 plan/build/render/qa，也不要向我追问可自行采用的默认项。
