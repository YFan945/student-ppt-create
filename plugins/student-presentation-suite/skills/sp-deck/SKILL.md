---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.13.4
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；编辑请求由 `sp-review` 诊断后以 `outputs/<topic>-slide-spec.yaml` 交接到本 skill。

## Dispatch

每一生产回合先问管线，不要 grep 插件源码、不要 spawn 名叫 `researcher` / `researcher-*` 的 teammate、不要直接跑 `run_with_pptxgenjs.js`、不要重新注入本 skill。

三类隔离 Agent 均由**主会话前台直接 spawn，且不要传 `name`**：

- `student-presentation-suite:presentation-researcher`：外部事实与引用；
- `student-presentation-suite:presentation-builder`：create/rebuild 的视觉校准、逐页 JS 首次实现与 targeted repair；
- `student-presentation-suite:visual-critic`：独立视觉复核。

`presentation-researcher` / `visual-critic` 带名字会变成 teammate，使 `*-execution.json` 凭据失效；研究员还可能嵌套 spawn。该错误由 `runtime_evidence` 硬拒绝。`presentation-builder` 虽不产生 QA receipt，也必须保持独立前台 context，避免逐页 JS 和 repair diff 回灌主会话。

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" next --work-dir <wd> --json
```

只读 `next` 列出的路径。**主会话不得直接实现、读取或修复 `pages/pNN-*.js`**：`plan` scaffold 后先让 `presentation-builder` 做高杠杆页 calibration，再由同一隔离 builder 补齐其余页面；主会话只接收 `BUILDER_DONE` / `BUILDER_BLOCKED` 紧凑信封，不接收页面源码。

视觉 QA **必须看图**（CD-9）：正式 deck 概览读 `contact-sheet-thumb.jpg`，全尺寸页 PNG 只在修具体 blocker 页时读、且同一轮并行。**主会话全尺寸大图（>150KB）预算是 6 张**。Calibration 是这个预算的高价值用法：一次只读 2–3 张真实高杠杆页预览。逐页最终复核属于隔离的 visual-critic，它的上下文不进本会话。同一 sha256 不得再读；同一条 `ls`/`cat`/`find` 类只读巡检命令一个会话最多 2 次，第 3 次会被 `cost_guard` 拒绝。

**会话分段（token 主杠杆）**：总 token ≈ (每请求新增上下文/2) × 请求数²。研究、视觉校准后的逐页生成和评审都在隔离子代理中完成；主会话只保留 spec/状态/校准图/紧凑信封/QA blocker。`next --json` 在 build+render 完成后仍会给出 `session_segment: boundary-recommended`，此时开新会话可以进一步避免 review/repair 继承前半段历史。

`next --json` 的 `contract` 是按阶段选择的紧凑执行契约，含当前 policy hash、QA 顺序和 repair budget；不再预读整套 references。仅在具体内容/设计问题无法由当前契约解决时，按需读对应 reference。intake 规则仍以 `../../references/presentation-intake.md` 为准，机器规则以 `../../references/pipeline-contract.json` 为准。

Helper API 用 `node scripts/pptx-helpers.js --describe`；逐页实现时由 `presentation-builder` 自己调用该描述接口，不把 helper 源码拉回主会话。正式与 calibration 的 raster render 都由插件内 `pptx_tool.py` 通过受控 pipeline/helper 调用，不依赖项目 PATH 中的同名脚本。

## State gate

每个 work-id 的状态表达为 `intake_pending → intake_confirmed → planned → producing → qa → complete`；异常终态为 `incomplete` / `blocked`。`workflow_guard.py` 只负责 intake 的 `init / confirm`。Production Summary 未确认、摘要 hash 已变化或状态不是 `intake_confirmed` 时，`ppt_pipeline.py plan` 会直接拒绝。`plan` 成功后，`build-manifest.json` 成为生产阶段权威状态，pipeline 自动镜像同 work-id 的 workflow-state.json；不得再手工调用 `workflow_guard.py transition` 推进生产状态。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" confirm --summary-file <summary> --work-id <work-id>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" status --work-dir <wd>
```

生产段 `planned → producing → qa → complete`；`qa → producing` 只能经 `ppt_pipeline.py repair`，repair 上限由 `pipeline-contract.json` 强制。**Calibration preview 不改变生产状态，也不写 `manifest.build/render`**；它只是正式 build 前的临时视觉证据。正式重复 build 仍必须先 repair 且 generator hash 必须变化；相同 PPTX/visual-review/previews 的 QA 自动复用上次结果。

## Workflow

1. **Intake**：按 `presentation-intake.md` 收集需求，完整 Production Summary 经用户明确确认后调用 `workflow_guard.py confirm --summary-file <summary> --work-id <work-id>`。
2. **Mode**：按 source deck/edit intent 唯一确定 `create` / `edit_ooxml` / `rebuild_from_source`。
3. **Research Gate + Compile**：依赖外部事实时先跑 `sp-research` 产生 `research-pack.json` 与 validation。主会话 spawn `student-presentation-suite:presentation-researcher` 必须前台、**不传 `name`、禁止再套一层**。`ppt_pipeline.py plan` 自己编译 evidence map 与带 E ids 的 spec，不让模型猜编译 CLI。
4. **Art Direction**：visual style 只作为 seed，形成 `art-direction.yaml` 与 3–5 个 high-leverage slides。
5. **Plan**：`<wd>` 必须为项目 `outputs/.pptx-work/<work-id>`；`edit_ooxml` 自动解包到 `ooxml/`，不生成 JS；`rebuild_from_source` 须先写 `source-analysis.md`。`ppt_pipeline.py plan --work-dir <wd> --slide-spec <compiled> --validation-report <报告> --art-direction <ad>`。程序验证 Production Summary、copy-fit、freeze Slide Spec、scaffold `deck.js` + `pages/pNN-*.js` + `composition/` 并建立 `build-manifest.json`。
6. **Reference + Composition**：high-leverage 页保存 reference selection、2–3 个 silhouette candidates 与 wireframe 选择证据；普通页保留明确 composition intent。
7. **Calibration Build**：仅 `create` / `rebuild_from_source`。从 Art Direction 的 high-leverage slides 选 **2–3 张**，优先覆盖封面 + 高密度/数据页 + 代表性图文页。主会话前台 spawn `student-presentation-suite:presentation-builder`，不传 `name`，传绝对 work-dir、`mode=calibration` 和目标 slide ids。Builder **只实现这些页面**，其余页面保持 scaffold，主流程此时故意不能正式 build。
8. **Calibration Preview**：收到 `BUILDER_DONE(mode=calibration)` 后，由主会话运行确定性 helper，而不是让 builder 自己 build：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/calibration_preview.py" \
  --work-dir <wd> --slides <id1> <id2> <id3> --json
```

helper 只把这些已实现页面组装成临时 `calibration/calibration.pptx`，渲染到 `calibration/render/`，并写绑定页面/PPTX/PNG SHA256 的 `calibration-manifest.json`；**不触碰生产 manifest/state**。主会话在同一轮并行 Read 这 2–3 张 PNG，检查 hierarchy、focal point、密度、配色、图像语言和 Art Direction 一致性。若存在会扩散到全 deck 的 Major/Critical 视觉问题，再 spawn builder `mode=calibration` 只修这些页，随后重跑 helper；不要先生成剩余 10–20 页再发现基础风格错误。
9. **Full Isolated Page Build**：Calibration 视觉系统可接受后，再前台 spawn `presentation-builder`，传绝对 work-dir 与 `mode=initial`。Builder 保留已校准页面，按它们已建立的 typography/spacing/surface/image language 实现**所有剩余 scaffold 页面**并写 `speaker-notes.md`。主会话不得打开逐页源码复核，只接受紧凑信封。
10. **Exploration Gates + Production Build**：运行一次 `run_gates.sh`，只把 blocker 回到主上下文，完整结果写盘。`edit_ooxml` 直接走原 OOXML 路径；create/rebuild 只有在所有页面 scaffold marker 都删除后才调用 `ppt_pipeline.py build --work-dir <wd> --entry <deck.js>`。任何未实现页仍会被正式 build 机械拒绝。Calibration PPTX 不是可交付物，也不能替代正式 build。
11. **Render**：调用 `ppt_pipeline.py render --work-dir <wd>`。Pipeline 一次渲染全部页面并生成 `contact-sheet.png` / 缩略图；相同 PPTX hash 复用。build 后旧渲染证据被归档，repair 后必须重新 render。
12. **Visual Critique**：前台 Agent `student-presentation-suite:visual-critic`，不传 `name`，独立读取当前 contact sheet 和所有页图，写绑定当前 SHA256 的 `visual-review.json`；最终 critic 仍负责全 deck rhythm，Calibration 不能替代它。
13. **QA DAG**：必须已有 `critic-execution.json`；`ppt_pipeline.py qa --work-dir <wd> --visual-review <visual-review.json>` 按 `package → rendered → actual-content → quality → delivery` fail-fast 执行并绑定本轮输入。
14. **Repair**：只有 QA blocker 才先运行 `ppt_pipeline.py repair --reason <摘要>`；随后 spawn `presentation-builder mode=repair`，只改 blocker 页及直接共享依赖。收到 `BUILDER_DONE` 后重新 `build → render → critique → qa`。generator hash 未变化时 build 拒绝；超过预算转 `incomplete`。
15. **Complete**：`ppt_pipeline.py complete --work-dir <wd>`；QA 全绿且 delivery 真正通过才允许完成。

## Generation core contract

```text
Production Summary confirmation
→ isolated research / compiled Slide Spec / Art Direction
→ ppt_pipeline plan
→ isolated builder(calibration: 2–3 high-leverage pages)
→ deterministic calibration preview + main-session visual check
→ isolated builder(initial: remaining pages, preserving calibration)
→ exploration gates → production build → render
→ isolated visual-critic + fail-fast QA DAG
→ bounded repair → isolated builder(repair targets only)
→ build → render → critique → QA → complete
```

核心原则：**先用极少数真实页面校准视觉系统，再把该系统扩散到整套 deck。** Skill 负责智能编排，Builder/Researcher/Critic 各自隔离高上下文工作，Pipeline 负责确定性状态和交付；Calibration helper 只负责便宜、可追溯的早期视觉反馈。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`。work dir 保留 `build-manifest.json`、Slide Spec lock、Art Direction、calibration preview evidence、research provenance、正式 render/contact sheet、visual review 与 QA/delivery reports。最终交付 PPTX、speaker notes、正式 preview/contact sheet、package/readback/quality/delivery reports；**`calibration/` 仅为内部早期反馈，不作为最终交付物**。编辑任务另含 change summary。禁止覆盖 source deck。
