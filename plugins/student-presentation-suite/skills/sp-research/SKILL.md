---
name: sp-research
description: Use only for a clearly student-owned academic context when a deck needs external facts, current data, statistics, or citations that must not be invented, or when the user restricts sourcing to their own material. Collects, grades, and cross-checks sources into a Research Pack. Does not design slides, write speaker notes, or produce PPTX.
version: 0.14.2
argument-hint: "[work-id] [brief-or-draft-spec-path] [scope:A|B|C|D] [materials-path-or--]"
arguments: [work_id, brief_path, scope, materials_path]
---

# Student Presentation Research

为需要外部知识支撑的内容提供**筛选过、可追溯、可引用、可直接进入 Slide Spec** 的研究材料。
设计宗旨：**Search for evidence, not text.**

## 隔离执行与输入

**检索必须在独立 context 中运行，且靠显式 spawn，不靠 `context: fork`。**
`context: fork` 在 `claude -p`（print）模式下不被 honor，skill 会被内联进主会话——真实 Live E2E
两次测得 `subagent_stats.spawned = 0`、事件流无任何 subagent 事件，主 session 甚至替研究员执行了
`validate_research_pack.py`。所以本 skill 的隔离契约是：

1. 主流程调用 Agent 工具，`subagent_type` 取 `student-presentation-suite:presentation-researcher`；
2. **等待研究完成再进入排页**：研究员异步运行时，收到 `RESEARCH_DONE` 信封前不推进下一阶段；
2b. **不要传 `name`**：带 `name` 的 Agent 调用会转成 teammate，`agent_type` 变成名字本身，
   于是它自己再 WebSearch 会被 `runtime_evidence` 拦（"must run in the isolated
   presentation-researcher"），历史上正是这一步诱使它**再嵌套 spawn 一层研究员**
   （2026-09-16 实测：外层空转 2.4M token、0 次有效检索）。现在该 spawn 会被 hook
   当场拒绝；被拒时的正确动作是**去掉 `name` 从主会话重发一次**，不要再包一层
   （再 spawn 也会被拒，外层继续空转 0 次检索）；
3. 子代理看不到本次对话，也读不到本文件里的 `$work_id` 等绑定——**四个参数必须写进 spawn 的
   prompt 文本**，缺任何一个就让它按 `RESEARCH_BLOCKED` 契约返回，不要替它猜；
4. 主流程只接收它返回的 `RESEARCH_DONE` / `RESEARCH_BLOCKED` 信封，不接收原始网页、搜索轨迹
   或失败页。

解析后的输入是：

- work-id：`$work_id`
- Brief / draft Slide Spec 路径：`$brief_path`
- scope：`$scope`
- D 模式用户材料路径：`$materials_path`

`work_id` / `brief_path` / `scope` 缺失或 scope 不在 A/B/C/D 时，不猜参数，按 agent 的 `RESEARCH_BLOCKED` 契约返回；D 模式还必须有 `materials_path`。

## 职责与硬约束

- 检索、分级、交叉验证、知识缺口、留痕 → 本 skill；排页/讲稿 → `sp-outline`；PPTX/视觉 → `sp-deck`；审查 → `sp-review`
- 按需各读一次 `../../references/research-workflow.md`、`../../references/evidence-and-citations.md`、`../../references/research-pack.schema.json`；不要 grep 插件源码
- 不决定版式、不设计页面、不生成 PPTX、不改视觉风格、不撰写成段讲稿；不编造数字、日期、机构或引文
- 检索只在本 fork 内完成；主流程只接收文件路径和紧凑 envelope，不接收原始网页或搜索摘要。`validate_research_pack.py` 是 pack 唯一的 `ok: true`；回传正文用 `assert_research_envelope.py` 校验
- 输出只写 `${CLAUDE_PROJECT_DIR}/outputs/.pptx-work/<work-id>/`，不得写 `${CLAUDE_PLUGIN_ROOT}`

## 工作流

1. **Research Need Analysis**：读 Brief / draft spec，把待证内容拆成逐条 Claim，判 A/B/C/D；C 不消耗预算，D 禁止联网。
2. **预算**：按 scenario 选 simple / standard / deep（3/5、8/12、15/25 queries/sources），用户覆盖优先。
3. **逐 Claim 检索**：只查需要被证明的论断；每个来源记录 `url` 或 `locator` 与 `independence_group`。
4. **分级与交叉验证**：按 Tier S/A/B/C/D；高置信度数字必须来自 ≥2 个独立组；冲突则 `confidence: low` + `notes` + `conflicts`。
5. **补缺口与可视化候选**：模糊陈述进入 `knowledge_gaps`；可画图内容进入 `visual_candidates`，只标类型与优先级。
6. **受阻留痕**：打不开、付费、不可得、超预算全部写 `unresolved.reason + impact`，禁止静默降级。
7. **校验**：运行 `validate_research_pack.py <pack> --output <work-dir>/research-pack-validation.json`；有 blocker 就修 pack 再验。

## 输出契约

- `research-pack.json`：唯一研究内容载体；形状必须符合 schema
- `research-pack-validation.json`：必须 `ok: true`，并含当前 pack 的 `research_pack_sha256`
- `research/<topic>.json`：原始检索留盘审计，**永不回传主流程**
- `queries` 只记录实际执行过的检索词；D 模式必须为空且 sources 全为 `user-file`
- 最终聊天返回严格服从 agent 的固定 `RESEARCH_DONE` / `RESEARCH_BLOCKED` envelope（`assert_research_envelope.py` 可校验），不追加研究摘要。主对话不得出现 WebSearch / WebFetch

## 与图片检索分工

本 skill 只负责知识证据。照片、截图、Logo、示意图等走 `../../references/image-sourcing.md`；可信度/时效性与分辨率/构图/版权是两套目标，不合并。

运行时凭据：研究员用 Write 写 pack；插件的 SubagentStart/PostToolUse/SubagentStop
hooks 生成 `research-execution.json`。主会话 WebSearch/WebFetch 被阻止。
A/B/D 的 spec 写 `research_scope`；plan 必须验证真实子代理凭据与 pack hash。
