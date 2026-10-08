# Student Presentation Suite for Claude Code

中文 | [English](README.md)

**本文件（插件 README）：** 安装后的行为——管线、四个 skill、intake、交接、产出、
视觉系统、门禁和 runtime CLI。安装/更新/卸载见仓库根
[README-zh.md](../../README-zh.md)。细则在 `references/` 与 `SKILL.md`。
同步规则：仓库 [AGENTS.md](../../AGENTS.md) 的 Documentation Ownership；
插件内说明见 [AGENTS.md](AGENTS.md)。

`student-presentation-suite` 是面向大学生课程汇报、答辩和小组展示的 Claude
Code 插件。它将外部知识检索、内容规划、可编辑 PPTX 生成和已有 deck 审查拆成独立
skill，并共享统一的需求表、Slide Spec 与质量标准。

发布源是 `YFan945/student-ppt-create` 的 **`main`**。安装见
[根 README](../../README-zh.md)。

安装 ID：`student-presentation-suite@claude-personal`。

管线：

```text
sp-research → sp-outline → sp-deck → sp-review
 证据层        内容层        生成层      审查层
```

## 四个 Skill

### `sp-research`

只负责**证据层**：判断哪些内容需要外部证据支持，检索高质量来源，做交叉验证与来源
分级，产出结构化的 `research-pack.json` 供后续 skill 直接消费。

设计宗旨是 *Search for evidence, not text*——不是"帮忙找点 PPT 内容"，而是"识别需要
证据支持的论断并把它坐实"。它不决定版式、不设计页面、不生成 PPTX、不改视觉风格、
不撰写成段讲稿；职责混在一起会污染后面每一层的产物。

会上屏的数字要求**逐字**，所以取原文这一层是确定性的：`pptx_tool.py fetch-text` 直接取
HTTP 原文与抽取文本并落盘，两份 sha256 一起写进 provenance——中间不经过会改写数字的小模型。
`--scope` 是权限门（只有 A/B 授权联网取原文，C/D 一律拒绝）。检索结果页和目录页按
`host_class` 分类，不做题材拦截；回环、私网、链路本地和保留地址在连接前拒绝，重定向的
每一跳都重新检查，记录里保留最终 URL。结果页是定位手段、永远不是来源。claim 逐条收口
（普通论断一个可读来源即可，关键论断按任务做独立交叉核验），这才是"同一个问题不问八十遍"的机制。
规则见 `references/research-workflow.md` §七。 新 A/B 任务将 claim、数字与引文绑定到原文片段及文件哈希。
未知搜索响应只提示，确认未执行才暂停 WebSearch；原文读取仍开放；有效包允许明确的未解决 claim。
旧包仍可读取，但提示尚未检查原文绑定。输入通过已校验的 research-task.json 交接，
spawn 只传任务文件和 work-dir 路径。

它同时是**上下文防火墙**——而且是**机制**，不是提示词约定：主流程通过 Agent 工具
**显式 spawn `agents/presentation-researcher.md`**（`subagent_type:
student-presentation-suite:presentation-researcher`，不传 `name`），检索因此**不在主对话
上下文里运行**。子代理看不到主对话历史，主流程也拿不到它的搜索过程与原始网页
（约 10 万 token → 约 8 千）。背景、work-id、brief 路径、scope 与材料路径在
已校验的 research-task.json 中；spawn 仅传 task 与 work-dir 的绝对路径。顺序是有意的：
研究必须先完成，`sp-outline` 才能开始排页——收到 `RESEARCH_DONE` 信封前不推进下一阶段。

早先的版本依赖本 skill frontmatter 里的 `context: fork`。该机制在 **`claude -p`（print）
模式下不被 honor**：两次 Live 实测都是 `subagent_stats.spawned = 0`、事件流里没有任何
subagent 事件，主 session 甚至替研究员跑掉了它自己的命令。显式 spawn 在交互与 print
两种模式下行为一致，这才让防火墙成为机制而不是约定。

Research Pack 到 Slide Spec 的转换同样是确定性的：`scripts/research_pack_to_evidence.py`
按固定规则（findings 按 id 排序、再 data_points 按 id 排序 → `E01, E02, …`）编译出
`evidence-map.json`，不由模型手写 ledger。同一个 pack 编译两次得到完全相同的 ledger，
且未通过校验的 pack 会被拒绝编译。`slide_spec_guard.py freeze` 可把
`research-pack.json` / 校验报告 / `evidence-map.json` 三个哈希一起绑进冻结锁——
它们之后被改动，`check` 会立即失败。

规则见 `references/research-workflow.md`，产出形状见 `references/research-pack.schema.json`，
校验用 `scripts/validate_research_pack.py`（会拦截"高置信度只靠单一来源""原文绑定错误""标了冲突却没降置信度""检索受阻却静默降级"等问题）。

关键核验由任务指定。并行抓取与进度保存支持续做，校验区分契约有效与
`ready` / `partial` / `insufficient` 交付状态。研究交接通过一个本地命令完成，仅返回
统计；工具边界按时间与停滞状态停止新增检索，并允许保存部分结果（默认值与覆盖方式见
[研究流程](references/research-workflow.md)）。研究进度仅计入通过校验的任务证据，不再由
无关网页或包重写刷新；新任务要求记录原文支持与范围的二次复读，这不能自动证明语义正确。
有界原文摘录工具保留多行原文，可更新已有证据绑定并只返回元数据。同一会话每个任务仅派
一次；交接失败后的补检须由用户明确发起。

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
质量目标默认 `fast`，引用风格默认课堂引用，两者都不在 intake 中询问。
即使用户说“你决定”，也只是自动采用推荐值，仍需用户通过 `AskUserQuestion`
（确认 / 调整方案 / 更换视觉风格）确认完整 Production Summary。

生产状态为：

`intake_pending → intake_confirmed → planned → producing → qa → complete`

处于 `intake_pending` 时，不得运行环境检查、生成、渲染或交付命令。

插件通过 `workflow_guard.py`（init/confirm/transition）记录状态。
`intake_pending` 下不得跑环境检查、生成、渲染或交付。`ppt_pipeline.py` 拒绝非法
生产步骤。窄的 PreToolUse hooks 分工明确：`scripts/cost_guard.py` 只负责插件源码考古、
未变图片重读、重复巡检和主会话图片/上下文成本；`scripts/runtime_evidence.py` 负责
研究员/critic 的隔离 spawn 与执行凭据；`scripts/production_entry_guard.py` 负责稳定生产
CLI 表面并拒绝直接调用内部 build/evidence 旁路；`scripts/builder_guard.py` 把逐页
 authoring 源码限制在隔离的 presentation-builder 中。上述运行时约束不替代
Production Summary 确认。

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

QA 通过后，`complete` 只把已确认的交付物发布到 `${CLAUDE_PROJECT_DIR}/outputs`，
环境变量不可用时回退到当前项目的 `outputs/`，核对哈希后才标记完成；不同内容的同名文件不会被覆盖。示例：

- `<topic>-presentation.pptx`（讲稿写入 PPTX 备注区；质量门按交付产物判定，
  不读冻结 spec 的 `speaker_notes` 字段）
- `<topic>-speaker-notes.md`
- `<topic>-preview.png` 或 contact sheet
- 已有 deck 改进时的 `<topic>-change-summary.md`
- 按需输出 PDF、HTML 提词版、训练卡、引用清单、质量报告和 revision manifest

生产中用 `ppt_pipeline.py advance --brief-json --work-dir <wd>` 只取下一动作和产物路径；
诊断时再用 `next --json` 查看完整阶段契约。当前独立评审报告和 receipt 到位后，下一次
`advance` 自动执行 QA；全绿则交付，有 blocker 则登记 repair 并返回 Builder 边界，
同一渲染不会再次派 critic。
渲染图由独立 Critic 读取；主会话只在处理具体 blocker 或争议页时按需看图。

确定性步骤失败或执行后无进展时立即停止。修复登记后才激活 Builder Packet；内容未变的 Packet 和哈希校验通过的 critic 预览直接复用；校准输入与证据未变时复用校准预览，不额外消耗轮次。critic 报告结构错误先交回 critic 修正，再决定是否修复页面。每次真实 QA 只记一轮历史，按具体问题而非错误数量比较收敛；持续失败不能豁免完成门禁。

每类交付物独立验收：`full-script` / `teleprompter` 不会隐含要求一份 speaker-notes；
请求 PDF 时必须存在带 PDF 文件签名的真实 `.pdf`，PNG 预览不能替代。因而只请求 PPTX
时，即使没有独立讲稿文件也可以完成。完整稿、提词器正文和独立讲稿按页号从最终
PPTX 备注区导出，规划性的 `note_goal` 不能冒充完整演讲稿。

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

12 种风格不负责选择页面的 `move`。它们的 `visual_language` 会进入绘制：封面色块、焦点旁的
rule、序列页的强调记号，以及页面未指定类型时的默认图表。SVG 母题仍是可选参考。风格参考不能
绕过容量、来源、对比度或用户模板规则。

默认页面声明一个 `move`（`thesis`、`weighted`、`metric`、`proof`、`sequence`、`figure`）。
[`visual-reference-library.json`](skills/sp-deck/references/visual-reference-library.json)
里的参考配方和线框候选是可选探索记录，不是 build 前置。搜图与生图从不默认可用：在
`image-sources.json` 中声明 provider（见
[`references/image-sourcing.md`](references/image-sourcing.md)），环境检查会报告
`image_search_ready` / `image_generation_ready` / `user_assets_ready`。

仓库内含可复现的[黄金样例](examples/golden-sample/README.md)，跑通全流程并达到
`status: complete`。

所有风格共享 `layout-library.json` 中的 36 套页面构图，它们是构图动作装不下文案时的退路。
默认页面声明一个 `move`（`thesis`、`weighted`、`metric`、`proof`、`sequence`、`figure`），
由 `pptx-composition.js` 在绘制时计算字号、主区域和留白。`pptx-layouts.js` 仍会映射 Slide Spec
原生 kind/visual 值，先按素材、数据、项目数量、禁用条件、声明容量和标题区几何容量过滤，
缺输入时沿明确且可行的 fallback 链处理，再结合密度和连续轮廓排序，视觉风格不参与排序。
`scripts/visual_system_smoke_gallery.py` 会生成 12×6 轻量风格参考 gallery、独立
36 版式参考/兜底 gallery 和 12 页 SVG atlas，并在 LibreOffice/Poppler 可用时渲染。

`renderArchetype()` 仍把库内 normalized zones 编译成退路几何。背景同样机读化——
`resolve_design_tokens()` 从每个风格的 `visual_language` 派生按页型的
`background_directives`（深浅三明治渐变场、纹理、角部母题、结构色块），由
`pptx-helpers.js` 的 `renderBackground()` 确定性执行。`pptx-design-grammar.md` 的反 AI 味
硬规则 D1–D10 中可几何判定的部分（标题下强调线、装饰细条、近失对齐、非正交连接线、
内容死区）由 element registry 执行，warning 经 `<pptx>.registry-report.json` sidecar 进
repair packet。

v0.19 落地 html2pptx 思路的无浏览器部分：`pptx-helpers.js` 的 `solveStack()` 量测子项
自然尺寸并分配剩余空间（start/center/between/end），稀疏 claim 栈自动居中、注释列均匀
分布、KPI 值不再挤压标签。同时引入两个机制：PPTAgent 式参考 deck 摄取
（`reference_deck_analysis.py` + `plan --reference-analysis`，`rebuild_from_source` 可继承
好参考 deck 的逐页功能类型作为 archetype 建议）；`style_previews.py` 在 intake 渲染 2–3
份真实两页风格小样，让用户对像素而非形容词做选择（opt-in）。

`deck.js` 遵守 `skills/sp-deck/references/pptxgenjs-safety.md` 中的官方 gotchas，并使用
`pptx-helpers.js` 执行硬安全检查；`pptx-composer.js`、`pptx-layouts.js`、`pptx-shapes.js`、
`pptx-svg-library.js` 与 `pptx-visuals.js` 是可选灵感、工具箱和兜底。未锁定的 `layout` 可自由
调整，`layout_lock: true` 才恢复精确构图；`pptx-icons.js` 提供约 30 个随 token 着色的矢量图标。兜底 composer 先完成全 deck preflight，再用可编辑形状、
连接线、标签和图片/图表结构实现 hero/visual-dominant/process-path/timeline/comparison/
dashboard/architecture/matrix/quote/summary/reference 等布局族。图片默认等比包含并写入 alt text，
图表使用投影可读字号。

## 质量门禁

默认流程的门禁、轮次预算与交付档位见文末「管线流程」生成表（由
`references/pipeline-contract.json` 生成，勿手改）。content QA、asset、visual-inspection、
QA manifest 等独立报告只保留给高风险编辑、排错或用户明确要求审计证据的场景。

v0.8 的视觉门禁（Art Direction、composition 候选、探索证据）由一次运行覆盖：

```powershell
python skills/sp-deck/scripts/run_gates.py --art-direction <a.yaml> --slide-spec <s.yaml> --evidence-dir <work-id> --lock-file <lock.json>
```

通过时只回显 1 行，完整明细写入 `gates-report.json`，delivery 需要的 canonical
`visual-generation-report.json` 同时自动落到 work-dir。生产会话不直调内部 gate 脚本。
该报告不是冻结的计划输入：repair 后允许重新生成，QA 绑定当轮文件，complete 会拒绝
QA 之后再次变化的报告。
render 之后，`ppt_pipeline.py prepare-deliverables` 只按冻结 Slide Spec 中已确认的类型
确定性生成支持/导出文件。PDF 直接采用本轮 render 产出的 PDF，不会扫描同目录的无关
PDF；每个产物在 critic 和 QA 前绑定哈希。QA 后任一产物变化都会阻断 complete，管线回到
生产态重新生成并重跑确定性 QA 与 Delivery；只要 PPTX 和 render 证据未变，就复用已有
视觉评审，不重复启动 critic。
生产段用 `skills/sp-deck/scripts/ppt_pipeline.py next --work-dir <wd> --json` 发现下一步
（`plan` 会 scaffold `deck.js` + `pages/pNN-*.js`，整文件生成器会被 `build` 拒绝）。
工作方式约束（并行调用、定点编辑、写盘即弃、阶段小结、检索走 `sp-research` 显式 spawn、
CD-8 按 200k 窗口工作、CD-9 DeepSeek 读图并行且同 hash 不重读）见
`references/cost-discipline.md`。`session_cost.py` 会在 2 秒内合并用量相同的 assistant
记录，避免 JSONL 三份重复把成本放大。runtime hook 职责按机制拆分：
`scripts/cost_guard.py` 只处理上下文/巡检成本；`scripts/runtime_evidence.py` 负责 Agent
隔离与执行凭据；`scripts/production_entry_guard.py` 负责直接生产入口完整性；
`scripts/builder_guard.py` 负责逐页源码隔离。这样避免重复策略，同时不拦截第一次合法读图。

发现 blocker 时用 `skills/sp-deck/scripts/ppt_pipeline.py repair --work-dir <wd>`
走返工边，不要手工 `workflow_guard.py transition` 推进 `producing` / `complete`。
返工轮次预算见「管线流程」生成表；仍有 blocker 则交付 `incomplete`。确定性缺陷在更早处拦截：`build` 打包后立即本地
跑 `rendered` + `actual-content` 以及 `quality` 门的确定性部分（evidence/timing/lock），
不绿则 `render` 拒绝、`next` 指向免 repair 轮的 builder 改页重建——critic 从不评审
注定返工的 deck。QA 通过后 `complete` 使用 `ppt_pipeline.py complete --work-dir <wd>`。
本地 `scripts/scenario_render_matrix.py --require-render` 可渲染完整场景矩阵，
不会提交生成产物。pull request 会用 `python-constraints.txt` 跑 unittest 套件；push 不跑。
发布验收仍在本地完成，没有必需的发布状态检查；保留手动真实验收与每月依赖巡检报告。

`quality_level: fast`（默认）在 8 页分片线以下由一个 Builder 完成全部页面，超过分 2 片、超过 14 页分 3 片，再做一次最终独立评审。主观视觉分数和风格建议保留为 advisory；页面不可用及确定性门失败仍阻止交付。
每一档都先看样本页再写其余页。fast，以及 standard / rigorous 页数 ≤ 8，先看封面加一张内容页。这两页预览是下一步调度，不会仅因为预览还没生成就拒绝直接 `build`。更长的 standard / rigorous 在 archetype 校准证据现势且 palette 与 style-summary 通过之前会拒绝 `build`，或者该档校准轮次预算已经用完。更长的 standard 校准一轮 archetype 样本，rigorous 至多两轮。独立 `visual-critic` 评审收敛为生产边界的一次——主会话是
Slide Spec 与 Art Direction 的作者，永远不代替 critic 看图；dispatch 在 critic 边界物化
`critic-preview-map.json`（hook 启用时 spawn 时再刷新）；hook 启用时 critic 只能读取
其中列出的当前压缩预览、写 map 指定的 `review_output`。校准由确定性门判定
（证据现势 + palette 门 + style summary），独立评审收敛为生产边界的一次；历史校准评审文件
只作 advisory，不再设门。通过
`builder_packet.py --mode calibration --slides ...` 指定的校准样本会与 active round 原子记录，
后续 `next` / `advance` 会保持这组页面，不会静默退回默认样本。
校准绿灯仅在其绑定的 Slide Spec、Art Direction、页面源码、校准 PPTX、每张预览 PNG、
palette 报告与 render manifest 的路径和 SHA-256 均未变化时有效；陈旧证据会回到 preview
或 critic。校准预览与最终 `rendered` gate 还会检查 PPTX 的 slide、chart 与 diagram XML，
解析 theme `schemeClr`，只允许所选 style 的浅/深两套六角色 palette；raster 图片颜色仍由
来源记录与视觉评审约束。该静态检查会解析 scheme 的基础色与 XML 中的直接色值，但不声称
完整复现所有 OOXML `tint`、`shade`、`alpha` 等颜色变换；最终呈现仍以渲染图和 visual-critic
判断为准。

**每轮 repair 都 spawn 一个新的 builder 实例**，不要继续上一个：一个扛了多轮的实例
常驻上下文涨到 699K，96% 的成本花在 200K 以上；`next --json` 检出跨轮实例时会报
`builder_instance_reuse`。builder 在 build 之后又改了页时，`build` 允许一次补差量重建，
免得为一处微调单开一轮。隔离 builder 也**不做渲染**：`calibration_preview.py` 与所有
render 属于主会话，`builder_guard.py` 同时拒绝渲染命令，以及"用内联脚本读 work-dir
JSON / 改页面模块"的各种写法。

**墙钟 = 回合数 × 往返延迟，而门不占时间**：全套门在一次 147 分钟的运行里实测只有
**150 秒（1.7%）**，其余是 **519 个模型回合**、每个回合只带一个工具调用。`next --json`
`standard`/`rigorous` 给出 `builder_shards` 时，主会话**在同一条消息里 spawn 全部 shard** 让页面工作并发——
分片天然互斥，每个只写自己的 `speaker-notes-shard-<N>.md`（`build` 按页号合并，repair
分片中较新的同页讲稿会替换旧稿，不会重复），并以已有 `speaker-notes.md` 作为逐页基线，
所以覆盖同名 repair shard 不会丢失未修改页面。任何一道门都没有改动。`session_cost.py` 现在输出 `turns`、
`tool_calls_per_turn` 与 `turns_under_20min`，让时间预算可以对着数据判断；它的请求计数
也改为"每个 API 调用一行"（按 message id 取最大 ctx）——旧规则把一个子代理读成 480 个
请求，实际只发了 261 个。

`repair_convergence` 在"某组 blocker 连续两轮逐字相同、其余在动"时报
`suspect_gate_defect`：这组不是页面能修的，对着产物核对一次后，要么给出页面级修法，
要么记为已知门限；当它占 blocker 多数时提额会被拒绝。

会话中断（CLI 在管线子代理仍在运行时被关闭）后重开项目，跑同一条
`ppt_pipeline.py next --work-dir <wd> --json` 即可：包括校准在内的每一步都从盘上
证据（`calibration/` 的 manifest 与 render）推导，管线会指向正确的下一步，
而不是从头重跑，也不会带着未修复的校准 blocker 直接全量 build。

## Runtime

Claude Code 不会自动安装本包的 Python 和 Node runtime 依赖。可以使用仓库
根目录安装脚本，或在本目录手动执行：

```powershell
python -m pip install -r requirements.txt -c python-constraints.txt
python -m pip install -r requirements-claude-pptx.txt -c python-constraints.txt
npm ci
```

### 工作流状态恢复

QA 发现 blocker 时**不要 reset**：走管线返工边重建 generator 并重新进入 QA：

```powershell
python skills/sp-deck/scripts/ppt_pipeline.py repair --work-dir <wd>
```

QA 通过后用以下命令交付：

```powershell
python skills/sp-deck/scripts/ppt_pipeline.py complete --work-dir <wd>
```

`reset` / `unblock` 只是最后手段——它们会丢弃已确认的 Production Summary 并强制
完全重启。修复缺失依赖后从 `blocked` 状态恢复：

```powershell
python scripts/workflow_guard.py unblock
```

`unblock` 会把项目退回 `intake_pending`；恢复生产前需重新确认 Production Summary。

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
python scripts/bump_version.py <version> --dry-run  # 统一版本升级
python scripts/session_cost.py --last 1  # 会话成本复盘（/sp-cost-report 命令等价）
python scripts/session_cost.py --model-io <model-io.jsonl> --agent-metadata-dir <agents-dir> --json
node scripts/run_with_pptxgenjs.js --probe
python scripts/smoke_pptx.py
```

## 环境变量

插件依赖 Claude Code 自动注入的两个环境变量：

| 变量 | 注入方 | 用途 |
|------|--------|------|
| `${CLAUDE_PLUGIN_ROOT}` | 插件系统 | 插件安装目录，用于脚本引用 |
| `${CLAUDE_PROJECT_DIR}` | 运行时 | 当前项目目录，作为交付物输出根目录 |

用户交付物始终写入 `${CLAUDE_PROJECT_DIR}/outputs`；该变量不可用时，插件回退到
当前工作目录。

插件不携带 dotenv 加载器或 `.env.example`。这些变量由 Claude Code 注入；诊断请走
`sp-check-env`，不要复制本地 env 文件。

## 包边界

这是 Claude Code 专用包，不包含 `.codex-plugin`、`agents/openai.yaml`、
`artifact-tool` 或 Codex runtime 声明。

### Open XML SDK 校验

套件在 `shared/pptx_runtime/openxml_validator/` 自带一个小型 .NET 适配器，封装
`DocumentFormat.OpenXml` 3.5.1 做 PPTX 标记/schema 校验。构建方式：

```powershell
dotnet restore shared/pptx_runtime/openxml_validator/OpenXmlValidator.csproj
dotnet build shared/pptx_runtime/openxml_validator/OpenXmlValidator.csproj
```

这是套件自有实现；不复制、不分发 `document-skills` 上游的任何 ECMA/ISO XSD 文件。
完整审计记录见 `references/pptx-runtime-provenance.md`。

安装与更新见仓库根目录 [README-zh.md](../../README-zh.md)；验证与发布见
[AGENTS.md](../../AGENTS.md)；版本历史见 [CHANGELOG.md](../../CHANGELOG.md)。

每个任务使用 `outputs/.pptx-work/<work-id>/workflow-state.json`（init/confirm 传
`--work-id`）。三种模式：create、edit_ooxml、rebuild_from_source（须
source-analysis.md）。编辑保留源文件并须 change-summary.md。QA/complete 前校验
隔离 visual-critic / 研究员凭据（适用阶段）。图片 provider command 需用户批准的
SHA256，项目 JSON 不能自行授权。PowerPoint 验收见
`references/powerpoint-smoke.md`；LibreOffice 通过不代表 Office 已验收。

<!-- pipeline-table:start -->
### 管线流程（由 references/pipeline-contract.json 生成，勿手改）

状态机：`intake_pending` → `intake_confirmed` → `planned` → `producing` → `qa` → `complete`（终止态 `incomplete` / `blocked`）。

QA 门按契约顺序执行：`package` → `static_risk` → `rendered` → `actual_content` → `structural_contract` → `quality` → `delivery`。`build` 打包后立即跑确定性 pre-QA（`static_risk` + `rendered` +
`actual_content` + `structural_contract` + `quality` 门的确定性半部）；非确定性绿的 deck 不会进入 render 与 critic。

| 轮次预算 | 数值 |
| --- | --- |
| QA 返工轮（基数） | 3 |
| QA 返工轮（`repair --extend` 申报后硬上限） | 6 |
| pre-QA 免返工重建（不消耗返工预算） | 2 |
| 并行 Builder 分片上限（按档位收紧） | 3 |

交付档位（`quality_level`，旧值 `basic` / `high-score` 作为别名兼容）：

| 档位 | 校准轮 | 分片上限 | 阻断项 |
| --- | --- | --- | --- |
| `fast` | 0 | 1（≤8 页），2（9–14），3（多于 14） | critical + 确定性失败 |
| `standard` | 1 | 2 | 同上；主观分和探索材料只作建议 |
| `rigorous` | 2 | 3 | + 风格 Major + 视觉回归 + 连续三页同一动作 |

交付保证：每个已确认产物在 `complete` 前按冻结 Slide Spec 核对内容与页数（PPTX/PDF 页数、
逐页讲稿段数），并绑定最终路径与哈希到 `outputs/` 目录。
<!-- pipeline-table:end -->
