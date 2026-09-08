# PPTX Production

本文件只负责生产阶段编排。Intake、内容、证据、图片和视觉标准由共享 canonical references 负责；低层命令见 `pptx-runtime.md`。

生产前必须具备：已确认的 Production Summary、验证通过的 Presentation Brief 与 Slide Spec、明确的 output prefix、selected visual style、selected design grammar，以及唯一 production mode。

## Mode decision

| Mode | 使用条件 | 生产机制 |
| --- | --- | --- |
| `create` | 没有 source deck，或 source 为 PDF/preview 等非 PPTX（未损坏） | pptxgenjs + suite helper |
| `edit_ooxml` | 要保留模板、布局或已有内容（含“用这个 PPTX 模板做新 deck”）；source 必须是可解包的 `.pptx`/`.potx` | 解包、结构修改、内容修改、clean、pack |
| `rebuild_from_source` | 原文件损坏或重建更安全，且理由已记录 | 读取原文件后新建，不声称原位编辑 |

`source_deck`、`edit_intent`、`review_findings`、`preserve` 和 `change_summary_required` 是 Slide Spec 顶层字段。判定规则：

- 存在可解包的 PPTX/POTX 模板 → `edit_ooxml`；不得因为新建更方便而静默改为 rebuild。
- source 为 PDF/preview 等非 PPTX → 不能 `edit_ooxml`；源文件损坏走 `rebuild_from_source`，否则 `create`。
- `edit_intent: "rebuild-clean-copy"` 优先走 `rebuild_from_source` 并记录理由。

## Shared invariants

- 输出和 work directory 必须在项目 `outputs/` 下。
- source deck 只读，生产前后都记录 SHA-256。
- 中文正文不低于 22pt，英文正文不低于 20pt，主要标题不低于 24pt。
- 文本不适配时依次拆页、删减、扩大容器，禁止突破字号下限。
- 坐标必须落在画布内；标题、正文、页脚区与安全边距保持一致。
- create/rebuild 的每个实际 text/shape/image/chart/line 必须登记进 Actual Element Registry，不能只检查 advisory composition。
- 所有最终 candidate 都必须通过 package validation、artifact readback、完整 render 和视觉复核。

## Visual design

默认采用内容驱动的 `adaptive-freeform`，但不允许“裸自由构图”。生成顺序必须是：

```text
Slide Spec
  → Design Grammar
  → Per-slide composition intent
  → Actual PptxGenJS elements
  → Actual Element Registry static analysis
  → PPTX
  → Artifact Readback
  → Render
  → Visual Critic
  → Repair if needed
```

设计规则：

- 先选 `pptx-design-grammar.md` 中的场景语法，再选 visual style；layout catalog 只是局部构图灵感。
- 每页只建立一个 primary focal point；页面之间避免连续 3 页同构。
- `visual_strategy: typography` 是合法的一等策略，高质量文字主导页不需要强塞图片或 icon。
- 禁止标题下划线、装饰性色条、默认卡片堆砌、无语义渐变和 filler visual。
- 深色背景必须显式重新选择并验证浅色文字角色。

## Create branch

1. 按 Slide Spec 创建 `outputs/.pptx-work/<work-id>/deck.js`。加载 validated Slide Spec、resolved tokens、`pptx-design-grammar.md` 和 `pptx-visual-engine.md`。
2. 每页先确定最小 composition contract：`role`、`visual_strategy`、`focal_point`、`hierarchy`、`composition_intent`；`layout` 默认只是提示，`layout_lock: true` 时才严格解析。
3. 可用 `suggestLayouts()` / `suggestCompositions()` 获得 2–3 个候选，但最终真实元素必须进入 `${CLAUDE_PLUGIN_ROOT}/scripts/pptx-element-registry.js`。`preflightSlide()` 只算早期检查，不替代 registry。
4. generator 在 `pptx.writeFile()` 前调用 `registry.assertSafe()`。阻断实际越界、明显文字重叠等几何错误；warning 必须在最终 render 中确认。
5. deck.js 从 `process.argv[2]` 接收输出路径；每个输出只创建一个 pptxgen 实例。
6. 执行：

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --output <candidate.pptx> <deck.js>
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate <candidate.pptx> \
  --output <candidate-stem>-package-report.json --json
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/pptx_actual_content_check.py" \
  <candidate.pptx> <slide-spec.yaml> \
  --output <candidate-stem>-actual-content-report.json --json --strict
```

7. `pptx_actual_content_check.py` 是默认 artifact readback：直接读取最终 PPTX slide XML，检查页数、计划标题、key claim、显式 `slide_copy` 与关键数字是否在实际文件中出现。它不是语义评分器，但能阻止“Slide Spec 说有，实际 PPT 丢了”的 silent drift。
8. 通过 package validation + actual content check 后再进入 QA render。禁止把 candidate 仅因“成功写盘”称为 ready-to-present。

## Render-conditioned repair

视觉修复不是交付前一次性的“看看图片”，而是生成算法的一部分。

- 首次完整 render 后逐页检查 hierarchy、spacing、crop、contrast、text wrapping、visual relevance、slide rhythm、明显内容漂移。
- 有 blocker 时进入 repair：修改 Slide Spec/composition/generator，重新生成整份 candidate，再重跑 Actual Element Registry、package validation、artifact readback、完整 render。
- 单个任务最多进行 3 个 design repair iterations。若第 3 次后仍有 blocker，状态转 `incomplete`，不得无限循环。
- workflow-level 的 `qa → producing` 状态边仍用于记录一次正式返工；其内部可以完成多次受控 generator/render 修复。每一轮必须记录 blocker 是否减少，禁止无收敛重复试错。

## Edit branch

严格按 `pptx-editing.md`：inspect/thumbnail → unpack → 所有结构操作 → 内容/样式修改 → clean → pack → `validate --original --output <package-report>`。

编辑后同样运行 artifact readback；若存在 review handoff Slide Spec，则必须验证 plan-vs-actual。不得无条件编写 deck.js，也不得调用会原位覆盖 source 的 vendor CLI。

## Rebuild branch

记录 source hash、无法安全编辑的原因、保留项如何迁移，以及与 edit contract 的差异。之后执行 create branch，并强制生成 change summary。

## Transition to QA

生产完成只代表获得 candidate。`build_support_outputs.py` 仅按已确认 deliverables 生成 speaker notes、full script、teleprompter、training cards 和 references；preview、contact sheet 与 PDF 统一由 render/export 流程生成。完成这些产物后转为 `qa`，执行 `pptx-qa.md`；此时不得提前对用户声称文件 ready-to-present。
