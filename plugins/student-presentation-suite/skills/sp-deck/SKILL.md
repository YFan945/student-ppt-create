---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.10.4
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；编辑请求由 `sp-review` 诊断后以 `outputs/<topic>-slide-spec.yaml` 交接到本 skill。

## Canonical references

- 始终加载 `../../references/presentation-intake.md`、`../../references/shared-standards.md`。
- 规划加载 `../../references/content-workflow.md`、`../../references/slide-spec.md`、`../../references/image-strategy.md`、`../../references/image-sourcing.md`、`references/pptx-production.md`。
- 生产视觉加载 `references/pptx-design-grammar.md`、`references/pptx-art-direction.md`、`references/visual-reference-library.json`、`references/pptx-visual-engine.md`、`references/pptx-visual-critic.md`。
- 引用加载 `../../references/evidence-and-citations.md`；外部知识来源加载 `../../references/research-workflow.md` 与 `sp-research` 产出的 Research Pack。
- **执行契约以 `../../references/pipeline-contract.json` 为机器事实源**；成本纪律见 `../../references/cost-discipline.md`。文档不得另行发明 QA 顺序、repair 次数或重复执行策略。

## State gate

`workflow_guard.py` 只负责 intake 的 `init / confirm`。Production Summary 未确认、摘要 hash 已变化或状态不是 `intake_confirmed` 时，`ppt_pipeline.py plan` 会直接拒绝。`plan` 成功后，`build-manifest.json` 成为生产阶段权威状态，pipeline 自动镜像 legacy workflow state；不得再手工调用 `workflow_guard.py transition` 推进生产状态。

生产状态：`planned → producing → qa → complete`；`qa → producing` 只能经 `ppt_pipeline.py repair`，repair 上限由 `pipeline-contract.json` 强制。重复 build 必须先 repair 且 generator hash 必须变化；相同 PPTX/visual-review/previews 的 QA 自动复用上次结果。

## Workflow

1. **Intake**：按 `presentation-intake.md` 收集需求，完整 Production Summary 经用户明确确认后调用 `workflow_guard.py confirm --summary-file <summary>`。
2. **Mode**：按 source deck/edit intent 唯一确定 `create` / `edit_ooxml` / `rebuild_from_source`。
3. **Research Gate + Compile**：依赖外部事实时先跑 `sp-research`，再由 `research_pack_to_evidence.py` 确定性完成 `F/D/Q → E<n>` 与 Evidence Ledger；research-backed freeze 必须同时绑定 pack、validation、evidence map。
4. **Art Direction**：visual style 只作为 seed，形成 `art-direction.yaml` 与 3–5 个 high-leverage slides。
5. **Plan**：`ppt_pipeline.py plan --work-dir <wd> --slide-spec <compiled> --validation-report <报告> --art-direction <ad>`。程序验证已确认 Production Summary、执行 copy-fit preflight、freeze Slide Spec、建立 `build-manifest.json` 并绑定输入 SHA256。需求或 spec 需要重 plan 时，先重新确认 Production Summary，再 `plan --force`。
6. **Reference + Composition**：high-leverage 页保存 reference selection、2–3 个 silhouette candidates 与 wireframe 选择证据；普通页保留明确 composition intent。
7. **Exploration Gates**：final generator 前运行一次 `run_gates.sh`，只把 blocker 回到上下文，完整结果写盘。
8. **Build**：生成器拆为 `deck.js` + `pages/pNN-*.js`；调用 `ppt_pipeline.py build --work-dir <wd> --entry <deck.js>`。成功 build 后再次 build 会被拒绝；只有 QA blocker → `repair` → generator 实际变化后才允许重建。
9. **Render**：调用 `ppt_pipeline.py render --work-dir <wd>`。Pipeline 一次渲染全部页面并生成 `contact-sheet.png`，同一 PPTX hash 重复调用直接复用。视觉 critique 默认只读取这张 contact sheet；只有具体问题页才允许额外放大。
10. **Visual Critique**：基于当前 contact sheet 写绑定当前 PPTX 的 `visual-review.json`；评 hierarchy、focal point、composition、visual interest、whitespace、Art Direction alignment、reference/candidate intent、AI-template feel 和 deck rhythm。
11. **QA DAG**：`ppt_pipeline.py qa --work-dir <wd> --visual-review <visual-review.json> [--preview <contact-sheet.png>]`。顺序唯一来自 machine contract：`package → rendered → actual-content → quality → delivery`；本轮报告自动喂给下一级并绑定 SHA256，失败即停；相同输入重复 QA 自动复用。
12. **Repair**：只有 QA blocker 才运行 `ppt_pipeline.py repair --reason <摘要>`；程序记录 repair budget。修改 generator 后重新 `build → render → critique → qa`。generator hash 未变化时 build 直接拒绝；超过预算转 `incomplete`，不得继续循环。
13. **Complete**：`ppt_pipeline.py complete --work-dir <wd>`；QA 全绿且 delivery 真正通过才允许完成，同时镜像 legacy workflow state 为 complete。

## Generation core contract

```text
Production Summary confirmation
→ Research / Compiled Slide Spec / Art Direction
→ ppt_pipeline plan
→ build
→ render + contact sheet
→ model visual critique
→ fail-fast QA DAG
→ bounded repair (only when needed)
→ complete
```

核心原则：**Skill 负责智能，Pipeline 负责确定性、状态、缓存、预算和依赖。** 不再用“请不要重复 build / QA / 逐页读图”这类提示词承担可靠性。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`。work dir 保留 `build-manifest.json`、Slide Spec lock、Art Direction、research provenance、render/contact sheet、visual review 与 QA/delivery reports。最终交付 PPTX、speaker notes、preview/contact sheet、package/readback/quality/delivery reports；编辑任务另含 change summary。

交付完成后可运行 `sp-review` 做只读复核/评分，并报告绝对路径、页数、QA 状态与剩余限制。
