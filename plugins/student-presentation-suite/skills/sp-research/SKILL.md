---
name: sp-research
description: Use only for a clearly student-owned academic context when a deck needs external facts, current data, statistics, or citations that must not be invented, or when the user restricts sourcing to their own material. Collects, grades, and cross-checks sources into a Research Pack. Does not design slides, write speaker notes, or produce PPTX.
version: 0.25.1
argument-hint: "[work-id] [brief-or-draft-spec-path] [scope:A|B|C|D] [materials-path-or--]"
arguments: [work_id, brief_path, scope, materials_path]
---

# Student Presentation Research

只负责学生学术 PPT 的证据层：检索、核验、留痕与 Research Pack。
设计宗旨：Search for evidence, not text。排页/讲稿归 sp-outline，PPTX 归 sp-deck。
不决定版式、不设计页面、不生成 PPTX、不撰写成段讲稿。

## 输入与隔离

1. 将 work_id、brief_path、scope、materials_path、budget、背景及逐条 claim/id/验收要求
   并设置 semantic_review_required=true，写入 `<work-dir>/research-task.json`（schema：`../../references/research-task.schema.json`）。
   work-dir 必须是当前项目 outputs/.pptx-work/<work-id> 的绝对路径，所有输入路径也用绝对路径。
2. 调用 `scripts/validate_research_task.py <task>`；失败就补齐输入，不开始检索。
3. 按 `../../references/spawn-templates.md` 显式调用 Agent，subagent_type 为
   `student-presentation-suite:presentation-researcher`，不传 name，不嵌套 spawn。
   prompt 只传 task 路径和 work-dir；不得转抄 claim/标题/数字。
   隔离不依赖 context: fork（claude -p 下曾内联 skill）；输入绑定不自动传给子代理。
4. 主流程等待 RESEARCH_DONE 或 RESEARCH_BLOCKED；无可解析信封或有效校验报告时记 blocked，
   同一会话只允许派一次该任务，不自行 resume，不再 spawn 同一任务。
   unknown_payload 不是环境变化；交付不足时报告缺口，等待用户提供新材料或明确补检指令。主会话不执行 WebSearch/WebFetch。
   收到信封后只运行一次：
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/research_handoff.py" --work-dir <work-dir>`。
   命令核验当前 pack、validation、task 和真实执行回执，只返回路径/状态/统计/缺口。
   不再逐文件检查，不重读网页，不浏览插件目录、hooks、实现代码或环境变量。

scope 为 A/B/C/D；C 不检索，D 禁止联网且只用用户材料。
D 默认用 import_user_materials.py 确定性导入；仅用户点名研究员整理时派本 agent。
缺失参数或无效 scope 不猜，返回 RESEARCH_BLOCKED。

## 工作流与输出

详细政策只由 `../../references/research-workflow.md` 所有；按需读 evidence-and-citations.md
及 research-pack.schema.json，不 grep 插件源码。

- 按 claim 检索，档位不设次数配额；独立调用批量执行，同 URL 复用。
- `unknown_payload` 只代表响应未知；`backend_not_executed` 需要运行时执行状态。
  通道关闭之后仅暂停 WebSearch，不限制直取文档、目录定位和定点读取；恢复由主流程操作。
  `degenerate_channels` 表示重复不作答端点；通道按类判定一次，不按次数累加。
- 原文用 fetch-text，整轮同一个 --out-dir；数字/引文绑定原文片段与文件 sha256。
  新 A/B 包默认 source-backed-v1，普通论断单源 medium 即可；text-bound-v1 为严格模式。
  verified/usable 经 entity_ids/claim_id 绑定；task 指定 core/supporting 与 source/text/cross_check；状态及停止规则见 research-workflow。
  每轮有效进展保存 pack 并校验，读取 research-progress.json 续做缺口；主流程按
  ready/partial/insufficient 交接，located/unresolved 不入事实账本。
- 原始报告/数据集用 origin_id，并组转载来源；来源等级仅标注，观点类来源仍为 minor 提示。
- 每条 claim usable、verified 或 unresolved 收口；缺口记录 reason/impact 和已获得来源。
  继续前必须能指出新增证据收益，无收益则结束；有效部分包可以交付。
- validate_research_pack.py 校验必须带 --task、--search-log、--fetch-report。报告 ok:true 且绑定当前 pack；
  审计 advisory（含 degenerate_channel、search_backend_not_executed）必须阅读并处理。

输出仅放 `<work-dir>`：research-pack.json、research-pack-validation.json、research/ 审计文件。
queries 记录实际执行调用，D 为空且来源全为 user-file。只返回 agent 固定的
RESEARCH_DONE / RESEARCH_BLOCKED 信封；assert_research_envelope.py 校验，禁止追加正文。
运行时 hooks 持有 research-execution.json；主流程核验凭据和 pack hash 后才进入 sp-outline。

图片获取另走 ../../references/image-sourcing.md，不与知识证据研究合并。
