# Context And Cost Discipline

本文件是 suite 范围内**工作方式**的 canonical 来源。`shared-standards.md` 规定
"做成什么样"，本文件规定"怎么做到"。

适用范围：`sp-research`、`sp-outline`、`sp-deck`、`sp-review` 的全部阶段。

## 约束的作用域（Batch 6.1）

本文件描述的成本纪律约束的是 **PPT 生产任务**，不是安装了本插件的每一段会话。
守卫的生效边界由 `scripts/pipeline_context.py` 统一判定，只认三个确定性信号，
不做关键词或 LLM 意图猜测（"帮我检查 PPT 插件的代码"是插件维护，不是 PPT 生产）：

- **Agent 身份**（hook 事件自带）：isolated builder / researcher / critic 天然在管线作用域内；
- **会话激活状态**：Skill（sp-research / sp-deck / sp-outline）或研究员 spawn 触发
  `research-active-<session>.json`（Stop 清理兜底 + 6h TTL，崩溃会话的残留状态自动过期）；
- **资源边界**：目标路径位于 `outputs/.pptx-work/` 之下。

由此：普通开发会话的 `ls`、重复读同一张图、读插件源码不消耗 PPT 预算；插件维护
会话可以自由读取源码与 references。唯一刻意**不做**作用域收窄的是
`production_entry_guard`——直接调用内部生产脚本在任何会话都被拒绝，因为那是绕过
状态机，不是成本问题。

## 为什么需要这份约束

一次 PPTX 任务的 token 与时间开销，主要由**会话结构**决定，而不是内容难度。实测
数据（一次 12 页课程报告，33.5 分钟）：

```text
总 token ≈ 请求数 × 平均常驻上下文 = 548 × 23.4 万 = 1.29 亿
总时间  = 请求数 × 单次预填充时间  = 548 × 3.67 秒 = 33.5 分钟
工具净执行时间合计只有 8.5 分钟 —— 其余都是把同一份上下文反复重灌
```

同一次会话中：

- 上下文从 2.6 万单调涨到 44.2 万 token，中途没有任何回落；
- `deck.js` 被整文件重写了 **4 遍**（共 13.3 万字符），四个版本同时留在历史里；
- 269 次工具调用产生了 548 次请求——每次工具调用平均消耗 2 个全上下文往返；
- 16 次联网检索的原始结果全程留驻；44 份 reference 一次性读入后全程携带。

这些都不是内容问题，而是工作方式问题。下面九条是硬约束。

## CD-1 合并工具调用

同一轮里能并行的调用必须一起发出：多个文件读取、多个 gate、多个 render、多条互不
依赖的检索。禁止"一个 shell 一条命令"的串行节奏。

每次工具调用平均产生约 2 次模型往返。把 8 次串行调用合并为 1 轮 8 个并行调用，
往返从约 16 次降到 2 次。

**可验证**：单轮内 `tool_use` 数量 > 1 的比例明显大于 0；不得连续 3 轮各只发出一个
本可并行的调用。

## CD-2 禁止整文件重写

修改任何**已存在**的文件，默认使用定点替换，不得整文件重写。只有两种情况允许整
文件写：

1. 文件尚不存在；
2. 改动幅度超过文件 70%，且已在阶段小结中记录理由。

生成器必须**按页拆成多个文件**，不是「一个文件里每页一个函数」：

```text
outputs/.pptx-work/<work-id>/
  deck.js            # 薄入口：tokens / helpers / registry / 网格常量，再依次装配各页
  pages/
    p01-cover.js     # module.exports = function (ctx) { ... }  一页一个文件
    p02-*.js
    ...
```

`deck.js` 仍保持单一入口，`run_with_pptxgenjs.js --output <x.pptx> <deck.js>` 的调用
方式不变；它只负责 require `pages/` 下的页模块并依次调用。

**为什么强调"文件"而不是"函数"**：一次 933 行的整文件重写会让多个版本同时留在会话
历史里，此后每一轮都为它们付费，而其中只有最后一个是有效的。更重要的是两点——

1. `pages/` 拆分后，**不同页的修复可以放在同一轮里并行发出**（配合 CD-1）。同一个
   文件上的多处 Edit 无法安全并行（`old_string` 会互相失效），拆成文件后可以。
2. 避免「改动面 > 70% → 触发整文件重写」这个陷阱：全局性改动（例如所有页的 claim
   都要逐字上屏）在单文件下必然越线，按页拆分后它退化成若干个独立的小改动。

要说清楚它的收益边界：**拆分本身几乎不省 token**——写入的总体积不变，页数变多反而
增加调用次数。它的价值是让上面两条成为可能，尤其是第 1 条。

**可验证**：`pages/` 下的文件数等于页数；`deck.js` 只含装配与共享定义、不含任何页面
坐标；任一次修复只命中一个 `pages/` 文件；同一路径的整文件写次数 ≤ 1（第 2 次写入
必须伴随 `slide_spec_guard.py revise --reason ...` 或阶段小结中的明确理由）。

## CD-3 产物写盘即弃

大产物（`slide-spec.yaml`、`art-direction.yaml`、`deck.js`、
`composition-candidates-*.json`、`visual-review.json`、门禁报告）一旦落盘，后续只按
**路径**引用。

- 禁止把已落盘产物的全文重新读回上下文；需要确认时读**结构性摘要**（字段名、计数、
  行数、hash），不读正文。
- 校验脚本自行从磁盘读取文件。不要让模型把文件内容"搬运"给脚本——脚本能读盘，
  模型不需要中转。
- 同一份内容只在必要位置出现一次；不要在 summary、report、notes 之间复制粘贴。

参考文档（`references/*.md`、schema、layout/reference 库）同理：**先摘后弃**。读完立刻把
用得到的规则提炼成检查清单或结论，而不是把原文段落复制到 summary、brief 或其它产物里。
同一份参考文档**在每个会话中**只读一次；需要再次确认时读差异部分，不重读整篇。
`cost_guard.py` 的作用域是会话级：seen 状态写在
`outputs/.pptx-work/.guard/seen-<session>.json`，所以上一个任务的已读记录不会让下一个任务的
首次读取被拒；去重键是 **resolved path + sha256**，不同目录的同名文档不会互相冲突，
文档内容更新后也允许重读。

**可验证**：同一产物的全文读取次数 ≤ 1；同一条规则不会同时出现在多个产物中；此后只出现
路径引用与摘要。

## CD-4 阶段 checkpoint：小结落盘

在 `planned`、`producing`、`qa` 三个边界各写一份阶段小结
`outputs/.pptx-work/<work-id>/stage-<state>-summary.md`，**不超过 30 行**，只记录四件
事：

1. 本阶段的结论；
2. 已冻结/已产出产物的路径与 SHA-256；
3. 未决问题与已知限制；
4. 下一阶段需要的输入。

**小结必须被消费，不是只被写出来。** 进入下一阶段时，入手材料只有两份：最新小结，
以及本阶段真正要改动的那一个产物。上一阶段的产物（spec 全文、art-direction 全文、
旧的候选 JSON、旧的渲染图）默认**不重读**；需要其中某项时，读它的路径与 hash，或
用脚本按需抽取，不要把正文读回上下文。

这是一条**落盘与阅读纪律**，不是流程改造：它不改变状态机、不新增门禁、不阻断任何
步骤、不要求清空或改写任何既有内容。它唯一的目的是让每个阶段有一个体积小、位置
稳定的入口。是否回看更早的记录，由当前阶段按需决定——但默认是不读。

> 反例：第二轮三份小结都写了（`stage-planned` / `stage-producing` / `stage-qa`），
> 上下文依旧从 2.9 万单调涨到 40.9 万，55% 的请求跑在 20 万 token 以上。小结写了但
> 没被当作入口，这条规则就等于没执行。

**可验证**：三个状态各存在一份小结；每份行数 ≤ 30；**进入新阶段时的第一次读取是
小结**，而不是上阶段产物的全文；同一份大产物在一次任务中不会被第二次整篇读回。

## CD-5 检索一律委派 `sp-research`

**任何外部检索——图片检索、话题资料检索、事实与数据核查、案例与竞品搜索——一律
交给 `sp-research`，由它显式 spawn `student-presentation-suite:presentation-researcher`
执行。主流程不直接发起检索，也不 spawn 名字里带 `researcher` / `critic` 的通用
teammate（`researcher-carbon-pv-wind` 与名叫 `researcher` 是同一个洞：Claude Code 会
把带 `name` 的 Agent 转成 teammate，`agent_type` 变成名字本身）。**

隔离靠显式 spawn，不靠 `context: fork`——后者在 `claude -p` 下不被 honor，skill 会被内联进
主会话，检索上下文于是计入主 context（详见 `live_prompts/FINDINGS.md` 的两次实测）。

`/sp-deck` `/sp-outline` `/sp-research` 一旦进入会话，主会话与非研究员子代理的
WebSearch/WebFetch 会被 `runtime_evidence` 拒绝。被拒后**禁止再嵌套 spawn 一层研究员**；
正确动作是回到主会话、不带 `name` 重发一次。`plan` 会自行编译 `evidence-map.json`，
不要让模型去猜 `research_pack_to_evidence.py` 的参数。

子代理契约：

- **输入**：检索意图、需要的字段清单、允许的来源范围、时间范围。
- **产出 ①（落盘）**：原始结果写入
  `outputs/.pptx-work/<work-id>/research/<topic>.json`。
- **产出 ②（回传主流程）**：固定 `RESEARCH_DONE` / `RESEARCH_BLOCKED` envelope
  （`scripts/assert_research_envelope.py` 可校验），外加 pack 路径。
  `validate_research_pack.py` 是 pack 唯一的 `ok: true`。
- **禁止**把检索结果的原始正文回灌主流程；主对话不得出现 WebSearch / WebFetch。

主流程只收 envelope 与 pack 路径；`research_pack_to_evidence.py` 再编译 `E<n>` ledger
（见 `evidence-and-citations.md`）。图片检索的额外许可要求见 `image-sourcing.md`——
委派给 `sp-research` **不豁免**图片权限门禁，同样必须先确认 `image_search_ready` /
`image_generation_ready`。

理由：检索原文体积大、留存久；委派之后，主流程在历史里只保留一小段结构化结论，
而完整原文仍然可查。

**可验证**：主流程不出现直接的外部检索调用，也不出现名字含 `researcher`/`critic` 的 teammate；
Evidence Ledger 的每一条都能对应到 `research/*.json` 中的一条记录；回传正文通过
`assert_research_envelope.py`。

## CD-6 门禁一次运行

门禁统一通过一次运行完成：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/run_gates.py" \
  --art-direction <art-direction.yaml> \
  --slide-spec <slide-spec.yaml> \
  --evidence-dir <work-id 目录> \
  --lock-file <slide-spec-lock.json>
```

- 通过时只输出 **1 行**；有阻塞时只列出 blocker/major；完整明细落在
  `gates-report.json`。
- 不再逐条调用单个 gate，也不再逐个回显每个 gate 的完整 JSON 报告。
- 单个 gate 脚本（`art_direction_check.py`、`composition_candidate_check.py`、
  `pptx_visual_generation_gate_v08.py`、`slide_spec_guard.py`）仍是 canonical 实现，
  但生产会话只通过 `run_gates.py` / `ppt_pipeline.py` 间接调用；entry guard 会拒绝
  直调，避免报告生成、manifest 绑定与 revision 链脱节。

**可验证**：一次门禁运行的 stdout ≤ 15 行（通过时恰为 1 行）；`gates-report.json`
存在且包含每个子门的计数与输入 SHA-256。

## CD-7 汇报纪律

中间步骤的汇报只写四件东西：**状态**、**路径**、**问题项**、**下一步**。

- 不得回显工具输出的完整正文；
- 不得复述文件内容或把 JSON 报告整篇粘贴；
- 需要完整信息时给出路径，让需要的一方自己去读。

**可验证**：中间汇报中不出现超过 20 行的原始工具输出粘贴。

## CD-8 按 200k 窗口工作

管线按 **200k 上下文**设计。模型提供 1M 窗口不是跳过压缩的许可证：峰值仍应
≤150k，任务总量目标 ≤25M token。

**计量口径（必须沿用）**：一个 API 请求的成本取该 `message.id` 下 **ctx 最大的一行**——
流式分片会把同一条消息写成多行，首行只报增量，终稿行才报完整 prompt。按首行统计会
少算 2.7 倍（子代理可达 4.9 倍），把全部行相加又会多算。2026-09-18 同一次会话三种口径
分别得到 48.0M / 130.0M / 175.7M，真值 **130.0M**。

- 进入新阶段只读 `stage-<state>-summary.md` 与本阶段要改的那一个产物。
- 下一动作以 `ppt_pipeline.py next --work-dir <wd> [--json]` 为准，不要 `--help`
  插件脚本、不要 grep 插件源码。`scripts/cost_guard.py` 会拦截这些考古动作
  （作用域见上：对 isolated builder 硬拒绝，对已激活的生产会话重定向到 `next`）。
- 不要把 SKILL 或 20 份 reference 在每一回合重新灌入。
- **不要自己渲染**：`calibration_preview.py` 与所有 render 属于主会话，
  `builder_guard.py` 会拒绝。2026-09-18：一个 builder 实例自行调用
  `calibration_preview.py` **38 次**，每轮重渲染又把新 PNG 读回来，把该实例从 8.7K 推到
  699K 常驻上下文，而同一实例后续每个请求都要重付这份上下文。

**可验证**：同一 reference 全文读取次数 ≤ 1；单个子代理实例峰值 ctx ≤200k
（2026-09-18 实测 699k）；`next --json` 的 `builder_instance_reuse` 不报任何实例跨轮。

## CD-9 读图：并行、一次、看图

DeepSeek Flash 视觉按约 1300×1300 缩放，**每张图封顶 1024 token**。禁止的是
**串行** Read 和 **同一 sha256 再读**，不是 Read PNG 本身。

视觉 QA 与 wireframe 选择**必须看图**：contact sheet 与全部 blocker 页 PNG 在
**同一轮并行 Read**。hash 变了（新的 render）才允许再读。`ppt_pipeline.py next`
在 `producing` 状态会列出本轮 `read_images`。

**读图前先确认图属于当前 PPTX**：`build` 会把上一版渲染证据归档到
`stale/render-<sha8>/`，因此 repair 后 `contact-sheet.png` 一定不存在，直到重新 render。
`next` 只有比对 `manifest.render.pptx_sha256` 与当前 PPTX hash 一致时才把下一步指向 `qa`；
否则指向 `render`。**旧图不得用于视觉 critique**——那是针对上一版 PPT 的判断。

**critic 只评审确定性门全绿的 deck**：`build` 打包后立即本地跑 `rendered` +
`actual-content` + `quality` 的确定性部分（evidence/timing/lock，只读 PPTX 与 spec、零
critic 成本）；不绿时 `render` 拒绝、`next` 指向免 repair 轮的 builder 改页重建（上限
`max_pre_qa_rebuilds` 次）。绕过 `next` 直接 render 或 spawn critic，是对注定返工的 deck
花冤枉钱（2026-09-17 live：一个缺失的 planned number 付完了 render + 一整轮 critic 才在
QA 暴露；2026-09-18 live：build #1 报 0 blocker，render + critic 付完之后 QA 回 48 条，
其中 16 条只靠 PPTX 与 spec 就能算出来）。

**校准的评审者必须是独立 critic，不能是主会话**：主会话写了 spec 与 art direction，
检查 hierarchy/密度/配色时会全部通过，唯独看不见自己选的视觉语言在每页重复。2026-09-18
live：主会话接受了校准图，独立 critic 在全量建完后判定"13 页套同一个带边框通栏面板"，
代价 76.4M token（该次会话 58.8%），而 3 页规模的评审只需 1.4M。

**可验证**：同一 PNG sha256 的 Read 次数 ≤ 1；含图的回合里 `Read` 次数 > 1
（并行发出），而不是每张图单独一轮；`visual-review.json` 绑定的渲染图 SHA256 与
`manifest.render.contact_sheet.sha256` 同源；`calibration/calibration-visual-review.json`
存在且早于正式 build。

## CD-10 一个 builder 实例只服务一轮
每轮 repair 都 **spawn 一个新的 builder**，不要用 SendMessage 继续上一个实例。

上下文只增不减，所以"同一个实例继续下一轮"会让每一轮的单价都更高：2026-09-18 live
的一个 builder 实例从 8.7K 涨到 **699K**，261 个请求里 **212 个在 ≥200K 上下文下发出**
（占该实例成本的 96.1%），最后一轮只有 3 个请求却花了 2.1M token。

**实测反事实（修正早期估算）**：只做实例重置、轮 1 不变，是 **98.7M → 80.9M（省 17.8M）**——
轮 1 在单实例内部自己就从 8.7K 长到 606K，重置修不了它；省下的主要是轮 2（17.4M → 3.5M）
与轮 3（4.8M → 0.9M）。轮 1 的 38 次自渲染 + 49 次图片读 + 111 次内联脚本另有约 **16M** 的
"留存成本"（内容加进上下文后被后续每个请求重付），去掉后约 67M。
**最大的杠杆是"校准阶段就挡掉全 deck 返工"（CD-9 的校准一条），而不是重置实例。**

上一轮的结论不需要留在上下文里：把它以 **报告路径 + 本轮 blocker 清单** 传进去，
builder 自己会读。`next --json` 的 `builder_instance_reuse` 会在检出跨轮实例时报出
实例 id 与它覆盖的轮次。

**可验证**：`builder_instance_reuse` 缺失；各 builder 实例的 `peak_ctx` ≤200k，
`total` ≤8M。

## CD-11 时间预算 = 回合数 × 往返延迟：并行分片与合并调用

**墙钟与门无关。** 实测 2026-09-18 全会话：5 道 QA 门 4 次共 17.3 秒、18 次 build 33.1 秒、
12 次 plan 19.9 秒、4 次 render 58.2 秒、4 次 repair 4.3 秒、17 次 gates orchestrator 17.5 秒
——**管道脚本合计 150 秒 = 147 分钟 pipeline 的 1.7%**。其余 100% 是 **519 个模型回合**
（中位 10 秒、均值 18.9 秒、p90 31 秒）。

**20 分钟的预算 = 60~116 个回合**（按均值/中位延迟）；0.14.2 用了 ~490 个。

**批处理在这个栈上可用，已实测。** 早期测量曾得出"单回合永远只有 1 个调用"，那是假象——
Claude Code 把一条消息的 content blocks 拆成多行，逐行数就永远得 1。按 `tool_use.id`
对同一 message 取并集后，全部 transcript 的真相是：**单回合最多 8 个调用，19.8% 的回合
带 ≥2 个，整体 1.21 个/回合**。所以"一个调用一个回合"是**任务形态**造成的，不是能力上限：

| 实例 | 回合 | 调用/回合 | 批处理回合占比 |
| --- | ---: | ---: | ---: |
| 0.13.4 某 builder 实例 | 115 | **1.50** | **51.3%** |
| 0.14.2 builder | 261 | **1.08** | 12.6% |
| 0.14.2 主会话 | 168 | 0.95 | 3.0% |

0.14.2 的 builder 之所以低，是它 164 次 shell 调用里有 111 次要"改一页→验一页"，
**依赖链上没有可并行的对象**。所以杠杆是两件事：

1. **把工作变独立**：多页写入同一回合、多张图读取同一回合、
   `page_brief.py --json`（不带 `--slide`）一次拿全 deck 的契约。三个 agent 定义里都写了这条。
2. **并行分片**：页面拆给多个隔离 builder，构建阶段墙钟 ÷N（CD-11 下一条）。

**注意**：这条端点收到的是**精简版 system prompt**（实测 5.9K 字符 / 10 段），
其中**不含** CLI 自带的 `# Using your tools`（"Maximize use of parallel tool calls"）。
所以并行调用必须由**插件自己的指令面**要求——agent 定义确实会进 prompt
（实测 22 份快照含其正文），这里写的每一句都是到达模型的。

**并行分片**：`next --json` 在 `initial` / `repair` 给出 `builder_shards` 时，在**同一条消息里
spawn 全部 shard**（各自不传 `name`、只做自己的 slide ids、只写自己的
`speaker-notes-shard-<N>.md`）。分片由管线按页号轮转计算，**天然互斥且页数均衡**；
`build` 把碎片拼成 `speaker-notes.md`。少于 `parallel_builder_min_pages`（默认 4）页不拆。
**没有页号的 deck 级 blocker 不分片**——那说明整 deck 在范围内。

**不要用并行换质量**：分片只改变谁在何时写哪个文件，不改判定。评审、QA、delivery 全部照旧。

**可验证**：`session_cost.py` 的 `tool_calls_per_turn`、`batched_turn_share` 与
`largest_batch`（`largest_batch` ≥2 证明批处理可用）；`turns` 与 `turns_under_20min`
对照时间目标；单轮 builder `turns` ≤ 页数 × 8。

## 条款索引

| 条款 | 针对的实测问题 |
| --- | --- |
| CD-1 | 269 次工具调用产生 548 次请求（2.04 程/调用） |
| CD-2 | `deck.js` 被整文件重写 4 遍，多个版本同时留在历史里 |
| CD-3 | 16 次检索原文（64 KB）与 44 份 reference 一次性读入后全程留驻 |
| CD-4 | 上下文从 2.6 万单调涨到 44.2 万 token，全程无回落 |
| CD-5 | 检索原文体积大、留存久；委派后主流程只留结构化结论 |
| CD-6 | 三个门禁各自打印一份完整 JSON 报告 |
| CD-7 | 中间步骤回显完整工具输出 |
| CD-8 | 1M 窗口被当成可以不压缩；峰值涨到 45 万 |
| CD-9 | 禁止读图导致模型不看 wireframe/渲染；或串行读同一 hash |
| CD-10 | 一个 builder 实例扛 3 轮，常驻 ctx 涨到 699k，占该次会话 75.8% 的成本 |
| CD-11 | 147 分钟里门只占 150 秒（1.7%），其余全是模型回合的往返；批处理可用（实测单回合最多 8 个调用），瓶颈是任务形态造成的依赖链 |

## 与其它 references 的关系

| 关注点 | 归属 |
| --- | --- |
| 做成什么样（版式、密度、语言） | `shared-standards.md` |
| 怎么做到（本文件） | `cost-discipline.md` |
| 检索内容的证据要求 | `evidence-and-citations.md` |
| 图片的能力与许可 | `image-sourcing.md` / `image-strategy.md` |
| 门禁的判定逻辑 | 各 gate 脚本自身 |
