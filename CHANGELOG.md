# Changelog

本文件记录 `claude-code` 分支的 Claude Code marketplace 与
`student-presentation-suite` 插件版本。版本按时间倒序排列；`main` 分支的
Codex 发行记录不在此维护。

## Unreleased

### CI 修复：渲染矩阵适配视觉复核证据契约（2026-09-12）

- **修复 gallery 冒烟（`visual_system_smoke_gallery.py`）的两层失败**：
  1. style tokens 缺 geometry 时 `addTitle` 的 fallback 标题框只有 ~0.56in，
     装不下 32pt 标题行——`addTitle` 现在对标题框做自适应兜底（不足时按
     title 字号单行所需扩展，扩幅落在标题区与内容区之间的 gap 内）；
  2. 长标题压力用例的框尺寸按旧的宽容行为设计——已按新契约调整框高，
     并让小 zone 的样例文本在角色下限放不下时降级为 caption 重试
     （连 11pt 都放不下仍照常抛错，真缺陷不被掩盖）。
- **修复 `scenario_render_matrix.py --require-render` 的 CI 失败（两个根因）**：
  1. 反自证收紧后裸 `--visual-reviewed` 不再放行，矩阵脚本的 strict delivery
     调用缺 sha256 绑定的复核报告——矩阵现在在渲染后按场景编写绑定当前 PPTX
     的 `visual-review.json` 并传给 delivery，与实战流程一致；
  2. **normalize 新增 chart ser 子元素重排**：pptxgenjs 单系列多色柱状图
     （逐点配色 accentRamp）把 `<c:dPt>` 写在 `<c:dLbls>` 之后，违反 CT_*Ser
     元素序列，OpenXML SDK 校验报 unexpected child——normalize 现在把 dPt
     统一移到 dLbls 之前（保持相对顺序），单测
     `tests/test_normalize_chart.py`（2 例）锁定。
- **补齐 `pptx_delivery_check_v071.py` 的 `--visual-review-report` 参数**并透传
  给 `inspect_delivery`——此前该 wrapper 在 simple 模式下永远无法达到 complete
  （第二处被"致命 1"修复牵连的调用点）；`pptx-qa.md` Gate 4 示例同步更新。
- `slide_spec_to_pptx_brief.py` 生成的 QA 指引同步：说明裸 `--visual-reviewed`
  不再通过，复核报告是必备证据。
- 教训：收紧校验或新增生成特性时，必须全仓 grep 同一脚本的**全部调用点**，
  并让渲染矩阵（CI 的 Linux 路径）在本地跑一遍——两个问题都是 CI 首次暴露。

### 质量检查流程优化：gate-all 单进程门禁（2026-09-12）

- **新增 `pptx_tool.py gate-all`**：package validate / actual-content readback /
  rendered readback / quality gate 四个门禁在**一个进程内**顺序执行，共享一次
  解释器启动；每个门禁仍写出各自独立的报告文件，另产 `gate-all-report.json`
  合并汇总（含每步耗时与 blocker 数）。实测 10 页 deck：**4.10s → 2.12s（-48%）**。
- **fail-closed 语义不变**：任一门禁失败整体 exit 2；单步异常被隔离（崩溃的门禁
  记 error，不拖垮其余步骤）；各单门禁 CLI 与报告 schema 完全向后兼容。
- 行为测试 `tests/test_gate_all.py`（2 例，fixture 由真实 Node 管线生成）：
  全绿路径（4 报告 + 哈希绑定 + merged 汇总）与 fail-closed 路径（9pt 违例 +
  claim 回读失败 + 复核哈希失效三重拦截，其余步骤仍独立出结论）。
- `pptx-qa.md` 写入迭代期快速通道与 spec 报告复用约定（O2/O5）；
  三个门禁脚本拆出 `run(args)` 供编排复用，CLI 行为不变。
- 分析依据与后续优化项（O3 视觉审查分级看图、O4 deck 模板化、O6 validate 单次
  解析经评估收益 <1s 暂缓）见 `outputs/质量检查流程分析.md`。

### 实战验收暴露并修复的缺陷（2026-09-12）

- **workflow_guard 状态机与 v0.8 门禁链口径分裂**：`validate_completion_manifest`
  硬编码只认 `simplified-v1` + core 0.7.1，v0.8 全链路（全部门禁绿灯）在 complete
  转换处被旧口径挡死。新增 `simplified-v08` 分支：校验强度对齐（7 项检查显式
  True + 6 个产物哈希 + 预览全覆盖 + core 0.8），并补行为测试
  （`test_complete_accepts_simplified_v08_delivery`）。
- 同日实跑中修复：`runtime_paths.project_root` 空 env dict 回退泄漏
  `CLAUDE_PROJECT_DIR`、MSYS `/e/foo` 路径在 Windows 错拼当前盘符（原被误标为
  "环境性测试失败"，实为影响所有真实生成的运行时缺陷）。
- 实跑记录：一次全新主题的 10 页生成中，各门禁依次拦截了 spec 枚举违规、
  标题溢出、6 页缺 claim 原文、evidence ledger 不对账等 4 类真实问题，
  最终全门禁通过、状态机走完 complete（详见 outputs/ai-showcase/）。

### 图表逐点配色、章节页锚点与视觉基线归档

- **单系列柱/条形图逐点配色**：`pptx-shapes.js` 新增 `accentRamp()`——以强调色为最重色、
  其余按"向画布方向递减"生成同族色阶（深色页上淡化即为压暗），并支持 `highlight_index`
  指定用满色的数据点。此前 `chartColors` 按 series 分配，单系列多类目时所有柱子同色，
  色彩不承载任何分类信息；pptxgenjs 只在 `chartColors` 长度 >1 时才写 `<c:dPt>`，
  现在单系列时按数据点数量展开配色。实测 3 类目 → `1D4ED8 / 7593E6 / ABBEEF`；
  多系列与 stacked 仍保持按 series 着色。
- **章节分隔页补页脚锚点 + 修正页码错位**：黄金样例的章节页是全 deck 唯一没有页脚的页面，
  内容仅占页面高度 31%、底部留白 39%，深色场上明显悬空。补上页脚后底部留白降至 1.8%、
  内容占比升至 68.7%。顺带修复页码错位——该页不计数导致页码序列为
  `01,02,03…07,09`（"08" 从未出现，末页却标 09/09），现已按出现顺序重排为 01–09。
- **留白问题的量化复核**：新增量测脚本按页统计顶部/底部留白与内容占比。
  144 页风格样张库平均底部留白 **3.6%**、无一页 >15%；黄金样例修复后全部页面底部留白 1.8%。
  结论：**此前"内容页底部 30–40% 死空间"的判断不成立**（该说法源自未经证实的目测），
  真实问题只有章节页这一处，已修复。
- **视觉基线归档**：`outputs/_diag` 下 golden / v2 / v3 三套 9 页渲染长期并存，
  三套封面-页头-页脚体系互不相同，导致 visual-baseline 无法区分"版本差异"与"真实缺陷"。
  现移入 `outputs/_diag/_archive/`，并补 `README.md` 说明唯一有效基线由
  `examples/golden-sample/build.py` 与 `examples/visual-template-gallery/build.py` 重建。
- 顺带修复 `ruff` 报出的 2 处 import 排序（`pptx_tool.py`、`pptx_runtime/__init__.py`，
  前序改动遗留），`ruff` / `eslint` / `prettier` 现已全部干净。

### 代码审查驱动的安全与健壮性修复（逐项来自 `插件代码审查报告.md`）

- **修复两个长期被误标为"环境性失败"的真实缺陷**（`test_runtime_paths` 的 2 个
  失败从项目开跑第一天就存在，本轮根因定位后全部转绿）：
  - `runtime_paths.project_root` 的 `env or os.environ` 让空 dict（调用方明确表示
    "无环境变量"）回退到真实进程环境，`CLAUDE_PROJECT_DIR` 泄漏进测试与子命令；
    改为 `env if env is not None else os.environ`；
  - `CLAUDE_PROJECT_DIR` 为 Git-Bash/MSYS 形式（`/e/foo`）时，Windows 上
    `Path('/e/foo').resolve()` 错误拼接到当前盘符根（实际观测输出到
    `E:/e/student-ppt-create/outputs`）；新增 `_normalize_platform_path`，首段为
    单个盘符字母时按 MSYS 约定转换成 `X:\foo`，`/tmp` 类路径不受影响；
  - node wrapper probe 测试的 fixture 迁出用户 home 祖先链（本机
    `C:\Users\<user>\node_modules` 残留有 pptxgenjs，会让空项目误判 project 命中）
    与插件 node_modules 祖先链，并清除 `NODE_PATH` 兜底，契约验证不再依赖机器
    环境巧合。

- **优化建议区落地一批（2026-09-11 第五轮）**：
  - `pptx-element-registry.js` 默认画布 13.333×7.5 → **10×5.625in**，与
    `pptx-helpers.js` 的 STUDENT_WIDE 版式对齐——越界判定此前用了错误基准；
  - `design-tokens.json` 移除指向 draft-2020-12 的假 `$schema`（校验器按空 schema
    处理、任何内容都通过）；
  - `run_with_pptxgenjs.js` 硬链接失败改为**除 EEXIST 外一律降级复制**（FAT/exFAT
    的 ENOSYS、网络盘的 EACCES 不再让构建崩溃；EEXIST 才视为竞态异常）；
  - `pptx-layouts.js` 在 `executableLayout` 消费点注明 `LAYOUT_VARIANTS` 第二形状
    当前不被消费（8 个 family 的 shape_slots 均为 1 槽）；
  - **修正一条审查误报**：`coverImage` 的 `imageSize()` 结果实际用于 fail-fast
    校验（图片损坏提前抛错），并非死 IO，保持原样。
  - 同时：composer 重构后的**带渲染完整构建再次 exit 0**（golden9，全门禁含
    delivery）。

- **26 条收尾：文档声称的关键阻断行为全部改为行为测试**。新增
  `tests/test_composer_preflight.py`（4 例，真实 Node 子进程驱动 composer）：
  adaptive-freeform 缺 caller-supplied zones 即阻断、zone 越画布即拒绝、合法 zones
  通过且结果携带 composition、renderDeck 抛错信息含页号与每页明细（第 23 条行为的
  直接验证）；`test_pptx_delivery_check` 新增"缺预览 → delivery incomplete（且复核
  报告本身有效）"行为用例，替代 qa 文档的纯文本断言。文档契约断言（SKILL.md 须写明
  某指令）保留——该技能的运行时就是模型读文档；门禁退出码/证据绑定/渲染回读的行为
  覆盖已由 test_gate_exit_codes、test_resolution_evidence、test_rendered_check 补齐。

- **一般级条目清账（第 16–32 条中尚未处理的 11 条）**：
  - 17 `pptx_delivery_check_v08.validate_visual_generation_report`：报告根为 list 时
    非 dict 早退，不再在后续行触发 AttributeError；
  - 18 `pptx_visual_generation_gate_v08`：high-leverage 页检索引用与候选引用**任一侧
    为空即阻断**（`evidence_chain_incomplete`），旧写法两侧同时缺失会整段跳过；
  - 19 `art_direction_check`：asset_plan 增加**总量下限**（`asset_mix_total_too_low`，
    high_score 需 ≥5 个视觉元素），旧判定只数"类别数"不看总量，审查原始反例
    （8 页 deck 仅 4 个元素）现被拦截；
  - 20 `art_direction_check`：caption 允许区间 8–13pt → **11–13pt**，与
    design-tokens `caption_min_pt: 11` 统一；
  - 21 `pptx-composer`：compose 阶段的 preflight 结果（含 composition layout）
    直接传入 renderSlide，每页不再重复跑 2 次 preflight / 3 次 actualComposition；
  - 22 `pptx-composer`：asset 存在性按绝对路径缓存（`assetExists`），消除同一文件
    每页最多 5 次同步 `existsSync` 的 IO 放大；
  - 23 preflight 抛错信息拼入每页 `errors` 明细，不再只列 slide_id；
  - 25 `requirements-claude-pptx.txt` 显式声明 `python-pptx>=1.0`（tests 直接 import，
    过去靠 markitdown[pptx] 传递依赖）；
  - 28 `pptx_tool.py` 未提供 `--preview` 时 `rendered_page_count` 记 `null`（"未渲染"），
    与"渲染 0 页"区分，下游 delivery_check 本就按 None/0 容忍；
  - 30 `bump_version.py`：去掉 `shell=sys.platform=="win32"` 分裂行为，改
    `shutil.which("npm")` 解析真实可执行文件（Windows 的 npm 实为 .cmd）；读 JSON
    改 `utf-8-sig` 容忍 BOM；
  - 32 `render.py` 清理旧 PDF 的 `glob()` 模式对用户文件名 `glob.escape`，防
    `[`/`*`/`?` 通配符误匹配。
  - 另核对 16/24/27/29/31 五条在先前轮次已修（16 的 `??`、24 的尺寸下限、27 的
    try 包裹、29 的 posix 回退与 stderr 诊断、31 的 zones 空值），本轮确认无需再动。

- **Python ↔ Node 双栈契约测试（审查架构 D）**：新增 `tests/test_stack_contract.py`
  （4 例），用真实 Node 管线生成 3 页 deck 后在同一产物上断言两侧一致：
  ① JS `SLIDE_W_IN/H_IN`（10×5.625in）× 914400 == Python `pptx_static_core`
  兜底 EMU；② 产物 `p:sldSz` 与两侧常量一致；③ zip 条目口径（workflow_guard /
  delivery_check）与 `sldIdLst` 直系子元素口径（`pptx_runtime.package`）页数相同；
  ④ design-tokens 的 `title_min_pt/body_cjk_min_pt` ≥ 1.45 且 `pptx_rendered_check`
  读同一令牌文件。**对齐过程中确认并修复一处真实分歧**：画布事实标准在 JS 侧
  （`applyTokens` 以 STUDENT_WIDE 写盘 9144000×5143500 EMU），而 Python 兜底常量、
  `pptx-visual-engine.md` 文档示例均为 13.333×7.5in——已全部对齐为 10×5.625in
  （`pptx_static_core.DEFAULT_SLIDE_*`、`pptx_rendered_check.DEFAULT_SLIDE_*`、文档），
  未改 JS 布局引擎，144 页既有版式不受影响。

- **质量门禁反自证（审查致命 1）**：
  - `pptx_quality_gate_v071.py`：阻断级 finding 的 `resolved: true` 不再被直接跳过——
    必须携带 `resolved_evidence`（`before_sha256` 非空、`after_sha256` 等于当前被门禁的
    PPTX 哈希），否则视为未解决并追加 `resolved_without_evidence`。模型自证"已修复"
    从此要么有产物凭证、要么可被证伪。
  - `pptx_delivery_check.py` / `pptx_delivery_check_v08.py`：simple 模式的完成判定
    不再信任裸 `--visual-reviewed` 布尔量（该 flag 由生成方自己断言，证明力为零），
    必须提供 `--visual-review-report <visual-review.json>`，且报告的 `pptx_sha256`
    与当前 PPTX 一致、含逐页条目；缺失/过期/未绑定均判 incomplete。
  - `build.py` 传入绑定报告；SKILL.md 第 13 步与 `slide_spec_to_pptx_brief.py`
    命令模板同步更新。
  - 新增 `tests/test_resolution_evidence.py`（6 例）；交付测试新增"裸 flag 拒绝"
    与"过期报告拒绝"两例，既有契约测试改为传绑定报告。

- **cjk-fonts 原地覆盖写用户原件（审查致命 2）→ 原子替换**：`shared/pptx_runtime/cjk_fonts.py`
  过去在 `output is None` 时直接 `ZipFile(target, "w")` 写回输入文件本身，写入中途异常/断电/
  磁盘满即永久损毁用户原 PPTX，且 docstring 声称"原子替换"与实现相反。现改为写临时文件 +
  `os.replace` 原子落盘；同时补 zip 成员大小/压缩比上限，杜绝 zip bomb。
- **`addFittedText` 静默吞掉调用方字号（审查严重）→ 调用方优先**：`fontSize: fit.fontSize`
  原本写在展开运算符之后，任何调用方传入的字号都被覆盖且不报错；`addSectionHero` 传 32pt
  实际输出 26pt，导致 Hero 标题与副标题同号。现改为"调用方显式给字号则尊重，否则自适应"。
- **NaN / 负数坐标守卫**：`weightedColumns` 的 `gap` 无默认时 `NaN <= 0` 恒假，NaN 坐标会写进
  OOXML；现给 `gap` 默认 0 并校验 `usable <= 0` 抛 `RangeError`。散点图 `x/y` 缺失时回退值可能为
  `NaN`，现用 `Number.isFinite` 守卫。标题框在 `area.y` 大于回退顶时出现负高度，现已钳制。
- **权限检查方向反了（审查严重）→ 缺省拒绝**：`check_claude_pptx_env.py` 用
  `permission.get("allow_web_search") is not False` 缺省放行，而 `fetch_images.py` 用真值判定
  缺省拒绝，两处语义矛盾。统一为缺省拒绝（显式 `false` 才关闭）。
- **`fetch_images` 安全加固**：provider id 经 `_slug` 净化，防止 `../` 把抓取结果写到 `out_dir`
  之外；子进程改为列表化参数（无 shell 注入）、加 `timeout`、失败时记录 stderr 便于诊断；
  `shlex` 解析回退为默认 posix（非 posix 模式不剥离引号会让 `python -c "..."` 失效，原先认为
  "posix 吞反斜杠"的审查结论经实测不成立）。
- **`pptx_tool.py` 健壮性**：`add-slide` 用 `_basename` 净化来源文件名，避免路径穿越；
  markitdown / 缩略图子进程改为列表化参数并显式 `encoding="utf-8"`；`package.py` 解包已具备
  Zip-Slip 与符号链接防护（审查确认）。
- **三个 v0.8 门禁默认 fail-open（审查严重）→ 默认失败收紧**：`art_direction_check.py`、
  `composition_candidate_check.py`、`pptx_visual_generation_gate_v08.py` 原为
  `if args.strict and not report["ok"]: return 2`，不加 `--strict` 永远 `return 0`。
  现改为"默认 fail-closed，显式 `--lenient` 才退出 0"，`--strict` 保留为兼容空操作。
  `build.py` 全程已传 `--strict`，行为完全不变；新增 `tests/test_gate_exit_codes.py`
  锁定该退出码契约（审查指出这三处退出码此前无任何测试覆盖）。
- **渲染产物回读门禁（审查架构 A："校验声明值而非渲染产物"）**：新增
  `skills/sp-deck/scripts/pptx_rendered_check.py`，直接解包生成的 PPTX 量测四项实际指标——
  ① 全部字号 ≥ `caption_min_pt`；② deck 级 max/mode 字号比值 ≥ 令牌要求的 1.45×；
  ③ 每个含值轴的图表必须显式 `c:max`/`c:min`（禁止自动缩放）；④ 每页底部留白 ≤ 25%。
  默认失败收紧、`--lenient` 显式退出（与其他门禁契约一致），已接入 golden 构建
  与 SKILL.md 第 9 步 Actual Artifact Check。**首次运行即拦截一处真实缺陷**：
  golden 样例证据页的图表裸调 `slide.addChart` 绕过 `addChartWithTakeaway`，
  值轴自动缩放——且该图 `valAxisHidden`，说明轴隐藏时柱高比例同样失真，门禁对此不豁免；
  已补显式 `80/0/20`。**第二次拦截（144 页样张库压测）**：12 个风格的全部内容页
  kicker/页码/标签规格为 9–10pt，低于令牌下限 11pt——已统一提升至 11pt 并把页码盒
  加高（0.24→0.30in，底边不变）以满足 0.85 填充率上限。新增 `tests/test_rendered_check.py`
  （6 例，合成最小 PPTX，不依赖 node）。
  已知局限：ratio 以 mode 作为"正文"代理，页面小标签 run 数量超过正文时会低估风险
  （golden 中 mode=11pt），属纵深防御而非精确判定。
- 顺带收敛一处自引入隐患：字号修复把 `body_max_pt` 设为 26，导致 `32/26=1.23` 低于
  `art_direction_check` 的 1.45× 门禁；现收敛为 22，`32/22=1.45` 恒成立。

### 视觉缺陷修复：字号层级、图表轴、结论面板与换行（逐项来自视觉审查报告）

- **字号层级兑现文档承诺**：`design-tokens.json` 的 `typography` 实际值长期停留在
  `title 24 / body 22 / caption 10`，而 12 份 `visual-styles/*.md` 与 `visual-style-menu.md`
  声明的是 **40 / 32 / 26 / 22 / 11**，且文档明确要求"标题/正文 ≥ 1.45×"。
  现在 defaults 改为 `title_min_pt 32`、`title_max_pt 44`、`cover_title_pt 40`、
  `subtitle_min_pt 26`、`label_min_pt 16`、`caption_min_pt 11`；
  `fontSizeScale()` 新增 `subtitle` 中间档，并在缺失 `title_min_pt` 时按
  `max(32, body×1.45)` 兜底。实测标题/正文比值由 1.09 提升到 **1.50**。
- **图表纵轴不再完全交给 pptxgenjs 自动缩放**：`pptx-visuals.js` 新增
  `niceNumber()` / `resolveAxisRange()`，为数值轴计算"整齐上限 + 8% 顶部余量"并写出
  `valAxisMaxVal` / `valAxisMinVal` / `valAxisMajorUnit`，同时开放
  `axis_max` / `axis_min` 覆盖（位于 `visual.details`，无需改 schema）。
  此前最高点的 `outEnd` 数据标签会顶到绘图区上沿，且轴上限随数据浮动导致跨页比例不可比。
- **图表内文字改为从字号层级派生**：图表标题 22pt→17pt、数据标签 18pt→14pt、
  图例 18pt→13pt、轴标签 18pt→12pt，全部低于正文 22pt，消除"一页两个准标题"。
- **结论面板自适应**：`takeawayLayout()` 按结论文案字数决定面板宽度与高度并垂直居中，
  空出的宽度还给图表/表格；短结论不再撑成整列高的空盒子
  （实测：17 字 → 2.39×1.43in，5 字 → 2.18×0.86in）。图表与表格两处共用。
- **架构图跨行连线改为竖直**：节点 >3 换行时，旧实现直接连两格中点会画出斜穿版面的
  对角箭头；现在同行画水平线、跨行画指向正上方节点的竖直线。
- **卡片填充对比度保护**：`pptx-shapes.js` 新增 `ensureFillContrast()`，
  当卡片填充与画布亮度差过小时（如纯白卡片落在 `F8FAFC` 画布上），
  沿远离画布的方向按固定 4% 步长微调填充。12 套风格中 5 套的卡片/画布对比度
  由 1.05 提升到 1.13–1.14，其余 7 套本就达标、保持不变。
- **孤字换行控制**：`pptx-helpers.js` 新增 `balancedBox()` / `resolveTextPlacement()`——
  估算末行长度，若会出现 ≤25% 行宽的孤字，就把文本框收窄到 `ceil(字数/行数)` 宽度
  （居中文本同步调整 x 保持视觉居中）；收窄后若放不下则回退原盒子。
  不改文本本身，因此不影响"claim 必须出现在渲染文本"一类门禁。
  实测 13 字标题由 12+1 的孤字断行改为 7+6（盒宽 5.30in→3.09in）。
- 同步对齐 `examples/golden-sample/tokens.json`、
  `examples/visual-template-gallery/gallery-input.json` 等内联 tokens 的字号体系。
- 验证：264 个单元测试无新增失败（仍为 2 个既有环境性失败）；
  ruff / eslint / prettier 全过；12 风格 × 12 版式 144 页样张库重建成功，
  OpenXML 校验 0 错误；各项修复均以生成物 XML 中的实际数值核对，未依赖目测。

### 视觉风格深化：9 维视觉语言 + 144 页样张库

- `design-tokens.json`（catalog 2.5）：`visual_language` 从 6 维扩到 **9 维**——
  新增 `pattern`（背景纹理 dots/waves/grid/none）、`emphasis_marker`（列表强调符
  dot/square/slash/chevron/number/dash/leaf）、`cover_band`（封面装饰几何
  bottom-band/side-band/corner-block/none），12 风格按气质差异化分配且互不重复。
- `patternBackground` 改用 SVG `<pattern>` 平铺整页（原实现拉伸 32px 贴片会变成
  一个巨大孤立图形）。
- 样张库 9→**12 版式/风格**（共 144 页）：新增 KPI 看板（消费 `emphasis`）、
  架构分层、参考文献（消费 `emphasis_marker`）；章节页纹理按 `pattern` 全风格
  启用；封面按 `cover_band` 加装饰几何；密集文字页支持 `noMotif` 避免母题压字。
- 144 页基线已用 `visual-baseline` 记录。

### 富文本修复、图片执行器与视觉回归基线

- **富文本行内强调解禁**：normalize 新增富文本修复——pptxgenjs 对多 run 文本
  在每个 run 后写出非法 `<a:pPr>`，导致含行内变色的页面必然不过 OpenXML 校验；
  现在自动删除游离 pPr，行内强调正式可用（探针 + 回归测试锁定）。
- **图片 provider 执行器**：新增 `shared/pptx_runtime/fetch_images.py` 与
  `pptx_tool.py fetch-images` 命令，按 `image-sources.json` 契约执行：
  user-assets 优先匹配复制；image-generation / web-search 跑声明的 command
  模板（`{query}`/`{url}`/`{output}` 占位符）；权限门禁运行时强制
  （`allow_web_search` / `allow_generation`），requires 命令缺失自动跳过；
  产出带 `provider_id`/`permission`/`source_url`/`retrieved_at` 的留痕记录。
- **视觉回归基线**：新增 `shared/pptx_runtime/visual_baseline.py` 与
  `pptx_tool.py visual-baseline record|compare`——渲染页降为 64 位感知哈希，
  超阈值的页面变化、缺失页全部报告，为样张库与成品 deck 提供可复现的
  视觉回归防线（阈值可调，默认 6/64）。
- 测试 +6（共 264）。

### 落地精美制作差距调研的 6 项改进（P0/P1 全部完成）

- **中文字体族**：`design-tokens.json`（catalog 2.3）12 种风格各配专属字体组合——
  拉丁 title/body（全部在安全白名单内、12 组合互不重复）+ CJK `cjk_title_font`/
  `cjk_body_font` 配对（黑体/宋体/雅黑/等线/楷体/仿宋按风格气质分配）；
  新增 `pptx_tool.py cjk-fonts` 后处理命令（`shared/pptx_runtime/cjk_fonts.py`），
  为所有 `<a:latin>` 补写 `<a:ea>` 东亚字体——此前中文 deck 的字体意图对汉字完全失效。
- **阴影系统**：defaults 新增 `effects.soft_shadow` token；`H.softShadow()` 以浅色盘
  primary_text 为影色，深色页自动禁用；`addStyledContainer` 浅色页面板默认带 soft shadow
  （`options.shadow === false` 可关），`addAnnotatedVisual` 图片同步应用。
- **组件去等宽化**：新增 `H.weightedColumns()`；`addComparison` 支持 `weights`，
  且 `highlight` 时默认 1.55 倍不对称倾斜；`addProcessFlow` 支持 `weights`；
  `addMetricDashboard` 支持 `emphasis`（1.6 倍权重）。默认等宽行为向后兼容。
- **图表扩展**：`addChartWithTakeaway` 支持 `kind: bar/line/doughnut`、bar `orientation`、
  `hole_size`；valGridLine 默认关闭（`gridlines: true` 显式恢复）。normalize 修复
  pptxgenjs line 图三处非法输出：缺 `<c:grouping>`、ser 内非法 `invertIfNegative`、
  chart 级与 ser 级 `marker` 位置错误。
- **表格与图片**：新增 `addStyledTable`（表头强调/斑马纹/`highlight_row`/可选右侧结论栏，
  注册为 `table` 视觉家族）；`addAnnotatedVisual` 支持 `fit: 'cover'` 裁切与
  `tint: <透明度>` 单色着色叠层。
- **纹理背景**：新增 `H.patternBackground()`（dots/waves/grid，复用现成 getPatternSvg，
  此前从未接线）；样张库中 expressive 风格（cherry/creative/coral）章节页启用。
- 测试 +7（共 257）：CJK 配对唯一性、a:ea 后处理、softShadow 三态、5 项不对称布局断言。

### 每风格视觉语言层 + 108 页渲染模板样张库

- `references/design-tokens.json`（catalog 升至 2.2）：12 种风格各新增 `visual_language`
  （`rule` 强调规则线手法 / `panel` 面板处理 / `radius` 圆角 / `motif_at` 母题位置 /
  `chart` 签名图表语法 / `decor` 装饰密度），12 套互不重复，回答"同一版式在不同风格下
  该长什么样"。
- 新增 `examples/visual-template-gallery/`：参数化生成器按 layout-library 的归一化分区
  为 12 种风格各渲染 9 页高质量模板（分栏封面/章节陈述/论点聚焦/数据论证/前后对比/
  时间线路径/引语聚焦/图注案例/收尾呼应，共 108 页），全部通过文本适配守卫与
  OpenXML 打包校验，作为生成时的"视觉上限参考"。
- `visual-style-menu.md` 新增「The shared visual system and per-style language」一节，
  说明 visual_language 契约与渲染样张的参考用法（借手法、不抄文案）。
- 测试 +1（共 250）：锁住 12 套 visual_language 的词表、半径范围与互不重复。

### 12 种风格补齐深色体系，封面与正文统一色系

- 问题：每个风格只有一套浅色 palette，没有配套的封面/章节/收尾配色，导致深色封面与浅色
  正文各说各话；`paletteMode(tokens, 'dark')` 对任何内置风格都会抛
  "Dark palette mode requires tokens.dark_palette"。
- `references/design-tokens.json`（catalog 升至 2.1）：12 种风格各新增 `dark_palette`
  六角色配色，与浅色盘同色相家族（封面/章节/收尾底色取自该风格 primary_text 的深色化，
  强调色为浅色强调在同色相上的提亮），并逐一对通过对比度门禁。
- `shared/design_tokens.py`：新增 `derive_dark_palette()`，为自定义/未知风格自动派生
  对比度安全的深色配套；`resolve_design_tokens()` 保证任何风格都返回 `dark_palette`；
  `validate_custom_style()` 接受可选 `dark_palette` 并按同一标准做对比度校验，
  对比度逻辑收敛为 `_palette_errors()`。
- 12 个 `visual-styles/*.md` 重写表述：说明 40/32/26/22/11pt 字号层级、强调色的语义
  （强调句/推荐方案/关键数字/结论节点）、背景节奏（深封面→浅内容→深章节→深收尾）与
  evidence rail 母题，并把深浅两套 color scheme 的对应关系写清楚。
- `visual-style-menu.md` 新增「Light and dark are one scheme, not two」与「The shared visual
  system」两节，明确双 palette 契约与对比度下限。
- 测试：新增深色配套对比度、12 套深色互不重复、自定义深色缺失时派生/提供时校验、
  以及风格文件必须写出深色底色的断言（249 个用例）。
- 补齐会让配色再次脱节的指导缺口：`pptx-art-direction.md` 新增
  「Bind pages to the style's two palettes」一节（原 2–6 节顺延为 3–7），明确
  `background_rhythm` 的 `mode: dark` 只表示"用该风格的 dark palette"，不得自选深色、
  不得在 generator 里写死 hex；`pptx-visual-critic.md` 新增配色一致性原则与必查项
  （把深浅两页并排比对，palette 之外的强调色/底色按 art-direction 或 implementation 返修）。
- 黄金样例改为直接使用风格自带的深色方案，移除本地临时派生，深色收尾 hairline 改用
  `secondary_accent` token。

### 黄金样例视觉系统重做

- `examples/golden-sample/deck.js` 重写视觉系统：真实的背景节奏（深色封面 / 浅色内容 /
  深色章节页 / 深色收尾）、40/32/26/22/11 字号层级、强调色承担语义（强调句、推荐方案、
  关键数字、结论节点）、统一的页面系统（眉标 + 标题 + 强调规则线 + 细分隔页脚），
  以及贯穿全篇的 evidence rail 母题。
- 图表改为手写：去掉网格线、单强调色系列、直接数据标签、大数字先于图表被读到。
- 第 4 页由"三等分卡片"改为"三个从属因素汇聚到一个主导结论面板"；第 8 页由等宽卡片
  改为带强调终点的编号路径；第 6 页以排版化引用证据取代占位图。
- 修复生成期真实缺陷：连接线出现负宽度（无效 `a:ext`）、深色页误用深色盘文字色导致
  白底白字、`title/body` 比值低于 1.45 门禁（标题提至 32pt）。
- 记录并通过规避 pptxgenjs 缺陷：富文本数组（≥2 run）会写出非法 `a:pPr`，导致
  OpenXML schema 校验失败；强调色改用逐行独立文本框实现。
- `build.py` 支持输出文件被占用时的重试与降级命名，并新增完整交付链路
  （spec 冻结/修订 → 讲稿 → 渲染 → 质量门禁 → 交付门禁）。

### 视觉参考库扩至 32 条 recipe

- `skills/sp-deck/references/visual-reference-library.json` 从 16 条扩展到 32 条，
  新增图片主导（`cover-full-bleed-overlay`、`image-dominant-edge-crop`、
  `image-pull-quote-duotone`）、案例/引语（`quote-pull-attribution`）、
  结构关系（`concept-diagram-split`、`process-linear-steps`、`process-cycle-loop`、
  `hierarchy-layered-funnel`）、对比与表格（`comparison-before-after`、
  `table-editorial-clean`）、数据（`data-kpi-dashboard`、`data-small-multiples`）、
  章节与收尾（`section-divider-typographic`、`recap-numbered-path`、
  `hook-question-tension`、`closing-next-step-ask`）。
- 新 recipe 沿用既有 role/grammar/visual_strategy/density 词表，silhouette 与 id 均唯一；
  `visual_reference_select.py` 检索结果覆盖全部 8 种 visual strategy，且不改变既有
  retrieval 断言。

### 显式图片获取能力（搜图/生图）

- 新增 `references/image-sourcing.md` 契约与 `references/image-sources.schema.json`：
  会话通过项目根目录 `image-sources.json` 声明 `user-assets` / `web-search` /
  `image-generation` provider、权限开关与来源留痕要求；未声明时一律视为不可用。
- `check_claude_pptx_env.py` 新增 `resolve_image_sources()`，报告
  `Image sourcing` / `Image search` 检查与 `image_search_ready` /
  `image_generation_ready` / `user_assets_ready` 三项能力；无配置时
  `External image generation` 仍为 `optional-unknown`，保持既有行为。
- `references/asset-manifest.schema.json` 增加可选来源字段 `provider_id`、
  `source_url`、`license`、`retrieved_at`、`prompt`，用于外部/生成素材留痕。
- `image-strategy.md`、`presentation-intake.md`、`sp-deck/SKILL.md` 与根 `AGENTS.md`
  接入该契约：intake 的配图选项可用性以解析出的能力为准。

### 可复现黄金样例

- 新增 `examples/golden-sample/`：9 页「AI 幻觉」课程汇报，含 brief、Slide Spec、
  Art Direction、4 个高价值页的多候选构图、`deck.js`、`image-sources.json`、
  `asset-manifest.json`、期望视觉评审与驱动脚本 `build.py`。
- `build.py` 按真实顺序运行 art-direction 门禁 → 参考检索 → 候选校验 → wireframe →
  v0.8 visual generation gate → 生成 → package 校验 → 素材清单校验 → 内容回读 →
  Slide Spec 冻结 → 讲稿 → 渲染 → 质量门禁 → v0.8 交付门禁，达到 `status: complete`。
- 样例刻意声明 diagram-only 来源，无需联网或外部生图即可复现；二进制产物由
  `.gitignore` 排除，源码与文档入库。

### v0.7.1：冻结计划与设计质量闭环

- Slide Spec 校验后生成 `slide-spec-lock.json` 并绑定 SHA-256；生产、readback 与 QA 阶段禁止
  静默修改计划。确需改计划时必须重新校验并显式 `revise --reason`，记录 parent spec hash。
- 新增结构化 render visual critic：逐页记录 hierarchy、focal point、composition、visual interest、
  whitespace、visual structure 与 AI-template feel；High-score 单项低于 6 或整套均分低于 7 阻断。
- 新增 deck-level rhythm gate：连续两页等权卡片/卡片网格/三等分/普通编号列表即 Major，
  任意页面结构连续三页或整套结构多样性不足也会触发返工。
- 新增 Evidence Closure 与 speaker timing：`evidence_refs`、Evidence Ledger、页面短引用和最终
  References 必须闭环；讲稿按中文约 240 字/分钟、英文约 130 词/分钟估时，整体超时 15% 阻断。
- v0.7.1 delivery 与 `workflow_guard complete` 绑定 actual-content、quality report、冻结 Slide Spec
  与 spec-lock hash，旧 simplified delivery 不能绕过新 quality gate。
- Typography grammar 增加 thesis contrast、oversized keyword、one-claim-three-supports、
  question→answer 等表达语法，明确禁止把并列 bullet 机械换成 01/02/03/04 或 N 个等宽矩形。

- 默认门禁由多份中间证据链收敛为三步：一次 Slide Spec/Brief 校验、最终 PPTX 的 package
  validation + 全页渲染/查看、一次 `simplified-v1` delivery check；普通任务不再生成
  content/asset/visual/QA manifest 独立报告。
- `workflow_guard complete` 在简化流程中只需当前 PPTX 与 delivery report；旧的 QA manifest
  evidence-chain 继续作为高风险编辑、排错和显式审计模式兼容保留。
- 将正式视觉选择收敛为三类、每类四种轻量参考，另设 `Other` 自定义入口；每种参考只定义
  风格气质、六角色 palette、四类背景和一个可选 SVG，不再驱动布局、形状、图片、图表或节奏。
- `Berry Cream` 与 `Sage Calm` 分别兼容迁移到 `Warm Terracotta` 与 `Forest Moss`；其他
  未知旧名称保留气质文字并使用 Modern Minimal 安全参考，同时输出兼容警告。
- 默认视觉生产模式保持 `adaptive-freeform`：AI 根据页面任务和素材自由决定比例、形状与
  坐标，36 版式、12 个 SVG 和视觉组件只提供建议与确定性兜底。
- Slide Spec 新增可选 `layout_lock`；未锁定的已知版式 ID 也仅为构图提示，显式锁定可恢复
  精确版式。composer 不再为自由构图自动添加角饰或缺图插画，完整 safety/来源/渲染 QA 保持硬门禁。
- Brief 与 Slide Spec 支持并校验 `visual_style_custom`；`Other` 四项结构不完整时不能进入规划。
- 视觉 gallery 调整为 12×6，SVG atlas 调整为 12 页；布局候选排序明确与视觉风格无关。

### 重构：Anthropic 对齐的视觉引擎与生产证据链

- 新增 suite-owned 受控 composer、八维可执行 Style DNA、非矩形形状、14 套原创 SVG
  角饰、形状安全内缩、角色化文字适配与阻断式 preflight，同时保留全部 36 个版式 ID。
- gallery 扩展为 14×8 风格页、36 版式页和 14 页 SVG atlas。
- 新增 content QA、显式逐页 visual inspection、asset manifest 校验与 hash 绑定；状态机最多
  允许一次整份 candidate 重建返工，仍有 blocker 时交付 incomplete。
- 通过独立 suite-owned 实现对齐已审计 Anthropic PPTX 工作流的 create/edit/clean/pack/
  validate/render 顺序；运行时不依赖缓存路径，也不分发上游文件。

### 修复：0.6.0 后续契约与验收加固

- Brief→Slide Spec 校验现在把应镜像字段缺失视为错误；support outputs 的 `--only`
  只能缩小已确认 deliverables，不能在生成阶段新增未确认产物。
- 版式选择器兼容 Slide Spec 原生 kind/visual enum，并同时执行素材、数量、禁用条件、
  标题字符和标题区几何容量检查；缺素材时沿显式 fallback 链选择可落地版式。
- 无 markitdown 时的 suite-owned OOXML fallback 提取完整 slide、notes 与 chart 文本，
  不再截断长页内容；create/edit/rebuild 的 source 与 production mode 组合执行一致性校验。
- review rendered 场景验证逐页预览覆盖且不修改源文件；gallery 改为真实语义版式样例，
  并把静态文字溢出风险作为失败条件。
- 三个 skill frontmatter 版本纳入 bump、release checker 与测试；CI 环境检查改为 strict。

## 0.6.0 — 2026-08-06

### 重构：视觉系统、工作流契约与运行时完备性

- 新增 36 套机器可读共享版式及 `pptx-layouts.js` 选择/解析接口；先做素材与容量过滤，
  再按风格 DNA、密度和连续页面轮廓稳定排序。
- 为 14 种风格增加可执行 `style_dna` 与 restrained/standard/expressive 强度；当前八个
  可执行视觉维度至少五项互异，统一 gallery 覆盖 14×8 风格页、36 版式页和 SVG atlas。
- 统一 outline/review/deck/env 边界、Brief/Slide Spec 交接校验、显式 production mode 与
  Production Summary 重确认回退；无完整逐页预览和视觉检查证据时只能 incomplete。
- env check 增加 outline/review 能力，OOXML 文本提取增加无 markitdown fallback，support
  outputs 改为只按确认 deliverables 生成，学校模板场景执行真实 OOXML 编辑链路。
- 删除误导性的 `.env.example` 与插件内 `outputs/.gitkeep`，收敛 review findings、视觉规则和
  脚本引用图，并修正 manifest 链接到 `claude-code` 分支。

### 精修：14 套自适应视觉风格与可执行约束

- 移除 14 个风格文件重复的通用尾注，将共享优先级、硬/软约束、字号、视觉结构和
  组件上限统一收敛到 visual style menu 与 PPTX production reference。
- 把逐页强制图片、引文、流程、旅程或卡片改为按页面叙事任务选择；补齐缺图、缺数据、
  长内容和组件不适配时的 fallback，允许有明确焦点的排版主导页。
- 修正 Coral Energy、Creative Student、Sage Calm 与 Midnight Business 的浅底可读色，
  删除未建模的 orange/mint 色，并新增 `H.paletteMode()` 以整套切换深色页面角色。
- 修复 editable chart 忽略 series `color` 后回落为默认红色的问题，改由 `chartColors`
  写入 token 驱动的系列颜色，并通过 package schema 与渲染复核。
- 加强视觉风格字段顺序、token 一致性、组件引用、WCAG 对比度与深色 palette 测试；新增
  `visual_system_smoke_gallery.py`，覆盖 14 种风格的六类页面和独立 36 版式 gallery。

## 0.5.1 — 2026-08-05

### 修复：PPT 生产功能缺陷与流程缺陷

- **修复 ≥10 页渲染/缩略图页序错位**：`render.py`/`thumbnail.py` 改用数值页号排序，
  不再把 `slide-10.png` 排在 `slide-2.png` 前（含隐藏页时预览内容错位、缩略图标签错配
  此前会静默通过门禁）。
- **统一 slide 计数口径**：`pptx_tool` 按 `presentation.xml sldIdLst` 注册页计数，
  与 render 的 `slide_metadata` 一致；validate 把未注册的孤儿 slide part 升级为 error。
- **visual QA 门禁死锁修复**：文档此前宣称"预览可选、0/0 不阻断 complete"，与交付
  check 默认 `require_preview` 冲突，按文档执行会卡死 `complete`。现文档与门禁对齐：
  未渲染时以 `--allow-missing-preview` 交付，状态为 `incomplete`，补渲染后经
  `incomplete → qa` 恢复；`--allow-missing-notes` 同步文档化。
- **视觉检查证据诚实化**：qa-manifest 仅在显式提供 `--no-repair-needed-reason` 且
  blocker 为 0 时才写 `visual_inspection.completed=true`；delivery 校验讲稿非空。
- **状态机轻量防线**：`transition --to complete` 重验 Production Summary hash（未确认
  或 summary 被改则拒绝）；`confirm --force` 支持需求变更时保留进度的重新确认。
- **production_mode 判定有据**：intake 增加 `source_deck`/`edit_intent` 收集；
  env check 移至模式确定之后；`pptx-production.md` 补充模板新建/PDF 来源的裁决规则。
- **env-check 修正**：`markitdown` 由 required 降为 recommended（仅 `inspect
  --text-output` 需要）；note 与 B 门禁新语义对齐；`check-pptx-env.md` 提示默认
  `--mode all` 对纯编辑任务过严。
- **其他**：quality report 文档改为"仅绑定 Slide Spec"（规划期产物，不绑定 PPTX）；
  `add_slide` 从布局新建时继承占位符；chart"有公式但无有效 workbook"升级为 error；
  macOS soffice 路径与可配置渲染超时；死代码清理（`_local`/SHA/计数收拢、
  `addNumberMarker` 参数、`EMU_PER_CM`、SKILL frontmatter 版本同步 0.5.0）。
- CI `release-checks` 补跑 `check_claude_pptx_env.py --mode all --json` 冒烟。

## 0.5.0 — 2026-08-04

### 全面修复：skill 衔接性与流程自洽

- 交接链：outline 转 PPTX 时必写 `outputs/<topic>-brief.yaml` 与
  `outputs/<topic>-slide-spec.yaml`；review 报告默认写 `outputs/<topic>-review.md`，
  编辑交接写 `outputs/<topic>-slide-spec.yaml`（`review_findings` 字段与
  `slide-spec.schema.json` 对齐为 severity/target/problem/fix）。
- 流程自洽：`transition --to complete` 不再要求 `--package-report`（已废弃）；
  新增 `incomplete → qa` 恢复边（补齐缺失门禁后可重入 QA，无需 reset）；
  `production_mode` 在环境检查前确定；环境检查 `common_required` 补
  jsonschema/PyYAML；移除 `pptx_delivery_check.py` 中 static-risk 死代码与
  "style report"/"visual plan"/"style-adherence" 残留文档；修正 10 处相对路径。

### 门禁删减

- 移除 PreToolUse hook 与 `hooks/hooks.json`：`workflow_guard.py` 保留为显式
  状态机命令（init/confirm/transition），不再对 Bash 命令自动拦截；状态由
  SKILL 文本自律维护。
- 删除 `shared/types.py`、`shared/visual_plan.py`、`shared/style_adherence.py` 与
  `scripts/compile_visual_plan.py`、`scripts/style_adherence_check.py`，同步移除
  对应文档与测试。
- 清理发布/CI 冗余门禁：版本一致性收敛到 `check_marketplace_release.py`；
  Release checks 移出 OS 矩阵单跑一次；smoke 冒烟仅 Windows 跑（Ubuntu 由
  render-matrix 覆盖）；移除 `blocked`/`incomplete` 字面量与 `keywords≥5` 阈值；
  `FORBIDDEN_PATH_PARTS` 不再一刀切禁止 `agents/`；删除未生效的 mypy 配置。

### PPTX 内嵌运行时适配

- 移除直接引入的上游 `pptx_skill` 目录和 guide，改为本仓库维护的
  `shared/pptx_runtime/` 与稳定入口 `scripts/pptx_tool.py`；不再依赖
  `document-skills` 插件或本地缓存路径。
- 将生产流程拆分为 `create`、`edit_ooxml`、`rebuild_from_source` 三种模式；
  已有 deck 默认执行保留原件的 OOXML 修改，不再生成无关的 `deck.js` 指令。
- 新增安全解包、显式 pack 输出、非覆盖式增页/删页/重排、孤立部件清理、
  包级校验、LibreOffice/Poppler 渲染和最终 QA manifest 哈希绑定。
- 复制已有页面时选择性深复制 notes/comments、chart、SmartArt 数据、embedded package
  和 OLE 依赖，并重定向 notes 的反向 slide 关系；补充 shared master/theme、未声明
  relationship ID、part root、notes 和重复 chart axis 检查。
- 缩略图按实际 slide XML 顺序标注，支持隐藏页占位与多 contact sheet 分页，避免
  LibreOffice 跳过隐藏页后发生标签错位。
- clean 增加 package roots、slide 注册、悬空关系和 symlink 拒绝规则，并通过临时
  trash + rollback 实现事务式孤立部件清理，避免中途失败留下半清理 package。
- 引入 MIT 许可的 Open XML SDK 3.5.1 adapter，执行 markup/schema validation，并叠加
  suite-owned OPC 语义检查；不再表述为内置完整 PML/DML/OPC XSD 文件集。
- PptxGenJS 入口改为显式 `--output`、临时生成、非覆盖归一化和原子落盘，拒绝覆盖
  已存在输出或输入文件；发布检查同时拒绝必需文件“仅存在但未被 Git 跟踪”。
- QA manifest 现在必须读取并重新验证原始 Slide Spec；严格交付同时验证完整 Open XML
  schema profile，并将 quality/style report 分别绑定到 Spec/PPTX SHA-256，阻断伪造或过期证据。
- 图片组件改为等比包含并写入 alt text；图表数据契约要求完整 series，组件使用主题色和
  至少 18pt 的轴、图例与数据标签。场景矩阵联合覆盖全部 11 种可编辑布局家族。
- 图表校验增加 plot axis cardinality、series idx/order、crossAx reciprocity、extLst、
  cache ptCount/index/number、formula range、series cardinality、externalData relationship、
  embedded workbook 可读性和公式工作表存在性检查；ChartEx schema 由 Open XML SDK 覆盖。
- classic chart 校验允许合法稀疏 cache，将 named/dynamic formula 与基数差异降为
  info/warning，并增加真实 PptxGenJS `addChart` 正向样例。
- inspect/thumbnail 输出 versioned 完整 slide metadata；Linux sandbox 阻断 AF_UNIX 时
  可按需编译 suite-owned `LD_PRELOAD` shim；CI 强制模拟 EPERM 并执行 LibreOffice 渲染矩阵。
- render 在 LibreOffice 跳过隐藏页时按原页序生成占位预览；master/theme 共享仅作为
  info 风险报告，不再因 XML 子元素顺序抑制或升级风险。
- .NET SDK 下载改为显式 `-InstallDotNetSdk` opt-in，并固定 8.0.423；CI 中 pip、npm、
  NuGet 漏洞审计改为阻断式，Open XML 错误数和 ZIP 解压资源均设置上限。
- 补强 `intake_pending` 命令门禁、严格交付的 package report、发布包旧 runtime
  禁止项、跨目录 CLI 测试、真实 PPTX 编辑测试及路径穿越测试。
- 固定 ESLint/Prettier 开发依赖，避免 CI 临时安装最新版导致配置不兼容。
- 修复共享标题安全区把标题框强制扩进内容区的问题，新增边界内 `footerArea` 和硬性
  `assertTextFits`。
- 静态重叠检查忽略卡片包含标签等预期组合，同时继续阻断部分相交；`complete` 强制
  绑定通过的 package/delivery report。
- 生成 helper 增加 `gridLayout`、受控通用文本框和页脚原语，把坐标、字号和 fit 约束
  前移到首次生成；QA/delivery 对未修改 PPTX 直接复用 package report，并取消首个
  candidate 无问题时的强制修复循环。
- 新增 11 个可编辑视觉布局组件和原生可编辑 chart-with-takeaway，避免把流程、对比、
  数据和架构内容退化为纯文字卡片。
- generated-package normalization 会移除 PptxGenJS 4.0.1 在二维 chart 中写入但未声明的
  series-axis reference，确保原生可编辑图表通过 Open XML SDK schema validation。
- QA manifest 绑定 Slide Spec validation report、全部 preview 与 package report 的
  hash；移除可自报的 scenario contract 参数（结果由 Slide Spec 重校验推导），并把
  manifest 调整到 strict delivery 之前。producing 阶段的 package report 在 PPTX
  未变化时直接复用。

## 0.4.2 — 2026-07-22

### 安全修复

- **路径穿越防护**（P0-3）：`runtime_paths.py` 的 `project_root()` 现在拒绝
  包含 `..` 的环境变量值，防止恶意 `CLAUDE_PROJECT_DIR` 导致意外路径解析。
- **`relative_luminance` 输入校验**（P0-2）：十六进制颜色字符串现在先校验长度
  和字符集，非法值返回默认亮度 0.0 而非崩溃。
- **`or 40` 回退 bug**（P0-1）：`presentation_quality.py` 中
  `meta.get("max_words_per_slide") or 40` 已修复：显式设为 0 不再被错误回退。
- **`effective_ppi` 除零保护**（P1-8）：跳过小于 0.5 英寸的装饰性形状的 PPI 检查。

### 门禁硬化

- **delivery `--strict` 测试覆盖**（P0-4）：新增 6 个失败路径测试覆盖静态扫描
  错误、blocker 未清、QA manifest 缺失、PPTX 不可读、风格报告失败等场景。
- **状态机 `qa→complete` 门禁测试**（P0-5）：新增 hash 不匹配、blocker 未清、
  无视觉检查记录等 4 个失败路径测试。

### 工程基础设施

- **Python 代码质量**（P1-1）：新增 `pyproject.toml`，配置 Ruff（E, F, W, I,
  N, UP, B, SIM, ARG, RET 规则集）+ mypy 渐进式引入。
- **JavaScript 代码质量**（P1-1）：新增 `.eslintrc.json`（Node.js 标准规则）
  和 `.prettierrc`（100 字符宽、单引号）。
- **跨编辑器格式**（P2-3）：新增 `.editorconfig`，统一缩进 4 空格、UTF-8、
  LF 行尾。
- **依赖管理**（P1-7）：`package-lock.json` 已纳入版本追踪；Dependabot 配置
  覆盖 pip、npm 和 GitHub Actions。
- **CI 增强**：新增 `ruff check`、`eslint`、`prettier --check` 步骤；新增
  `security-scan` job 运行 `pip-audit` + `npm audit`。

### 类型安全

- **TypedDict 类型定义**（P1-2）：新增 `shared/types.py`，为 Presentation Brief、
  Slide Spec、Design Tokens、QA Manifest 和 Delivery Report 提供结构化
  TypedDict 类型，逐步替代裸 `dict[str, Any]`。

### 测试优化

- **测试工具提取**（P1-5）：新增 `tests/test_helpers.py`，统一 `load_module()`
  函数。7 个测试文件（`test_workflow_guard`、`test_pptx_delivery_check`、
  `test_bump_version`、`test_manage_versions`、`test_revision_manifest`、
  `test_support_outputs`、`test_version_consistency`）全部迁移使用共享加载器。
- **集成测试**（P2-6）：新增 `tests/test_end_to_end.py`，包含 5 个冒烟测试
  验证关键脚本 CLI 入口点正常启动。

### 代码质量修复

- **`pptx-helpers.js` 修复**（P1-3）：
  - 惰性导入改为顶层 `require("pptxgenjs")` — 原注释称"避免循环依赖"，
    但顶层 require 不会导致循环依赖。
  - `estimateTextFit` 增加零尺寸盒子防护，`boxW ≤ 0 || boxH ≤ 0` 时
    返回 `{lines: 0, fillRatio: 0, overflow: false}`。
  - `applyTokens` 接受可选 `opts.slideW / opts.slideH` 参数，不再硬编码
    16:9 尺寸。
- **`_import_helpers.py` 重构**（P1-6）：`load_inspect_pptx` 的 `sys.path`
  操作封装为 `_plugin_root_on_path()` context manager，`remove()` 失败时
  安全 pass。
- **场景角色验证集成**（P1-4）：`presentation_quality.analyze_spec()` 现调用
  `slide_spec_validation._validate_scenario_roles()`，在质量分析中产出
  场景必需故事角色的缺失 findings。
- **`shape_bounds` 调用验证**：确认所有调用的 None 检查已正确实现。

### 社区与文档

- **社区标准**（P2-1）：新增 `CONTRIBUTING.md`、`SECURITY.md`、Issue 模板
  （`bug_report.md`）、PR 模板。
- **`.env.example`**（P2-4）：新增环境变量文档清单。
- **`README.md` / `README-zh.md`**：在开发与发布章节新增工程工具链描述。
- **`AGENTS.md`**：更新仓库布局、编辑规则和验证流程，加入 lint 检查步骤。
- **`CLAUDE.md`**：新增项目级 CLAUDE.md，记录结构、命令和约定。
- **`CHANGELOG.md`**：本版本日志。

### 测试覆盖

- 测试总数：121 → **136**（+15 个新测试）
- 全量测试通过：✅

| 字段 | 内容 |
| ---- | ---- |
| 版本 | `0.4.1` |
| 时间范围 | 2026-07-21 |
| Git 范围 | `claude-code` |
| 发布分支 | `claude-code` |
| 主要贡献者 | YFan945 |

### 版本概述

本版本为审计后的修复与质量门禁加固版本，统一 schema、references、示例与文档，修复生产 hook、subprocess 编码、单位换算、发布检查等工程缺陷，并补齐 CI 与安装脚本中的遗漏。

### 修复与改进

- 严格交付门禁现在会阻断静态 blocker、损坏/空白预览以及缺少或失效的 QA manifest。
- 新增与 PPTX、渲染预览 hash 和全页检查绑定的 QA manifest，并要求其通过后才能转换到 `complete`。
- 修复超长文本预警的 bridge 字段错误，并改用未舍入的溢出比率进行阈值判断。
- `unblock` 现在回到 `intake_pending`，生产 hook 同时验证 Production Summary 文件与 hash。
- 14 套标准视觉风格现有机器可读 design tokens；production brief 会展开 palette、几何、字体与线条约束，并可生成 style-adherence report。
- Slide Spec 现按 scenario 验证必需 story role，静态检查新增可见对象的大面积重叠风险。
- 新增低分辨率/拉伸图片 blocker、connector 线宽 token 检查，以及 LibreOffice/Poppler 驱动的临时场景渲染矩阵；CI 在 Ubuntu 上强制渲染九种代表性场景。
- 静态 QA 继续增加标题区/页脚区、最小 gutter、前景背景对比度、connector 路由，以及图表标题和标签字号门禁。
- 新增显式文本框 padding、叠放对象对齐误差和图片 containment 的结构化检查。
- delivery check 现可写出包含 static/render/style 证据与最终状态的 `delivery-report.json`。
- QA manifest 现必须明确记录 `scenario_contract_passed: true`，交付报告同步输出该结论。
- 文本溢出估算现在考虑段落、显式换行、bullet 缩进与文本框内边距，降低复杂排版漏报。
- `visual-led` Slide Spec 现强制提供内容页视觉结构；timeline、comparison、process 和 chart 各自验证可生成的结构化 details。
- 静态报告新增 deck 级布局模式统计，配合已有颜色和字体统计支持风格重复审查。


- 修复 CI `runtime` job 与 `render-matrix` job 未设置 `PYTHONPATH` 导致单测/渲染失败的问题。
- 统一引用风格枚举：`presentation-intake.md` 增加 `GB-T-7714`，schema 增加 `IEEE`/`MLA`；`evidence-and-citations.md` 同步定义。
- 修复 `high-score-research-slide-spec.yaml` 因缺 `problem`/`background` story role 导致校验失败的问题，并在 `slide-spec.md` 中补全 scenario role 规则。
- 修复 `student-presentation-ppt/SKILL.md` 中 `pptx_delivery_check.py` 命令缺少必需 `--pptx` 参数的问题。
- 消除 `visual-style-menu.md` 中“unsure 用户展示全部样式”与“仅在明确要求时展示全部样式”的矛盾。
- 修正 `presentation-intake.md` 中 Production Summary 项数（18 → 20）与风格方向归因错误。
- 补全 audience_type 的 `teacher+classmates`、deliverables 的 `full-script`/`contact-sheet`，并理清 image_source 与 intake 选项的映射。
- 加固 `workflow_guard.py`：支持 `py`/`python3.12`/`node.exe`/`uv run` 等常见解释器形式；hook 命令改为 `python3 || python` 回退；stdin 使用 UTF-8 读取并捕获 `UnicodeDecodeError`。
- 修复 `run_with_pptxgenjs.js` 在 Windows 上因 Node 20+ 禁止直接 spawn `.cmd` 导致全局回退失效的问题。
- 修复 `pptx-helpers.js` 中 `paraSpaceAfter` 单位错误（英寸当磅），统一 exit code 为 `1` 表示 strict/运行时失败、`2` 表示输入解析错误。
- 修复 `create_revision_manifest.py` 对非法 YAML 崩溃、`build_support_outputs.py` 坏输入 traceback、`analyze_presentation_spec.py` 缺 `yaml` 时 `NameError` 等问题。
- 统一 `subprocess.run` 的 `encoding="utf-8", errors="replace"`，避免中文 Windows 环境崩溃或乱码。
- 在 `check_plugin_release.py` 中增加 `hooks.json` 格式与命令指向校验；`bump_version.py` 增加 semver 校验与 Windows `npm` 调用兼容性。
- 修复 `manage_versions.py` 同名文件覆盖问题，使用相对路径保留目录结构。
- 同步 `README-zh.md` 的输出清单与质量门禁细节；为 `CHANGELOG.md` 0.4.0 补充元数据表；`AGENTS.md` 补录 `PPT-GENERATION-QUALITY-AUDIT.md`。
- 安装脚本改用 HTTPS clone；新增 `.gitattributes` 规范化行尾。
- 测试：`test_workflow_guard.py` 不再直接读真实 stdin；新增门禁用例；`test_bump_version.py` 验证 dry-run 不修改文件与非法 semver 拒绝。

## 0.4.0 — 2026-06-21
| 字段 | 内容 |
| ---- | ---- |
| 版本 | `0.4.0` |
| 时间范围 | 2026-06-21 |
| Git 范围 | `claude-code` |
| 发布分支 | `claude-code` |
| 主要贡献者 | YFan945 |

### 版本概述

本版本将插件从“生成与审查工作流”扩展为可控的学生演示生产系统，并强化
Claude Code 安装版本一致性。新增 Presentation Brief、Slide Spec v2、
Evidence Ledger、分层内容、结构与质量分析、页面锁定、revision manifest、
训练卡、提词版及扩展交付检查。

### 重大功能

- 自动分类课程汇报、答辩、竞赛、社团展示和研究展示，并按受众深度选择表达。
- 支持问题解决、研究、时间线、对比、案例和产品六种叙事结构。
- 固定目录→逐页主张→PPT 文案→演讲版→Slide Spec 的分层生成流程。
- 新增每页字数、图文比、讲稿、金句、引用、导出和版本控制字段。
- 新增 Evidence Ledger、来源可信度和证据引用完整性检查。
- 新增重复页、逻辑倒退、开头/结尾、密度、AI 套话和证据缺口分析。
- 新增局部修改、锁定页面保护、版本差异和 revision manifest。
- 新增逐页五维评分、训练卡、老师/评委追问和 HTML 提词版。
- 扩展静态 PPTX 几何风险检查与可选 PDF/提词版/质量报告交付门禁。

### Claude Code 与发布

- 新增源码与 `claude plugin list/details` 版本一致性检查。
- 新增插件级 `PreToolUse` hook 和持久化工作流状态，确认前确定性阻断生产脚本。
- 安装脚本在完成 update 后强制验证实际加载版本。
- 修复 README 中合法旧安装 ID 迁移说明被测试误判的问题。
- Marketplace、manifest、package 和 lockfile 同步升级到 `0.4.0`。

## 0.3.0 — 2026-06-20

| 字段 | 内容 |
| ---- | ---- |
| 版本 | `0.3.0` |
| 时间范围 | 2026-06-20 |
| Git 范围 | `claude-v0.2.0` → `claude-code` |
| 发布分支 | `claude-code` |
| 主要贡献者 | YFan945 |

### 版本概述

本版本将 PPTX 工作流升级为确定性的“先澄清、再规划、后生成、最后验证”。
完整需求表和 Production Summary 成为生成与编辑的硬门槛，同时压缩 skill
入口、明确三个 skill 的关系，并将确认后的需求完整传入 Slide Spec 与 Claude
PPTX brief。仓库级和插件级文档也完成重写，形成可安装、可维护、可验证、
可发布的闭环。

### 重大功能

- **完整需求表**：新增 `references/presentation-intake.md`，统一主题、课程、
  汇报类型、受众、语言、时长、页数、成员、评分标准、资料来源、模板、图片
  策略、视觉风格和交付物的确认规则。
- **强制确认门禁**：信息不完整时只展示已确认项和缺失项；每个缺失项附推荐值
  与影响。用户说“你决定”只会采用推荐值，仍需确认完整 Production Summary。
- **确定性状态机**：统一
  `intake_pending → intake_confirmed → planned → producing → qa → complete`，
  并明确 `incomplete`、`blocked` 的进入条件。
- **结构化 intake → Slide Spec**：新增 `topic`、`audience`、
  `source_material`、`visual_style` 和 `deliverables` 字段，并由 bridge 写入
  Claude PPTX 生产 brief。
- **review → edit 交接**：继续以 `source_deck`、`edit_intent`、
  `review_findings`、`preserve` 和 `change_summary_required` 传递已有 deck
  改进要求，且始终生成独立改进版。

### 重要调整

- **Skill 职责重构**：大纲、PPTX 生产、审查三个 skill 分别稳定在 38、60、
  50 行，只保留触发、职责、状态、核心步骤和输出契约。
- **规则归属统一**：澄清与状态归 `presentation-intake.md`，路由和质量标准归
  `shared-standards.md`，结构化交接归 Slide Spec，避免重复规则漂移。
- **生产 reference 精简**：移除与 intake 重复的默认值和提问逻辑，禁止绕过
  intake 直接进入生成。
- **完整文档体系**：重写根级和插件级中英文 README，扩充 `AGENTS.md`，
  增加架构、安装、工作流、验证、版本同步和发布约束。
- **受保护分支发布**：release check 在 PR 中校验目标分支为 `claude-code`，
  直接发布时仍校验当前分支；发布流程统一通过 required checks 和 PR。
- **版本同步**：Marketplace、插件 manifest、`package.json` 和 lockfile
  统一升级到 `0.3.0`。

### 验证记录

- `python -m unittest discover -s plugins/student-presentation-suite/tests`
  — 34 项测试通过。
- `python plugins/student-presentation-suite/scripts/smoke_pptx.py` — 通过。
- 插件 release check 与 marketplace release check — 通过。
- Claude PPTX environment strict check — 通过。
- 插件包与 marketplace 两级 `claude plugin validate --strict` — 通过。
- `git diff --check` — 通过。

### 兼容性与边界

- 仍只支持明确的学生/大学/课程/答辩场景。
- pptx skill 已内嵌，不再依赖 `document-skills@anthropic-agent-skills` 外部插件。
- 不包含 `.codex-plugin`、`agents/openai.yaml`、`artifact-tool` 或 Codex
  runtime 依赖。
- Claude Code 改动只发布到 `claude-code`，不发布到 `main`。

## 0.2.0 — 2026-06-19

| 字段 | 内容 |
| ---- | ---- |
| 版本 | `0.2.0` |
| 时间范围 | 2026-06-13 ~ 2026-06-19 |
| Git 范围 | `2f96064` → `5f9d5d7` |
| Tag | `claude-v0.2.0` |
| 主要贡献者 | YFan945 |

### 版本概述

本版本完成 Claude Code 专用分支、marketplace、安装迁移脚本和运行时闭环，
并系统强化 skill 路由、已有 deck 改进、视觉风格控制、Slide Spec、CI 与
发布检查。

### 重大功能

- 建立 `claude-code` 专用 marketplace，统一安装 ID 为
  `student-presentation-suite@claude-personal`。
- 新增安装与迁移脚本，自动处理旧 `personal` 注册、依赖安装、marketplace
  注册和插件启用。
- 打通已有 deck 的 review → edit 结构化交接，要求独立改进版和 change
  summary，不覆盖源文件。
- 将视觉风格拆分为菜单与 14 个独立、按需加载的生成控制规范。
- 新增跨 cwd 的 runtime resolver、`pptxgenjs` wrapper、smoke PPTX 与严格
  环境检查。

### Bug 修复

- 修复 CI 测试导入路径和调用目录依赖。
- 修复根目录、插件目录和 Claude cache 之间的资源定位问题。
- 修复 marketplace 名称、manifest 元数据和插件安装 ID 不一致。
- 修复 review 结论无法稳定进入 PPTX 生成 brief 的问题。
- 修复只凭静态 XML 风险就宣称渲染溢出的不可靠判断。

### 重要调整

- 将 Codex manifests、OpenAI agent 文件和 Codex runtime 依赖从 Claude
  package 中移除。
- 用户交付物统一写入当前 Claude 项目的 `outputs/`。
- 收紧学生场景与 PPT 意图门槛，减少对通用 presentation 请求的误触发。
- 强化中英文课堂可读性、anti-AI wording、小组分工和讲稿规范。
- CI 在 Windows/Linux 上运行 schema、测试、smoke 和 release checks，并
  单独执行 Claude strict validation。

### 验证记录

- 单元测试、schema validation、PPTX smoke、release checks 和 Claude strict
  validation 均纳入发布流程。
- Tag：`claude-v0.2.0`。

## 0.1.0 — 2026-06-07

| 字段 | 内容 |
| ---- | ---- |
| 版本 | `0.1.0` |
| 时间范围 | 2026-06-07 |
| Git 范围 | `7a310a5` → `a55b94b` |
| 主要贡献者 | YFan945 |

### 版本概述

首次公开发布学生演示插件与 marketplace 基础结构，提供学生 PPT 大纲、
PPTX 生成和审查三个核心入口，并修正 GitHub clone URL。

### 主要能力

- 初始 student presentation planning、PPTX production 和 review skills。
- 共享课堂可读性、内容密度、语言与 anti-AI writing 规则。
- 基础 Slide Spec、图片策略、示例和发布文档。
- GitHub marketplace clone 与安装入口。
