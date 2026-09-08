# PPTX QA And Completion

默认 QA 采用四道门禁：Plan、Actual Artifact、Render Critic、Delivery。普通任务仍不生成冗长审计链，但必须保存最小的 package、actual-content 和 delivery 报告。

## Gate 1 — Plan

用一个命令完成 Slide Spec schema、跨字段语义和 Brief 交接检查：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_slide_spec.py" <slide-spec> \
  --brief <brief> --output <slide-spec-report.json> --json
```

`analyze_presentation_spec.py` 默认提供写作建议；出现来源不可追溯、未知 evidence ref、结构无效、rubric 明确遗漏等 Major/Critical 问题时必须先修正 Slide Spec。

## Gate 2 — Actual Artifact

最终 candidate 不是以 generator 或 composition plan 为准，而以**实际 PPTX**为准。

1. `pptx_tool.py validate`：Open XML package/schema/relationship 检查。
2. `pptx_actual_content_check.py`：直接回读最终 slide XML，与 Slide Spec 对比页数、标题、关键 claim、显式 slide_copy 和计划关键数字。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate <pptx> \
  --output <package-report.json> --json
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/pptx_actual_content_check.py" \
  <pptx> <slide-spec.yaml> \
  --output <actual-content-report.json> --json --strict
```

`--strict` 失败即阻断。该检查不替代语义判断，但必须阻止以下 silent drift：

- 实际页数与规划不一致；
- 标题未落入实际 PPTX；
- key claim 被 generator 意外遗漏；
- 显式 slide_copy 大量丢失；
- 规划中的关键数字在实际页面中消失。

## Gate 3 — Render Critic

完整渲染全部页面，然后**逐页观察实际 artifact**。Render 是 inference loop 的一部分，不是只在最后盖章。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" render <pptx> \
  --output-dir <render-dir> --prefix <topic>
```

逐页检查至少包括：

- 裁切、溢出、重叠、字体 fallback、低对比；
- 图片比例、焦点裁切、图表标签可读性；
- focal point 是否清楚、层级是否正确、页面是否过密/过空；
- 是否连续 3 页同构；
- visual 是否服务内容，而不是 filler；
- 标题/结论/图表之间是否存在明显语义漂移；
- rubric 中可由最终页面直接观察的要求是否满足。

### Repair loop

发现 blocker 时，进入受控 repair：

```text
Render
  → identify concrete blocker
  → revise spec/composition/generator
  → rebuild candidate
  → Actual Element Registry
  → package validation
  → artifact readback
  → full render
```

最多 3 个 design repair iterations。每轮应减少 blocker；若连续一轮无改善，应换构图或拆页，不得只微调坐标。第 3 次后仍有 blocker → `incomplete`。

workflow state 仍只记录一次正式 `qa → producing` 返工边；该正式返工内部允许最多 3 个受控 render-repair iterations。

## Gate 4 — Delivery

用简化交付检查绑定预览有效性、页数覆盖、规划报告、package report、用户要求输出文件和最终 PPTX hash：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/pptx_delivery_check.py" \
  --simple --strict --visual-reviewed \
  --pptx <pptx> --slide-spec-report <slide-spec-report.json> \
  --package-report <package-report.json> \
  --preview <page-1.png> --preview <page-2.png> \
  --notes <speaker-notes.md> --output <delivery-report.json> --json
```

在运行 delivery check 前，`actual-content-report.json` 必须 `ok: true`；该报告作为 work artifact 保留，即使当前 simplified-v1 delivery schema 尚未显式绑定它。

每页必须对应一张有效 PNG/JPEG 预览；缺预览或未完成逐页视觉复核时状态只能是 `incomplete`。用户明确不需要 notes 时可传 `--allow-missing-notes`。

交付报告通过后：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" transition --to complete \
  --pptx <pptx> --delivery-report <delivery-report.json>
```

`complete` 要求：Production Summary 未变化、Slide Spec 校验通过、Actual Artifact gate 通过、package validation 通过、预览覆盖全部页面、人工/模型逐页视觉检查完成、交付报告绑定当前 PPTX。

## Advanced evidence mode

旧的 `content-qa`、`validate-asset-manifest`、`visual-inspection`、`qa-manifest` 和 evidence-chain delivery 接口保持兼容，仅在以下情况使用：

- 用户明确要求逐项审计证据；
- 高风险模板/OOXML 编辑需要保存细粒度诊断；
- 外部素材的许可、alt text 或来源必须单独归档；
- 排查 content drift、preview hash 或 package relationship 问题。
