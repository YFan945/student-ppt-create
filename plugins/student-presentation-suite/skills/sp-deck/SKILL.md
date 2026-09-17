---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.13.4
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；编辑请求由 `sp-review` 诊断后以 `outputs/<topic>-slide-spec.yaml` 交接到本 skill。

## Dispatch

每一生产回合先问管线，不要 grep 插件源码、不要 spawn 名叫 `researcher` / `researcher-*` 的 teammate、不要直接跑 `run_with_pptxgenjs.js`、不要重新注入本 skill。
更严格地说：**spawn `presentation-researcher` / `visual-critic` 时一律不要传 `name`**——带名字会变成
teammate，`agent_type` 变成名字本身，`*-execution.json` 凭据永不生成（QA 会死锁），而研究员还会
再嵌套 spawn 一层做重复检索。该 spawn 现由 `runtime_evidence` 的 PreToolUse 硬拒绝。

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" next --work-dir <wd> --json
```

只读 `next` 列出的路径。`pages/pNN-*.js` 用同一轮并行 Edit 填写。视觉 QA **必须看图**（CD-9）：概览读 `contact-sheet-thumb.jpg`（render 产出的廉价缩略图），全尺寸页 PNG 只在修具体 blocker 页时读、且同一轮并行——**主会话全尺寸大图（>150KB）预算是 6 张**，逐页复核属于隔离的 visual-critic，它的上下文不进本会话。同一 sha256 不得再读；同一条 `ls`/`cat`/`find` 类只读巡检命令一个会话最多 2 次，第 3 次会被 `cost_guard` 拒绝——状态一律问 `next`（一次给全 read / forbidden / next_command）。`cost_guard.py`（PreToolUse hook）还会拦截插件源码考古、第二次整篇读同一 reference、以及未变 hash 的 PNG 重读。

**会话分段（token 主杠杆）**：总 token ≈ (每请求新增上下文/2) × 请求数²，上下文随会话单调增长，所以**请求数是平方项**。`next --json` 在 build+render 完成后会给出 `session_segment: boundary-recommended`——此时开新会话（新 `/sp-deck` → 直接 `next --json`），work-dir 携带全部状态，新会话不必重读本会话历史。研究、评审本就跑在隔离子代理里；能切出去的是 spec/build 与 review/repair 两段。

`next --json` 的 `contract` 是按阶段选择的紧凑执行契约，含当前 policy hash、QA 顺序和 repair budget；不再预读整套 references。仅在具体内容/设计问题无法由当前契约解决时，按需读对应 reference。intake 规则仍以 `../../references/presentation-intake.md` 为准，机器规则以 `../../references/pipeline-contract.json` 为准。

Helper API 用 `node scripts/pptx-helpers.js --describe`。

## State gate

每个 work-id 的状态表达为 `intake_pending → intake_confirmed → planned → producing → qa → complete`；异常终态为 `incomplete` / `blocked`。`workflow_guard.py` 只负责 intake 的 `init / confirm`。Production Summary 未确认、摘要 hash 已变化或状态不是 `intake_confirmed` 时，`ppt_pipeline.py plan` 会直接拒绝。`plan` 成功后，`build-manifest.json` 成为生产阶段权威状态，pipeline 自动镜像 同 work-id 的 workflow-state.json；不得再手工调用 `workflow_guard.py transition` 推进生产状态。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" confirm --summary-file <summary> --work-id <work-id>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" status --work-dir <wd>
```

生产段 `planned → producing → qa → complete`；`qa → producing` 只能经 `ppt_pipeline.py repair`，repair 上限由 `pipeline-contract.json` 强制。重复 build 必须先 repair 且 generator hash 必须变化；相同 PPTX/visual-review/previews 的 QA 自动复用上次结果。

## Workflow

1. **Intake**：按 `presentation-intake.md` 收集需求，完整 Production Summary 经用户明确确认后调用 `workflow_guard.py confirm --summary-file <summary> --work-id <work-id>`。
2. **Mode**：按 source deck/edit intent 唯一确定 `create` / `edit_ooxml` / `rebuild_from_source`。
3. **Research Gate + Compile**：依赖外部事实时先跑 `sp-research` 产生 `research-pack.json` 与 validation。主会话 spawn `student-presentation-suite:presentation-researcher` 必须前台、**不传 `name`、禁止再套一层**。`ppt_pipeline.py plan` **自己编译** evidence map 与带 E ids 的 spec（work-dir 里有 pack 即可），不要让模型去猜编译 CLI。
4. **Art Direction**：visual style 只作为 seed，形成 `art-direction.yaml` 与 3–5 个 high-leverage slides。
5. **Plan**：`<wd>` 必须为项目 `outputs/.pptx-work/<work-id>`；`edit_ooxml` 自动解包到 `ooxml/`，不生成 JS；`rebuild_from_source` 须先写 `source-analysis.md`。`ppt_pipeline.py plan --work-dir <wd> --slide-spec <compiled> --validation-report <报告> --art-direction <ad>`。程序验证已确认 Production Summary、执行 copy-fit preflight、freeze Slide Spec、scaffold `deck.js` + `pages/pNN-*.js` + `composition/`、建立 `build-manifest.json` 并绑定输入 SHA256。缺少 `pages/`、页数对不上 spec、或任一页仍带 scaffold marker（`student-presentation-suite-scaffold`，即该页从未实现）时 `build` 直接拒绝；**完成一页就删掉该页的 marker 注释**，`deck.js` 作为纯装配文件允许保留它。需求或 spec 需要重 plan 时，先重新确认 Production Summary，再 `plan --force`。
6. **Reference + Composition**：high-leverage 页保存 reference selection、2–3 个 silhouette candidates 与 wireframe 选择证据；普通页保留明确 composition intent。
7. **Exploration Gates**：final generator 前运行一次 `run_gates.sh`，只把 blocker 回到上下文，完整结果写盘。缺任一探索证据不得交付。
8. **Build**：`edit_ooxml` 改 `ooxml/` 后直接 `build --work-dir <wd>` 打包；原 source hash 始终受保护。其他模式：生成器拆为 `deck.js` + `pages/pNN-*.js`；调用 `ppt_pipeline.py build --work-dir <wd> --entry <deck.js>`。成功 build 后再次 build 会被拒绝；只有 QA blocker → `repair` → generator 实际变化后才允许重建。底层 `run_with_pptxgenjs.js` / `pptx_tool.py` 由 pipeline 调度，Agent 不再手工编排。
9. **Render**：调用 `ppt_pipeline.py render --work-dir <wd>`。Pipeline 一次渲染全部页面并生成 `contact-sheet.png`，同一 PPTX hash 重复调用直接复用。**渲染证据只对产生它的那个 PPTX hash 有效**：`build` 会清空 `manifest.render` 并把上一次的 contact sheet / 页面 PNG 归档到 `stale/render-<sha8>/`，所以 repair 后必须重新 render，`next` 会据此把下一步指向 `render` 而不是 `qa`。视觉 critique **必须看图**（CD-9）：contact sheet 与全部页 PNG 同一轮并行 Read；同一 sha256 不重读。
10. **Visual Critique**：前台 Agent `student-presentation-suite:visual-critic`（**不要传 `name`**：带名字的 Agent 调用会变成 teammate，`agent_type` 变成名字本身，`SubagentStop` 便不会再生成 `critic-execution.json`，QA 会永久阻断）独立读取当前 contact sheet 和所有页图，Write 绑定 PPTX/contact/page SHA256 的 `visual-review.json`；评 hierarchy、focal point、composition、visual interest、whitespace、Art Direction alignment、reference/candidate intent、AI-template feel 和 deck rhythm。
11. **QA DAG**：必须已有 hook 生成的 `critic-execution.json`；默认自动读取 `speaker-notes.md` 和当前 render 预览。`ppt_pipeline.py qa --work-dir <wd> --visual-review <visual-review.json> [--preview <page-1.png> <page-2.png>]`。顺序唯一来自 machine contract：`package → rendered → actual-content → quality → delivery`；本轮报告自动喂给下一级并绑定 SHA256，失败即停；相同输入重复 QA 自动复用。
12. **Repair**：只有 QA blocker 才运行 `ppt_pipeline.py repair --reason <摘要>`；程序记录 repair budget。修改 generator 后重新 `build → render → critique → qa`。generator hash 未变化时 build 直接拒绝；超过预算转 `incomplete`，运行时/关键输入不可用时转 `blocked`，不得继续循环。
13. **Complete**：`ppt_pipeline.py complete --work-dir <wd>`；QA 全绿且 delivery 真正通过才允许完成，同时镜像 同 work-id 的 workflow-state.json 为 complete。

## Generation core contract

```text
Production Summary confirmation
→ Research / Compiled Slide Spec / Art Direction
→ ppt_pipeline plan → build → render + contact sheet
→ isolated visual critic + runtime receipt → fail-fast QA DAG
→ bounded repair (only when needed) → complete
```

核心原则：**Skill 负责智能，Pipeline 负责确定性、状态、缓存、预算和依赖。** 不再用“请不要重复 build / QA / 逐页读图”这类提示词承担可靠性。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`。work dir 保留 `build-manifest.json`、Slide Spec lock、Art Direction、research provenance、render/contact sheet、visual review 与 QA/delivery reports。最终交付 PPTX、speaker notes、preview/contact sheet、package/readback/quality/delivery reports；编辑任务另含 change summary。**禁止覆盖 source deck，所有模式输出新文件。**

交付完成后可运行 `sp-review` 做只读复核/评分，并报告绝对路径、页数、QA 状态与剩余限制。
