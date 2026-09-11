# Student Presentation Suite for Claude Code

中文 | [English](README.md)

`student-presentation-suite` 是面向大学生课程汇报、答辩和小组展示的 Claude
Code 插件。它将内容规划、可编辑 PPTX 生成和已有 deck 审查拆成独立 skill，
并共享统一的需求表、Slide Spec 与质量标准。

安装 ID：`student-presentation-suite@claude-personal`。

## 三个 Skill

### `sp-outline`

用于 PPT 大纲、叙事主线、逐页口播规划、小组分工、转场、Q&A 准备和可选
Slide Spec。该 skill 不创建也不会声称创建 PPTX。

### `sp-deck`

用于新建可编辑 PPTX，或为已有 deck 生成独立改进版。底层包编辑、校验和渲染
统一通过本套件维护的 `scripts/pptx_tool.py` 与 `shared/pptx_runtime/` 完成；
不加载外部 `document-skills`，也不分发其复制代码。
它会深复制页面的可变依赖，执行 Open XML SDK markup/schema validation 与本套件
package/presentation 语义检查，并生成支持隐藏页和分页的 contact sheet。
clean 具备事务回滚，inspect 返回版本化逐页 metadata；仅当 Linux sandbox 实际阻断
AF_UNIX 时，render 才按需编译并加载内置 shim。

### `sp-review`

用于审查、评分、风险诊断、计划与成品对比和逐页修改建议。默认只读。
用户说“直接改好”时，先完成诊断，再把结构化 findings 交给 PPTX skill。

## 完整 PPTX 需求表

正式生成前必须确认：

- 主题；
- 课程/场景与汇报类型；
- 受众与语言；
- 时长与页数；
- 个人/小组形式及成员；
- 评分标准或必需章节；
- 资料来源和证据边界；
- 模板、logo 或品牌限制；
- 图片来源策略；
- 视觉风格；
- 必需交付物。

插件会复用已确认的信息，只询问缺失项，并为每个缺失项提供推荐值和影响。
质量目标默认 `high-score`，引用风格默认课堂引用，两者都不在 intake 中询问。
即使用户说“你决定”，也只是自动采用推荐值，仍需用户通过 `AskUserQuestion`
（确认 / 调整方案 / 更换视觉风格）确认完整 Production Summary。

生产状态为：

`intake_pending → intake_confirmed → planned → producing → qa → complete`

处于 `intake_pending` 时，不得运行环境检查、生成、渲染或交付命令。

插件通过 `workflow_guard.py` 状态机命令（init/confirm/transition）记录状态。
PreToolUse hook 已移除，命令不再自动拦截；状态由 SKILL 文本自律维护——状态未
推进到 `intake_confirmed` 前不运行生产脚本。

## 结构化交接

Slide Spec YAML 将确认后的规划传入 PPTX 生成。`meta` 可记录主题、汇报类型、
受众、语言、时长、页数、分工、课程、评分标准、资料来源、模板、图片策略、
视觉风格、交付物和输出前缀。

已有 deck 改进额外使用：

- `source_deck`
- `edit_intent`
- `review_findings`
- `preserve`
- `change_summary_required`

原始 deck 永远不会被覆盖。

Slide Spec v2 还可以携带场景、受众深度、结构模式、质量控制、分层文案和讲稿、
Evidence Ledger 引用、锁定页面及 revision 元数据；旧版 Slide Spec 仍兼容。

提供 Presentation Brief 时，所有已确认且需要镜像的字段都必须在 Slide Spec 中存在并一致；
字段缺失属于交接错误，不能按隐式默认值放行。support outputs 可以缩小、不能扩大已确认的交付物集合。

## 输出文件

交付物写入 `${CLAUDE_PROJECT_DIR}/outputs`；环境变量不可用时，回退到当前
项目的 `outputs/`：

- `<topic>-presentation.pptx`
- `<topic>-speaker-notes.md`
- `<topic>-preview.png` 或 contact sheet
- `<topic>-presentation-package-report.json`（suite validation 产物，可复用）
- `<topic>-delivery-report.json`（最终门禁证据）
- 已有 deck 改进时的 `<topic>-change-summary.md`
- 按需输出 PDF、HTML 提词版、训练卡、引用清单、质量报告和 revision manifest

用户文件不得写入插件安装目录。

## 视觉系统

PPTX skill 先从三类、每类四种风格中选择一个，或选择“其他”，再加载
`visual-styles/` 下的一份轻量参考。正式风格包含气质、浅色六角色 palette、配套的深色
六角色 palette（封面/章节/收尾）、背景参考和一个可选 SVG 参考；“其他”使用相同结构，
并在 Production Summary 中完整展示后确认。

深浅是**同一套体系的两面，而不是两套配色**：深色配套与浅色 palette 同色相家族，
不会出现"深色封面硬贴浅色正文"的割裂。两套 palette 都要通过同一组对比度下限
（正文 4.5:1、强调色 3:1，对 canvas 与 surface 均适用）。`resolve_design_tokens()`
保证任何风格都有深色配套，并为自定义/历史风格自动派生对比度安全的版本。

风格是自适应生成方向，不是固定模板。硬约束只保护可读性、证据真实性、来源边界和
内容适配；页面配方、比例、母题和常规密度范围均可根据叙事任务调整。没有合适视觉素材时
允许排版主导页，不能用无意义图标、卡片或引文填空。

12 种风格不控制布局、形状、图片处理、图表语法、组件或页面节奏。SVG 母题只作可选参考，
不得自动插入；风格参考不能绕过容量、来源、对比度或用户模板规则。

在写最终坐标前，每页会从 32 条
[`visual-reference-library.json`](skills/sp-deck/references/visual-reference-library.json)
中检索 2–3 个正向构图先验，高价值页必须产出 2–3 个真正不同的 silhouette 候选。搜图与生图
从不默认可用：在 `image-sources.json` 中声明 provider（见
[`references/image-sourcing.md`](references/image-sourcing.md)），环境检查会报告
`image_search_ready` / `image_generation_ready` / `user_assets_ready`。

仓库内含可复现的[黄金样例](examples/golden-sample/README.md)，跑通全流程并达到
`status: complete`。

所有风格共享 `layout-library.json` 中的 36 套页面构图灵感。`pptx-layouts.js` 会映射 Slide Spec
原生 kind/visual 值，先按素材、数据、项目数量、禁用条件、声明容量和标题区几何容量过滤，
缺输入时沿明确且可行的 fallback 链处理，再结合密度和连续轮廓排序，视觉风格不参与排序。
`scripts/visual_system_smoke_gallery.py` 会生成 12×6 轻量风格参考 gallery、独立
36 版式参考/兜底 gallery 和 12 页 SVG atlas，并在 LibreOffice/Poppler 可用时渲染。

`deck.js` 遵守 `skills/sp-deck/references/pptxgenjs-safety.md` 中的官方 gotchas，并使用
`pptx-helpers.js` 执行硬安全检查；`pptx-composer.js`、`pptx-layouts.js`、`pptx-shapes.js`、
`pptx-svg-library.js` 与 `pptx-visuals.js` 是可选灵感、工具箱和兜底。未锁定的 `layout` 可自由
调整，`layout_lock: true` 才恢复精确构图；`pptx-icons.js` 提供约 30 个随 token 着色的矢量图标。兜底 composer 先完成全 deck preflight，再用可编辑形状、
连接线、标签和图片/图表结构实现 hero/visual-dominant/process-path/timeline/comparison/
dashboard/architecture/matrix/quote/summary/reference 等布局族。图片默认等比包含并写入 alt text，
图表使用投影可读字号。

## 质量门禁

默认流程只有三道门禁：一次 Slide Spec/Brief 校验；最终 PPTX 的 package validation、完整
渲染和逐页查看；最后一次简化 delivery check，绑定当前 PPTX、规划报告、package report、
预览和用户要求的输出。content QA、asset、visual-inspection、QA manifest 等独立报告只保留给
高风险编辑、排错或用户明确要求审计证据的场景。

`complete` 使用 `workflow_guard.py transition --to complete --pptx <pptx> --delivery-report <report>`。
发现 blocker 时最多允许一次“修 spec/composer/generator → 重建整份 candidate → 重跑最终门禁”；
仍有 blocker 则交付 `incomplete`。CI 继续渲染完整场景矩阵，但不会提交生成产物。

## Runtime

Claude Code 不会自动安装本包的 Python 和 Node runtime 依赖。可以使用仓库
根目录安装脚本，或在本目录手动执行：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-claude-pptx.txt
npm ci
```

常用检查：

```powershell
python scripts/check_claude_pptx_env.py --json --strict
python scripts/check_claude_pptx_env.py --mode edit_ooxml --json --strict
python scripts/pptx_tool.py --help
python scripts/validate_slide_spec.py path\to\spec.yaml --json
python scripts/validate_presentation_brief.py path\to\brief.yaml --json
python scripts/analyze_presentation_spec.py path\to\spec.yaml --json  # 建议性分析
python scripts/build_support_outputs.py path\to\spec.yaml --output-dir <project>\outputs --json
python scripts/create_revision_manifest.py old.yaml new.yaml --strict
python scripts/manage_versions.py snapshot --output-root <project>\outputs --revision-id r1 --file <deck>
python scripts/slide_spec_to_pptx_brief.py path\to\spec.yaml --output-dir <project>\outputs
python scripts/bump_version.py 0.5.0 --dry-run  # 统一版本升级
node scripts/run_with_pptxgenjs.js --probe
python scripts/smoke_pptx.py
```

## 包边界

这是 Claude Code 专用包，不包含 `.codex-plugin`、`agents/openai.yaml`、
`artifact-tool` 或 Codex runtime 声明。

安装、维护和发布说明见仓库根目录
[README](../../README-zh.md)、[AGENTS.md](../../AGENTS.md) 和
[CHANGELOG.md](../../CHANGELOG.md)。
