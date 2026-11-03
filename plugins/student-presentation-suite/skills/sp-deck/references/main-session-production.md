# Main-session production

主会话直接读取素材、编写页面、查看当前预览并修复。Python 负责执行工具，不派发模型或评判审美。

普通技术校验、变化范围与停止条件由 [validation-policy.md](../../../references/validation-policy.md) 所有；不串联多份评分和回执。

## Commands

完成 intake 后，工作目录为项目 `outputs/.pptx-work/<work-id>`：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan --work-dir <wd> --slide-spec <spec>
# 主会话实现 pages/pNN-*.js（编辑模式改 ooxml/）。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" measure --work-dir <wd>
# measure 不构建不渲染：按真实页面代码一次报出全部文本溢出与余量偏紧的块，写 _tmp/measure-report.json。
# measure 只覆盖文本溢出/偏紧；颜色对比度、元素重叠与对齐由 run 检查。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" run --work-dir <wd>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" preview --work-dir <wd> --slides 1-3,5
# 只加载选中的已实现模块；不覆盖完整 deck 或 manifest。OOXML 编辑按当前页面顺序生成独立选页副本。
# 主会话查看返回的预览、实际文本和讲稿；有实际问题直接改，再 run。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" run --work-dir <wd> --no-render
# 只构建+全检、跳过渲染：迭代读 check_summary/geometry 报告用，不产出预览；complete 会按需补齐当前渲染，主会话仍须实际查看。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" complete --work-dir <wd>
```

`run` 的构建按页收集错误：多页同时溢出/失败时一次列出全部页面，不再在第一页中止。页面源码运行所需的环境变量由 pipeline 自行注入（`PPTX_HELPERS_DIR` 指向插件 `scripts/`）；作者手写调用页面代码的脚本时，需自行设置 `PPTX_HELPERS_DIR` 并经 `pptx-runtime-paths.js` 的 `installSearchPaths` 注册 pptxgenjs/fontkit——此类探测脚本属于 `_tmp/`。

`plan` 自动验证 Spec 并生成源码；`--art-direction <file.yaml|json>` 可选，接受的键（含深色 `palette_mode`）与类型见 [pptx-art-direction.md](pptx-art-direction.md)。`typography` 是整套字体定制的受支持通道：覆盖 `title_font`、`body_font`、`cjk_title_font`、`cjk_body_font` 等 `*_font` 键，合入内联 TOKENS 并驱动构建期的 Latin→CJK `<a:ea>` 映射。需要整套换字体（如 CJK 用 Microsoft YaHei）时走这里，不要在每个文本调用上单独指定 `cjkFontFace`——那不进入字体映射。研究任务可提供 `--research-pack`，工具批量编译证据。无需先调用多个验证或状态推进命令。

研究包缺失或未收口时，plan仍准备正式脚手架并返回draft/research.status=pending；先实现不依赖缺口的页面并使用run/preview，不另写probe或手抄tokens。complete前工具刷新采用证据，核心缺口仍阻止正式交付。只补影响页面的具体缺口，不因未采用候选而重建整包。

重新执行 `plan` 时，已含作者实现的 `pages/pNN-*.js` 不会被覆盖；`deck.js` 只在仍带脚手架 marker 注释行时才会被重写——手工调整 deck.js（配色、字体等）后删除该 marker 注释行即冻结。测量脚本等临时文件放在工作目录的 `_tmp/` 下：第一级以 `_` 或 `.` 开头的路径不参与 authoring 绑定与变更检测，可随时删除；`pages/` 内部的共享模块（如 `pages/_shared.js`）正常参与绑定，散放在工作目录根的其他 `.js` 也会被绑定进 manifest。

`run` 执行构建、字体处理、事实精确项、包与作者几何报告检查和全页渲染，返回 `technical_checks`、`geometry`、`review_required` 及当前页面路径。`ok` 只表示列出的技术检查通过，不代表审美、核心语义或逐页看图已经验收。几何 warning 和字体替换供作者对照完整渲染判断；合理的装饰覆盖不按数量阻断。不以金额、token 或修复次数阻断当前工作。当前文件与预览绑定一致时可复用渲染。

几何和文字容量是预测性诊断：保留元素 id、重叠比例和所需高度，允许候选稿生成并渲染，作者对照实际页面判断。无效坐标/尺寸及代码执行失败仍阻止生成；包损坏、缺少明确精确项和实际指标错误仍阻止交付。`measure` 可选，用于提前定位；`run --no-render` 可用于只读技术结果，之后补齐当前预览并完成实际看图。

`complete` 绑定当前产物并生成已确认的辅助文件。主会话在调用前完成看图和核心语义自检；工具不假装替作者做独立视觉评审。`status` 可以读取历史 manifest，旧管线任务须保留原件后以新 work-id 继续。

看图后可在 `complete` 使用 `--review-note "已查看哪些最终页、发现并修复了什么、哪些条件未实测"`。工具将说明与当前PPT、Spec及页面图绑定，写入已有质量报告；status区分 recorded-current、stale、unrecorded。不填时明确报告自检未留记录，不能自动声称语义验收完成。记录是作者自述，不证明真实查看、不表示独立评审，也不新增强制文件、评分、生产凭据或审批阶段。只有实际完成的检查才写入。

`outline` 导出使用最终可回读正文及已核验的作者标题，保留规划中的页面作用，不再仅导出旧标题和一句claim。导入OOXML标题沿用规划标题，避免误把任意模板文字猜作标题；冻结Spec独立保留。

## Student-content inspection

`plan` and `run` return student_design, including each page’s core information, visible support, main visual/template choices and speaking-order questions. Use these alongside the full renders: point to the main answer, show how evidence/diagrams explain it, and repair missing support or competing emphasis. Readability warnings are returned beside these questions. In the existing --review-note describe concrete page findings and changes in focus, supporting content, speaking order, rich color and template adaptation, rather than listing technical checks alone. Do not manufacture a note or claim automated aesthetic approval.

## Minimal reference path

常规创建按顺序只读当前SKILL、content-workflow的规划要求、template-workflow的默认参考检索、authoring-quickstart的接口及本文件的执行要求。plan返回reference_library候选，创作前查看适合的预览及单页配方，采用后按真实内容重建；用户指定模板优先。结构选择只读slide-structures中适合当前任务的方法；语言查shared-standards。已经读过的规则不重复加载。其他参考按当前操作选择：严格保留模板/封面查cover-and-template，丰富视觉或松散问题查content-to-visual，获取图片查image-sourcing，具体API疑问查单函数帮助。不要在创作前遍历全部规范、示例或运行时实现。各文件保持自身所有权，入口仅链接，不复制整份政策。

用户要求“充实/丰富”、提供参考件或诊断松散时，content-to-visual属于本次必要参考，不能只读通用接口后把文字排进矩形就算完成。diagram-only仅限定素材类型，仍需表达主题对象与关系。对照材料逐句检查新增解释的依据：不能把“缺少持续跟进”扩写为已观察到“无人维护联系、参与停在一次活动”。在真实主会话看图发现这些问题后直接修复；自述检查记录不能替代修复。

交付前必须渲染所有最终页面，总览看节奏，再逐页完整查看断行、裁切、意外重叠、连接线、标签归属、页码、信息密度、颜色层级和图文关系。检查同级一致、跨级区分、重点突出、对齐间距、正文支撑完整和简短讲解路径；再按课堂投影/目标观看条件缩放检查表格、图例和重点。封面与模板按 `cover-and-template.md` 对照真实页面。占位须确认是有意设计且已获允许，有替换目标和可读内容，不把遗留 TODO、空白页或缺失核心证据当作完成。修复后再次 `run`，查看变化页；公共样式或叙事变化时扩大检查范围，单纯备注修改不重看未变图片；最后确认内容、素材来源和用户要求。自动报告不证明美观、事实语义正确或已在 PowerPoint 中实测。

## Authoring

新任务 pages/ 导出页面函数：直接使用 ctx.slide（pptxgenjs）、ctx.pptx 和按需选用的 ctx.H。完整画布可用，背景和版式由页面源码绘制；脚手架不放置任何视觉元素，不按 design_freedom 限制函数或自动选择布局。presentation_copy 可选地提示标题/标签，实际正文和讲稿以 PPTX 回读为准；notes 或原生 slide.addNotes 均可写讲稿。原生 addTable 支持自动尺寸和合并单元格，文字由 OOXML 回读。

从事实材料和参考页面设计构图，保留必要的解释、证据与细节。使用组件时由作者选定输入与区域，不把其内部示例坐标复制成整套页面格式。接口查阅 pptxgenjs-helper-api.md、pptxgenjs-safety.md；图文实现可参阅 main-session-visual-examples.md。

INPUT 保留该页视觉用途、结构数据、页面功能、时间与原始展示材料；用途描述不是上屏文案。正文供观看与选择性讲解，module.notes 只写重点、解释与转场。图片缺失时按已确认策略制作设计占位，登记 asset-manifest.json；其 placeholder_policy 默认为 forbid，明确允许时为 allow，记录格式见 image-sourcing.md。空页面函数必须完成实际绘制；已实现函数保留来源注释不会被判为未完成，允许素材占位不等于允许未实现页面。

图片按真实比例与证据保留区域布局；addPlannedImage 默认完整显示，明确裁切才使用 cover/crop。图表使用有来源的数据。调用原生或共享文本工具时可直接指定字号、字体、对齐、边距和坐标；最终检查实际渲染。

## Current reports and delivery

Read `authoring-quickstart.md` for normal page creation instead of discovering helper internals. `run` returns a concrete `check_summary` and `changed_pages`; shared source modifications flag all affected pages. Read `status --work-dir <wd>` for stored reports and current delivery health without production. Do not rerun merely to print a report. A persistent build replacement lock reports its exact stage/path; close that artifact and retry, without deleting unrelated files.

`meta.output_dir` 必须位于项目 outputs 内且不在 .pptx-work 中，默认 `outputs/<work-id>`。已确认任务可在同一 work-id 内修订 Spec/设计配置，再 `plan` 或 `run`；重新 plan 保留已写页面并同步脚手架管理的入口。JSON/YAML 排版变化不撤销确认；Production Summary 实质变化需在同一 work-id 重新确认。编辑源稿保留 `_inputs/` 快照，外部原件变化不锁死任务。工具仍保护原件和输出路径。

`complete` 根据当前 PPTX 和素材契约刷新检查；未变的技术输入复用校验结果，不要求旧报告、文案副本或所有源码哈希一致。当前逐页预览用于真实看图；仅缺失的预览按需恢复，不重建 PPTX。备注/ZIP 元数据变化可复用视觉内容相同的页面；PDF、联系表仅在实际请求时要求，联系表可由页面图重建。`preview` 导出全页 PNG，`contact-sheet` 单独导出概览。`status` 将用户修改的交付文件报告为 modified；缺失文件才使交付 incomplete。

Review content roles against `../../../references/content-to-visual.md`, not shape quotas. Full final pages and the latest overview must reflect the last changes. Check unsupported comparisons/guarantees/causality in notes as well as visible text. Do not claim a target viewer or projector was tested unless it was actually used.

`check_summary.expression_findings`汇总实际正文/备注的行文风险与显式标为 primary 的图标跨页复用，不改变technical ok，不自动删除引文或判断美观。每条发现带 severity：`info` 命中规划或用户提供的文本（含 `must_convey`/`content`/标题等），确认展示意图即可；`advisory` 为作者自撰文字，结合上下文判断是否确有问题，不要求清零；`must_show_exact` 条目不产生发现。对应详情在现有production-check.json的expression_review。查看提醒涉及的页，按content-to-visual检查主体与整套布局；未登记的图标仍需看图。允许的提示词占位按image-sourcing登记prompt_visible，必须能在对应页回读提示词。工具不会为本次规则更新修改既有PPT。

失败记录包含阶段：生成失败需修源码；技术校验或渲染失败时，可用未变的候选PPT继续run/complete，不再次生成。返回的review_required只针对当前变化：首次完整看图，后续只看受影响页，备注修改不重看图片。辅助讲稿按展示页序输出，稳定ID无需连续。
