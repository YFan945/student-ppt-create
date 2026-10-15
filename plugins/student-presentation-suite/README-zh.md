# Student Presentation Suite

面向学生学术展示的 Claude Code 插件：证据检索、大纲、可编辑 PPTX 生成和只读审查。

安装、更新、迁移和卸载见[市场仓库 README](../../README-zh.md)。运行时由插件自有，不依赖外部 document-skills 或 Codex runtime。

设计参考仅为可选工具。字号、图表与图标数量、配色、背景节奏和构图由内容与实际页面决定；当前创作指引不再夹带旧的数字设计规则。

新页面源码只接收配色、字体族和作者提供的 typography，不注入版式规则、字号上下限、列数、标题/页脚分区或背景方案。所有 design_freedom 值均可使用自由页面函数；运行时不自动选版或绘制背景。展示保留必要解释与证据。

展示语言遵循共享规范的重要正文要求；表格支持可编辑的主题表头、分层底色与有意义的重点强调。

已移除自动金额、token、请求次数、研究总时长和修复轮数预算。用量报告仅记录实际用量；真实错误和未完成工作仍需修复。

## 四个 skill

| Skill | 输出 |
| --- | --- |
| `sp-research` | 可追溯外部证据的 Research Pack；需要检索时使用隔离研究员 |
| `sp-outline` | 结构化大纲、Slide Spec 和演讲计划 |
| `sp-deck` | 主会话直接创作或改进可编辑 PPTX |
| `sp-review` | 已有文稿的只读诊断；编辑须有单独请求 |

激活需有学生学术场景和明确的演示文稿意图。只读审查保留原文件。

## 生产方式

主会话读取真实素材、决定构图、编写逐页模块、查看渲染并在同一上下文修复。PPT 生产不再使用 Builder/critic 子代理、校准、Packet、分片或执行回执。

新任务默认 `design_freedom: auto`：自由坐标和共享绘图工具；`guided`、`deterministic` 保留为可选工具。`quality_level` 表达期望的细致程度，不增加代理阶段或模板限制。

图片、可编辑图表和结构图应解释内容。不设固定图片配额、全局字号地板、配色比例或 gallery 模仿要求。用户指定的品牌、模板、logo 和保留项继续有效。Art Direction 可选。

Slide Spec 2.1 冻结核心信息、精确事实、数字和来源，允许改写展示文案。实际文案从最终产物记录。语义和视觉由主会话作者自检，**不再声称独立语义评审**。旧 1.0/2.0 保留原文案匹配行为。

工具批量完成构建、字体处理、精确项回读、包结构验证和渲染，返回具体问题与当前预览。作者先看图再导出。生产流程为 `plan → run → complete`，命令及可运行写法见 [main-session-production.md](skills/sp-deck/references/main-session-production.md)。

## 素材、排版与编辑

新学生任务追求内容充实、视觉表达丰富、色彩有层次。按内容和完整渲染选择字号、信息密度及构图，字数上限只记录明确要求；正文保持充实，备注选择性讲重点。主动用已授权工具获取/生成主题图片，并制作可编辑关系图、表格和图表；明确允许时可交付有设计且有替换目标的占位图，不把它作为事实证据。见 [可运行视觉示例](skills/sp-deck/references/main-session-visual-examples.md)。

交付前逐页完整查看所有渲染，比较用户参考件，修复并重新渲染，再扫描整套。`run` 返回技术检查、几何风险和待主会话检查事项；`ok` 不代表审美合格或视觉/语义自检完成。命令仍为 `plan → run → complete`。

新任务不设图解条目配额或支撑点上限；明确字数限制接受正整数。自定义风格可增加语义分类色，省略未使用的背景/SVG 母题。文字重叠优先按实测行区域检测，缺少测量时保守检查文本框。

- 优先真实素材，保留比例和证据区域，记录来源与权限，不编造比较数据。
- 共享 fontkit 测量支持中文断行和 rich-text 强调；最终以实际渲染可读性为准。
- 页面使用共享 helpers 或原生 pptxgenjs 对象；harness 登记几何、背景、讲稿和实际文案。
- 作者决定字体及字号；页面字号别名明确映射，未知键返回具体错误。
- OOXML 编辑保留源文稿，重建仍保持可编辑；编辑附修改摘要。
- 讲稿和辅助演讲材料来自最终 PPTX 备注区；备注简短不要求压缩正文，只导出已确认类型。

## 工作文件与恢复

产物写入项目 `outputs/`，页面源码和预览写入 `outputs/.pptx-work/<work-id>/`。不得在安装插件或市场仓库内生成产物。

保留已有 intake 确认。状态和产物绑定由工具维护，不由模型转抄。按真实问题继续修复直到任务完成，不以默认修复轮数预算停止生产。

历史 manifest 可通过 `status` 读取，不自动迁移，也不沿已删除的子代理管线续跑。继续旧成品时保留原件，以新的编辑任务开始。

## 参考

- [模型自由设计](references/model-led-design.md)
- [主会话生产](skills/sp-deck/references/main-session-production.md)
- [图片来源](references/image-sourcing.md)
- [研究流程](references/research-workflow.md)
- [开发与验证](AGENTS.md)

新计划支持项目 outputs 内的 `meta.output_dir`，默认 `outputs/<work-id>`。预览导出全部页面 PNG 与绑定索引；contact-sheet 单独导出总览。`status` 读取当前检查和交付有效性，不重建。正常创作接口见[创作快速说明](skills/sp-deck/references/authoring-quickstart.md)；[内容转视觉](references/content-to-visual.md)指导充分的信息表达，不设置版式配额。

大纲拆解方法与跨页信息递进见[结构参考](skills/sp-outline/references/slide-structures.md)；面向听众的直接表达要求见[共享规范](references/shared-standards.md)。

最终大纲使用产物可回读内容；可选作者自检说明及其当前/过期状态见[制作流程](skills/sp-deck/references/main-session-production.md)。配置就绪与已验证图片获取记录的区别见[图片获取规范](references/image-sourcing.md)。

制作前规划充分正文、支撑内容与主要视觉；已有质量报告增加已登记图标复用与行文风险提醒。获准的图片占位可显示生图提示词，并校验对应页的可见性。具体要求见[内容流程](references/content-workflow.md)、[视觉组织](references/content-to-visual.md)和[图片获取](references/image-sourcing.md)，不设置密度或版式配额。

### 视觉审计修复

当前生产检查不透明前景对文字的遮挡，并检查已知纯色表面的对比度；图片/渐变等情况明确交给渲染检查。Slide Spec 2.1可选数值绑定保护指标、数值与单位的对应。intake采用一次完整摘要、可选Brief复用和run修复。完整同材料视觉案例与关系工具辅助创作，不增加版式配额或审美门禁。具体规则见intake、Slide Spec、创作快速入口与视觉案例参考。
