# 搜索研究员修复验收 — 2026-10-01

验收对象：基于 v0.24.0 / 05b5db9 的本轮工作区改动，纳入 v0.25.0；不是使用端已安装版本的验收。

## 最终真实样本

| 场景 | 状态 | 耗时秒 | 工具数 | WebSearch调用/日志失败 | 抓取失败 | 权限拒绝 |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 中文技术文档三论断 | ready / 通过 | 101.011 | 26 | 1 / 1 | 0 | 0 |
| 独立来源交叉核验 | ready / 通过 | 189.241 | 42 | 1 / 1 | 0 | 0 |
| 指定缺失页面后部分交付 | partial / 通过 | 123.105 | 31 | 0 / 0 | 1 | 0 |

缺失页面场景实际请求了指定 URL 并记录 HTTP 失败，核心证据保留、辅助论断 unresolved。
交叉核验使用不同机构来源，并保留默认 GIL 构建的限定。两个定位场景均实际调用 WebSearch；
返回未产生可用搜索结果，按发布方/已知文档 URL 直取原文后完成。不能据此宣称搜索索引恢复。

## 前轮失败与修复

- 中文政策样本提供方返回 `API Error: Output data may contain inappropriate content`，未生成包；主流程没有自行重派，失败不算通过。后改用中文技术文档作为另一场景，不掩盖原失败。
- 首轮交叉核验额外实体继承了 cross_check 却只有单组支持；保留核心证据并移除不足实体后形成 ready。已改进校验消息和实体生成纪律。
- 动态 Python 摘录、受控摘录工具附带 echo/有界 head 曾被正文防火墙拒绝；增加最多 2000 字符的摘录工具及受控命令识别，并覆盖追加 cat/整页打印仍拒绝的回归。
- 早期宿主超时存在管道/子进程遗留，主流程还自行恢复旧任务；现在保存实时流、终止验收进程树，同会话同任务只派一次。

## 验证与边界

- 完整 unittest：1283 项，1 项跳过，其余通过；ruff、插件/市场发布检查、严格 Claude manifest、git diff --check 通过。
- 来源支持复读由同一研究员执行，机器校验覆盖与声明一致性，不是独立评审，也不自动证明语义。
- 每场景仅一个最终样本；上表不作为总体成功率、所有主题耗时或提供方稳定性的承诺。
- 初始失败、复测与最终结果分别保存，不覆盖历史。生成物均在 TEMP，未写入插件目录。

## 本机证据路径

- `C:\Users\28603\AppData\Local\Temp\research-matrix-v0240-fixed`（matrix、result、stream/live 和日志）
- `C:\Users\28603\AppData\Local\Temp\research-matrix-v0240-cn-recheck`（matrix、result、stream/live 和日志）
- `C:\Users\28603\AppData\Local\Temp\research-matrix-v0240-cross-recheck`（matrix、result、stream/live 和日志）
- `C:\Users\28603\AppData\Local\Temp\research-matrix-v0240-gap-recheck`（matrix、result、stream/live 和日志）
- `C:\Users\28603\AppData\Local\Temp\research-matrix-v0240-cross-final`（matrix、result、stream/live 和日志）
- `C:\Users\28603\AppData\Local\Temp\research-matrix-v0240-gap-final`（matrix、result、stream/live 和日志）

汇总：`C:\Users\28603\AppData\Local\Temp\research-four-fixes-acceptance.json`。
复现入口与预算见本目录 README.md；临时目录可能被系统清理。
