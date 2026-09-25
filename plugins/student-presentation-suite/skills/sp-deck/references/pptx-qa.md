# PPTX QA And Completion

v0.7.1 默认 QA 仍按四个阶段组织：Plan Freeze、Actual Artifact、Render + Quality Critic、Delivery。普通任务不生成旧式冗长审计链，但必须保存最小的 spec lock、package、actual-content、visual-review、quality 和 delivery 报告。

**正式生产入口**：生产会话只执行 `ppt_pipeline.py next|advance|qa|complete` 与
`run_gates.py` 返回的公开动作。下面的 `slide_spec_guard.py`、`pptx_tool.py`、
`quality_gate.py`、`delivery_check.py` 命令只用于维护者调试和解释内部 Gate，不得绕过
pipeline manifest、状态守卫或证据绑定在正式会话中单独执行。
`pptx_quality_gate_v071.py` / `pptx_delivery_check_v071.py` 等版本脚本是 wrapper 内部实现，
仅保留给维护者定位问题，不是平级生产入口。

兼容性说明：v0.6 的“三道门禁”和 v0.7 仅依赖 `--visual-reviewed` 的交付形式仍保留兼容脚本，但新的 `sp-deck` 不得把它们当作完整高质量证明。

## Gate 1 — Plan Freeze

先完成 Slide Spec schema、跨字段语义和 Brief 交接检查：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_slide_spec.py" <slide-spec> \
  --brief <brief> --output <slide-spec-report.json> --json
```

`analyze_presentation_spec.py` 默认提供写作建议；出现来源不可追溯、未知 evidence ref、结构无效、rubric 明确遗漏等 Major/Critical 问题时必须先修正 Slide Spec。

验证通过后立刻冻结：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/slide_spec_guard.py" freeze \
  --slide-spec <slide-spec.yaml> \
  --validation-report <slide-spec-report.json> \
  --lock-file <slide-spec-lock.json>
```

从这一刻开始，Slide Spec 是**不可静默修改的生产计划**。进入生成、readback、render repair 前都可以/应该执行：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/slide_spec_guard.py" check \
  --slide-spec <slide-spec.yaml> --lock-file <slide-spec-lock.json>
```

Artifact 与 Plan 不一致时默认修 `deck.js` / composition / actual PPTX，**禁止通过改 Slide Spec 让检查通过**。只有计划本身确实错误、用户要求变化或发现事实/结构问题时才允许修订。正式生产中，尚未开始 build 时用 `ppt_pipeline.py plan --force --reason <原因>` 重新规划；生产已经开始后创建新 work-id。下列底层 revision 仅供维护者调试锁文件：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/slide_spec_guard.py" revise \
  --slide-spec <slide-spec.yaml> \
  --validation-report <new-slide-spec-report.json> \
  --lock-file <slide-spec-lock.json> \
  --reason "<为什么必须改计划>"
```

revision 会保存 parent spec hash 和 reason；修改计划后必须重新生成受影响 artifact，不得继续使用旧 candidate。

## Gate 2 — Actual Artifact

最终 candidate 不是以 generator 或 composition plan 为准，而以**实际 PPTX**为准。

1. 先 `slide_spec_guard.py check`，确认 plan 没有被静默修改；
2. `pptx_tool.py validate`：Open XML package/schema/relationship 检查；
3. `pptx_actual_content_check.py`：直接回读最终 slide XML，与冻结 Slide Spec 对比页数、标题、关键 claim、显式 slide_copy 和计划关键数字，并绑定 PPTX/Slide Spec SHA-256。

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

**重要：readback 失败后先修 actual artifact。** 不允许把“编造”改成“编出”这类 plan wording 来迁就已经生成的 PPTX，除非走上面的显式 spec revision。

### 快速通道：deck 迭代期用 gate-all 单进程跑完 4 个门禁

deck 反复重建的迭代期，Package/Actual/Rendered/Quality 四个门禁可以用
`gate-all` 在**一个进程内**顺序执行（省 3 次解释器启动，实测 4.1s → 2.1s）。
每个门禁仍写出各自独立的报告文件，合并汇总写入 `gate-all-report.json`；
任一门禁失败整体 exit 2（fail-closed），单步崩溃不拖垮其余步骤。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" gate-all \
  --pptx <pptx> --slide-spec <slide-spec.yaml> \
  --spec-lock <spec-lock.json> --visual-report <visual-review.json> \
  --output-dir <reports-dir> --output <gate-all-report.json> --json
```

约定：

- **迭代期快速通道**：deck 未定稿前用 gate-all + 跳过渲染先把结构类门禁跑绿；
- **最终交付前**：渲染一次全部页面，人眼逐页完成视觉审查后再跑一次 gate-all；
- **Spec 报告复用**：冻结时产出的 `slide-spec-report.json` 在其
  `slide_spec_sha256` 与当前 spec 一致时可直接复用于交付链，无需第三次校验；
  spec 一旦走 revise，旧报告即失效并重新校验。

## Gate 3 — Render + Structured Quality Critic

完整渲染全部页面，然后逐页观察真实 artifact。Render 是 inference loop 的一部分，不是只在最后盖章。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" render <pptx> \
  --output-dir <render-dir> --prefix <topic>
```

逐页查看后，按 `pptx-visual-critic.md` 写 `visual-review.json`。它必须绑定当前 PPTX hash，并为每页记录：

- `visual_structure`；
- `hierarchy / focal_point / composition / visual_interest / whitespace` 1–10 分；
- `ai_template_feel`；
- Major/Critical/Minor findings 及 `resolved` 状态；
- deck-level 节奏问题。

默认视觉审查不只检查裁切/溢出/重叠，还必须检查：

- focal point 是否清楚、层级是否正确；
- 页面是否只是“内容正确地装进框里”；
- typography 是否只是编号列表换皮；
- 封面是否只有标题/副标题/大片空白而没有视觉命题；
- 是否连续使用 equal-cards、card-grid、three-column、numbered-list、plain-list；
- visual 是否服务内容，而不是 filler；
- rubric 中可由最终页面直接观察的要求是否满足。

完成真实看图报告后运行统一质量 gate：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/quality_gate.py" --core v071 \
  --pptx <pptx> --slide-spec <slide-spec.yaml> \
  --spec-lock <slide-spec-lock.json> \
  --visual-report <visual-review.json> \
  --output <quality-report.json> --json --strict
```

该 gate 同时执行四类检查：

1. **Structured Visual Critic**：`hierarchy` / `focal_point` 低于下限（rigorous 6、其余 5）在 rigorous/standard 是 Major 阻断（standard 按 6.0 判定结构性低分），fast 记 advisory；`composition` / `visual_interest` / `whitespace` 低于下限与整套平均低于目标值是 **advisory**——记录并计数（`advisory_count`），不机械阻断交付；未解决 Major/Critical finding 照常阻断（管线 `visual_score_policy`）；
2. **Deck Rhythm**：连续两页相同弱卡片/列表结构或任意结构连续三页阻断；
3. **Evidence Closure**：Slide `evidence_refs` ↔ Evidence Ledger 使用页一致，课堂/学术引用必须能在最终 reference area 找到每个已使用来源；
4. **Speaker Timing**：按约 240 中文字/分钟、130 英文词/分钟估算真实讲稿时长；整套预计超过确认时长 15% 视为 Major。判定对象是**交付的 PPTX 备注区**（`ppt/notesSlides/*.xml`），不是冻结 spec 的 `speaker_notes` 字段——后者从 `plan` 起一直为空、也没有任何步骤被要求填写它，2026-09-17 live 因此在一个备注区完好的 deck 上报出 10 项幽灵 `speaker_notes_missing`，直接导致交付 `incomplete`。门读产物，不读计划。

### Repair loop

发现 blocker 时，进入受控 repair：

```text
Render
  → write structured visual review
  → run v0.7.1 quality gate
  → identify concrete blocker
  → revise composition/generator/notes/references
  → rebuild candidate
  → check frozen Slide Spec
  → Actual Element Registry
  → package validation
  → artifact readback
  → full render
  → rewrite visual review for the new PPTX hash
  → quality gate again
```

最多 3 个 design repair iterations。每轮应减少 blocker；若连续一轮无改善，应换构图、改视觉层级、压缩讲稿或重新组织 reference area，不得只微调坐标。

**一轮 iteration 必须修完所有阻断页，禁止按页分批。** 实测过一次反例：13 页 deck 的
修复被切成 P12 → P7/P9/P13 → P2/P8 → P10 → P6 五批，每批都走完整套
`编辑 → 构建 → 渲染 → 读图 → 判断`，构建 18 次、渲染 20 次、逐张读渲染图 36 次，
约 5300 万 token——占整次生成成本的 45%。按页分批时"最多 3 轮"会悄悄滚成 5 轮以上。
同因的 blocker（比如都是行高或同一处文案）必须在同一轮一次改完。

**修复循环必须看图，但同一轮并行读、同一 hash 不重读（CD-9）。** DeepSeek Flash
把每张图缩放到约 1300×1300 并封顶 1024 token，读 PNG 本身不贵；贵的是串行读和
对未变 PPTX 再读一遍。`full render` 之后在**同一轮**并行 Read contact sheet 以及
每一张 blocker 页 PNG。不要逐张串行；不要在 hash 未变时重读。`ppt_pipeline.py next`
会列出本轮该读的图。

**Spec revision 不是普通 repair 手段。** 只有 plan 本身错误时才通过公开的
`ppt_pipeline.py plan --force --reason ...`（仅 planned 状态）修订；生产开始后使用新 work-id。

**能在写生成器之前发现的问题，不要留到 readback。** 动手写 `deck.js` 之前先跑：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/copy_fit_preflight.py" \
  --slide-spec <slide-spec.yaml> --art-direction <art-direction.yaml> \
  --output <work-dir>/copy-fit-report.json
```

它按字号与区域宽度算术地判断 `title` / `claim` / `slide_copy` 能不能逐字上屏。
`pptx_actual_content_check.py` 要求这些文案**逐字**出现，Spec 里写 60–90 字的策划性
claim 必然在 readback 阶段炸成几十个 blocker，进而迫使生成器整文件重写、整条修复链
重来。这一步把那次返工提前到"改 Spec 还很便宜"的时候。

workflow state 仍只记录一次正式 `qa → producing` 返工边；该正式返工内部允许最多 3 个受控 render-repair iterations。

## Gate 4 — Delivery

v0.7.1 默认使用新的 delivery wrapper。除了 preview/package/spec/actual-content，还要求 frozen spec 与 `quality-report.json` 全部绑定当前 artifact。

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/delivery_check.py" --core v071 \
  --strict --visual-reviewed \
  --visual-review-report <visual-review.json> \
  --pptx <pptx> --slide-spec <slide-spec.yaml> \
  --spec-lock <slide-spec-lock.json> \
  --slide-spec-report <slide-spec-report.json> \
  --package-report <package-report.json> \
  --actual-content-report <actual-content-report.json> \
  --quality-report <quality-report.json> \
  --preview <page-1.png> --preview <page-2.png> \
  --notes <speaker-notes.md> --output <delivery-report.json> --json
```

`--visual-review-report` 是逐页视觉复核的证据文件（`pptx_sha256` 绑定当前 PPTX + 每页条目）；只传裸 `--visual-reviewed` 而不传该报告时，simplified 门禁停留在 `incomplete`。

**交付物按类型逐个验证（v0.15.3+）**。门禁不再用"要不要讲稿"一个布尔代表所有可读产物：`speaker-notes` / `full-script` / `teleprompter` 是三个不同的文件（`*-speaker-notes.md` / `*-full-script.md` / `*-teleprompter.html`），各自按 `build_support_outputs.py` 的命名契约查存在性（PDF 按 `<prefix>*.pdf` 兜底），缺哪个就报哪个名字，并在 v08 报告里写入 `owed_deliverables` / `missing_deliverables`。**任一已确认交付物缺文件都会把交付判为 `incomplete`**，不是只在报告里留一行提示。文件由 `--notes` / `--pdf` / `--full-script` / `--teleprompter` 传入，未传则按名发现——所以"确认了 PDF 但没导出"现在会被检出，而不是静默跳过。`--pdf` 同时是导出型预览的证据，**同一个文件不会被要求两次**。

`--deliverables` 未显式传入时，v08 从 `--slide-spec` 的 `meta.deliverables` / `export_formats` 读取；两者都缺时回退到**与 `slide_spec_to_pptx_brief.py` 同一份**默认值（`["pptx"]`），不会出现"Brief 说只要 PPTX、Delivery QA 却要 Notes"的分裂。缺 `meta.deliverables` 的旧项目由 `--deliverables` 显式传入旧集合来迁移。

每页必须对应一张有效 PNG/JPEG 预览；缺预览、spec lock 失效、quality gate 未通过或未完成逐页视觉复核时状态只能是 `incomplete`。用户明确不需要 notes 时可传 `--allow-missing-notes`（只免除它命名的那个类型）。

正式生产不单独执行上面的 delivery wrapper；由 pipeline QA 调用并绑定报告。通过后：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" complete --work-dir <wd>
```

v0.7.1 delivery report 继续使用 `gate_profile: simplified-v1` 保持 workflow_guard 兼容，同时写入：

- `generation_core_version: 0.7.1`；
- `actual_content_check_passed`；
- `quality_check_passed`；
- `quality_report_sha256`；
- `slide_spec_sha256`；
- `spec_lock_sha256`。

`complete` 要求：Production Summary 未变化、冻结 Slide Spec 未变化、Slide Spec 校验通过、Actual Artifact gate 通过、package validation 通过、完整 render/visual review 通过、quality gate 0 blocker、预览覆盖全部页面、delivery report 绑定当前 PPTX。

## Advanced evidence mode

旧的 `content-qa`、`validate-asset-manifest`、`visual-inspection`、`qa-manifest` 和 evidence-chain delivery 接口保持兼容，仅在以下情况使用：

- 用户明确要求逐项审计证据；
- 高风险模板/OOXML 编辑需要保存细粒度诊断；
- 外部素材的许可、alt text 或来源必须单独归档；
- 排查 content drift、preview hash 或 package relationship 问题。
