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
- 视觉选择加载 `references/visual-style-menu.md` 和一个 `references/visual-styles/<style>.md`；生产视觉必须加载 `references/pptx-design-grammar.md`、`references/pptx-art-direction.md`、`references/visual-reference-library.json`、`references/pptx-visual-engine.md`、`references/pptx-visual-critic.md`。
- 引用加载 `../../references/evidence-and-citations.md`；外部知识来源加载 `../../references/research-workflow.md` 与 `sp-research` 产出的 Research Pack；版本/编辑加载 `../../references/revision-training-export.md`；低层规则见 `references/pptx-runtime.md`、`references/pptxgenjs-safety.md`、`references/pptx-editing.md`、`references/pptx-qa.md`。
- **全程遵守 `../../references/cost-discipline.md`**：调用并行批量发出、禁止整文件重写、产物写盘即弃、阶段小结落盘、检索一律委派子代理、门禁一次运行。

## State gate

状态按 `intake_pending → intake_confirmed → planned → producing → qa → complete` 正向推进，终态为 `incomplete` 或 `blocked`。`qa → producing` 是一次正式返工边，其内部最多 3 个受控 render-repair iterations；`incomplete → qa` 仅用于补齐门禁，均须 `--reason <摘要>`。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" <init | confirm --summary-file <summary> | transition --to <state> [--reason <摘要>]>
```

intake 段由 `workflow_guard.py` 记账；`planned → complete` 段由 `skills/sp-deck/scripts/ppt_pipeline.py` 以 `build-manifest.json` 在执行层强制——状态不对程序直接拒绝，而不是靠提示词请求。确认前只允许读取材料和收集需求，不得检查环境、生成、编辑、渲染或交付。必须让用户明确批准完整 Production Summary，再调用 `workflow_guard.py confirm --summary-file <summary>`。

## Workflow

1. **Intake**：按 `references/presentation-intake.md` 收集需求；其中配图选项的可用性以 `check_claude_pptx_env.py` 解析的 image capability（`image_search_ready` / `image_generation_ready` / `user_assets_ready`，见 `../../references/image-sourcing.md`）为准，不得承诺不可用能力。完整 Production Summary 经用户确认后继续。
2. **Mode**：按 source deck/edit intent 唯一确定 `create` / `edit_ooxml` / `rebuild_from_source`。
3. **Research Gate + Compile**：只要 deck 依赖外部事实（数字、政策、引文），先跑 `sp-research` 得到 `research-pack.json` + `research-pack-validation.json`；D 模式禁止联网但同样产出 pack。排页阶段的 draft Slide Spec 可以在 `evidence_refs` 里直接写 Research Pack 的 `F/D/Q` id，**不得手写 Research Evidence Ledger**。随后运行 `research_pack_to_evidence.py --validation-report ... --slide-spec <draft> --compiled-slide-spec <compiled> --output <evidence-map>`，由程序确定性完成 `F/D/Q → E<n>`、完整 `source_ids` / `primary_source_id`、`used_on_slides` 和 ledger，并验证 **compiled Slide Spec**；冻结统一推迟到第 5 步 `ppt_pipeline.py plan` 执行，`--research-pack`、`--research-validation`、`--evidence-map` 三者缺一或任一 provenance hash 对不上当前 compiled spec 都不得冻结。不含外部事实的 deck 可不带 Research Gate。查不到的事实只能降级/标注无来源，不得伪造。
4. **Art Direction**：visual style 只作为 seed；根据 design grammar 生成 `art-direction.yaml`，具体决定色彩支配、字体尺度、图片裁切、图标语言、图表语法、组件语言、motif、背景节奏、asset mix，并明确 3–5 个 `high_leverage_slides`；其校验由第 8 步的门禁运行统一完成。
5. **Plan（执行层冻结）**：`ppt_pipeline.py plan --work-dir <wd> --slide-spec <compiled> --validation-report <报告> --art-direction <ad>`，并按第 3 步传 `--research-pack`、`--research-validation`、`--evidence-map`。程序一次完成 copy-fit preflight（文案逐字上屏的算术校验，阻断即拒绝）与 `slide_spec_guard.py freeze`，建 `build-manifest.json` 并绑定全部输入 SHA256；此后锁由程序在每次 build 时自动复查，改 spec 不重 plan 直接拒绝。
6. **Reference Retrieval**：每页按 role/grammar/visual strategy/density/tags 调 `visual_reference_select.py` 取 2–3 个正向视觉参考 recipe；high-leverage 页必须把结果保存为 `references-slide-<slide>.json`。36 layouts 继续作为二级 inspiration/fallback。
7. **Multi-candidate Composition**：每个 high-leverage 页先写 2–3 个不同 silhouette 的 `composition-candidates-<slide>.json`，经 `run_gates.sh --candidates`（等价于 `composition_candidate_check.py`）后用 `scripts/composition_wireframe.js` 生成 `wireframes-<slide>.pptx` 并渲染观察；选择理由必须记录。普通页至少参考检索结果形成一个明确 composition intent。
8. **Gates（一次运行）**：final `deck.js` 之前、最迟 QA 前运行 `scripts/run_gates.sh`，一次覆盖 frozen plan、Art Direction、composition 候选与 v0.8 探索证据，绑定 Slide Spec / Art Direction 及每个 high-leverage 页的 reference-selection、candidate、wireframe hash；通过时只回显 1 行，完整明细写入 `gates-report.json`。缺任一探索证据不得交付。
9. **Production + Build**：create/rebuild 写最终生成器；生成器按 CD-2 拆为 `deck.js`（装配）+ `pages/pNN-*.js`（每页一文件），便于不同页并行修复。每个真实 text/shape/image/chart/line 登记进 `scripts/pptx-element-registry.js`，`registry.assertSafe()` 在写盘前通过；helper 的可用 API 读 `references/pptxgenjs-helper-api.md` 或 `node scripts/pptx-helpers.js --describe`，不要用内联探针试探。写完后 `ppt_pipeline.py build --work-dir <wd> --entry <deck.js>`——绕过 manifest 手工起 `run_with_pptxgenjs.js` 的产物不得交付。
10. **Visual Critique**：渲染全部页，写绑定当前 PPTX hash 的 `visual-review.json`；除工程缺陷外评 hierarchy、focal point、composition、visual interest、whitespace、Art Direction alignment、reference/candidate intent、AI-template feel 和 deck rhythm，不信任任何声明值，量测实际字号层级（≥1.45×）、图表轴显式 min/max 与底部留白（≤25%）。
11. **QA（一次 DAG）**：`ppt_pipeline.py qa --work-dir <wd> --visual-review <visual-review.json> [--notes <讲稿>] [--preview <渲染图>]` 依序跑 package（`${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py validate`）→ actual-content readback → rendered → quality → delivery，**上一级刚产出的报告由程序喂给下一级并绑定 SHA256**，失败级即停，只回显 blocker；不得手工串各门禁或传递报告路径。
12. **Spec Revision / Repair**：只有计划本身错误、需求变化或事实/结构问题时才 `slide_spec_guard.py revise --reason <原因>` 并 `ppt_pipeline.py plan --force` 重建锁（研究支持的 spec 修订必须重新编译 Research Gate chain 并重新传三件 research artifacts，不能静默丢掉 evidence provenance；revision 保留 parent hash）；生成器问题则 `ppt_pipeline.py repair --reason <摘要>` 进入正式返工边，最多 3 轮 build → qa，不收敛转 `incomplete`。
13. **Complete**：`ppt_pipeline.py complete` —— QA 全绿且 delivery 阶段真实运行过才放行；复核 finding 标 `resolved` 时必须附 `resolved_evidence`（修复前后 sha256），否则按未解决阻断。所有模式输出新文件，禁止覆盖 source deck。

## Generation core contract

```text
Production Summary → Brief
→ Research Pack + Validation → Draft Slide Spec
→ Evidence Compiler → Compiled/Frozen Slide Spec
→ Design Grammar → Art Direction
→ Visual Reference Retrieval
→ Multi-candidate Composition + Wireframe Selection
→ v0.8 Visual Generation Evidence Gate
→ Model-authored native PptxGenJS
→ Actual Element Registry → PPTX validation/readback
→ Full Render → Structured Visual Critic
→ Rhythm + Evidence + Timing Gate → Controlled Repair → v0.8 Delivery
```

核心原则：模型负责研究判断、内容与视觉智能；compiler/gate 负责证据转换、hash provenance 和不可绕过的确定性。不得把模型一次性自评、手工搬 ledger、无 hash 的“已经验证”当作完成。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`。研究型 deck 的 work dir 至少保留 `research-pack.json`、`research-pack-validation.json`、draft/compiled Slide Spec、`evidence-map.json`、`slide-spec-lock.json`；其余中间文件包括 `art-direction.yaml`、阶段小结、high-leverage references/candidates/wireframes、`gates-report.json`、`visual-generation-report.json`。最终交付 PPTX、speaker notes、preview/contact sheet、package report、`actual-content-report.json`、`visual-review.json`、`quality-report.json` 和 v0.8 delivery report；编辑任务另含 change summary。

交付完成后提示可运行 `sp-review` 做只读复核/评分，并报告绝对路径、页数、visual-generation/package/readback/quality/visual QA 状态与剩余限制。