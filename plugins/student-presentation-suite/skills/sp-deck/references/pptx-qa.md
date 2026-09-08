# PPTX QA And Completion

默认 QA 不再只检查 package + preview。普通生成任务也必须验证**真实 PPTX artifact**和
**Slide Spec → actual PPTX** 一致性，但仍保持报告轻量，不恢复旧版复杂 evidence-chain。

## Gate 1 — Plan

先验证 Slide Spec schema、跨字段语义和 Brief 交接：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_slide_spec.py" <slide-spec> \
  --brief <brief> --output <slide-spec-report.json> --json
```

`analyze_presentation_spec.py` 仍以建议为主；未知 evidence ref、结构错误、关键 rubric 约束必须先修复。

## Gate 2 — Actual artifact

对最终 candidate 检查真正写入 PPTX 的对象，而不是仅依赖 generator/preflight 声明：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_static_analyzer.py" <pptx> \
  --output <static-report.json> --json --strict

python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_plan_check.py" <slide-spec> <pptx> \
  --output <plan-actual-report.json> --json --strict

python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate <pptx> \
  --output <package-report.json> --json
```

规则：
- `out_of_canvas` / invalid bbox 等 objective geometry blocker 必须修复；
- text-fit、视觉/文字几何重叠属于 warning，必须进入 render review；
- slide count、标题、关键数字明显漂移属于 blocker/major，必须修复；
- static/plan report 必须绑定当前 PPTX SHA-256，candidate 改变后报告作废。

## Gate 3 — Render-Reflect

完整渲染全部页面：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" render <pptx> \
  --output-dir <render-dir> --prefix <topic>
```

逐页查看预览，不只是确认“能打开”。每页至少检查：
- 裁切、溢出、重叠、低对比；
- 标题/正文/关键数字的视觉层级；
- 视觉焦点是否明确、页面是否失衡；
- 图片裁剪、清晰度和内容相关性；
- chart/table 是否有清晰 takeaway；
- 是否存在 AI 式卡片墙、装饰性 icon、机械重复；
- 该页是否真正实现 Slide Spec claim / visual purpose；
- rubric/scenario 是否被满足。

发现 blocker/major 时：
1. 记录具体 slide + finding；
2. `qa → producing --reason <finding 摘要>`；
3. 修改 spec/composition/generator；
4. 重新生成完整 candidate；
5. 从 Gate 2 开始全部重跑。

Render 是生成循环的一部分，不得通过只设置 `--visual-reviewed` 跳过真实复审。

## Gate 4 — Delivery

简化交付报告继续作为最终 hash 绑定，但 complete 前必须同时存在：
- Slide Spec validation pass；
- static artifact report 无 blocker；
- plan-vs-actual report 无 blocker/major；
- package validation pass；
- preview 覆盖全部页面；
- 已完成全页视觉复审且无剩余 blocker。

当前 `pptx_delivery_check.py --simple` 保持兼容；在 v0.7 中，agent 必须把 static/plan 报告作为输出证据，
不得把 `--visual-reviewed` 布尔值本身视为视觉质量证明。

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/pptx_delivery_check.py" \
  --simple --strict --visual-reviewed \
  --pptx <pptx> --slide-spec-report <slide-spec-report.json> \
  --package-report <package-report.json> \
  --preview <page-1.png> --preview <page-2.png> \
  --notes <speaker-notes.md> --output <delivery-report.json> --json
```

交付报告通过后：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" transition --to complete \
  --pptx <pptx> --delivery-report <delivery-report.json>
```

缺渲染能力、未完成视觉复审、static/plan blocker 未解决时状态只能是 `incomplete`。

## Advanced evidence mode

旧的 `content-qa`、asset manifest、visual-inspection manifest 和 evidence-chain 接口继续兼容，
仅用于显式审计、高风险模板编辑、许可/来源归档或深度排错。普通任务不需要恢复整套重型 manifest。
