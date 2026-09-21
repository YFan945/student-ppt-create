---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.15.6
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；编辑请求由 `sp-review` 诊断后以 `outputs/<topic>-slide-spec.yaml` 交接到本 skill。

## Dispatch

每一生产回合先问管线，不要 grep 插件源码、不要 spawn 名叫 `researcher` / `researcher-*` 的 teammate、不要直接跑 `run_with_pptxgenjs.js`、不要重新注入本 skill。

三类隔离 Agent 均由**主会话直接 spawn，且不要传 `name`**：

- `student-presentation-suite:presentation-researcher`：外部事实与引用；
- `student-presentation-suite:presentation-builder`：create/rebuild 的视觉校准、逐页 JS 首次实现与 targeted repair；
- `student-presentation-suite:visual-critic`：独立视觉复核。

`presentation-researcher` / `visual-critic` 带名字会变成 teammate，使 `*-execution.json` 凭据失效；研究员还可能嵌套 spawn。该错误由 `runtime_evidence` 硬拒绝。`presentation-builder` 虽不产生 QA receipt，也必须保持独立 context，避免逐页 JS 和 repair diff 回灌主会话。

**Spawn prompt 一律从 `../../references/spawn-templates.md` 实例化**（固定段逐字复制、只填数据槽），禁止自由撰写。字节级内容（claim / 来源标题 / 数字）传文件路径让子代理自己读原文——QA 门做逐字节判定，模型转抄即失真源（2026-09-17 live：S07 标题手打失真 ×6、researcher 信封漂移、critic schema 手贴 4 次）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" next --work-dir <wd> --json
```

只读 `next` 列出的路径。**主会话不得直接实现、读取或修复 `pages/pNN-*.js`**：`plan` scaffold 后先让 `presentation-builder` 做高杠杆页 calibration，再由同一隔离 builder 补齐其余页面；主会话只接收 `BUILDER_DONE` / `BUILDER_BLOCKED` 紧凑信封，不接收页面源码。

视觉 QA **必须看图**（CD-9）：正式 deck 概览读 `contact-sheet-thumb.jpg`，全尺寸页 PNG 只在修具体 blocker 页时读、且同一轮并行。**主会话全尺寸大图（>150KB）预算是 6 张**。Calibration 是这个预算的高价值用法：一次只读 2–3 张真实高杠杆页预览。逐页最终复核属于隔离的 visual-critic，它的上下文不进本会话。同一 sha256 不得再读；同一条 `ls`/`cat`/`find` 类只读巡检命令一个会话最多 2 次，第 3 次会被 `cost_guard` 拒绝。

**会话分段（token 主杠杆）**：总 token ≈ (每请求新增上下文/2) × 请求数²。研究、视觉校准后的逐页生成和评审都在隔离子代理中完成；主会话只保留 spec/状态/校准图/紧凑信封/QA blocker。`next --json` 在 build+render 完成后仍会给出 `session_segment: boundary-recommended`，此时开新会话可以进一步避免 review/repair 继承前半段历史。

**后台代理与回合结束**：隔离 Agent 异步运行；回合结束时若仍有未返回的 pipeline 子代理，收尾必须固定提示用户「页面代理后台运行中，关闭会话将丢失该轮工作」。会话中断后重开时先跑 `next --json`——`planned` 状态会依据 `calibration/` 的现有证据（manifest 与 render）自动指回正确的校准步骤，不会把带 blocker 的页面直接导向全量 build。

`next --json` 的 `contract` 是按阶段选择的紧凑执行契约，含当前 policy hash、QA 顺序和 repair budget；不再预读整套 references。仅在具体内容/设计问题无法由当前契约解决时，按需读对应 reference。intake 规则仍以 `../../references/presentation-intake.md` 为准，机器规则以 `../../references/pipeline-contract.json` 为准。

**常规推进用 `advance --json`，`next --json` 退为调试/巡检入口**（v0.15 Batch 3，Batch 3.1 收紧）：`advance` 自动串行执行所有确定性步骤（校准预览、build（calibration green 且无 scaffold stub 时首次 build；repair/pre-QA 修复使 generator fingerprint 变化后的 rebuild）、render、repair 登记、complete），只在真正需要智能的边界停下并返回 `needs_agent`（agent + builder_mode + packet 路径，dispatch 字段就是 `next` 的完整应答）/ `needs_user` / `complete`，附带 `actions` 列表记录本轮执行了哪些确定性步骤。它不 spawn 任何子代理，也永远不会替你判断视觉质量——boundary 到了就停。`pending_repair` / pre-QA 失败状态下，generator fingerprint 未变化时 advance 指向 repair builder（deck 即将改变，先评审旧图没有意义），fingerprint 已变化时 advance 直接自动 rebuild。每次 advance 调用记入 manifest history，`pipeline_report.py` 汇总 collapsed round-trips。edit_ooxml 模式的首次 build 前必须由主会话先应用编辑意图，advance 会以 `needs_user` 停下。

**回执门与 doctor（2026-09-19 实测）**：`plan`/`qa` 因 `missing successful isolated
*-execution.json` 拒绝时，**不要**反向排查 hook 机制（一次实测为此烧掉 52 个请求、6.5M
输入 token，占全程一半）。回执只由 `runtime_evidence.py` 在 SubagentStop 落盘，模型写入
会被守卫拒绝。先跑 `doctor --work-dir <wd> --json`：若报告 receipts
suspected-unavailable（本机 ZCode 默认如此——SubagentStart/SubagentStop 不达插件 hook；
doctor 只给出疑似判定，可用一次零检索研究员运行确认），`plan` 加
`--receipt-policy allow-missing` 走降级路径。**策略是 work-id 状态**：之后 qa/complete
自动继承，`next_command` 会自带该参数，无需 Agent 记忆补参（manifest 记录
`spawn_verified: false` 与 `receipt_policy: allow-missing`，QA 报告与交付摘要保留标记）。
已存在但为空、损坏或绑定不符的回执是硬拒绝——只有真正不存在的回执文件才能降级。
visual-critic 无法 spawn（provider 不可用）时的降级：只读 `contact-sheet-thumb.jpg` +
最多 3 张疑似 blocker 页全尺寸图，禁止逐页读全尺寸大图（2026-09-19 实测 13 张大图把
上下文推到 compaction，一次性多花约 170K fresh tokens）。

**管线受阻 ≠ 绕过管线（P0 硬规则，2026-09-19 实测教训）**：正式管线在任何一步被拒时，
**禁止**主会话自行编写 PPT 生成器（python-pptx / pptxgenjs 脚本、或任何 off-pipeline
路径）替代生产。一次真实执行在 plan 被回执门拒绝后，误诊"pptxgenjs 不可用"（实际
`run_with_pptxgenjs.js` 会回退到插件自带 node_modules），手写了 472 行独立生成器——
Builder Packet、calibration、QA gate、complete 全部没有运行，交付物失去全部管线保证。
正确动作按序是降级阶梯，每级都有机器标记：

1. `doctor --work-dir <wd> --json` —— 一次性判定：回执可产生性、build 后端
   （node/pptxgenjs）、渲染器、work-dir 可写性。
2. 回执不可产生 → `plan`/`qa` 加 `--receipt-policy allow-missing` 走完**整条管线**
   （manifest 记录 `spawn_verified: false`、`receipt_policy: allow-missing`，QA 报告与
   complete 的 stage summary 保留降级标记，交付时必须向用户说明）。
3. build 后端缺失 → `npm --prefix <plugin-root> ci` 修复，**不**换生成器。
4. 仅当上述全部不可行（环境完全不可修复），才把 work-id 置为 `incomplete` 并向用户
   说明阻塞点——宁可明确失败，不产生无验收证据的成品。

失败分类同样固定：**环境能力缺失**（回执、后端、渲染器）→ doctor + 降级阶梯，不重跑
研究、不重派研究员、不再 spawn "触发用" 复检代理；**研究内容问题**（数据缺失、来源
不可靠）→ 才走 SendMessage gap-fill 或重派研究员。


Helper API 用 `node scripts/pptx-helpers.js --describe`；逐页实现时由 `presentation-builder` 自己调用该描述接口，不把 helper 源码拉回主会话。正式与 calibration 的 raster render 都由插件内 `pptx_tool.py` 通过受控 pipeline/helper 调用，不依赖项目 PATH 中的同名脚本。

## State gate

每个 work-id 的状态表达为 `intake_pending → intake_confirmed → planned → producing → qa → complete`；异常终态为 `incomplete` / `blocked`。`workflow_guard.py` 只负责 intake 的 `init / confirm`。Production Summary 未确认、摘要 hash 已变化或状态不是 `intake_confirmed` 时，`ppt_pipeline.py plan` 会直接拒绝。`plan` 成功后，`build-manifest.json` 成为生产阶段权威状态，pipeline 自动镜像同 work-id 的 workflow-state.json；不得再手工调用 `workflow_guard.py transition` 推进生产状态。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" confirm --summary-file <summary> --work-id <work-id>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" status --work-dir <wd>
```

生产段 `planned → producing → qa → complete`；`qa → producing` 只能经 `ppt_pipeline.py repair`，repair 上限由 `pipeline-contract.json` 强制。**Calibration preview 不改变生产状态，也不写 `manifest.build/render`**；它只是正式 build 前的临时视觉证据。正式重复 build 仍必须先 repair 且 generator hash 必须变化；相同 PPTX/visual-review/previews 的 QA 自动复用上次结果。

## Workflow

1. **Intake**：按 `presentation-intake.md` 收集需求，完整 Production Summary 经用户明确确认后调用 `workflow_guard.py confirm --summary-file <summary> --work-id <work-id>`。intake 询问必须按该文件的 Round 结构**批量**发出（每轮一次 `AskUserQuestion`、最多 4 问），禁止拆成单问多次调用（2026-09-17 实测：3 次单问违反 Round 契约，多耗两轮交互）。
2. **Mode**：按 source deck/edit intent 唯一确定 `create` / `edit_ooxml` / `rebuild_from_source`。
3. **Research Gate + Compile**：依赖外部事实时先跑 `sp-research` 产生 `research-pack.json` 与 validation。主会话 spawn `student-presentation-suite:presentation-researcher` **不传 `name`、禁止再套一层**。`ppt_pipeline.py plan` 自己编译 evidence map 与带 E ids 的 spec，不让模型猜编译 CLI。
4. **Art Direction**：**先读 `references/design-tokens.json`，再呈现具体样式选项或做任何颜色/视觉承诺**——选项只能引用 token 名；6 角色位之外的配色语义（如"暖色琥珀当第二主角"）禁止承诺（2026-09-17 live：承诺"光伏配琥珀"后才发现调色板契约禁色族外颜色，被迫中途换风格并重绑确认哈希）。visual style 只作为 seed，形成 `art-direction.yaml` 与 3–5 个 high-leverage slides。
5. **Plan**：`<wd>` 必须为项目 `outputs/.pptx-work/<work-id>`；`edit_ooxml` 自动解包到 `ooxml/`，不生成 JS；`rebuild_from_source` 须先写 `source-analysis.md`。`ppt_pipeline.py plan --work-dir <wd> --slide-spec <compiled> --validation-report <报告> --art-direction <ad>`。程序验证 Production Summary、copy-fit、freeze Slide Spec、scaffold `deck.js` + `pages/pNN-*.js` + `composition/` 并建立 `build-manifest.json`。仍处于 `planned` 时确需更新 spec / research chain，直接给同一命令加 `--force --reason <具体原因>`；管线会调用 revision、保留锁的 revision/parent 链，不要 reset intake、移动旧锁或直调 `slide_spec_guard.py`。`--validation-report` 若描述的不是将被 freeze 的那个 spec（研究型 deck 会是 plan 自己编译出的 `slide-spec-compiled.yaml`），plan 会**自动对该 spec 重新生成报告**并在 manifest 记 `spec_report_regenerated`；不要为此手工跑第二遍 plan，也不要自己猜 compiled 文件的哈希。
6. **Reference + Composition**：high-leverage 页保存 reference selection、2–3 个 silhouette candidates 与 wireframe 选择证据；普通页保留明确 composition intent。
7. **Calibration Build**：仅 `create` / `rebuild_from_source`。校准样本按 **archetype coverage** 选取（`calibration_archetypes.py` 从 spec 的 kind / layout_family / layout 关键词确定性分类，覆盖最多不同视觉语法的 2–3 张；high-leverage 页优先认领组席位；packet 已含默认集，**默认集就是答案，除非你能说出一个它没覆盖到的视觉语法**——"这几页更重要"不是换的理由。要覆盖就跑 `builder_packet.py --mode calibration --slides <ids>` 读它的 `coverage` 块：覆盖的 archetype **数量不少于**默认集才算可以换（换掉一种语法换另一种可以，少一种不行）。**这条判定是硬门禁**：显式 `--slides` 覆盖若丢掉一种语法，脚本会在写出 packet **之前**拒绝（`SystemExit`，packet 不落盘——落盘的 packet 就是 builder 被要求信任的任务输入）；确有理由时要显式 `--force`，代价照样记进 `coverage` 块。**默认集永远不被拒**（它构造上就是最宽的样本）；默认集的**子集**（更短的样本）只记录不拒绝。主会话 spawn `student-presentation-suite:presentation-builder`，不传 `name`，传绝对 work-dir、`mode=calibration` 和目标 slide ids。Builder **只实现这些页面**，其余页面保持 scaffold，主流程此时故意不能正式 build。
8. **Calibration Preview**：收到 `BUILDER_DONE(mode=calibration)` 后，由主会话运行确定性 helper，而不是让 builder 自己 build：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/calibration_preview.py" \
  --work-dir <wd> --slides <id1> <id2> <id3> --json
```

helper 只把这些已实现页面组装成临时 `calibration/calibration.pptx`，渲染到 `calibration/render/`，并写绑定页面/PPTX/PNG SHA256 的 `calibration-manifest.json`；**不触碰生产 manifest/state**。

**校准必须由独立 critic 评审，不能由主会话自己看图**。主会话是这份 spec 与 art direction 的作者，检查 hierarchy/密度/配色时会全部通过，唯独看不见自己选的视觉语言是否在每一页重复。2026-09-18 live 就是这样：主会话接受了 3 张校准图，独立 critic 随后判定"13 页套同一个带边框通栏面板"要求全 deck 重做，代价 76.4M token（该次会话的 58.8%），而 3 页规模的评审只需 1.4M。

`next --json` 这时给出 critic 的 spawn 参数与 `calibration/calibration-visual-review.json` 的写入路径：spawn `student-presentation-suite:visual-critic`（不传 `name`）。runtime hook 会从当前 `calibration-manifest.json` 生成 `critic-preview-map.json`（`scope=calibration`），critic 只读 map 列出的压缩预览、只写 map 指定的 `review_output`；正常停止后 hook 写 `calibration/calibration-critic-execution.json`。生产 build 会同时校验报告的 PPTX/PNG 绑定和该 receipt 对所有校准预览的读取覆盖；`receipt_policy=allow-missing` 只允许 receipt **缺席**时降级，已经存在但损坏或不匹配仍然硬失败。critic **只判会扩散到全 deck 的形态**——不同页型是否套用了同一结构、Art Direction 是否一致、页型之间是否还看得出区别；细则打磨留给最终 critic。评审带 Major/Critical 就 spawn builder `mode=calibration` 只修这些页并重跑 helper；**评审全绿之前正式 `build` 会被机械拒绝**。不要先生成剩余 10–20 页再发现基础风格错误。

显式改校准样本时，`builder_packet.py --mode calibration --slides <ids>` 会把 packet 与 `builder-active-round.json` **原子地一起更新**；随后 `next` / `advance` 复用这组 slide ids，不会重新落回默认校准集。不要手改 packet 或只改其中一个文件。
9. **Full Isolated Page Build**：Calibration 视觉系统经独立评审可接受后，再 spawn `presentation-builder`，传绝对 work-dir 与 `mode=initial`。Builder 保留已校准页面，按它们已建立的 typography/spacing/surface/image language 实现**所有剩余 scaffold 页面**。主会话不得打开逐页源码复核，只接受紧凑信封。

   **页数够多时并行分片（`next --json` 会给出 `builder_shards`）**：墙钟 = 回合数 × 每回合往返延迟，而全套门实测只花 150 秒（占全程 1.7%）——**唯一不碰门、又能压缩墙钟的杠杆就是让页面工作并发**。给出 `builder_shards` 时，在**同一条消息里 spawn 全部 shard**（每个都不传 `name`），每个只做自己的 slide ids、只写自己的 `speaker-notes-shard-<N>.md`，绝不碰别人的页面；`build` 会按页号合并，并让较新的 repair 分片替换同页旧稿，不会因重分片产生重复讲稿。分片由管线按页号轮转计算，天然互斥且页数均衡。少于 `parallel_builder_min_pages`（默认 4）页时不拆——启动与读取开销不划算。
10. **Exploration Gates + Production Build**：运行一次 gates orchestrator，只把 blocker 回到主上下文，完整结果写盘：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/run_gates.py" \
  --art-direction <ad> --slide-spec <spec> --evidence-dir <wd> --lock-file <wd>/slide-spec-lock.json
```

Windows 下优先用这个 python 形式；`run_gates.sh` 只是定位解释器的包装，在 `sh` 解析到 WSL 的机器上打不开 `C:/...` 路径（2026-09-17 live：exit 127，白跑一轮）。`edit_ooxml` 直接走原 OOXML 路径；create/rebuild 只有在所有页面 scaffold marker 都删除后才调用 `ppt_pipeline.py build --work-dir <wd> --entry <deck.js>`。任何未实现页仍会被正式 build 机械拒绝。Calibration PPTX 不是可交付物，也不能替代正式 build。

该 orchestrator 会把 delivery 所需的 canonical `visual-generation-report.json` 自动写入 work-dir，QA 会自动绑定；不得直调内部 visual-generation gate 或手写报告。校准预览和正式 `rendered` gate 都会从 PPTX 成品核对所选 style 的浅/深六角色 palette，越位色值直接回到对应页面修复。
11. **Render**：调用 `ppt_pipeline.py render --work-dir <wd>`。Pipeline 一次渲染全部页面并生成 `contact-sheet.png` / 缩略图；相同 PPTX hash 复用。build 后旧渲染证据被归档，repair 后必须重新 render。**render 只接受确定性预检全绿的 deck**：build 打包后会立即在本地跑 `rendered` + `actual-content` + `quality` 的确定性部分（evidence/timing/lock，只读 PPTX 与 spec、不依赖 critic）；不绿时 `render` 直接拒绝，`next --json` 会指向免 repair 轮的修法——spawn builder `mode=repair` 读 `pre-qa-*.json` 报告改页后重建（连续失败上限 `max_pre_qa_rebuilds`，超过即转正式 render/critic 流程）。critic 从此只评审确定性门全绿的 deck，不再为一个注定返工的 deck 花一整轮评审。
12. **Visual Critique**：Agent `student-presentation-suite:visual-critic`，不传 `name`，独立读取当前 contact sheet 和所有页图，写绑定当前 SHA256 的 `visual-review.json`；最终 critic 仍负责全 deck rhythm，Calibration 不能替代它。
13. **QA DAG**：必须已有 `critic-execution.json`；`ppt_pipeline.py qa --work-dir <wd> --visual-review <visual-review.json>` 按 `package → rendered → actual-content → quality → delivery` 执行并绑定本轮输入。**产物可用性门（package/rendered）失败即停；内容质量门（actual-content/quality/delivery）全部跑完再汇总**——一轮 repair 必须拿到完整 blocker 清单，而不是每轮只发现一层门（2026-09-17 live 因此耗掉 6 轮 repair、约 199M token）。`pipeline-qa.json` 的 `failed_stages` 与 `blockers_by_gate` 就是给 repair 的清单：传报告路径给 builder 让它自己读，不要转抄；`derived_problems` 是上游失败的派生结论，不要当成独立任务去修。
14. **Repair**：只有 QA blocker 才先运行 `ppt_pipeline.py repair --reason <摘要>`；随后 spawn `presentation-builder mode=repair`，只改 blocker 页及直接共享依赖。**给 builder 的输入是 `pipeline-qa.json` 路径 + 一句话摘要**——该报告已含全部门的问题（`failed_stages` / `blockers_by_gate`），一轮把它们全修完，不要按门分批。

   **每轮必须 spawn 一个新的 builder 实例，不要用 SendMessage 继续上一个。** 一个实例扛多轮时上下文只增不减：2026-09-18 live 的一个 builder 实例从 8.7K 涨到 **699K**，261 个请求里 212 个在 ≥200K 上下文下发出（占其成本的 96.1%），最后一轮仅 3 个请求就花了 2.1M token。**实测反事实**：只做重置是 **98.7M → 80.9M（省 17.8M）**——轮 1 在实例内部自己就会涨到 606K，重置修不了它，其余要靠不让全 deck 返工发生。`next --json` 的 `builder_instance_reuse` 会在检出复用时报出实例与轮次——看到它就把下一轮换成新 spawn。

   **builder 自己不 build、不 render**（渲染与 `calibration_preview.py` 属于主会话，hook 会拒绝）；页面全改完再回报，主会话跑唯一一次 build。若 builder 在 build 之后又改了页，`build` 允许**一次**补差量重建（`carryover_builds`），避免为一处微调单开一轮。

   **blocker 页跨多个 shard 时同样并行**：`next --json` 在 `qa` 状态给出的 `builder_shards` 覆盖 blocker 页，`repair` 之后在**同一条消息**里 spawn 一个 builder 对应一个 shard。**没有页号的 deck 级 blocker 例外**——那说明整 deck 都在范围内，用**一个** builder 读报告，不要分片。

   **减少回合数本身就是目标**：实测每个回合平均只带 ~1.0 个工具调用（发一个、等结果、再发下一个）。合并调用（CD-1）在时间上等价于省钱——一个回合 10~19 秒，13 页的构建阶段每少 30 个回合就是少 5~10 分钟。`page_brief.py --work-dir <wd> --json`（不带 `--slide`）一次给全 deck 每页的契约，不要逐页调。

   收到 `BUILDER_DONE` 后重新 `build → render → critique → qa`（重建后若确定性预检不绿，仍先走免 repair 轮的预检修法）。generator hash 未变化时 build 拒绝；超过预算转 `incomplete`。

   **续轮与否由数据判定，不问用户**：`next --json` 的 `repair_convergence` 给出逐轮 blocker 数与趋势（`improving` 才值得继续，`flat` 要换做法，`worse` 必须先恢复被弄坏的回归），`repair_budget` 给出 `base`/`granted`/`effective`/`hard_cap`。**若 `repair_convergence.suspect_gate_defect` 出现**（某组 blocker 连续两轮逐字相同、其余在动），说明这组不是页面能修的：对着产物核对一次，要么它有页面级修法（写进 `--extend-reason`），要么它是门的误报——记为已知门限、继续修剩下的，**不要为它问用户交付策略**，提额也会被拒绝。需要提额时用 `ppt_pipeline.py repair --extend N --extend-reason "<本轮与上轮的 blocker 差异>"`——授权写进 `build-manifest.json`，**不要改已安装插件里的 `pipeline-contract.json`**（升级即失效、不可审计）；硬顶由契约 `max_repairs_hard_cap` 强制，到顶就如实交付 `incomplete`。
15. **Complete**：`ppt_pipeline.py complete --work-dir <wd>`；QA 全绿且 delivery 真正通过才允许完成。

## Generation core contract

```text
Production Summary confirmation
→ isolated research / compiled Slide Spec / Art Direction
→ ppt_pipeline plan
→ isolated builder(calibration: archetype-coverage sample)
→ deterministic calibration preview + independent visual-critic review（全绿才放行正式 build）
→ isolated builder(initial: remaining pages, preserving calibration)
→ exploration gates → production build（确定性预检：rendered + actual-content + quality 确定性部分）
→ render（预检全绿才放行）→ isolated visual-critic + QA DAG（内容门全跑后汇总）
→ bounded repair（每轮新 spawn 一个 builder 实例）→ isolated builder(repair targets only)
→ build → render → critique → QA → complete
```

核心原则：**先用极少数真实页面校准视觉系统，再把该系统扩散到整套 deck。** Skill 负责智能编排，Builder/Researcher/Critic 各自隔离高上下文工作，Pipeline 负责确定性状态和交付；Calibration helper 只负责便宜、可追溯的早期视觉反馈，**但它的判定权属于独立 critic，不属于 spec 的作者**。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`。

**交付物**由 Production Summary 里确认的 `deliverables` 决定，不多不少。用户只选 `pptx` 时，最终交付就是 PPTX 本身。PPTX 备注窗格里有没有讲稿由 Slide Spec 的 `meta.include_speaker_notes` 决定，与 `deliverables` 无关——不要因为"10 分钟汇报没讲稿会吃力"就私自把 `speaker-notes` 加进交付清单，在最终确认轮提示用户即可。

**管线证据**始终写入 work dir，但**不是交付物**：`build-manifest.json`、Slide Spec lock、Art Direction、calibration preview evidence、research provenance、正式 render/contact sheet、visual review、package/readback/quality/delivery reports。visual critic 与 QA 门禁依赖它们，所以 `deliverables` 只有 `pptx` 时它们依然会存在——呈报时标注为"质检留痕"，不要列进交付清单，也不要因为"用户没选 preview 却产出了预览图"而判定自己违约。`pptx_delivery_check` 已从 Slide Spec 的 `meta.deliverables` 推导 notes/preview 是否必需，无需手工传 `--allow-missing-*`。

**`calibration/` 仅为内部早期反馈，不作为最终交付物。** 编辑任务另含 change summary。禁止覆盖 source deck。
