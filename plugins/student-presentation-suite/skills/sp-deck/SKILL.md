---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.8.0
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；编辑请求由 `sp-review` 诊断后以 `outputs/<topic>-slide-spec.yaml` 交接到本 skill。

## Canonical references

- 始终加载 `../../references/presentation-intake.md`、`../../references/shared-standards.md`。
- 规划加载 `../../references/content-workflow.md`、`../../references/slide-spec.md`、`../../references/image-strategy.md`、`references/pptx-production.md`。
- 视觉选择加载 `references/visual-style-menu.md` 和一个 `references/visual-styles/<style>.md`；生产视觉必须加载 `references/pptx-design-grammar.md`、`references/pptx-art-direction.md`、`references/visual-reference-library.json`、`references/pptx-visual-engine.md`、`references/pptx-visual-critic.md`。
- 引用加载 `../../references/evidence-and-citations.md`；版本/编辑加载 `../../references/revision-training-export.md`；低层规则见 `references/pptx-runtime.md`、`references/pptxgenjs-safety.md`、`references/pptx-editing.md`、`references/pptx-qa.md`。

## State gate

状态按 `intake_pending → intake_confirmed → planned → producing → qa → complete` 正向推进，终态为 `incomplete` 或 `blocked`。`qa → producing` 是一次正式返工边，其内部最多 3 个受控 render-repair iterations；`incomplete → qa` 仅用于补齐门禁，均须 `--reason <摘要>`。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" <init | confirm --summary-file <summary> | transition --to <state> [--reason <摘要>]>
# 完成：transition --to complete --pptx <pptx> --delivery-report <report>
```

确认前只允许读取材料和收集需求，不得检查环境、生成、编辑、渲染或交付。必须让用户明确批准完整 Production Summary，再调用 `confirm --summary-file <summary>`。

## Workflow

1. **Intake**：按 `references/presentation-intake.md` 收集需求；完整 Production Summary 经用户确认后继续。
2. **Mode**：按 source deck/edit intent 唯一确定 `create` / `edit_ooxml` / `rebuild_from_source`。
3. **Plan + Freeze**：验证 Brief 与 Slide Spec；`slide_spec_guard.py freeze` 绑定 spec/report SHA-256 后转 `planned`，之后禁止静默改 plan。
4. **Art Direction**：visual style 只作为 seed；根据 design grammar 生成 `art-direction.yaml`，具体决定色彩支配、字体尺度、图片裁切、图标语言、图表语法、组件语言、motif、背景节奏、asset mix，并明确 3–5 个 `high_leverage_slides`；`art_direction_check.py --strict` 必须通过。
5. **Reference Retrieval**：每页按 role/grammar/visual strategy/density/tags 调 `visual_reference_select.py` 取 2–3 个正向视觉参考 recipe；high-leverage 页必须把结果保存为 `references-slide-<slide>.json`。36 layouts 继续作为二级 inspiration/fallback。
6. **Multi-candidate Composition**：每个 high-leverage 页先写 2–3 个不同 silhouette 的 `composition-candidates-<slide>.json`，经 `composition_candidate_check.py --strict` 后用 `scripts/composition_wireframe.js` 生成 `wireframes-<slide>.pptx` 并渲染观察；选择理由必须记录。普通页至少参考检索结果形成一个明确 composition intent。
7. **v0.8 Visual Generation Gate**：final `deck.js` 之前/最迟 QA 前运行 `pptx_visual_generation_gate_v08.py --strict`，绑定 frozen Slide Spec、Art Direction，以及每个 high-leverage 页的 reference-selection、candidate 和 wireframe hash；缺任一探索证据不得交付。
8. **Production**：进入 `producing` 前先 `slide_spec_guard.py check`。create/rebuild 才开始写最终 `deck.js`；每个真实 text/shape/image/chart/line 登记进 `scripts/pptx-element-registry.js`，`registry.assertSafe()` 在写盘前通过。composer 仅用于锁定/兼容/fallback。
9. **Actual Artifact Check**：用 `${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py validate` 做 package validation，再运行 `pptx_actual_content_check.py --strict` 与冻结 Slide Spec 回读对比。失败修 `deck.js`/PPTX，不能倒改 spec。
10. **Spec Revision**：只有计划本身错误、需求变化或事实/结构问题时才 `slide_spec_guard.py revise --reason <原因>`；revision 保留 parent hash，并重新生成受影响 artifact/visual-generation report。
11. **Render-conditioned QA**：完整渲染所有页，写绑定当前 PPTX hash 的 `visual-review.json`；检查工程缺陷之外，还评 hierarchy、focal point、composition、visual interest、whitespace、Art Direction alignment、reference/candidate intent、AI-template feel 和 deck rhythm。
12. **Quality + Repair**：`pptx_quality_gate_v071.py --strict` 继续检查视觉、节奏、Evidence Closure 和 speaker timing。blocker 进入一次正式 `qa → producing`，内部最多 3 次 `render → critique → revise artifact → rebuild → validate/readback → render`；不收敛则 `incomplete`。
13. **Complete**：PPTX、spec lock、Art Direction、`visual-generation-report.json`、package、actual-content、preview、visual review、quality report 全通过后运行 `pptx_delivery_check_v08.py --strict --visual-reviewed`，再转 `complete`。所有模式输出新文件，禁止覆盖 source deck。

## Generation core contract

```text
Production Summary → Brief / Frozen Slide Spec
→ Design Grammar → Art Direction
→ Visual Reference Retrieval
→ Multi-candidate Composition + Wireframe Selection
→ v0.8 Visual Generation Evidence Gate
→ Model-authored native PptxGenJS
→ Actual Element Registry → PPTX validation/readback
→ Full Render → Structured Visual Critic
→ Rhythm + Evidence + Timing Gate → Controlled Repair → v0.8 Delivery
```

核心原则：模型先做 art direction 和视觉方案搜索，再写坐标；reference 是可变形的正向先验而不是固定模板；runtime 负责安全和 plan-vs-actual；render critic 负责最终页面质量。不得把“无 overflow/overlap”、模型一次性自评通过，或没有 hash 证据的“我已经比较过多个方案”当作设计完成。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`。中间文件位于 `outputs/.pptx-work/<work-id>/`，至少保留 `slide-spec-lock.json`、`art-direction.yaml`、high-leverage `references-slide-*.json`、composition candidates/wireframes 和 `visual-generation-report.json`。最终交付 PPTX、speaker notes、preview/contact sheet、package report、`actual-content-report.json`、`visual-review.json`、`quality-report.json` 和 v0.8 delivery report；编辑任务另含 change summary。

交付完成后提示可运行 `sp-review` 做只读复核/评分，并报告绝对路径、页数、visual-generation/package/readback/quality/visual QA 状态与剩余限制。