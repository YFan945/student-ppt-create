# PPTX Production

本文件只负责生产阶段编排。Intake、内容、证据、图片和视觉标准由共享 canonical references 负责；低层命令见 `pptx-runtime.md`，PptxGenJS 安全规则见 `pptxgenjs-safety.md`。

生产前必须具备：已确认的 Production Summary、验证并冻结的 Presentation Brief / Slide Spec、明确 output prefix、selected visual style seed、selected design grammar，以及唯一 production mode。v0.8 create/rebuild 还必须先完成 Art Direction 与 composition exploration，不能从 Slide Spec 直接跳到 final `deck.js`。

## Mode decision

| Mode | 使用条件 | 生产机制 |
| --- | --- | --- |
| `create` | 没有 source deck，或 source 为 PDF/preview 等非 PPTX（未损坏） | v0.8 visual exploration → PptxGenJS + suite helper |
| `edit_ooxml` | 要保留模板、布局或已有内容；source 必须是可解包 `.pptx`/`.potx` | 解包、结构修改、内容修改、clean、pack |
| `rebuild_from_source` | 原文件损坏或重建更安全，且理由已记录 | 读取原文件后走 v0.8 create core，不声称原位编辑 |

`source_deck`、`edit_intent`、`review_findings`、`preserve` 和 `change_summary_required` 是 Slide Spec 顶层字段。存在可解包 PPTX/POTX 模板时优先 `edit_ooxml`；source 为 PDF/preview 不能 `edit_ooxml`；`edit_intent: "rebuild-clean-copy"` 走 rebuild 并记录理由。

## Shared invariants

- 输出和 work directory 必须在项目 `outputs/` 下；source deck 始终只读，生产前后记录 SHA-256。
- 坐标必须落在画布内；正文不能为了塞内容而突破硬可读下限。Art Direction 的标题/正文层级目标优先于“把所有文字硬塞一页”。
- create/rebuild 的每个真实 text/shape/image/chart/line 必须登记 Actual Element Registry，不能只检查 advisory composition。
- 所有最终 candidate 必须通过 package validation、artifact readback、完整 render 和视觉复核；同一 package validation 证据要与 QA 和 delivery 绑定，不能重复生成相互矛盾的报告。
- reference recipe、wireframe 和 Art Direction 是正向视觉先验，不是真实内容来源；事实、数字和引用仍受 Evidence Ledger 约束。

## v0.8 visual generation front-end

默认 `adaptive-freeform` 保留，但自由度必须建立在更强的视觉先验上。最终页面生成顺序固定为：

```text
Frozen Slide Spec
  → Design Grammar
  → Art Direction
  → Visual Reference Retrieval
  → 2–3 Composition Candidates for high-leverage slides
  → Low-cost Wireframe Render + Selection
  → Final Actual PptxGenJS elements
  → Actual Element Registry
  → PPTX → Readback → Full Render → Visual Critic
```

### Art Direction

1. 根据确认后的 style seed + design grammar 写 `outputs/.pptx-work/<work-id>/art-direction.yaml`。
2. Art Direction 必须具体决定色彩支配、字体尺度、图片裁切/处理、图标语言、chart grammar、component language、motif、background rhythm 与 asset plan；只写“现代、学术、简洁”不合格。
3. 运行：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/art_direction_check.py" \
  <art-direction.yaml> --quality <high-score|standard> --output <art-direction-report.json> --json --strict
```

### Visual Reference Retrieval

每页在写坐标前，用 slide role、grammar、visual strategy、density、tags 和最近页面历史检索 2–3 个 recipe：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/visual_reference_select.py" \
  --role <role> --grammar <grammar> --visual-strategy <strategy> --density <density> \
  --tags <comma-list> --history-ids <comma-list> --history-silhouettes <comma-list> \
  --count 3 --output <references-slide-N.json>
```

`visual-reference-library.json` 是 curated positive-prior library。每个 recipe 包含 `why_it_works`、dominant element、focal share、silhouette、normalized wireframe 和 adaptation notes。模型必须理解并变形参考，不得机械复制。

### Multi-candidate composition

3–5 个 high-leverage slides（通常为 cover / hook / central mechanism / strongest evidence / closing）必须探索 2–3 个不同 silhouette。候选保存在 `composition-candidates-<slide>.json`，至少包含：`id`、`visual_strategy`、`silhouette`、`reference_ids`、`dominant_element`、`focal_share`、`title_pt`、`body_pt`、normalized `zones`、`rationale`；选定后写 `selected_id` 与 `selection_reason`。

先校验：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/composition_candidate_check.py" \
  <composition-candidates-N.json> --quality <high-score|standard> --output <candidate-report-N.json> --json --strict
```

再生成低成本 wireframe：

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/composition_wireframe.js" \
  --input <composition-candidates-N.json> --output <wireframes-N.pptx>
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" render <wireframes-N.pptx> --output-dir <wireframes-N-dir>
```

模型必须观察 wireframe render 后再确认 selected composition。高价值页面不能用“给出三个名称但实际同构”的方式伪造探索。普通页不强制多候选，但仍必须从 reference retrieval + Art Direction 得到明确 composition intent。

## Final create branch

只有 visual generation front-end 完成后才开始正式 `deck.js`：

1. 加载 frozen Slide Spec、resolved tokens、Art Direction、当前页选中的/检索到的 reference recipes、`pptx-design-grammar.md` 与 `pptx-visual-engine.md`。
2. 每页确定 `role`、`visual_strategy`、`focal_point`、`hierarchy`、`composition_intent`、reference ids；high-leverage 页还必须遵循其 selected candidate 的主要 silhouette/focal ownership，除非记录新的 repair reason。
3. `suggestLayouts()` / `suggestCompositions()` 可以提供额外 2–3 个局部灵感，但 36-layout catalog 降为二级 inspiration/fallback；`layout_lock: true` 才是精确约束。
4. 最终真实元素必须进入 `${CLAUDE_PLUGIN_ROOT}/scripts/pptx-element-registry.js`。`preflightSlide()` 只是 composition-level safety preflight，不替代 registry；composer 仅为 deterministic fallback / compatibility path，不是默认生成器。
5. generator 在 `pptx.writeFile()` 前调用 `registry.assertSafe()`。阻断实际越界、明显文字重叠等几何错误；warning 在最终 render 中确认。
6. `deck.js` 从 `process.argv[2]` 接收输出路径；每个输出只创建一个 pptxgen 实例。
7. 执行：

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --output <candidate.pptx> <deck.js>
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate <candidate.pptx> \
  --output <candidate-stem>-package-report.json --json
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/pptx_actual_content_check.py" \
  <candidate.pptx> <slide-spec.yaml> \
  --output <candidate-stem>-actual-content-report.json --json --strict
```

8. `pptx_actual_content_check.py` 直接读取最终 slide XML，检查页数、计划标题、key claim、显式 `slide_copy` 与关键数字。通过 package + actual-content 后才能进入完整 QA render。

## Render-conditioned repair

视觉修复是生成算法的一部分，但 v0.8 要区分“探索不足”和“实现缺陷”：

- 若页面无明显 bug 但视觉平庸，先回到 Art Direction/reference/candidate decision，避免只微调 x/y 反复打磨一个错误构图。
- 若构图正确但存在 crop、wrapping、contrast、spacing 等实现问题，则只修 artifact/generator。
- 单任务最多 3 个 design repair iterations；每轮记录 blocker 与视觉质量是否改善。第 3 次仍阻断 → `incomplete`。
- workflow-level `qa → producing` 仍记录一次正式返工边，其内部可完成上述受控迭代。

## Edit branch

严格按 `pptx-editing.md`：inspect/thumbnail → unpack → 结构操作 → 内容/样式修改 → clean → pack → `validate --original --output <package-report>`。若 edit intent 是“整体美化/重设计”且允许改变视觉语言，可先补一份 Art Direction；若要求严格保留模板，则不强制多候选探索。

## Rebuild branch

记录 source hash、无法安全编辑的原因、保留项如何迁移，以及与 edit contract 的差异。之后执行 v0.8 create branch，并强制生成 change summary。

## Transition to QA

生产完成只代表获得 candidate。`build_support_outputs.py` 仅按确认 deliverables 生成 speaker notes、full script、teleprompter、training cards 和 references；preview/contact sheet/PDF 统一由 render/export 流程生成。完成后转 `qa` 执行 `pptx-qa.md`，不得提前声称 ready-to-present。
