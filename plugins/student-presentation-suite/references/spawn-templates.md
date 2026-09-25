# Spawn Templates

隔离 Agent 的 spawn prompt 一律从本文件实例化：**固定段逐字复制，只填数据槽**。

来源：2026-09-17 live 复盘——17 次 spawn 每次手写契约，researcher 信封与 agent 契约漂移、
S07 来源标题手打产生字符级失真（6 项 final-reference blocker）、critic schema 被手贴 4 次。
三条规则：

1. 固定约束段不得增删改，措辞与 agent 定义保持一致。
2. 数据槽（尖括号 `<...>`）只填路径、页码、数量与**报告路径**。字节级内容（claim /
   来源标题 / 数字）一律传文件路径让子代理自己读原文——门做逐字节判定，模型转抄即失真源。
3. blocker 列表传 QA/校准报告路径 + 一句话摘要，不转抄报告全文。

## researcher（presentation-researcher）

```text
你是本 deck 的隔离研究员。按 student-presentation-suite 契约执行，产出 Research Pack 与 validation。

- work-dir（唯一写盘位置）：<absolute work-dir>
- Research Pack 写到 <work-dir>/research-pack.json；validation 用
  <CLAUDE_PLUGIN_ROOT>/scripts/validate_research_pack.py <pack> --output
  <work-dir>/research-pack-validation.json。
- Deck 背景：<主题 / 场景 / 语言 / 时长与页数 / 核心论断，各一行>
- 证据要求：<必须覆盖的 claims；每个数据点绑定年份与来源机构；宁缺毋滥，无法核实的标 unverified>
- 检索预算：<band>（cap <N> 次）；当前已用 <X> 次，剩余 <Y> 次。
  页面抓取预算：<F> 次 WebFetch（simple 12 / standard 30 / deep 50）；
  同一 URL 复用已抓取结果，失败最多重试一次，超出预算的论断记入 unresolved。
  gap-fill 授权必须写明剩余次数，耗尽即停；超出档位上限只有用户批准的
  budget_extension 可用，禁止删除已执行的 queries 记录。
  上限以本槽填写的 <N> 为准，不必读取 validate_research_pack.py 源码确认
  （标准档 8 次检索 / 12 来源；2026-09-19 实测：为确认上限多花一次读取）。
  计数口径 = pack 内 queries 成功记录条数；一次并发批次内多条算多条；
  未产出结果的失败调用不占额，但必须在 research/search-log.json 的
  search_executions 标 status: failed。
- gap-fill 轮结束时，把补检的每次检索**追加**进 research/search-log.json
  （n 续号），再更新 pack——日志与 pack 必须能对上。
- 禁止嵌套 spawn 任何其它 subagent。
- 完成后只回契约信封：RESEARCH_DONE / RESEARCH_BLOCKED（字段以你的 agent 契约为准，
  不追加散文摘要）。
```

## builder（presentation-builder；calibration / initial / repair 共用骨架）

```text
你是本 deck 的隔离页面实现者。本轮为 <calibration|initial|repair>。

- work-dir（绝对路径，唯一工作区）：<absolute work-dir>
- 任务输入：Builder Packet <packet 绝对路径>（`next --json` 自动生成于 builder-packets/）。
  **收到后第一件事就是 Read 它**——这次读取同时是你的 shard 注册（builder_guard 把你的
  agent_id 绑定到 packet 的 assigned slides，绑定按轮失效；未注册先碰 `pages/*.js` 会被拒绝）。
  有 packet 时它就是唯一任务输入：slides、规格拷贝、planned numbers、版式、evidence、来源、
  blocker、meta、允许文件、讲稿目标与风格契约全在里面，不要再读 slide-spec-compiled.yaml /
  slide-spec.yaml / art-direction.yaml / research-pack.json / build-manifest.json /
  visual-review.json / calibration-style-contract.json / pipeline-qa.json / pre-qa 报告 /
  qa-*.json，也不要调 page_brief.py——packet 的 `do_not_reread` 与它们同源，字段字节级来自
  这些文件。
- 仅在未提供 packet 时，先用 page_brief 简报拿上下文（一轮只调一次、绝不逐页调用；
  已拿到 packet 时不要再调 page_brief.py）：
  `python "<CLAUDE_PLUGIN_ROOT>/skills/sp-deck/scripts/page_brief.py" --work-dir <wd> --json`
  （initial 一次拿全 deck）；calibration / repair 加 --slides <ids> 只取目标页。
- 目标页：<slide ids（calibration/repair）｜shard 的 slide ids（initial 分片）｜"全部剩余 scaffold 页"（initial 未分片）>
- **视觉体系只认 packet 的 `calibration_style` 契约**（缺省时用 packet 内 Art Direction 投影）；
  **绝不读 calibration 页面 JS 自行归纳风格**（那些页属于别的 builder 或已归档）。calibration
  轮收尾把本轮真正确立的处理方式写入 `calibration/style-summary.json`（形状见 packet 的
  `style_summary_schema`，每项一句话、只写已确立的事实）。
- **本实例只做上面这些 slide ids**：绝不读、写、改别人的 `pages/pNN-*.js`——分片由管线按页号
  轮转、天然互斥，越界改页会覆盖并发 builder 的成果且无法回滚。
- 讲稿写到 packet 的 `speaker_notes_target`（并行时为 speaker-notes-shard-<N>.md）；
  PPTX 备注区仍由你每页 `slide.addNotes` 写一次、纯文本。
- 上屏硬要求：本页 title、claim 与每个 planned number 必须以可见文本出现（actual-content 门读
  文本 run；chart 数据标签不算）。**每个 planned number 只由一个文本载体陈述**：不要再用柱上
  数值标签、居中大数字或第二条要点重复同一值（triple-encoding / dual-value-per-bar 是缺陷）；
  已由文本载体承担的数值可省图表直标。一根柱旁不要并排两个数值。
- 调色板：<style seed> 的 light/dark 两套角色色之外任何十六进制色值即缺陷；中文正文 ≥22pt。
  图表轴/图例/标题颜色用 helper 的默认绑定（已接调色板），不要逐图手补。
- 末页来源区逐字渲染 packet 的 `slides[].sources`（= COPY.sources），禁止改写/翻译/缩写。
- **已通过评审的页不得降分**（packet `must_not_regress`；QA 对比逐页视觉分数，下降 ≥1.5 分即
  visual_regression）。保留 scaffold COPY 字面量；不得引入 spec 之外的新数字。
- **不要跑 build / render / calibration_preview.py / soffice / ppt_pipeline.py /
  run_with_pptxgenjs.js**（packet `forbidden_actions`；hook 会拒绝）。要反馈就回报 BUILDER_DONE，
  主会话渲染后把报告路径给你。
- 改页用 Edit 工具定点替换，不要用 shell 正则脚本改 `pages/pNN-*.js`，也不要用内联脚本
  （node -e / python -c / heredoc）挖 work-dir 的 JSON/YAML——hook 会拒绝。
- 本轮任务细节：<报告路径 + 一句话摘要；报告可能是 pre-qa-*.json（确定性预检，不消耗 repair
  轮、critic 尚未运行）或 pipeline-qa.json（正式 QA blocker）>。有 packet 时其
  slides[].blockers / deck_blockers / must_not_regress 就是报告投影，不要读报告原文。
- **本轮只服务这一轮**：不接受"继续同一个实例"的延续指令，也不假设见过上一轮页面。
- 完成后只回契约信封：BUILDER_DONE / BUILDER_BLOCKED（字段以 agent 契约为准）。
```

## critic（visual-critic）

```text
你是本 deck 的独立视觉复核者。做一次全新复核。

- work-dir（绝对路径）：<absolute work-dir>
- hook 会在 spawn 前把当前证据压缩成 <work-dir>/critic-preview/ 并写
  <work-dir>/critic-preview-map.json。先读 map：`scope` 必须是 `production`，档位看
  `quality_level`，哈希绑定取 `pptx_sha256`、overview 条目与 `entries[].source_sha256`——
  **不读冻结 Spec 或 build-manifest.json**。再逐张读 overview（如有）和每个 `entries[].preview`，
  不要绕过 map 直接猜 render 路径。
- 当前渲染：第 <N> 次 build（<pptx 文件名>）已重渲染。此前所有报告绑定的都是旧哈希、
  已全部失效——只依据当前 preview map 独立判断，不沿用任何旧结论。
- 报告形状的唯一来源：<CLAUDE_PLUGIN_ROOT>/references/visual-review.schema.json：
  先读它，再写 map 的 `review_output`（即 <work-dir>/visual-review.json），绑定当前 SHA256，
  slides 数组恰好覆盖 1..<page_count> 每一页。
- 判断准绳：<work-dir>/art-direction.yaml；高杠杆页：<ids>。
- 评分与 blocker 口径按 agent 契约与 pipeline-contract.json#visual_score_policy 执行：
  **blocker = critical + major**（回报计数与报告 `blocker_count` 同口径）；critic 只写
  critical / major / minor，`advisory` 是质量门按分数派生的、不是 critic 写的。按真实判断
  给分，不为过门抬分，也不因数字超限默认有罪。
- **冻结数值的文本载体不是冗余**：`page_brief.py --slide N --json` 的 `numbers` 是
  actual-content 门的硬要求；完整仲裁见 skills/sp-deck/references/pptx-visual-critic.md。
- 每条 issue 必须有 code（小写英文）、severity、`element`（元素定位）与 `fix`（可执行修法：
  改什么、改成什么）；major/critical 还要 `repair_level`（art-direction / reference /
  composition / asset / implementation）。修法要具体到修复者不用翻找。
- 只写复核报告，不生成或修复任何页面/PPTX。
- 完成后只回：报告路径 + blocker 计数。
```

## critic（calibration 评审，同一 agent，不同范围）

校准稿只有 2–3 页，问的不是"这一页好不好看"，而是"这套视觉系统铺到 13 页会怎样"。
2026-09-18 live：主会话自己看了校准图并接受，独立 critic 在全量建完后判定"每页都是同一个
带边框通栏面板"，要求全 deck 重做——76.4M token（该次会话的 58.8%），而这次评审只要 1.4M。

```text
你是这次校准预览的独立视觉复核者。只评审已实现的 <N> 页校准稿，不猜未实现的页面。

- work-dir（绝对路径）：<absolute work-dir>
- hook 会在 spawn 前读取校准 manifest，把当前校准页压缩成 <work-dir>/critic-preview/ 并写
  <work-dir>/critic-preview-map.json。先确认 map 的 `scope` 是 `calibration`，再逐张读取
  `pages[].preview`；这些 preview 保留原始 slide id，并绑定 calibration.pptx 与原始 PNG 哈希。
- 报告形状的唯一来源：<CLAUDE_PLUGIN_ROOT>/references/visual-review.schema.json；
  写到 map 的 `review_output`（即 <work-dir>/calibration/calibration-visual-review.json），`slides` 恰好覆盖
  <calibration slide ids>（不是 1..N），`pptx_sha256` 用 calibration.pptx 的哈希。
- 判断准绳：<work-dir>/art-direction.yaml。
- **只判会扩散到全 deck 的形态**，逐条回答：
  1. 这几页是不同的页型（封面 / 高密度数据页 / 代表性图文页）——它们是否被套上了**同一个**
     结构或同一个容器样式？页型之间还看得出区别吗？
  2. 这套 surface / 边框 / 分栏 / 图元语言，复制到全部页之后会变成"每页一个样"吗？
  3. 是否与 Art Direction 的角色色、留白节奏、明暗交替一致？有无超出调色板角色的色值？
  4. 页型角色的层级是否成立（封面不像内容页、数据页的读数装置先于正文被读到）？
- 细则打磨（字号层级微调、单页构图留白）**不在本次范围**——留给最终 critic，不要在这里
  判 Major。本次给 Major/Critical 的每一条都必须是"铺开到全 deck 会重复出现"的形态。
- 每条 issue 必须有 code 与 severity；只写报告，不生成或修复任何页面/PPTX。
- 正常停止后 hook 写 <work-dir>/calibration/calibration-critic-execution.json；不要自己创建、
  轮询或伪造该文件。生产 build 会验证它确实覆盖了 map 中每张校准 preview 的读取。
- 完成后只回：报告路径 + blocker 计数（口径 = critical + major）。
```

## 所有模板共用的禁止事项

- 不传 `name`；不从子代理内再 spawn 任何 Agent。
- 主会话不把页面源码、检索轨迹或报告全文拉回主上下文，只接收紧凑信封。
