# Changelog

本文件记录 `YFan945/student-ppt-create` 的 `main` 发布线及 Claude Code 插件版本，按时间倒序排列。

## 0.14.4 — 2026-09-18

来源：owner 提出"我想要一项 ppt 任务能在 20 分钟内解决"。实测把这个目标拆成了可算的数：
**墙钟 = 回合数 × 往返延迟，而门本身几乎不花时间**——全会话 5 道 QA 门、18 次 build、
12 次 plan、4 次 render、17 次 gates orchestrator 合计 **150 秒**，只占 147 分钟 pipeline 的
**1.7%**；其余 100% 是 **519 个模型回合**，而每个回合只带 **0.95 个工具调用**。
目标页数 10~13 页、时间 20~30 分钟，全部质量门保留。

### 并行 builder 分片（不碰任何门的墙钟杠杆）

- `next --json` 在 `initial`（实现剩余页）与 `repair`（blocker 页）方向给出 `builder_shards`：
  按页号轮转拆成最多 `max_parallel_builders`（默认 3）个互斥且页数均衡的分片，并明确要求
  **在同一条消息里 spawn 全部 shard**。少于 `parallel_builder_min_pages`（默认 4）页不拆。
- 配套：每个 shard 只写自己的 `speaker-notes-shard-<N>.md`，`build` 按页序拼成
  `speaker-notes.md`（并行时唯一不会互相覆盖的写法）；**没有页号的 deck 级 blocker 不分片**
  ——那说明整 deck 在范围内，用一个 builder 读报告。
- 分片只改变"谁在何时写哪个文件"，判定链（critic / QA / delivery）一行没动。

### `session_cost.py` 的计量修正（必要前提）

- **同一 `message.id` 只算一个回合，取 ctx 最大的那一行。** 原先的规则是"2 秒内、usage 完全
  相同的连续行合并"，这漏掉了流式分片里 usage **不同**的行：一个子代理被读成 **480 个请求**，
  实际只发了 **261** 个，派生出的每个 per-turn 数字都偏 ~1.8 倍。修好后与手工核对完全一致
  （261 回合 / 99.1M，峰值 ctx 699,497）。没有 `message.id` 的旧 transcript 走原有规则。
- 新增回合经济指标：`turns`、`tool_calls_per_turn`、`turn_seconds`(median/p90/mean)、
  `turns_under_20min`；markdown 报告新增 "Turn economy" 一节，并在回合数 ≥40 且每回合调用
  <1.6 时给出一条明确的告警（指向 CD-11）。

### 契约与文档

- `pipeline-contract.json`：新增 `max_parallel_builders` / `parallel_builder_min_pages` /
  `parallel_builder_shards_allowed`，build 与 repair 阶段契约写明分片用法。
- `cost-discipline.md` 新增 **CD-11**：墙钟 = 回合数 × 往返延迟；把 150 秒 vs 519 回合的
  实测写进去，明确"合并调用"与"并行分片"是仅有的两条不碰门的时间杠杆。
- `SKILL.md` 第 9/14 步、`spawn-templates.md`、`agents/presentation-builder.md` 同步
  分片约束（只做自己的 slide ids、写自己的 notes 碎片、合并工具调用）。

## 0.14.3 — 2026-09-18

来源：owner 对 0.14.2 live 会话的追问——"qa 为什么每次都需要那么多轮；builder 为什么那么久；
最后都没修复到可达标准的 complete"。复盘同时修正了成本计量口径：**真值 130.0M token，其中
一个 builder 实例占 98.6M（75.8%）**，而不是先前报告里的 48.0M / 20.1M。
分析报告：`outputs/cost-time-diagnosis-0.14.2-2026-09-18.md`；脚本：`outputs/_analysis/`。

### `complete` 可达性：`missing_final_reference` 改为按来源匹配（16 → 0）

- **计量口径修正**：同一条 assistant message 在 transcript 里会被写成多行（流式分片），
  首行只报增量上下文，**终稿行才报完整 prompt**。按首行去重会少算 2.7 倍（子代理 4.9 倍），
  把全部行相加又会多算。本批数字按"取该 `message.id` 下 ctx 最大的一行"重算；CD-8 已固化口径。
- **门的意图与实现错位**：`evidence_ledger.title` 按设计是**论断/数值/引文**
  （`research_pack_to_evidence.py` 从 `finding.claim` / `data_point.meaning` / quote 文本构造），
  而参考区渲染的是**来源**标题。拿论断标题去匹配书目，对 42 条 used evidence 里的 16 条
  **数学上不可能成立**——该次会话的 S13 已逐字列出全部 25 条来源标题、按机构分三组，
  独立 critic 判 0 blocker、均分 7.1，但 QA 恒定报 16 条，`complete` 结构性不可达。
- 修法：spec 增加 `source_ledger`（由 `research_pack_to_evidence.py` 从 pack 写入），
  证据闭包校验改为**按 `source_ids` 解析到来源记录**再匹配（`source_markers` /
  `source_identifiable`）。实测：同一份 deck、同一份 spec，仅补 `source_ledger`，
  blocker **16 → 0**；把某个来源从参考区拿掉仍会失败，不会变成放行一切的门。
- 新增 `unresolved_source_ref`：被引用但不在 `source_ledger` 里的来源 id 不再被静默丢弃
  （那正是"deck 引用了一个不存在来源"的形态）。
- 没有 `source_ledger` 的旧 spec 保持原有条目级校验，不会因为升级而静默全绿。

### 校准由独立 critic 评审，不由主会话自己看图

- 校准检查原先被设计成"主会话并行 Read 这 2–3 张 PNG"。主会话是 spec 与 Art Direction 的
  作者，**"我给所有页面都套了同一个面板"恰恰是它看不见的那类问题**：2026-09-18 live 中它
  接受了校准稿，独立 critic 随后判定"13 页套同一个带边框通栏面板"要求全 deck 重做，
  轮 1 花掉 **76.4M token（该次会话 58.8%）**，而 3 页规模的评审只需 1.4M。
- `next --json` 在 planned 状态下、校准渲染就绪后改为给出 `visual-critic` 的 spawn 参数与
  `calibration/calibration-visual-review.json` 的写入路径；评审带 critical/major 时继续
  指向 builder `mode=calibration`。
- **机械拒绝**：有校准证据但评审缺失/过期/带 blocker 时，`build` 拒绝正式构建
  （`calibration_review()`）。文档约束在本项目已被跳过一次，所以这次落在运行时。
- `spawn-templates.md` 增加校准专用 critic 模板：只判"铺到全 deck 会重复出现"的形态
  （不同页型是否套同一结构、Art Direction 一致性、页型是否还分得开），细则打磨留给最终 critic。

### 一个 builder 实例只服务一轮（最大的单项成本）

- 实测：一个实例扛 3 轮 repair，常驻上下文从 8.7K 涨到 **699K**，261 个请求里 **212 个在
  ≥200K 下发出（占该实例成本 96.1%）**；最后一轮只有 3 个请求却花 2.1M token。
- **实测反事实（修正早期估算）**：只做实例重置、轮 1 不变，是 **98.7M → 80.9M（省 17.8M）**——
  轮 1 在单实例内部自己就从 8.7K 长到 606K，重置修不了它；省下的主要是轮 2（17.4M → 3.5M）
  与轮 3（4.8M → 0.9M）。轮 1 的 38 次自渲染 + 49 次图片读 + 111 次内联脚本另有约 **16M** 的
  "留存成本"（内容加进上下文后被后续每个请求重付），去掉后约 67M。
  **最大的杠杆是"校准阶段就挡掉全 deck 返工"，而不是重置实例。**
- `builder_guard.py` 记录每个 builder 实例的页面写入窗口（`.guard/builder-*.json`），
  `ppt_pipeline.py` 的 `builder_instance_reuse()` 与 manifest 的 repair 轮次交叉比对，
  `next --json` 检出跨轮实例时报出实例 id 与覆盖轮次。
- SKILL 第 14 步、`pipeline-contract.json`、`cost-discipline.md` 新增 **CD-10**：
  每轮 spawn 新实例，上一轮结论以报告路径 + blocker 清单传递。

### 渲染与内联脚本的归属收口（0.14.1 的收口被绕过的部分）

- **builder 不再自己渲染**：`calibration_preview.py` 与所有 render 属于主会话。实测该实例
  自行调用 `calibration_preview.py` **38 次**，每轮重渲染又把新 PNG 读回来，是它上下文
  涨到 699K 的主要来源之一。hook 现在拒绝这些命令（含 `soffice` / `libreoffice`）。
- **内联脚本按行为收口，而不是按写法**：`node -e` 被拦后 builder 改用
  `python - <<'PY'` **111 次**，而专门为它做的 `page_brief.py` 只用了 5 次。现在按
  "是否在读 work-dir 的 JSON/YAML、是否在用正则改 `pages/*.js`"判定，覆盖
  `-c` / `-e` / heredoc / stdin 各种等价形态；读图测像素的脚本仍然放行。
- builder 在 build 之后又改页时，`build` 允许**一次**补差量重建（`build.carryover_builds`）：
  2026-09-18 live 有一整轮 repair 唯一目的是"把 p6/p8 排版微调带入产物"。

### 门的确定性部分提前到 build；门误报不再烧预算

- `pre_qa_stages()` 增加 `quality` 门的确定性一半（evidence closure、notes timing、
  spec lock）：`pptx_quality_gate_v071.py` 的 `--visual-report` 改为可选，无该参数时只跑
  这三组、且不写视觉分数历史。2026-09-18 live：build #1 报 0 blocker，render + 一整轮
  critic 付完之后 QA 回 48 条，其中 16 条只靠 PPTX + spec 就能算出来。
- `gate-history.json` 的每轮记录增加逐 code blocker 数。`repair_convergence` 据此新增
  **`suspect_gate_defect`**：某组 blocker 连续两轮逐字相同、其余在动时，直接指出
  "这是门侧候选，不是页面工作"，并给出"核对一次 → 命名页面级修法或记为已知门限"的做法。
- 该组占当前 blocker ≥80% 时 `repair --extend` 被拒绝：更多轮次不能移动一个没有任何轮次
  移动过的东西。2026-09-18 live 为此烧掉 5.4M 取证 + 一次 4.08 小时的用户询问。

## 0.14.2 — 2026-09-18

来源：owner 对 0.14.1 预算口径的追问——"很多问题是小问题，或者本来在生成时就该做好"。
复盘确认 0.13.4 的 6 轮 repair 没有一轮是"正常的小问题"（全部由已修的结构性缺陷引起），
但门序仍有一个昂贵的洞：确定性门（`rendered` / `actual-content` 只读 PPTX、不依赖
critic）排在最贵的 critic 之后。本批把确定性拦截提前到 build，并收紧提额硬顶。

### 确定性预检（pre-QA）：生成时就该做对的事，不再花 render + critic + 一轮 QA

- `ppt_pipeline.py build` 打包完成后立即本地运行 `rendered` + `actual-content`
  两道确定性门（只读 PPTX 本身，零 critic 成本）。2026-09-17 live：一个缺失的
  planned number 直到 QA 阶段才暴露——此前 render 和一整轮隔离 critic 已经为一个
  注定返工的 deck 付完费。
- 不绿时：`render` 直接拒绝；`next --json` 指向免 repair 轮修法——spawn builder
  `mode=repair` 读 `pre-qa-actual-content.json` / `pre-qa-rendered.json` 报告改页后
  重建（**不消耗 repair 预算**，critic 从不评审注定返工的 deck）。连续失败上限为
  契约新增的 `max_pre_qa_rebuilds`（默认 2），到顶即转正式 render/critic 流程；
  重建仍要求 generator 指纹变化，防无改动死循环。预检报告写独立的 `pre-qa-*.json`，
  与权威 QA 运行（后续重新执行同样检查）明确区分。
- `status` 与 stage summary 同步展示预检状态；`repair` 契约明确"预检修法不占预算"。

### 预算口径

- `pipeline-contract.json`：`max_repairs_hard_cap` 12 → 6。基础预算 `max_repairs` 3
  轮不变（0.13.4 的 6 轮全部由已修缺陷引起，不存在需要 4 轮以上的已知场景）；
  真需要时 `repair --extend N --extend-reason <blocker 差异>` 提额通道仍在。

## 0.14.1 — 2026-09-18

来源：2026-09-18 对 0.13.4 live 会话 transcript 的成本诊断
（`outputs/token-rework-analysis-2026-09-18.md`）。子代理侧 286M 输入 token 里 **86% 花在
builder，其中 6 轮 repair 占 199M**——是 initial 全量实现（29.1M）的 6.8 倍。根因不是"搜索次数"
（同一会话 WebSearch 只有 16 次），而是**返工循环**：门串行让每轮只能看到一层问题；builder 缺少
投影式读取工具，一轮内自建 19~46 条内联脚本挖 JSON；视觉改动没有回归对比，第 5 轮改坏、第 6 轮
花 40M token 只用来回退。本批四项修复都落在"运行时能挡住"的位置（批次三）。

### QA：内容门全部跑完再汇总（解"6 轮 repair = 6 层门"）

- `ppt_pipeline.py qa`：产物可用性门（`package` / `rendered`）失败即停；内容质量门
  （`actual-content` / `quality` / `delivery`）**全部跑完再汇总**。原先的 `if not ok: break`
  让每轮 repair 只能看到一层门的问题——6 轮 repair 恰好对应门（rendered → actual-content →
  quality → evidence → 视觉）的逐层暴露，每轮都在"盲修"下游没跑过的门。
- `pipeline-qa.json` 新增 `failed_stages` / `blockers_by_gate` / `derived_problems`：一轮 repair
  拿到的就是完整清单。`delivery` 只汇总上游报告的结论，上游失败时它的失败记为派生、不计入
  blocker，避免把 builder 指向一个没有独立问题的地方。
- stage summary 与 SKILL 第 13/14 步同步：按报告路径交给 builder 自己读，**按门分批修是禁止项**。

### Builder：投影式读取工具取代内联脚本（解"每轮 19~46 条 `node -e`"）

- 新增 `skills/sp-deck/scripts/page_brief.py`：一次调用给出每页的逐字 `claim`、planned numbers、
  本页 blocker、引用来源（标题取自 research-pack 原文）。`--slide N` 给单页完整上下文，省略则给
  全 deck（`initial` 轮一次拿完，不再重复读 spec 11 次）。其 numbers 由新抽出的
  `pptx_actual_content_check.planned_requirements()` 产出，**与 actual-content 门同源**。
- `generator_scaffold.py`：page stub 从"本页要有 planned numbers"的通用提示，改为**注入本页实际
  内容**（title / claim / numbers / copy 片段），同一函数产出，stub 与门不可能互相矛盾。顺带修掉
  一个真实缺陷：spec 的 title 含 `*/` 时会提前闭合 JS 文档注释、把剩余标题变成代码。
- `builder_guard.py` 扩到 shell 工具：builder 的内联 `node -e …require('./*.json')…` 被拒绝并指向
  `page_brief.py`（`node` 语法校验、`pptx-helpers.js --describe`、临时目录试渲染不受影响）。
  `hooks.json` 的 builder_guard matcher 同步为 `Read|Write|Edit|Bash|PowerShell`。

### 视觉：回归检测与归因（解"第 5 轮改坏 → 第 6 轮回退"）

- `pptx_quality_gate_v071.py` 新增逐页分数对比：任一页相比**上一轮**下降 ≥1.5 判
  `visual_regression`（并给出前后分数）；低于**历史最佳** ≥1.5 判 `visual_regression_sustained`
  （捕捉每轮只降一点点的累积退化）。历史写在 work-dir 的 `visual-score-history.json`。
  第 5→6 轮那类"改了又撤"从此在 QA 里被点名归因，而不是变成一轮模糊的"revert regressions"。
- `presentation-builder.md` 与 spawn 模板：明确"不得把已通过的页当试验田"。

### 预算与轮次

- `pipeline-contract.json` + SKILL：提额（超过 `max_repairs`）必须附本轮与上轮的 blocker 差异；
  用同一做法加预算不构成修复策略（live 里 3 次提额中有一轮纯用于回退）。

### 守卫：修掉正则误伤（解"强制的命令恰好是被拦的命令"）

- `cost_guard.py`：`PLUGIN_INSPECT` / `GREP_SED` 原先在**整行任意位置**匹配
  `ls|dir|grep|head|…`，于是 `--work-dir` 里的 `dir` 命中了 `dir` 动词；而放行用的
  `PIPELINE_RUN` 要求 `.py` 后紧跟空白，**带引号的写法**
  （`python "…/ppt_pipeline.py" next --work-dir <wd>`，正是 SKILL 推荐的写法）静默失配。
  两者叠加的结果是"pipeline 要求的命令被 pipeline 自己的守卫拦下"——2026-09-17 live 的
  6 次 cost_guard 拦截里有一半是这一形态。
  现在：动词必须出现在**命令位置**（行首或 `&&` / `;` / `||` 之后）；`PLUGIN_PATH` 要求路径形态
  （`grep -l "student-presentation-suite-scaffold"` 不再因为标记名与插件同名而被判成读插件源）；
  管道里的 `head` / `tail` 放行——那是把输出**变小**的手段，拦它等于把更多文本灌进上下文。
  真正的拦截（列举插件缓存、cat 插件源码）保持不变。
- `--help`：带路径的 `ppt_pipeline.py --help`（含子命令 help）放行。pipeline CLI 是 agent 的
  操作面，help 只有几十行；拦它不会省轮次——模型改用试错找调用方式，同样的轮次产出的是
  失败而非信息（live：一次 `--help` 被拒后，紧接着的两条命令还是连环 `--help` 探测）。
  裸脚本名的调用仍然拒绝，让提示把绝对路径交出去。

### QA：门级回归与收敛度（解"提额之后把已经通过的门弄坏"）

- `gate_regressions()`：把每轮各门的通过状态记进 work-dir 的 `gate-history.json`，某门从
  通过变为失败即报 `gate_regression`。2026-09-17 live 第 6 轮把 `actual_content` 弄坏
  （该门自 build 3 起一直通过），当时没有任何东西对比过门的状态，于是它只表现为"又一堆
  blocker"，等被发现时额度已经用完、且那一轮做的事正好是回退自己的上一轮。
- `repair_convergence()`：`next --json` 现在输出逐轮 blocker 数与趋势。`improving` 才值得续轮，
  `flat` 要换做法，`worse` 必须先恢复被弄坏的回归——**这三种结论都由数据判定，不必再问用户**
  （live 里预算耗尽后问了两次，其中一次批准的轮次净收益为零）。

### 测试（批次三）

- 新增：内容门失败后下游门仍全部执行、`blockers_by_gate` 归类正确、派生 blocker 不计入；
  `page_brief` 与门同源 / 来源逐字节 / 派生分离 / 全 deck 覆盖；scaffold 注入本页契约与注释闭合；
  builder 内联 JSON 提取被拒而合法 node 命令放行；视觉回归的三个方向（相邻下降、噪声不报、
  累积退化）；门级回归（通过→失败被点名、未跑的门保留记录、首次运行不算回归）；
  收敛度三个趋势；cost_guard 的四个误伤场景放行 + 三个真实拦截保留。
- 全量 617 用例通过。

来源：2026-09-18 对同一份 transcript 的**契约矛盾**复核（批次四）。批次三修的是"每轮只能看到
一层门"，批次四修的是**两边都是明文规定、却互相要求相反行为**的地方——这类矛盾不会让某一轮报错，
只会让 repair 在夹缝里来回改，直到预算烧完。

### 守卫 vs 指令：强制的命令不能被自家守卫拦下（第二次发生）

- `production_entry_guard.py` 放行 `page_brief.py` 与 `run_gates.py`。`page_brief.py` 是
  spawn-templates 与 `builder_guard` 拒绝消息**共同强制** builder 使用的投影工具，却没进白名单——
  builder 一调用就被拒，与 2026-09-17 的 `visual_reference_select.py` 是同一形态的重演；而且这次
  更死：`builder_guard` 拒绝内联 `node -e` 后给出的唯一替代路径就是这条会被拒的命令。
- 拒绝消息一律给出**解析后的绝对路径**（`builder_guard` 原先让子代理去展开
  `${CLAUDE_PLUGIN_ROOT}`，子代理 shell 是否继承该变量不是我们能假设的）；spawn-templates 里新加的
  命令行同步为与相邻行一致的 `<CLAUDE_PLUGIN_ROOT>` 占位符形态。
- 新增 `tests/test_instruction_guard_consistency.py`：把 spawn 模板与三个守卫的拒绝提示里的命令
  机械地过一遍守卫，按主会话 / builder / researcher / critic 身份断言全部放行，同时保留三条真实
  拦截（读插件源码、`ls` 插件目录、`grep` 守卫源码）。指令、提示与白名单是同一个事实的三份拷贝，
  以后由测试比对，不再靠评审。

### Calibration：重跑不再被自己的输出挡住

- `calibration_preview.py` 在构建前删除上一份 `calibration.pptx`。该文件与它已经清掉的 render PNG
  同为**不可交付的临时预览证据**，而 `run_with_pptxgenjs.js` 拒绝覆盖已存在的输出——于是 0.13.5
  写明的恢复流程（"builder 修完 calibration 页后重跑 helper"）第二次必定 exit 2，live 里那一轮
  花在手工删文件上。

### blocker 口径：critic 与质量门说同一个词

- 质量门按 `BLOCKING_SEVERITIES = {critical, major}` 计 blocker，但没有任何地方告诉 critic 这一点。
  live 里 critic 回报"blocker 数：0（major 8）"，主会话据此认定"独立复核判定可交付"，而门对同一份
  报告算出 23 个 blocker，这个分歧被一路带进了提额决策。
- `visual-review.schema.json` 的 `blocker_count` / `verdict` 写入定义；`agents/visual-critic.md`、
  `skills/sp-deck/references/pptx-visual-critic.md` 与 spawn 模板同步；质量门在报告自称
  `blocker_count: 0` 而门推出 blocker 时补一条 minor `visual_review_blocker_count_mismatch`，把两个
  数字和定义写在同一条里。

### 冻结数值 × chart grammar：写明谁让路

- 三条规则互相顶：actual-content 门要求每个 planned number 有可见文本载体（chart 数据标签不算
  文本 run）；critic 按 chart grammar 要求柱子可直读；反冗余判定又把"同一数值出现两次"记成缺陷。
  live 第 5→7 轮就在删直标 / 加回直标之间震荡，最后一轮把一直通过的 `actual_content` 门弄坏了。
- 仲裁写进 `pptx-visual-critic.md`、critic agent 定义、spawn 模板（builder 与 critic 两侧）与
  scaffold 的 ON-SCREEN REQUIRED 注释块：冻结数值的文本载体**不是**冗余；已有文本载体的数值可以
  省掉图表直标且不得判 Major；真正算缺陷的三种重复（两个文本载体同值、一根柱旁两个数值、
  左栏逐条抄右栏数值）必须点名。

### asset_plan 是交付承诺：规划期校验图像能力

- 新增 `shared/image_capability.py`（`scripts/check_claude_pptx_env.py` 的原实现迁入，两个读者共用
  一个 owner）：`art_direction_check.py --work-dir` 现在会解析本会话的 `image-sources.json`。
  完全没有声明时，声明了 `hero_visuals` / `evidence_visuals` 的 plan 直接拒绝
  （`asset_plan_visuals_unavailable`，undeclared = unavailable）；已声明但 provider 都不 ready 时
  只给 minor（`asset_plan_visuals_not_ready`），因为 deterministic visual stack 本就是合法交付方式
  （golden sample 的 asset-manifest 即如此写）。没有图像能力时 mix 下限从"四类"降到可用的三类。
- 背景：live 的封面声明了生成插图但项目里没有 `image-sources.json`，`hero-visual-missing` 从第一轮
  critique 到最后一轮都在，预算内无法修复。

### 提额：写进 manifest，不改已安装插件

- `ppt_pipeline.py repair --extend N --extend-reason "<本轮与上轮的 blocker 差异>"`：授权记录在
  `build-manifest.json` 的 `build.repair_budget_grants`（含授权时的 blocker 数与
  `repair_convergence` 趋势），`next --json` 新增 `repair_budget`（base / granted / effective /
  hard_cap），`status` 显示有效预算。硬顶由契约 `max_repairs_hard_cap`（12）强制，到顶只能如实交付
  `incomplete`。原先超预算的唯一出路是改插件 cache 里的 `pipeline-contract.json`（live 就是这么做
  的）——升级即失效、不可审计，也违反仓库自己的"不写已安装插件"。

### 门禁调用形式

- 文档与 SKILL 的推荐命令从 `sh …/run_gates.sh` 改为 `python …/run_gates.py`（`run_gates.sh` 仍保留，
  只是定位解释器的包装）。live 里 `sh` 解析到 WSL，`C:/...` 路径打不开，exit 127 白跑一轮；
  `run_gates.py` 本来才是 canonical 实现，现已在守卫白名单内。

### 测试（批次四）

- 新增：模板 / 守卫提示的命令一致性（4 类身份）、真实拦截仍拦截、calibration 重跑不被自身输出挡住、
  critic blocker 口径三处同步、asset_plan 无声明拒绝 / 已声明未就绪只提醒 / 无图像能力时 mix 下限、
  `--extend` 授权与记录 / 缺 blocker diff 拒绝 / 硬顶拒绝 / `next` 报告有效预算。
- 全量 636 用例通过（批三基线 617）。

## 0.14.0 — 2026-09-18

来源：2026-09-17 0.13.4 全程 live 会话复盘的**契约级**修复（批次二）。0.13.5 修的是
"指令 / 说明 / 运行时行为三者互不匹配"的机械面；本批修根因——**契约没有前置，门只能追补**。
QA 门要求的每一项（讲稿备注、上屏文本、末页来源、数值轴定标）此前只存在于门里，没有任何
上游出处，于是 6 轮 repair 里有 4 轮在补门的需求。本批把每条要求放回它的 canonical 层：
schema 定义形状、scaffold 注入字节级内容、spawn 模板承载契约、设计期拦下运行时画不出的承诺。

### 研究：检索预算申报例外（解"超支即回退整轮"）

- `research-pack.schema.json`：新增可选 `budget_extension`（`extra_queries` ≥ 1、
  `approved_by: user`、非空 `reason`）。live 会话中 gap-fill 第 2 轮把 deep 档做到 16/15，
  唯一出路是回退整轮、12 页压成 10 页；现在超支有合规申报路径，审计零删除。
- `validate_research_pack.py`：上限按 `cap + extra_queries` 放行；申报字段不完整
  （缺 reason / `approved_by` 不是 user / `extra_queries` < 1）判 `budget_extension_invalid`。
- `ppt_pipeline.py` `next`：work-dir 已有 pack 时返回
  `budget: {band, used, cap, approved_headroom, remaining}`，并在 notes 里声明"gap-fill 授权
  必须写明剩余额度"。live 会话授权说"大约再 6 次"而实际余 7 次可用，研究员跑了 8 次。
- `presentation-researcher.md` / `research-workflow.md`：补检授权必须携带剩余额度，耗尽即停；
  禁止删除已执行的 queries 记录来迎合上限。

### QA 门：讲稿判定对象迁到交付产物（解"10 项幽灵 blocker → incomplete"）

- `pptx_actual_content_check.py`：新增 `extract_pptx_notes()`，从 `ppt/notesSlides/*.xml`
  按页抽取备注文本。
- `pptx_quality_gate_v071.py`：`check_timing()` 改为对**交付 PPTX 的备注区**判
  `speaker_notes_missing` 与时长估算。此前它读冻结 spec 的 `slides[].speaker_notes`——该字段
  从 `plan` 起一直为空且无人被要求填写，而备注区实际完好，10 项 blocker 纯属幽灵，并直接
  导致终局 `incomplete`。门读产物，不读计划。
- `presentation-builder.md` / `pptx-qa.md` / 插件 README 中英对：讲稿交付物明确为
  **PPTX 备注区**（`slide.addNotes`，每页一次、纯文本）+ `speaker-notes.md` 可读副本。

### 视觉复核：报告形状单一化 + 消费端校验（解"每轮手贴 1.5KB schema"）

- 新增 `references/visual-review.schema.json`：`visual-review.json` 的 canonical 形状，
  分数与结构词汇与 `SCORE_FIELDS` / `REPETITIVE_STRUCTURES` 对齐。
  **`required` 只含 QA 门真正消费的最小集**（`pptx_sha256`、`slides`；每页
  `slide`/`visual_structure`/`scores`/`issues`）——把门不读的字段设成必填，只会让 critic 每轮
  补写无人读取的内容，漏一个就返工，那正是本批要消灭的失败模式。其余属性是推荐完整形状，
  一旦出现即受类型约束。
- `pptx_quality_gate_v071.py`：`validate_visual_report()` 先按 schema 校验。结构性违规
  （required / type / enum / pattern…）判 critical `visual_review_schema_invalid` 并**直接点名
  缺哪个字段**；未知字段只报 minor `visual_review_schema_extra`，永不阻塞——live 会话里
  critic 按过时示例交了顶层 `issues` 结构，门只回派生错误（"must contain a slides array"），
  主会话于是手贴 schema 四次。
- `agents/visual-critic.md` / `pptx-visual-critic.md`：形状唯一来源改为指向上面的 schema 文件；
  参考示例补齐为完整形状（旧示例缺 9 个字段，正是漂移源头）。
- issue `code` 允许短横线与下划线两种形式（门自身用下划线，critic 用短横线描述问题）——
  形式没有语义价值，强制其一只会制造摩擦。

### Scaffold：门需求前置进生成契约（解"4/6 轮 repair 在追补"）

- `generator_scaffold.py`：每页 stub 头部写入 `ON-SCREEN REQUIRED` 注释——title、claim 与每个
  planned number 必须以可见文本出现（actual-content 门读 PPTX 文本 run，chart 数据标签不算）。
  此前这条只活在门里，repair 轮才发现。
- `generator_scaffold.py`：末页 `COPY.sources` 由**代码**从 `research-pack.json` 逐字节注入
  （title/publisher/year）。live 会话中来源标题被手打进 repair prompt 并在字符级失真
  （全角引号），final-reference 门拒了 6 条——现在没有模型经手这些字节。
- `slide-spec.md`：`claim` 定义补充"必须逐字上屏，只存在于本文件即视为未交付"。
- `pptx-visual-engine.md`：数值轴必须显式 `valAxisMinVal: 0` / `valAxisMaxVal`（否则
  `chart-axis-auto`）；line series 不得依赖 `line.width` / `dashType` 区分系列。

### Spawn 模板：跨层传递改走文件路径（解"17 次 spawn 每次手写契约"）

- 新增 `references/spawn-templates.md`：researcher / builder / critic 三套固定模板，分
  "固定约束段（逐字复制）"与"数据槽（只填路径、页码、报告路径）"。
- `skills/sp-deck/SKILL.md`：spawn prompt 一律从模板实例化，禁止自由撰写；**字节级内容
  （claim / 来源标题 / 数字）传文件路径让子代理自己读原文**——门做逐字节判定，模型转抄即
  失真源（S07 标题手打失真 ×6、researcher 信封漂移、critic schema 手贴 4 次）。

### 设计期：样式承诺前先读 token；设计承诺的运行时能力 lint

- `SKILL.md` step 4 + `presentation-intake.md` Round 3：呈现具体样式选项或做任何颜色/视觉承诺
  **之前必须先读 `design-tokens.json`**，选项只能引用其中实际存在的 token 名，6 角色位之外的
  配色语义禁止承诺。live 会话先承诺"光伏配暖色琥珀"，读到调色板契约后被迫中途换风格并重绑
  确认哈希。
- `art_direction_check.py`：新增 `line-series-stroke-encoding-unsupported`——chart grammar /
  motif / component language 里出现 line-series 描边/虚线承诺时，设计期即拒（pptxgenjs 忽略
  series 级 line.width/dashType，live 实测"实心 vs 描边"双主角编码画不出来，图例承诺了图形
  没兑现的编码）；形状描边不受影响。

### 清理与登记

- `pipeline-contract.json`：qa 契约登记 `visual-review.schema.json` 与"备注区判定"。
- `pptx-visual-critic.md`、`smoke_research_fork.py`：残留的 "前台 spawn" 措辞改为"主会话等待
  其返回"（0.13.5 已删除 `run_in_background` 强制，措辞不该继续暗示该机制存在）。

### 测试

- 新增：visual-review schema 顶层结构漂移点名缺失字段、未知字段只报 minor 不阻塞、`required`
  边界与门消费集一致；预算申报例外放行与拒收；scaffold 上屏契约注释、末页来源区逐字节
  注入；art-direction line-series 描边拦截与形状描边放行。
- 全量 586 用例通过。

## 0.13.5 — 2026-09-17

来源：2026-09-17 0.13.4 全程 live 会话复盘（碳中和光伏 vs 风电 10 页 deck：17 个子代理、
7 次 build、6/6 repair 耗尽，最终 `incomplete` 交付）。该会话暴露出一类系统性缺陷：
**指令（SKILL/spawn prompt）、说明（references/agent 定义）、agent 实际被 hook 允许的行为
三者互不匹配**。本批为机械修复（批次一），契约级修复（预算申报、QA 门对齐、scaffold
前置、spawn 模板）留待 0.14.0。

### 运行时：回执捕获脚本写盘（解"plan 拒健康 pack"）

- `runtime_evidence.py`：回执物（`research-pack.json` / `visual-review.json`）改为**哈希快照
  归因**——SubagentStart 基线 + 每次 child 工具调用后重扫 diff，`python json.dump` 等 Bash
  写盘与 Write 工具同权计入 `writes`。live 会话中研究员 22 次写盘只有 2 次走 Write，
  回执为空导致 `plan` 拒绝并消耗主会话 6+ 轮排查。
- `hooks.json`：runtime_evidence 的 PostToolUse matcher 扩为
  `Read|Write|Edit|Bash|PowerShell`。

### Guard：拒绝文案按子代理身份分支（解"14 次拦截死胡同"）

- `cost_guard.py` / `production_entry_guard.py`：`agent_type` 为
  `presentation-builder` 时，拒绝文案给出 builder 真实可跑的白名单
  （`pptx-helpers.js --describe` 与 `visual_reference_select.py` 绝对路径），不再把
  `ppt_pipeline.py next`——builder 被禁止的命令——当出路。live 会话中 builder 因此
  被迫手写 composition 证据、跳过正式校验。
- `pptx-helpers.js --describe`：新增 `chartTypes`（10 项）、`shapeTypes`（179 项）、
  `notesApi`（`slide.addNotes`）、`chartAxisRule`（显式轴下限规则）、`lineSeriesLimit`
  （pptxgenjs 忽略 line series 的 series 级 width/dashType，live 实证）——builder 不再
  需要 `node -e require('pptxgenjs')` 探测（项目 cwd 解析不到模块，live 实测失败）。

### 报错可执行化：freeze 附重生命令

- `slide_spec_guard.py`：spec / research 校验报告的"does not exist / not passing /
  stale"三类拒绝各附**精确重生成命令**，并注明必须校验 plan 编译版
  `slide-spec-compiled.yaml`。live 会话在此 3 次试错。

### 死代码与幽灵措辞清理

- `runtime_evidence.py`：移除 `run_in_background` 拒绝分支——Claude Code 2.1.x 的 Agent
  工具默认异步且不带该参数（live 会话三次 spawn 均无此字段），"foreground 强制"从未
  生效；SubagentStop 回据对异步代理同样成立。
- SKILL（sp-deck / sp-research）、`pipeline-contract.json`、`ppt_pipeline.py` notes、
  `builder_guard.py`、插件 README 中英对的全部 "foreground / 前台" 措辞改为异步现实：
  不传 `name` 直接 spawn，收到紧凑信封前不推进下一阶段。

### 中断恢复：`next` 按校准证据分派（解"修复轮被截断即白做"）

- `ppt_pipeline.py` `next` 的 `planned` 分支重写：依据 `calibration/calibration-manifest.json`
  与 render 的存在性分派——未校准 → spawn builder(calibration)；已实现未渲染 → 给出
  `calibration_preview.py` 命令（slides 参数从 manifest 读取）；已渲染 → 指向审查/修复/
  initial 分支。此前它无视校准状态直接回 `build`，并教主会话"parallel Edit 直接改
  pages/pNN-*.js"——恰是 `builder_guard` 禁止的唯一流程（live 会话在校准修复轮被截断，
  重开后按此指引有把带 blocker 页面直接全量 build 的风险）。
- `planned` create/rebuild 的 stage contract 固定为 `build`（校准流程契约），不再依赖
  next_command 子串嗅探。
- sp-deck SKILL：回合结束仍有未返回 pipeline 子代理时固定尾句提示（关闭会话丢该轮）；
  插件 README 中英对补"会话中断恢复"条目。

### Intake 批量合规

- sp-deck SKILL：intake 询问必须按 `presentation-intake.md` 的 Round 结构批量发出
  （每轮一次 `AskUserQuestion`、最多 4 问），禁止拆成单问多次调用——live 会话 3 次单问
  违反已有 Round 契约。

### 测试

- 新增：Bash 写盘回执（快照归因 + 既有产物不误记）、builder 身份拒绝文案不指向
  pipeline 死胡同、`next` 三种校准状态分派（未校准 / 未渲染 / 已渲染恢复）。
- 更新：`run_in_background` 拒绝断言随死代码移除；`next` planned 断言从"指向 build"改为
  "分派校准 builder"。全量 572 用例通过。

## 0.13.4 — 2026-09-17

### Live E2E：headless 研究权限路径

- 研究 smoke 在 headless `claude -p` 上把插件根加为额外工作目录，并预放行研究员工具
  （父会话 spawn 用的 Agent / Skill 一并放行）。`acceptEdits` 不再把插件根 Read 和
  Bash / PowerShell 变成自动拒绝。
- 场景 D 额外禁止 WebSearch / WebFetch。不使用 bypassPermissions。剩余权限拒绝仍判
  机制失败。
- `scripts/live_prompts/` 裸跑命令与 FINDINGS 同步。

## 0.13.3 — 2026-09-17

### 文档：README 职责拆分，去掉拷贝段与 `claude-code` 漂移

- 根 README（中英）只保留 marketplace 安装/验证/更新/排错；技能表改为现行
  `sp-research` / `sp-outline` / `sp-deck` / `sp-review`；更新命令改回 `main`。
- 插件 README（中英）声明自身职责，修正“PreToolUse 已移除”与 `cost_guard` 矛盾；
  删掉四份文件各抄一遍的「0.13 执行完整性」。
- `AGENTS.md` 增加 Documentation Ownership 矩阵；插件 `AGENTS.md` 只写插件内文档职责。
- `CLAUDE.md` 改为指向两份 AGENTS 的短指针，不再复制结构/分支/14 种风格。

### 契约：四技能路由与生产状态跟 pipeline 对齐

- 插件 `AGENTS.md` 与 `shared-standards.md` 把 `sp-research` 写进激活/路由/handoff；
  `cost-discipline.md` 适用范围含研究技能。
- 生产返工/交付改为 `ppt_pipeline.py repair|complete`；intake 写明 guard 只做
  intake，`build-manifest.json` 才是生产权威。根 README 排错命令同步。
- SKILL 相对路径指向真实文件；marketplace / plugin 描述不再写 `claude-code` 分支，
  并补上 research 关键词。
- 契约测试锁住：文档不得再教 `transition --to producing|complete`。

### 运行时：image-sources 契约接入、源 deck 只读、npm 漏洞

- `fetch_images` 与环境检查按 `image-sources.schema.json` 校验；schema 增加
  `url_template`；`assets_dir` 必须落在项目根内。
- `cjk-fonts` 必须 `--output` 且不得写回输入文件。`lxml` 写入
  `requirements-claude-pptx.txt`。
- `image-size` 直依赖升到 2.0.2（buffer API）。pptxgenjs 仍嵌套 1.2.1，
  npm audit allowlist 续期到 2026-12-01 并写明原因。不跟 Dependabot #20 的
  eslint 8→10。
- 发布门禁与 CI `json.tool` 补上 slide-spec / image-sources / asset-manifest /
  research-pack / evidence-map schema。

## 0.13.2 — 2026-09-17

来源：2026-09-16 0.13.1 真实执行会话复盘（碳中和光伏 vs 风电 12 页 deck），
主会话 46 个错误 tool_result、管线最终死锁在 `producing`。
成本归因（去重口径）：49.4M token / 287 请求，主会话占 94%；token ≈ (每请求新增上下文/2) × 请求数²，
**请求数是平方项**。死锁段 + 绕过段合计 46%。

### 逻辑修复：嵌套子代理、模糊命名、plan 自编译 evidence、禁止旁路出 PPTX

同一场 12 页 live 里，token 的平方项来自请求数，而请求数被两段逻辑错误放大：
研究阶段带 `name` 的 teammate 被拦后**再嵌套一层**（外层 0 次检索），以及 QA 死锁后
**绕过 pipeline 直接跑 builder**。本轮把剩余洞补成机械拒绝。

- `runtime_evidence`：`/sp-deck` `/sp-outline` `/sp-research` 进入后主会话 WebSearch
  即被拦；**子代理内禁止再 spawn** 研究员/critic；带 `name` 的拒绝文案改为
  「从主会话去掉 name 重发，不要再包一层」。
- `cost_guard`：名字**包含** `researcher`/`critic` 即拒（不再只匹配恰好叫
  `researcher`）；子代理内 spawn 凭据类型即拒；Bash 直接调用生成器脚本出 PPTX
  （环境探测除外）即拒，指向 `ppt_pipeline.py build`。
- `ppt_pipeline.py plan` **自己编译** evidence map（work-dir 里有 pack + validation 即可），
  不再要求模型传入 evidence map 路径。
- `plan` 接受 `--pack` 作为 `--research-pack` 的别名，并忽略多余的
  `--research-execution`（收据由 hook 落盘，模型传这个旗标只会 argparse 报错再空转一轮）。
- `plan` 在 copy-fit 之前跑 `art_direction_check`：缺 section 的 AD 不再拖到 exploration gates。
- 页 scaffold 写入 `COPY.title/claim/slideCopy` 字面量，降低 34 条 `planned_copy_missing` 的改写。
- `cost_guard` 拒绝 `ls` 插件缓存、手跑 `research_pack_to_evidence.py` / `slide_spec_guard.py`、
  以及对 `validate_research_pack.py` 等脚本的 `--help`。





### 成本杠杆：render 产出廉价缩略图，主会话大图设预算

- `render` 现在同时产出 `contact-sheet-thumb.jpg`（宽 1024、JPEG q72，实测约为全尺寸
  contact sheet 的 1/10），写入 manifest（`contact_sheet_thumb`，随 SHA 绑定与 stale 归档），
  cache-hit 时若缩略图缺失会从已绑定页图补生成。
- `next --json` 的 `read_images` 概览项优先指向缩略图；notes 写明全尺寸页图只在修具体
  blocker 页时读。
- `cost_guard` 新增**主会话大图预算**：>150KB 的图一session最多读 6 张，超出即拒绝并指向
  缩略图 / 隔离 critic（带 `agent_id` 的子代理不受限；缩略图尺寸不受限）。实测 19 张图
  占主会话工具回灌的 92%（3.27MB），此项把概览成本压掉约一个量级。

### 成本杠杆：只读巡检命令限流

- `ls`/`cat`/`head`/`tail`/`find`/`stat`/`dir`/`tree`/`du` 开头的命令，同一条（规范化后）
  在一个会话内第 3 次起被 `cost_guard` 拒绝并指向 `next`。实测浪费样本：
  `ls critic-execution.json` 连跑 5 次、`ls -la` ×4。
- build / gates / qa 等**动作命令不受限**（修复后重跑是合法路径）。

### 会话分段建议（文档 + next 提示）

- `next --json` 在 build+render 完成后给出 `session_segment: boundary-recommended`：
  此时是新会话的天然切点（work-dir 携带全部状态，新 `/sp-deck` → `next --json` 即可续跑）。
- `sp-deck/SKILL.md` Dispatch 写明分段原理（token ≈ (每请求新增/2) × 请求数²）与切点。
  这是流程约定：插件无法强制开新会话，但会让 `next` 主动提示。

### 修复：带 `name` 的凭据代理 spawn 会静默废掉执行收据（QA 死锁根因）

- `Agent` 调用同时传 `subagent_type` 和 `name` 时，Claude Code 会把它转成
  **in-process teammate**，其 `agent_type` 变成名字本身。而
  `runtime_evidence.py` 的收据机制按 `agent_type` 精确匹配
  `student-presentation-suite:visual-critic` / `:presentation-researcher`，
  于是 `SubagentStop` 全程不再触发，`critic-execution.json` 永不生成 →
  QA 门禁拒绝 → `repair` 又要求状态已是 `qa` → 死锁。
- **`runtime_evidence.py` PreToolUse 新增硬拒绝**：这类 spawn 必须不带
  `name`、且在前台运行（与既有 `run_in_background` 检查对称）。
  `cmd_next` 的 producing 提示同步写明"不要传 `name`"。
- `cost_guard` 同步拒绝名字含 `researcher` / `critic` 的通用 teammate（不再只匹配恰好叫 `researcher`）。
- 新增 `tests/test_runtime_evidence.py::test_named_evidence_agent_spawn_is_blocked`。

### 修复：run_gates.sh 在 Windows 上 exit 49 且零输出

- `command -v python3` 会命中 Microsoft Store 的 `python3.exe` 别名桩：命令存在但
  执行直接退出 49，原有 `command -v` 失败才降级 `python` 的写法永不触发。
- 改为实际执行 `"$PY" -c "import sys"` 探测，失败降级 `python`，两者都不可用时报
  清晰的 "no working Python interpreter" 并 exit 127。

### 修复：cost_guard 的指路信息缺绝对路径

- 拦截消息原先建议裸脚本名 `ppt_pipeline.py next --work-dir <wd>`，而它既不在 PATH
  上、也不在 hooks 目录旁边（实际位于 `skills/sp-deck/scripts/`）。子代理照做报
  "No such file or directory"，白白多一轮。现在提示里直接给出可执行的绝对路径
  （含 `sys.executable`）与 `pptx-helpers.js --describe` 的绝对路径。

### 修复：pptx-helpers.js 三处静默失败（首轮评审 2.8/10 的直接成因）

- `addTextBox` 无 `role` 时把请求字号静默钳到正文下限（CJK 22pt），数据标签/注解
  按 22pt 渲染导致溢出压叠——表现为"传了等于没传"。现在保留下限但**必须打印警告**
  并指明小字的正规通道（`role: 'caption' | 'source' | 'label'`）。
- `color`（`addFittedText` / `addTextBox`）现在校验调用方传入值：传调色板角色名
  （`primary_text` 等）直接抛 `RangeError`，而不是静默渲染成不可读文字。
- `assertTextFits` 在盒高扣边距后 ≤ 0 时不再打印"填充率 Infinity"，改为说明
  真正原因（可用区域 ≤ 0，请扩盒子或减边距）。
- 新增 `tests/test_pptx_helper_addtextbox.py`（6 个用例）。
- `color()` 缺 palette 角色时改为抛错后，`scenario_render_matrix` 的夹具补齐六角色
  （原先缺 `surface` / accent，CI render 在 `addArchitecture` 处直接炸掉）。
- Windows 上 evidence lock `unlink` 的 `PermissionError` 用 `contextlib.suppress`，过 ruff SIM105。
- `pptx-helpers.js` 过 Prettier（`color()` 抛错改动漏了格式化，挡住 runtime lint）。

### 修复：REFUSED 不带下一步、Art Direction 解析错误是裸 traceback

- `ppt_pipeline.py` 的 `REFUSED` 输出现在附带可直接执行的
  `next --work-dir <wd>` 命令（实测中 evidence-map 环节靠猜参数摸了约 10 轮）。
- `art_direction_check.py` 的 `load_structured` 捕获 YAML/JSON 解析错误与文件缺失，
  输出可读原因而非 traceback。

## 0.13.1 — 2026-09-16

### 修复：plugin.json 重复声明 hooks

- 移除 `.claude-plugin/plugin.json` 里的 `hooks` 字段。Claude Code 会自动加载标准的
  `hooks/hooks.json`，manifest 再显式引用同一文件会被判为重复并报
  `Duplicate hooks file detected ... The standard hooks/hooks.json is loaded
  automatically`，导致插件 hooks 整体加载失败（`runtime_evidence` 的隔离执行凭据、
  `cost_guard` 等都依赖这些 hooks）。

### 移除 6-deck live benchmark runner

- 删除 `scripts/benchmark_run.py`、`benchmarks/`（`decks.json` 与 0.11.1 baseline）
  以及 `tests/test_benchmark_run.py`。真实无头跑测要花真实费用，而两次实测都在
  build 之前停住：一次缺 isolated research receipt（`research-execution.json` 只能由
  真实派发的子代理产生），一次模型在 `planned` 状态就 end_turn、从未执行 build。
  确定性门禁已能覆盖同类问题，无需用真实消费去复现。
- `benchmark_report.py` **保留**并更名为 `scripts/pipeline_report.py`（测试同步更名）：
  它汇总 `build-manifest.json` 的执行成本（builds / repairs / render / qa / blockers），
  属于日常报告工具，不是 live benchmark 的一部分。
- 四个 README（中英各两份）移除 live benchmark 的操作说明。

### build 前拦截改写文案：page copy fidelity gate

来源：2026-09-16 复盘 0.11.1 pilot 的 11 个 QA blocker（8 个 `planned_copy_missing`
+ 3 个 `missing_key_claim`）。这些阻塞全部来自 `actual_content` 阶段，而
`pptx_actual_content_check.py` 只能在 build + render **之后**运行，于是"页面改写了
Spec 原文"这件事每次都要等昂贵的阶段付完钱才被发现——v0.8 run 2 的 30 blocker
（见 `copy_fit_preflight.py` docstring）也是同一条 cascade。

- **新增 `skills/sp-deck/scripts/page_copy_fidelity_check.py`**：在 `build` 之前比对
  `pages/*.js` 与 Slide Spec，要求 `title` / `claim` / `slide_copy` **逐字**出现在对应
  页面源码中；缺失即 exit 2，并逐条打印需要恢复的原文。页面按**序号**映射（`p01-*` 对应
  `spec.slides[0]`）——文件名里的 slug 不是 slide id（`p03-lcoe.js`、`p05-90.js`），
  按名字匹配不可靠。判定复用 `pptx_actual_content_check` 的 `normalize` /
  `compact_fragments`，避免两套"逐字"规则漂移。
- **`ppt_pipeline.py build` 接入该门禁**（`assert_page_split` 之后、生成之前）：
  改写文案现在在 build 前被拒，修复代价是一次 Edit 而不是整轮 rebuild。
- **拼接的字面量不算改写**：`'a' + 'b'` 视为携带原文，只有真正的改写才拦截。
- 新增 `tests/test_page_copy_fidelity_check.py`（11 个用例，含正向/负向/序号映射/拼接）。

## 0.13.0 — 2026-09-16

### 生产执行链路与发布治理

- QA 自动连接当前 preview 和 speaker notes；渲染、独立 critic 和 complete 逐项复核 SHA256。
- 三种 production mode 统一进入 Pipeline；OOXML 解包/打包保留 source，重建要求 source analysis，编辑交付附 change summary。
- 授权按 work-id 隔离，拒绝跨任务状态及 outputs 外路径。旧项目级状态须用新 work-id 重新确认。
- Research 与独立 visual critic 以实际子代理 hook 凭据绑定产物；next 输出紧凑阶段契约。
- 图片 provider command 须由独立 CLI SHA256 授权，项目 JSON 不能自行授权。
- CI 覆盖 skills，固定 Claude Code/Ruff/pip-audit，测试 Python 3.11/3.12；release workflow 必须等待全部验证。
- 可执行文件后缀解析使用 PurePath，避免 Linux/Python 3.11 的 Windows shim 模拟触发 WindowsPath 实例化错误。
- 增加 PowerPoint 独立 smoke/checklist，修正文档中的未发布版本和旧发布线表述。

## 0.12.0 — 2026-09-15

### 执行层修复：渲染证据与当前 PPTX 绑定、stub 页不得构建、guard 状态按会话隔离

来源：2026-09-15 对 `6df9086` / 0.11.1 的第三方评审。四项问题先在真实代码上逐条复现
（`outputs/_verify/repro_review_0915.py`），再修。

- **渲染证据绑定当前 PPTX**：`ppt_pipeline.py next` 在 `producing` 状态改为比对
  `manifest.render.pptx_sha256` 与当前 PPTX hash，不再只看 `contact-sheet.png` 是否存在。
  此前 repair → rebuild 之后 `build` 已清空 `manifest.render`，但磁盘上的旧图仍在，
  `next` 会把下一步指向 `qa`，模型于是用**上一版**的渲染图做视觉 critique。
- **build 归档失效渲染证据**：`build` 把上一次的 contact sheet 与页面 PNG 移到
  `stale/render-<sha8>/`（保留审计痕迹但并不留在约定路径），并在 build 历史里写入
  `stale_render_moved`。缓存判断本身仍在 `render` 内按 hash 进行，未改动。
- **stub 页不得进入 build**：`assert_page_split()` 拒绝任何仍含
  `student-presentation-suite-scaffold` 的 `pages/*.js`；`deck.js` 作为纯装配文件允许保留
  marker。此前只显示标题的 scaffold 页也能通过 build gate，要到 render 与视觉 QA 才暴露。
- **`cost_guard` 状态按会话隔离**：seen 状态从 `.pptx-work/cost-guard-seen.json`（被所有任务
  共享）改为 `outputs/.pptx-work/.guard/seen-<session>.json`；reference 去重键从 `path.name`
  改为 resolved path + sha256，不同目录的同名文档不再冲突，文档更新后允许重读。
- **缓存收益可观测**：`render` / `qa` 命中复用时写入 `reused` 记录，`benchmark_report.py`
  新增 `r_reuse` / `q_reuse` 列。此前复用分支不写 history，成本报告只能看到"花了多少"，
  看不到"机械门禁省了多少"，6-deck 基准将无法归因。
- **契约补强**：`pipeline-contract.json` 的 `repeat_policy` 增补
  `build_invalidates_render_evidence`、`render_evidence_must_match_current_pptx`、
  `no_scaffold_pages_at_build` 三条，并在 `test_pipeline_contract.py` 加断言。
- **新增测试**：`next` 路由（无证据 / 证据新鲜 / stale 图存在但 manifest 已清空）、
  stale 归档、复用记录、scaffold gate（含 `deck.js` 豁免）、guard 会话隔离与同名文档不冲突。

### 成本基准可执行化：6-deck runner

- **新增 `scripts/benchmark_run.py`**：`benchmarks/decks.json` 自 0.10.5 起已定义 6 类 deck，
  但从未真实跑过——brief 仍是 `<课程主题>` 占位符，也没有 runner，所以 0.11.x 的成本收益一直
  没有数据。本脚本把每个 deck 跑成一次真实的 `claude -p` 会话，再从该 deck 的
  `build-manifest.json` 读回确定性成本、从 CLI result 读回模型成本，汇总写入
  `benchmarks/baseline-<version>-<date>.json`，供折回 `decks.json` 的 `live_baseline`。
  - 占位符 topic 与不存在的 materials 路径在**花钱之前**就被拒绝；
  - `--all` 必须为每个 deck 提供 `--topic-deck id=topic`，防止对占位符跑基准；
  - `--dry-run` 只写 invocation 不调用 CLI；`--report` 只汇总既有记录；
  - 复用计数（`render_reused` / `qa_reused`）与 `stale_evidence_moved` 一并入报告，
    成本对比从"花了多少"升级为"花了多少 + 机械门禁省了多少"。
- **新增 `tests/test_benchmark_run.py`（22 项）**：占位符拦截、invocation 契约（work-id、
  页数、scope、intake 已确认、禁止追问）、预算与 session 固定、`modelUsage` token 汇总、
  `.cmd` shim 拒绝、intake 预确认、manifest 缺失不抛异常、汇总只统计真实运行并标注被截断的 deck。
- **首个真实数据点（pilot，`course-report-zh`，2026-09-15）**：一次真实 `claude -p` 会话产出
  10 页 deck（`deck.pptx` 54 KB + 10 页全渲染 + contact sheet），**73 turns / 8.95M token-context /
  $8.04 / 36.7 分钟**；对比 0.10 基线（307 requests / 82.5M）是 **请求 −76%、token −89%**。
  其中 `cache_read` 占 8.78M，真正的新增 input 只有 171 k。
  该轮在 `render` 之后撞上 `--max-budget-usd 8` 被截断（`terminal_reason: budget_exhausted`），
  **QA/delivery 尚未执行**，因此这两个数字是**下界**；报告用 `truncated_decks` / `comparable`
  显式标注，避免被当成完整 deck 成本。
- **成本口径修正**：单个 10 页 deck 的完整成本**大于 $8**，6-deck 基准应按 **$60~90** 预算，
  而不是先前估的 $6~36（原估偏低的来源：低估了 research + spec + 逐页 generator 的迭代轮数）。
  `benchmark_run.py` 的 `--budget-usd` 默认值因此从 8 上调到 **14**。
- **无人值守的前置条件**：`sp-deck` 的 intake 门禁要求 Production Summary 被确认，`-p` 单轮会话里
  没有人能回答，模型会停在 intake 追问题目（第一次 pilot 就是这样，49 秒结束、零产物）。
  runner 因此自带 `prepare_intake()`：生成 `production-summary.md` 并调
  `workflow_guard.py init` / `confirm --force` 推到 `intake_confirmed`，invocation 声明 intake 已完成。
  任何后续自动化（CI smoke、批量回归）都必须先过这一步。

### Research 隔离改为显式 spawn

- **`sp-research` 不再依赖 `context: fork`**：frontmatter 移除 `context: fork` / `agent:` /
  `background: false`，正文改为显式契约——主流程用 Agent 工具 spawn
  `student-presentation-suite:presentation-researcher`，前台等待，并把 work-id、brief 路径、
  scope、materials 路径写进 spawn 的 prompt 文本（子代理看不到主对话，也读不到 frontmatter
  的参数绑定）。原因见 `scripts/live_prompts/FINDINGS.md`：两次 Live 实测在 `claude -p` 下
  `subagent_stats.spawned = 0`、事件流无任何 subagent 事件，skill 实际内联跑在主会话里，
  主 session 甚至替研究员执行了 `validate_research_pack.py`。
- **判定标准收紧**：`smoke_research_fork.py` 只接受 `subagent_stats.spawned >= 1`，
  不再把 `context: fork` 的 fork 事件当作替代证据。
- **文档同步**：`README.md` / `README-zh.md` / `AGENTS.md` / `references/cost-discipline.md`（CD-5）/
  `skills/sp-outline/SKILL.md` / `live_prompts/*` 统一为"靠显式 spawn 隔离"，并注明不得回退到
  `context: fork`。
- **待实测**：改完后需重跑 `smoke_research_fork.py --scenario smoke --stream` 断言 `spawned >= 1`。

## 0.11.1 — 2026-09-15

- **静态溢出 CI 按真实行距判定裁切**：gallery / `inspect_pptx` 不再把 0.85 填充率的 `text-vertical-overflow-risk` 当失败。只有估算高度超过文本框（`fill > 1.0`，`text-vertical-overflow`）才拦 CI。行高优先读 PPTX 里的 `a:spcPts`（helpers 写出的 `fontSize * 1.18`），缺省才回落 1.18，不再用 1.4 去误报已经按 1.18 排过的标题。

## 0.11.0 — 2026-09-15

### 成本修复：机械门禁取代「请模型省 token」

一次实测 `/sp-deck`（光伏 vs 风电，DeepSeek Flash 1M，去重后约 82.5M token / 307 次请求 / 峰值 456k）说明：v0.8 的探索证据、多轮 intake、hybrid-adaptive 和看图 QA 都要保留，贵的是「始终加载 20 份 reference、整文件 generator、串行读图、提示词版 CD-2」。本版把那些变成程序拒绝。叠在 0.10.5 的 pipeline hardening（intake 绑定、幂等 build/QA、`render` + contact sheet）之上。

- **SKILL 不再有 80 行上限**。测试改为要求引用 canonical 规则；entry 文件可以写清 dispatch。
- **行距与 CJK 宽度对齐**：pptxgenjs 发出 `lineSpacing` 点数（`fontSize * 1.18`），禁止 `lineSpacingMultiple`；CJK 宽 1.0 em / 拉丁 0.58，与 `copy_fit_preflight.py` 一致。
- **`session_cost.py` 去重**：2 秒内用量相同的 assistant 行合并为一次请求，避免 JSONL 三份重复。
- **生成器按页拆分成为 build 门禁**：`ppt_pipeline.py plan` scaffold `deck.js` + `pages/pNN-*.js` + `composition/`；`build` 在页数 ≠ spec id 或 `deck.js` 未 require 各页时直接拒绝。golden sample 同步拆成 9 个 page 模块。
- **`ppt_pipeline.py next --json`**：告诉模型读什么、下一步跑哪条命令、本轮该并行 Read 哪些图；阶段小结由管线写入 `stage-*-summary.md`。
- **CD-8 / CD-9**：管线按 200k 窗口设计（1M 不是跳过压缩的许可证）；DeepSeek 每图封顶 1024 token，视觉 QA **必须看图**，contact sheet 与 blocker 页 PNG 同一轮并行 Read，同一 sha256 不重读。
- **`cost_guard.py` + `hooks/hooks.json`**：PreToolUse 拦截插件源码 grep/Read、第二次整篇读同一 reference、未变 PNG 重读、名叫 `researcher` 的 teammate；**不拦截第一次读图**。
- **研究回传 envelope**：`assert_research_envelope.py` 只接受 `RESEARCH_DONE` / `RESEARCH_BLOCKED`；`smoke_research_fork.py` 若在主对话看到 WebSearch/WebFetch 则判机制失败。`validate_research_pack.py` 仍是 pack 唯一的 `ok: true`。

目标（保持 v0.8 探索）：单次任务 ≤25M token，峰值 ≤150k。基线记在 `benchmarks/decks.json` 的 `live_baseline_0_10`。

## 0.10.5 — 2026-09-15

### Pipeline 1.0 hardening：状态权威、幂等执行、真实渲染与成本控制

- **机器契约成为事实源**：新增 `references/pipeline-contract.json`，统一 QA 顺序、repair 上限、manifest 版本与重复执行策略，避免 SKILL / workflow / pipeline 三套语义继续漂移。
- **Intake 与生产状态真正衔接**：`ppt_pipeline plan` 必须验证 `intake_confirmed` 与 Production Summary SHA256；plan 后 `build-manifest.json` 成为生产阶段权威状态并镜像 legacy workflow state。
- **执行成本硬约束**：禁止无 repair 的重复 build；repair 后 generator fingerprint 未变化拒绝重建；相同 PPTX / visual-review / previews 的 QA 直接复用；repair budget 在代码层固定为 3。
- **真实 Render 进入 Pipeline**：新增 `ppt_pipeline render`，统一 raster render、全页 PNG 与 `contact-sheet.png` 生成；相同 PPTX hash 复用 render 结果。
- **语义契约与成本基准补强**：新增 pipeline semantic contract tests；benchmark 增加 render events、rendered pages、QA runs 与 QA stage wall time，为后续 6-deck 成本对比提供可量化数据。
- **验证**：PR #19 的 Linux / Windows runtime、424 项测试、release checks、security scan、Claude manifest、scenario render matrix 与完整 visual gallery 全部通过。

## 0.10.4 — 2026-09-15

### sp-deck 收敛为 Pipeline CLI：结构约束取代提示词规则（P0-1/P0-2/P0-3）

- **新增 `skills/sp-deck/scripts/ppt_pipeline.py`**：生产段从"Agent 手动编排十几个脚本"收敛为
  单一入口 `plan / build / qa / repair / complete / status`，全部状态写在唯一的
  `build-manifest.json`（含 spec/lock/art-direction/pptx/各报告的 SHA256、build/repair 计数、
  转换历史）。
- **执行层状态机（P0-2）**：`build` 前必须 `plan`（freeze + copy-fit preflight），每次 build
  复查锁——改了 spec 不重新 plan 直接拒绝；`qa` 前必须有 build；`complete` 前必须 QA 全绿
  且 delivery 阶段真实运行过。SKILL 里一批"不得……"规则从此由程序拒绝兜底。
- **QA 从 batch 改为真 DAG（P0-3）**：`qa` 按 package → rendered → actual-content → quality →
  delivery 依序执行，**上一级刚产出的报告直接喂给下一级**（delivery 消费本轮的
  `qa-package / qa-actual-content / qa-quality`），Agent 不再手工传一堆报告路径；每份报告
  以 SHA256 绑进 manifest；失败级即停，防止下游对着陈旧产物出报告。
- **文档修正**：0.9.1 条目声称 `run_gates.sh` 扩展了一个 QA 聚合参数，与事实不符——
  `run_gates.py` 从未有该参数，QA 门禁实际由 `--pptx` 启用（`.sh` 只是解释器包装，透传全部
  参数）。历史条目按原貌保留，特此更正。
- **新增 `tests/test_cli_doc_contract.py`**：扫描 README / README-zh / CHANGELOG Unreleased /
  SKILL.md / references 中出现的脚本与 `--flag`，逐一对照真实 `--help` 语料（含
  `slide_spec_guard.py`、`pptx_tool.py` 的子命令），防止 CLI 与文档再次漂移。
- **新增 `tests/test_ppt_pipeline.py`（18 项）**：状态机拒绝路径（无 plan 不得 build、QA 无
  blocker 不得 repair、无 delivery 不得 complete）、锁复查、QA DAG 接线（delivery 消费本轮
  报告）与失败即停。
- **统一版本化 CLI（P1-4）**：新增稳定入口 `skills/sp-deck/scripts/delivery_check.py` 与
  `quality_gate.py`，以 `--core v07|v071|v08` dispatch 到内部实现（默认 v08 / v071）；
  `pptx_delivery_check_v07.py` 等历史脚本保留为内部模块与测试对象，不再作为平级 CLI 暴露。
  `references/pptx-qa.md` 的示例命令与入口约定同步更新。版本应进入 schema 与数据，而不是
  继续进入脚本文件名。
- **Python 依赖 constraints lock（第 11 节）**：新增 `requirements-lock.txt`（36 个包的精确
  闭包，由 requirements*.txt 范围解析生成，含 ruff 钉版）；CI 全部安装行与 pip-audit 改为
  `-c` 约束安装，消除"CI 每次装到不同版本"的漂移面。范围仍是唯一事实源，升级后重新生成 lock。
- CI：push 触发分支移除已删除的 `improve/ppt-generation-core-v0.7`。
- 新增 `benchmarks/decks.json`（6 类固定 deck 定义）与 `scripts/benchmark_report.py`（汇总各
  work-dir 的 build/repair/最终 blocker 指标），为 release 基准提供骨架。

## 0.10.3 — 2026-09-14

### Evidence Map 补 schema 与管线级 E2E（2026-09-14）

上一轮 review 的 14 项里，11 项已在 PR #18 修完；剩下三项中的两项在这里收尾。

- **新增 `references/evidence-map.schema.json`**（review 第 13 项）。此前 Evidence Map 只有
  `schema_version: "1.0"` 这个声明，没有真正的验证器——**声明了版本却不校验形状，等于
  没有版本**。现在 `research_pack_to_evidence.py` 在写盘前用这个 schema 校验自己的产出，
  违反即退出码 2 并打印具体路径。校验是 **fail-closed** 的：`jsonschema` 缺失或 schema
  文件不见了都算失败，不当作"无法验证所以放行"。
  schema 里把三处关键约束钉死：`evidence_ledger` 条目**必须**带 `source_ids`（多源关系
  不能丢）、`provenance.research_pack_sha256` 必须是合法哈希、`schema_version` 必须是
  `"1.0"`。
- **新增管线级 E2E 测试**（review 第 14 项的本地替代）。此前 371 项测试只证明组件各自
  正确，不证明串起来正确——这正是上一轮 review 第 9 条批评的点。新增的
  `ResearchPipelineEndToEndTests` 跑完整条链：

  ```text
  Research Pack → validate_research_pack → research_pack_to_evidence
      → compiled Slide Spec → slide_spec_guard freeze → check
  ```

  并断言：`F01/D01` 被改写成 `E01/E02`、ledger 的 `used_on_slides` 被算出、锁里绑定了
  三个 research 产物、冻结后改动 pack 会让 `check` 失败、draft 里写了不存在的 `F99`
  时编译器拒绝产出半个 spec。
- **明确 Evidence Map 的确定性边界**（review 第 12 项，`research-workflow.md`）：
  **语义内容确定性 ✅**（`semantic_sha256` 与 ledger 逐字一致）；**字节级位置无关确定性 🟡**
  （`provenance` 含绝对路径）。按 review 的建议**不删审计路径**，改用
  `semantic_sha256` 作为"是否同一份证据"的判据，并补了跨目录一致性测试。
- `check_plugin_release.py` 的 `REQUIRED_FILES` 增加 `evidence-map.schema.json`。

测试 371 → **380** 项。

> 请注意：**仍未完成的是 review 第 14 项本身——真实 Claude Code Live E2E。** 上面的
> 管线测试不经过真实模型与联网，它把"编译产物能否真的被冻结"从没测过变成每次 CI 都测，
> 但证明不了 fork 出来的子代理在真实会话里行为正确。这一项只能靠真跑。

## 0.10.2 — 2026-09-14

### 合并 PR #18：research 子系统的证据链与门禁加固（2026-09-14）

合并 `fix/research-subsystem-hardening`（26 个提交，16 文件，+1118/−555，合并提交
`43013e1`）。这一轮修的大多是 0.10.1 自身留下的洞：

**CI 门禁实际是 fail-open 的（最严重）**
`validate.yml` 里每条原生命令后面都补了 `if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }`。
pwsh 下原生命令的非零退出码**默认不会让 step 失败**——只要脚本最后一条命令成功，前面
某个 checker 挂掉也会显示 ✓。`check_plugin_release.py`、`check_marketplace_release.py`、
schema 校验、ruff、eslint、prettier 全都受影响。另外给 runtime job 加了 `PYTHONUTF8=1`，
并给测试 step 把 `TEMP`/`TMP` 收敛到 `runner.temp`。

**schema 与校验器互相打架（我引入的死锁）**
校验器要求 low 置信度的 `data_point` 必须写 `notes`，但 schema 里 `data_point` 没声明该
字段且 `additionalProperties: false` —— 一条合规的 pack 会**必然**卡在 schema 校验上。
已补 `data_point.notes`；`unresolved.impact` 也从"校验器要求"提升为 schema 必填。

**证据编译从"半成品"变成真正的编译器**
- 分配规则补上 **quotes**（此前 `Q` 完全没有到 `E` 的通路）；
- 接受 draft spec 里的 `F/D/Q` 或已分配的 `E`，重写 `evidence_refs`、重算
  `used_on_slides`、替换 ledger，并可写出**非破坏性**的 compiled Slide Spec，不再需要
  任何模型手工搬运；
- 保留全部 `source_ids` 并选出 `primary_source_id`（此前只留一个 locator，其余来源丢失）
  —— `slide-spec.schema.json` 相应新增这两个字段；
- 校验报告必须与 pack **哈希绑定**，过期或对不上另一份 pack 直接拒绝编译。

**freeze 校验整条来源链**
research-backed freeze 现在验证 Pack → Validation → Evidence Map → Compiled Spec 全链；
Research Gate 变成原子的（三个产物要么都有要么都没有）；research-backed revision 不能
静默丢掉 provenance；同时保留 legacy lock 的兼容性。

**子代理收窄**
`presentation-researcher` 加了工具白名单（`Read, Grep, Glob, Bash, PowerShell, Write,
WebFetch, WebSearch`——没有 Edit、没有 Agent）；`sp-research` 改用**具名参数**
`arguments: [work_id, brief_path, scope, materials_path]`，不再靠自由文本传参；
返回信封有界；纯 C 类（无需检索）大纲不再启动子代理。

测试 364 → **371** 项。

## 0.10.1 — 2026-09-14

### sp-research 从"提示词规则"升级为真正的独立子代理（2026-09-14）

0.10.0 交付的 `sp-research` 只是 Skill，而普通 Skill 默认在主对话上下文里运行。这
意味着文档里写的"检索一律在子代理内完成"**只是一条提示词规则**——从运行机制上并没有
保证主流程不会吃到原始搜索结果，Context Firewall 实际上是空的。

- **P0｜真正 fork**（`skills/sp-research/SKILL.md`）：
  - frontmatter 增加 `context: fork`、`agent: student-presentation-suite:presentation-researcher`、
    `background: false`、`argument-hint`；
  - **新增 `agents/presentation-researcher.md`**（插件级 subagent，Claude Code 官方支持
    插件 `agents/` 目录，注册名带插件前缀）。它是隔离执行的系统提示，自包含；
  - 因为 fork 的子代理**看不到主对话历史**，SKILL.md 新增「执行方式」一节，明确调用时
    必须把 `work-id` / brief 路径 / `scope (A|B|C|D)` / 用户材料路径作为参数传入；
  - `background: false` 是刻意的：研究必须先完成，`sp-outline` 才能开始排页。
- **P0｜Research Pack → Evidence Ledger 确定性桥接**：
  - **新增 `scripts/research_pack_to_evidence.py`**：按固定规则（findings 按 id 排序、再
    data_points 按 id 排序 → `E01, E02, …`）编译出 `evidence-map.json`（ledger + `F/D/S→E`
    映射 + 来源索引 + 三个哈希）。同一 pack 编译两次必须完全一致；
  - **拒绝编译未通过校验的 pack**——未经验证的 pack 不是交付物，不许变成证据；
  - `slide_spec_guard.py freeze` 新增 `--research-pack` / `--research-validation` /
    `--evidence-map`，把三者哈希绑进冻结锁；`check` 会发现冻结后被改动的 research 产物。
    三个参数都是可选的，不含外部事实的 deck 不受影响。
- **P1｜校验器补 8 个漏洞**（`validate_research_pack.py`）：
  - `independence_group` 成为必填字段，交叉验证改为**按独立组计数**——两篇转载同一个报告
    不再算"两个来源"。这正是文档写"≥2 个独立来源"而代码只查 `len(refs) >= 2` 的落差；
  - `finding` 标了冲突却无对应 `conflicts` 记录（原先只查 data_point）；
  - `jsonschema` 缺失时改为 **fail-closed**（原先直接跳过 schema 校验）；
  - **D 模式变成契约**：`queries` 为空 ⇔ 所有来源必须是 `user-file`，两个方向都查；
  - **来源 tier 按 type 设上限**（个人博客不能自称 S 级）；
  - `visual_candidate` 引用不存在的 finding/data/source 由 minor 升 **major**（把不存在
    的数据喂给图表比少写来源更危险）；
  - low 置信度必须写 `notes` 说明原因——静默降级要能被看见；
  - `unresolved` 必须写 `impact`。
  - `research-pack.schema.json`：新增 `user-file` 来源类型、`independence_group`，
    `version` 升到 `0.10`。
- **文档｜消除双轨协议**：`evidence-and-citations.md` 里旧的"子代理返回 ≤20 行、
  主流程据此手写 ledger 条目"与新的 Research Pack 协议并存，等于两个交接协议。已删除
  旧协议，只保留 canonical path（pack + 校验报告 + compact summary）。
- **`sp-deck` 第 3 步加入 Research Gate**：只要 deck 依赖外部事实，freeze 前必须先有
  通过校验的 pack 与编译出的 evidence map，`evidence_refs` 引用分配的 `E<n>`。
- 测试：Research Pack 契约 13 → **20 项**，新增 `test_research_pack_to_evidence.py`
  **16 项**（含编译确定性、拒绝无效 pack、freeze 绑定与篡改检测）。

## 0.10.0 — 2026-09-14

### 新增 sp-research：把外部知识获取拆成独立一层（2026-09-14）

管线由三段扩为四段（新增一整个 skill 层，故为 minor）：

此前外部检索是隐式的：既没有独立的角色定义，也没有产出契约。结果是"查了什么、查到
多少、哪些没查到"全靠临场判断——上次真实运行中 WebFetch 被域名策略拦截、只能退到
搜索摘要，却没有留下任何结构化记录，事后无法判断哪些数据需要复核。

管线从三段扩到四段：

```text
sp-research → sp-outline → sp-deck → sp-review
 证据层        内容层        生成层      审查层
```

- **新增 `skills/sp-research/SKILL.md`**（第四个 skill，与其余三个同级）。职责边界写死：
  只做证据层，**不决定版式、不设计页面、不生成 PPTX、不改视觉风格、不撰写成段讲稿**。
  设计宗旨 *Search for evidence, not text*。
- **新增 `references/research-workflow.md`**（canonical）：
  - **A/B/C/D 四类判定**——时效性内容必须查、会被打分的内容尽量查、与外部事实无关的
    不查、用户限定范围（"只根据我上传的论文"）的一律禁查。**知道什么时候不该搜索**比
    会搜索更重要。
  - **以 Claim 而非主题为调用单位**：不要 `research("生成式 AI")`，要按待证论断逐条查。
  - **Source Tier S/A/B/C/D** 与"用途 → 最低 tier"的对应表。
  - **交叉验证**：多源量级一致才给 high；不一致标 `conflict: true` 并把置信度降到 low，
    冲突逐条记录。先怀疑口径，再怀疑数据。
  - **知识缺口发现**：把"发展迅速"这类未量化陈述识别为缺口并去补。
  - **可视化机会识别**：标出材料适合什么图形（line_chart / comparison / timeline /
    taxonomy…），这是 PPT 研究与其他研究的分界。
  - **三档预算**（simple 3/5、standard 8/12、deep 15/25）与 scenario 的映射。
  - **检索受阻必须留痕**：打不开、付费、不可得一律进 `unresolved`，不许静默降级。
- **新增 `references/research-pack.schema.json`**：Research Pack 是唯一交付物，
  findings / data_points / quotes / sources / conflicts / knowledge_gaps /
  visual_candidates / unresolved 全部规定形状，**不写自然语言小作文**。
- **新增 `scripts/validate_research_pack.py` + 13 项测试**：schema 之外的语义规则才是
  真正让 deck 站得住的部分——引用完整性、来源分级强制（high 置信度需 S/A 来源、
  只靠 D 级不能支撑结论）、交叉验证（high 置信度数字需 ≥2 独立来源；标了冲突必须降
  置信度且有对应记录）、预算上限、来源可追溯（必须有 url 或 locator）、未被引用的
  来源提示。输出纪律与 `run_gates` 一致：通过时 1 行，有阻塞时只列问题项。
- **打通 Claim → Evidence → Source 链路**（`evidence-and-citations.md` 新增一节）：
  Research Pack 是外部事实的唯一入口；页面上任何外部数字都要能追到 finding/data_point
  再到具体 source。`confidence: low` 或有冲突的条目，页面必须写成区间或加限定语。
- **接线**：`sp-outline` 新增"Research Need Analysis"前置步骤（第 3 步，先查再排页）；
  `sp-deck` 在参考文献列表里加入 Research Pack；`shared-standards.md` 补归属；
  `AGENTS.md` 架构图与归属表更新；两份 README 加管线图与 `sp-research` 说明；
  `check_plugin_release.py` 的 `REQUIRED_FILES` 增补 4 项。

## 0.9.1 — 2026-09-14

### 按第二轮实测修正成本模型：修复循环才是主导项（2026-09-14）

第二轮（v0.9.0 规则已生效）实测：**501 次请求 × 平均 23.3 万上下文 = 1.17 亿 token、
工作时长 37.2 分钟**。相比第一轮 token 只降 9%，时长反而涨 11%——说明 CD-1…CD-7
打偏了。按调用归因：**渲染-修复循环占 45%**（18 次构建 + 20 次渲染 + 36 次逐张读
渲染图 + 40 次 deck.js 定点修），QA 门禁重跑 20%，API 内联探针 10%。

- **新增 `skills/sp-deck/scripts/copy_fit_preflight.py`**：在写生成器**之前**，按字号
  与区域宽度算术判断 `title` / `claim` / `slide_copy` 能否逐字上屏，并核对每页字数
  上限（默认 80，来源行与图注不计）。第二轮 r2 返工（readback 30 blocker → 生成器
  整文件重写 → 整条修复链重来）在算术上是可预知的，这一步把它提前到"改 Spec 还很
  便宜"的时候。附 7 项测试（含金样例必须仍然通过，防止检查过严误伤）。
- **`run_gates.sh` 扩展 `--qa`**：一次运行覆盖 actual-content / rendered / quality /
  delivery（缺哪个必需输入就跳过哪个），输出仍是 1 行 + 问题项。第二轮这四个门禁
  被分开调用了 14 / 9 / 7 / 7 次；现在合成 1 次。真实产物实测：`ok — blockers 0 |
  gates: actual-content, rendered`。附 3 项测试。
- **新增 `references/pptxgenjs-helper-api.md` + `pptx-helpers.js --describe`**：
  `--describe` 从 live exports 生成 API 清单（画布、安全字体、29 个导出的名称/签名/
  元数），不会与代码漂移；文档负责"什么时候用哪个"。用来取代第二轮的 25 次内联探针。
- **`pptx-element-registry.js` 几何前移**：新增 `footerTop`（内容不得越过来源行，
  报 `content_overflow_bottom`）与 `textOverflowErrorRatio`（默认 1.2，超出即为
  `text_overflow` 错误而非 warning）。第二轮 P9 末行越界、P12 表格压到底部说明都只有
  渲染后才被发现。
- **规约收紧**：
  - `pptx-qa.md`：一轮 repair iteration 必须**一次修完所有阻断页**，禁止按页分批
    （附第二轮的实测反例）；修复循环**只看 contact sheet**，禁止逐张 Read 渲染 PNG；
    写 `deck.js` 前先跑 `copy_fit_preflight.py`。
  - `cost-discipline.md` CD-4：小结**必须被消费**——进入新阶段时入手材料只有小结 +
    本阶段要改的那一个产物，上阶段产物默认不重读（附"三份小结都写了但上下文仍涨到
    40.9 万"的反例）。
  - `cost-discipline.md` CD-2 与 `pptx-production.md`：生成器拆分为 `deck.js`（装配）
    + `pages/pNN-*.js`（每页一文件），明确**不是**"一个文件里每页一个函数"——第二
    轮正是按后者执行，规则形同虚设。同时说明拆分本身的收益边界：它几乎不省 token，
    价值在于让不同页的修复可并行发出。
  - `SKILL.md`：生产步骤串起 `copy_fit_preflight → pages/ 拆分 --→ helper API 走
    `pptxgenjs-helper-api.md`。
- `check_plugin_release.py` 的 `REQUIRED_FILES` 增加 `pptxgenjs-helper-api.md`。

## 0.9.0 — 2026-09-14

> 注：本段此前为 `## Unreleased` 累积区。插件版本已推进到 0.9.0，故按 Keep a
> Changelog 惯例改为版本标题；其中也包含更早未单独建标题的 0.7.x / 0.8.x 条目。

### CI 维护：升级 GitHub Actions 运行时（2026-09-14）

`validate.yml` 里的四个官方 action 都还跑在 Node 20 上，GitHub 已标记其弃用并强制
转到 Node 24，每次 CI 都会产生弃用注解。按"升到第一个 node24 主版本"做最小升级——
逐个读取各主版本 `action.yml` 的 `using` 字段确认，不是凭印象：

| Action | 原 | 现 |
| --- | --- | --- |
| `actions/checkout` | v4（node20） | **v5**（node24） |
| `actions/setup-python` | v5（node20） | **v6**（node24） |
| `actions/setup-node` | v4（node20） | **v5**（node24） |
| `actions/setup-dotnet` | v4（node20） | **v5**（node24） |

共 18 处引用，升级后不再有 Node.js 20 弃用注解。更大的主版本（checkout v7 /
setup-python v7 / setup-node v7 / setup-dotnet v6）留给已配置的 Dependabot
（`github-actions`，每月、分组、上限 1）跟进，避免在这次发布里引入额外破坏面。

### 会话成本约束：门禁合并、cost-discipline 条款与常驻复盘脚本（2026-09-14）

起因：一次 12 页课程报告的实测开销为 **548 次 API 请求 × 平均 23.4 万 token 常驻
上下文 = 1.29 亿 token、33.5 分钟**，而工具净执行时间合计只有 8.5 分钟。同一次会话
里 `deck.js` 被整文件重写 4 遍，上下文从 2.6 万 token 单调涨到 44.2 万 token 且全程
没有回落。这些都是工作方式问题，不是内容难度问题。

- **新增 `skills/sp-deck/scripts/run_gates.py` + `run_gates.sh`**：把 Slide Spec
  冻结检查、Art Direction 检查、composition 候选校验与 v0.8 探索证据门禁合并为
  **一次进程内运行**。通过时 stdout 恰好 1 行；有阻塞时只列 blocker/major，并由
  `--max-items` 封顶；完整明细写入 `gates-report.json`。
  由于 visual-generation 门禁内部会重跑 Art Direction 与候选校验，编排层按
  (severity, code, message, slide) 去重，同一问题不会被计数两次。
  四个 gate 脚本仍是 canonical 实现，调试单个门禁时可直接调用。
- **新增 `references/cost-discipline.md`**（canonical，已加入发布必需文件列表）：
  七条工作方式约束。
  - CD-1 合并工具调用（同轮并行发出）；
  - CD-2 禁止整文件重写（已存在文件默认定点替换）；
  - CD-3 产物写盘即弃（落盘后只按路径引用，不回读全文）；
  - CD-4 阶段 checkpoint 小结落盘（`stage-<state>-summary.md`，≤30 行；**不改变
    状态机、不新增门禁、不阻断任何步骤，也不引入任何强制清理**）；
  - CD-5 检索一律委派子代理（图片/话题/事实核查，主流程只收 ≤20 行结构化结论）；
  - CD-6 门禁一次运行；
  - CD-7 汇报纪律（中间汇报只写状态、路径、问题项、下一步）。
  `shared-standards.md` 补上归属说明；`image-sourcing.md` 与
  `evidence-and-citations.md` 分别写明图片检索与话题检索的子代理契约，并明确
  **委派不豁免图片权限门禁**；三个 SKILL.md 各加一条引用。
- **新增 `scripts/session_cost.py` 与 `commands/sp-cost-report.md`**：解析
  `<CLAUDE_CONFIG_DIR 或 ~/.claude>/projects/**/*.jsonl`，输出 token 账目、乘法模型
  估算、上下文增长曲线、分桶统计、工具耗时与体积排名，并自动提示三类病灶——整文件
  重写（CD-2）、请求/工具往返比过高（CD-1）、cache-read 占比过高。
  支持 `--list` / `--last` / `--project` / `--session` / `--json`。
  注意区分 `Write`（整文件，计入重写）与 `Edit`（定点，CD-2 期望做法）。
- **新增测试**：`tests/test_run_gates_summary.py`（7 项，钉住"通过即一行、失败只列
  问题项、Art Direction 阻塞不重复计数、`--max-items` 封顶、参数组合校验"）与
  `tests/test_session_cost.py`（9 项，钉住乘法模型与实测总量一致、分桶统计、整文件
  重写检测、Edit 不计入重写、三种输出模式）。
- 文档同步：两份 README 补 `run_gates.sh` 与 `session_cost.py` 入口；
  `check_plugin_release.py` 的 `REQUIRED_FILES` 增加 `references/cost-discipline.md`。
- 验证：`ruff check` 全绿；新增 16 项测试全部通过；
  `check_plugin_release.py --allow-untracked` 0 错误。

### 修复 `bump_version.py`：回滚失效与 npm 依赖（2026-09-14）

版本升级到 0.9.0 时暴露了两个缺陷，均已在本次修复：

- **回滚是静默空操作**：`_set_key` / `_update_plugin_entry` 直接原地修改传入的 dict
  并返回同一个对象，因此 `bump()` 里保留的「升级前快照」`package_old` 与写出的
  `package_new` 是同一个已改过的 dict。npm 失败时 `_revert_package()` 把已经升级
  过的值原样写回，却仍然打印「package.json 已回滚」——实测确实留下了
  `package.json=0.9.0` 而 `plugin.json=0.8.0` 的半升级状态。现改为对传入数据做
  深拷贝，回滚才是真的回滚。
- **不再依赖 npm**：原实现用 `npm --prefix <plugin> install --package-lock-only`
  同步 lockfile，实测 npm 仍按 **cwd** 解析（在仓库根目录运行时直接报
  `ENOENT: E:\student-ppt-create\package.json`），且让发布流程依赖可用的 npm
  安装。对一次纯粹的版本升级而言，该命令只会改写 lockfile 的两个字段，因此改为
  直接编辑 `package-lock.json` 的 `version` 与 `packages[""].version`——确定、
  离线可复现、且与 `scripts/check_installed_version.py` 读取的版本源一一对应。
- 新增 4 项回归测试：updater 不得原地修改入参、lockfile 两个字段同步、重复调用
  幂等（`unchanged`）、lockfile 缺失时返回 `missing`，以及覆盖字段与
  `check_installed_version.py` 读取字段的一致性。

### 发布源统一：本仓库 main 取代 Personal-Student 的 claude-code 分支（2026-09-14）

- **单一发布源**：`YFan945/student-ppt-create` 的 **`main` 分支**成为唯一可发布
  来源；原 `YFan945/Personal-Student` 的 `claude-code` 分支停用。
- 同步改动的 11 处引用：
  - `scripts/install_claude_plugin.ps1`：`$Repository` / `$Branch` →
    student-ppt-create / main（`-SkipMarketplaceClone` 本地直装用法不变）；
  - 两个 manifest（`marketplace.json`、`plugin.json`）的 `homepage` /
    `repository` 指向新地址；
  - `check_plugin_release.py` 的硬校验由 `tree/claude-code` 改为
    `student-ppt-create/tree/main`——**防止悄悄回退到旧仓库**；
  - `check_marketplace_release.py`：发布分支与 PR 基线均要求 `main`
    （原要求 claude-code），顺带修掉该文件既有的 ruff I001；
  - `README.md` / `README-zh.md`：安装命令、Codex 说明、相关链接；
  - `CONTRIBUTING.md`：克隆地址与工作流（从 main 建分支、PR 到 main）；
  - `AGENTS.md`：发布源条款改写（原"禁止从 main 发布"已废止）。
- 验证：插件发布检查 0 错误；分支校验函数四类输入断言正确
  （main 放行 / 功能分支拒绝 / PR base=main 放行 / claude-code 拒绝）。
- 两份 README 的顶部说明改为面向使用者的“从 main 分支下载安装”写法（不再写
  迁移公告口吻），Codex 说明同步简化；安装命令与标题引用保持一致。
- 分支清理：`improve/ppt-generation-core-v0.7` 已合并并删除（远端 + 本地）。

### 插件市场支持直接指向 GitHub（无需本地克隆）（2026-09-14）

- **官方能力**：Claude Code 的 `claude plugin marketplace add` 支持直接传
  `owner/repo@branch`，无需先 clone 到本地。本插件市场采用该方式，固定 `main`
  分支（`YFan945/student-ppt-create@main`）。
- `scripts/install_claude_plugin.ps1` 改造：
  - 新增 `-Local` 开关。**默认（无 `-Local`）走 GitHub 远程注册**，跳过克隆；
  - 远程模式下，依赖（Python wheel / npm）自动装进 Claude Code 实际加载的插件
    缓存副本（`~/.claude/plugins/cache/claude-personal/...`），由
    `Resolve-InstalledPluginRoot` 定位，而非本地 clone；
  - `-Local` 保留原本地目录注册（开发 / 离线），克隆、依赖、注册逻辑不变；
  - 删除已废弃的 `-SkipMarketplaceClone` 参数（远程注册不再需要克隆）。
- 两份 README 安装章节重写：顶部改为“推荐方式：直接添加 GitHub 市场（无需克隆）”，
  给出 `marketplace add` + `plugin install` 两条命令及微软 CDN 下载安装脚本的方式；
  本地克隆方式降为“开发或离线”次级小节，命令统一加 `-Local`。
- 验证：PowerShell 语法检查通过；plugin 与 marketplace 发布检查均 0 错误。

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
