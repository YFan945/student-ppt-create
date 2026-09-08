# PPTX Production

本文件负责生产阶段编排。Intake、内容、证据、图片和视觉标准由共享 canonical references 负责；
低层命令见 `pptx-runtime.md`。

生产前必须具备：已确认的 Production Summary、验证通过的 Presentation Brief 与 Slide Spec、
明确 output prefix、selected visual style、design grammar 与唯一 production mode。

## Mode decision

| Mode | 使用条件 | 生产机制 |
| --- | --- | --- |
| `create` | 没有 source deck，或 source 为 PDF/preview 等非 PPTX | PptxGenJS + suite helper |
| `edit_ooxml` | 要保留模板、布局或已有内容；source 是可解包 `.pptx`/`.potx` | 解包、修改、clean、pack |
| `rebuild_from_source` | 原文件损坏或重建更安全，且理由已记录 | 读取原文件后新建 |

存在可编辑模板时不得因为新建更方便而静默切换到 rebuild。

## Shared invariants

- 输出和 work directory 必须在项目 `outputs/` 下；source deck 只读并记录 SHA-256。
- 中文正文不低于 22pt，英文正文不低于 20pt；放不下时依次删减、扩大、换构图、拆页。
- 使用 resolved design tokens；不得临时另造 palette。
- `layout` 默认是功能意图，不是固定模板。`layout_lock: true` 才要求精确使用指定 layout。
- 视觉策略允许 `data | diagram | image | typography | hybrid`。`typography` 是合法的一等策略。
- 禁止为了满足“每页有视觉”而强塞图标、卡片或无关图片。
- 模型负责语义层级、视觉焦点、页面比例和 composition；运行时负责安全 helper、实际 artifact 检查和 QA。
- 最终真实性以生成后的 PPTX 为准，不以模型声明的 composition/preflight 为准。

## Create branch

1. 按 Slide Spec、design grammar 和 resolved tokens 创建 `outputs/.pptx-work/<work-id>/deck.js`。
2. adaptive-freeform 仍是默认：模型可自行决定比例、形状、坐标和视觉焦点；`suggestLayouts()` 只提供候选，
   `composer_deck.js` 用于显式锁定、兼容或 deterministic fallback。
3. 所有文字优先使用 `addFittedText` / text-fit helper；所有关键 composition 在生成前做 safety preflight，
   但 preflight 只作为早期防线。
4. 执行 PptxGenJS wrapper 生成 candidate：

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --output <candidate.pptx> <deck.js>
```

5. candidate 生成后立即检查“真实 artifact”：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_static_analyzer.py" <candidate.pptx> \
  --output <candidate-stem>-static-report.json --json --strict

python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_plan_check.py" <slide-spec.yaml> <candidate.pptx> \
  --output <candidate-stem>-plan-actual-report.json --json --strict

python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate <candidate.pptx> \
  --output <candidate-stem>-package-report.json --json
```

`pptx_static_analyzer.py` 检查实际 PPTX 中的元素边界、异常 bbox、重叠与 text-fit 风险；
`pptx_plan_check.py` 检查实际页数、标题、关键数字与 Slide Spec 的语义漂移。

6. 静态报告中的 blocker 必须在 render 前修复；warning 必须进入 visual review，不允许静默忽略。

## Render-conditioned production

生成 candidate 不是生产结束。完整流程是：

`produce → inspect actual PPTX → render → observe → critique → revise → rerender`

视觉复审至少检查：
- 裁切/溢出/重叠；
- 文字层级、对比度、行长、字号；
- 视觉焦点是否明确；
- 图片裁剪/比例/清晰度；
- 图表 takeaway 是否比图表本身更容易看到；
- 页面留白是否失衡；
- 连续页面是否出现机械重复；
- 与 rubric / scenario / Slide Spec 是否一致。

发现 blocker/major 时修改 spec/composition/generator 后重建完整 candidate；禁止直接对打包后的 PPTX 做无法追踪的局部补丁。

## Edit branch

按 `pptx-editing.md`：inspect/thumbnail → unpack → 结构和内容修改 → clean → pack →
`validate --original`。打包后同样执行 actual artifact static analysis、plan-vs-actual（有 Slide Spec 时）和完整 render review。

## Rebuild branch

记录 source hash、重建原因、保留项和差异；之后执行 create branch，并强制生成 change summary。

## Transition to QA

生产完成只代表“candidate 已生成并通过初步 artifact 检查”。必须转到 `qa`，执行 `pptx-qa.md` 的
静态检查、plan-vs-actual、package validation、完整 render、视觉复审和 delivery gate 后，才能声称 ready-to-present。
