# Research Workflow

本文件是 suite 范围内**外部知识获取**的 canonical 来源：什么该查、什么不该查、查到
什么程度算够、查不到怎么记录。产出的形状见 `research-pack.schema.json`，语义校验见
`scripts/validate_research_pack.py`，引用如何进入页面见 `evidence-and-citations.md`。

设计宗旨一句话：

> **Search for evidence, not text.** 不是"帮我找点 PPT 内容"，而是"识别需要外部证据
> 支持的论断，检索高质量来源，完成交叉验证，并把事实、数据、来源与可视化机会压缩成
> 结构化 Research Pack"。

## 定位：知识获取层

```text
Presentation Brief   用户想讲什么
      ↓
Research Pack        外界事实是什么      ← 本文件负责这一层
      ↓
Slide Spec           每页讲什么
      ↓
Art Direction        每页怎么看
      ↓
PPTX                 最终怎么呈现
```

`sp-research` 只负责第二层。它**不**决定版式、不设计页面、不生成 PPTX、不改视觉风格、
不撰写成段讲稿。职责一旦混在一起，前面几层的产物就会互相污染。

## 一、什么时候必须查：A / B / C / D

**最重要的能力不是"会搜索"，而是"知道什么时候不该搜索"。**

| 类 | 判据 | 处理 |
| --- | --- | --- |
| **A 必须查** | 时效性内容：最新数据、最新政策、最新版本、最新榜单、某机构最新预测、产品现状 | 必须联网；查不到就进 `unresolved`，不得用模型记忆冒充 |
| **B 最好查** | 模型大概率知道，但结论会被打分的内容：课程答辩、论文汇报、竞赛、正式提交 | 查；拿不到就降级为"模型常识"并**在页面标注无来源**，不得假装有出处 |
| **C 不用查** | 与外部事实无关的任务：过渡页、把已有材料概括成三点、重排用户提供的结构 | 不产生检索 |
| **D 禁止查** | 用户明确限定范围："只根据我上传的论文 / 只用课程 PPT / 不要用外部资料" | 立即停止检索；用 `import_user_materials.py` 确定性导入用户材料（不派研究员子代理），只整理用户材料 |

D 类默认走确定性导入（`import_user_materials.py` → Research Pack + `research-import.json` 凭据，无子代理）；仅当用户点名要研究员整理时才 spawn 隔离研究员。D 类是硬约束：一旦触发，`sp-research` 不发起任何检索，只把用户材料整理成 Research Pack
（`queries` 为空、`sources` 只含用户材料）。D 类 pack 没有 F/D/Q 实体，Slide Spec 的
`evidence_refs` 直接引用来源 id（`S01`…）；编译器会把被引来源落成 source 级 ledger 条目
（标题/locator 与 pack 字节一致，附用户材料限定语）——v0.16.13 之前这类引用结构性无法解析。

## 二、调用单位是 Claim，不是主题

不要 `research("生成式 AI")`——范围太大，回来的东西没法用。要按**需要被证明的论断**
拆分：

```text
✗ research("生成式 AI")
✓ Claim 1  生成式 AI 的企业采用率近年明显上升
✓ Claim 2  多模态模型正在成为主流技术方向
✓ Claim 3  幻觉是企业部署生成式 AI 的主要风险之一
```

每条 Claim 各自找证据，最终形成：

```text
Claim → Evidence → Source
```

这条链路与 `evidence-and-citations.md` 的 Evidence Ledger 天然对齐。

## 三、知识缺口：不要接受模糊陈述

Slide Spec 草稿里出现"市场发展迅速"这类**未量化**的表述时，`sp-research` 不应直接
采用，而应识别为缺口并去补：

```yaml
knowledge_gap:
  claim: "AI Agent 市场发展迅速"
  reason: "缺乏定量证据"
  research_needed: [市场规模, CAGR, 主流机构预测]
```

补上之后才变成可上屏的内容：

```text
AI Agent 市场正在快速增长
2025 年 xx 亿美元 → 2030 年 xx 亿美元，CAGR xx%（来源 S03）
```

## 四、来源分级（标注元数据，不是门槛）

分级表只回答一个问题：**页脚怎么写**。它不决定置信度，不驱动检索，也不构成任何门禁
（2026-09-30 裁定：等级门是"搜很多次"的根因——当前检索环境里中文官方站常被 captcha 拦、
索引覆盖差，"往上升一级"的边际成本是几十次搜索，收益只是页脚一行字）。

| Tier | 内容 | 页脚标注参考 |
| --- | --- | --- |
| **S** | 法律法规、官方文件、官方数据库、论文原文、政府统计数据 | 按原文引用 |
| **A** | 顶会论文、权威研究机构、高校、国际组织、上市公司财报 | 按机构+报告名引用 |
| **B** | 主流媒体（Reuters / Bloomberg / Nature News 等） | 按媒体+稿件引用 |
| **C** | 技术博客、行业博客、厂商博客 | 按作者/厂商引用，避免作为关键数字唯一支撑 |
| **D** | 论坛、社区、个人博客 | **仅**作为"用户观点/舆论"标注 |

证据体系的硬门只有两条，都与等级 letter 无关：

| 硬门 | 内容 |
| --- | --- |
| **可追溯** | 来源必须有 `url` 或 `locator`；用户文件必须有导入回执绑定（`import_user_materials.py` 的 sha256） |
| **独立印证** | 标 `confidence: high` 必须 ≥2 个有效独立来源互相印证；同源转载冒充两个来源会被 `sources_are_not_independent` 拦下 |

一条**提示**（来源*种类*，不是等级，不拒绝——owner 裁定 2026-09-30）：条目只靠论坛/社区/
个人博客/厂商博客这类观点源支撑时，validator 记 minor advisory `opinion_only_support`，
pack 照常通过；页面必须把它表述为"社区/厂商观点"并标注来源类型，不得写成公认事实。

过渡期说明已失效（v0.23.3/v0.23.4 落地）：validator 的 tier 下限（`weak_source_for_data_point` /
`weak_source_for_high_confidence`）与类型上限（`tier_above_type_ceiling`）**已移除**；契约与
代码现在一致——等级只剩标注一个用途。validator 执行的是：可追溯、独立印证（**独立性按注册
域名机械判定**：同域默认并组，声明相互独立须写 `independence_note`，并留一条 minor advisory
供人工复核）、以及观点源提示（`opinion_only_support`，minor）。

## 五、交叉验证

数字必须多源比对，不许随便挑一个：

```text
Source A  50 亿
Source B  52 亿
Source C  48 亿   → 量级一致 → confidence: high（≥2 个独立来源）
```

```text
Source A  50 亿
Source B  120 亿
Source C  35 亿   → 量级不一致 → confidence: low，conflict: true，
                     并在 conflicts 里逐条列出取值与来源
```

口径差异（统计范围、年份、汇率、口径定义）也算冲突——**先怀疑口径，再怀疑数据**。

独立性判定是**机械规则**（v0.23.3 起 validator 执行）：同注册域名（gov.cn / com.cn 等后缀
正确处理）或同声明组的来源并为同一个独立组——同域页面通常源自同一个上游，"转载源当两组用"
从此凑不出 high confidence。确实独立（如同一门户下两份不同机构的报告）时，在该来源写
`independence_note` 说明理由，按声明组计，并接受一条 minor advisory（`independence_override_used`）
供人工复核。

## 六、可视化机会：PPT 研究与其他研究的分界

普通检索找"知识"；`sp-research` 还要找"**可以画图的知识**"：

| 材料形态 | visual_candidate.type |
| --- | --- |
| 一列随时间变化的数值 | `line_chart` |
| 几个并列的规模/占比 | `bar_chart` / `kpi` |
| 传统方法 vs 新方法 | `comparison` |
| 若干里程碑事件 | `timeline` |
| 方法分成几类 | `taxonomy` |
| 有先后依赖的步骤 | `process` |
| 多维对照 | `table` |

标出类型与优先级即可，**具体画法由 Art Direction 和 Composition 决定**。

## 七、检索深度档位

| 档位 | 适用 |
| --- | --- |
| `simple` | 普通课程展示、小组作业 |
| `standard` | 课程答辩、结题答辩 |
| `deep` | 论文汇报、竞赛答辩、毕业答辩 |

档位是**深度建议，不是次数上限**：检索与页面抓取均不设次数配额。纪律靠证据规则而不是
计数器——同一 URL 复用已抓取结果，失败最多重试一次；优先把检索花在会上屏的关键论断上，
其余记入 `unresolved`，不得把未经核实的数字写成已验证。
`research-execution.json` 记录实际 `WebSearch` / `WebFetch` 次数，供成本复盘。

默认由 `scenario` 推导，用户可覆盖。硬约束是：**不要为了某一页的一句话搜索二十个网页。**

### 检索机制：失败的签名决定换通道，不决定换措辞（2026-09-29 实测）

一次真实运行（`pv-wind-carbon-neutral`）：**86 次检索里 49 次没产出可用的东西**——23 次
`No links found`、**15 次返回无关结果**、7 次目标站 captcha 拦截、5 次域名过滤后为空。
关键不是"后端坏了"：同一次运行里 37 次检索成功，且**同一批 claim 的直连抓取拿到了原文**。
所以失败要按签名处理：

| 工具返回 | 机制含义 | 正确反应 |
| --- | --- | --- |
| 结构化运行时元数据明确 execution_status=not_executed | 已确认后端未执行；签名 backend_not_executed | 暂停该搜索通道，不引用响应。可继续原文抓取与定点核验 |
| 无有效候选链接的不识别格式、散文或伪工具调用 | unknown_payload：无法确认执行状态 | 仅提示，不暂停 WebSearch；禁止将其数字/日期当证据 |
| 完整 JSON 的 title + link/url 记录（字段顺序不限），或已适配的 web_search_prime_result_summary 包装 | 可解析的定位候选，不证明其中内容属实 | 获取文档并建立原文绑定；Markdown、纯文本有效 URL/DOI 也算候选定位成功；响应内数字不构成证据 |
| 裸的 Links: - No links found. | index_empty：该查询未返回定位候选，不能证明整轮服务正常或故障 | 换文档定位路线，不关闭整个会话 |
| **返回无关结果** | 查询太宽或把整句话塞进了检索框 | 砍到**一个可回答单元**（见下条"查询构造"），不要继续加限定词 |
| **captcha / 登录墙**（常见于部委、电网、协会站点） | 该站点只能直连，索引到不了它，也到不了它的站内检索 | 转直连路线；不要把同一 claim 再喂给索引 |
| **域名过滤后为空** | 过滤器把唯一命中的来源挡掉了 | 去掉过滤器，让发布方名字本身承担约束 |
| 目标页返回 JS 壳 / 与查询无关的泛化条目 | 该页面或该路径不可抓 | 记 `unresolved`，不要抓同域的其它页面试运气 |
| **同一端点对不同请求返回同一份字节**（`fetch-text-report.json` 的 `degenerate_channels`；判定＝同一端点下 ≥2 个**不同**请求 URL 共享同一 `raw_sha256`） | 该端点不按请求作答（缓存壳 / 查询被忽略）——换 `t=` / `page=` / `q=` 只是**同一个通道的变体** | **该通道判定一次即收口**：换端点（另一个发布方记录页、另一个 host）或直接取文档 URL；claim 按 `access_blocked` 记录，不要在同一端点上继续试参数 |

2026-09-30 live：上面最后一条是缺的那条。`sousuo.www.gov.cn/search-gov/data` 用十种不同
参数返回了同一份 97 字节空壳，执行者逐次换 `t=` 试了五轮——每轮一整次模型往返——因为轨迹
里没有任何东西说"这个端点不按请求作答"；而同一端点在 `t=zhengcelibrary_bm` 下返回的是
18–24k 字符的真结果，所以它也不是"整个站不可用"。这就是**通道级**判定的价值：重复的
**字节**（而不是重复的措辞）才是证据。

**通道按类判定一次，不按次数累加。** 上限是计数器，通道判定是分类；一条通道只判一次。
新步骤必须带来可指出的证据收益，不是同一通道的新参数或新措辞。
unknown_payload 是格式不确定性，只记录 advisory，不暂停；backend_not_executed 只来自结构化运行时执行状态。
JSON 空数组视为正常无命中。纠正语言、官方名称、时间范围或移除过滤器属于合理改写，
search-log 可用 adjustment_reason 说明新增收益；仅无收益的重复查询触发重试提示。
暂停状态按事件顺序更新，历史成功不能掩盖之后的故障；仅对应 WebSearch 被暂停。
主流程在提供方/适配器/环境发生具体变化后可恢复一次探测（研究员不得自行重置）：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/reset_research_channel.py" \
  --project <project> --session-id <researcher-session-id> --agent-id <researcher-id> \
  --reason <具体环境变化>
```

恢复事件与 hook 共用同一把锁，追加时间戳且不删除原记录；只有明确未执行再次暂停，未知格式仅提示。
只有一个活跃暂停通道时可省略两个 ID；多个通道必须明确选择。
没有环境变化就走其他可用路线或 unresolved 收口，不反复 reset，不为同一任务另派研究员。

**查询构造：一个查询 = 一个可回答单元。** 同一次运行的数据非常一致——成功的那批是
20–30 字符、只含 `主体 + 指标 + 时间`（或 `发布方 + 报告名`），失败的那批里塞着一整句 claim
（70–95 字符、最多 15 个词条）。规则：

- 一个单元一条查询（主体 + 指标 + 时间），**不要把 claim 句子粘进检索框**；
- 用发布方的语言：IRENA / IEA / GWEC / UN 用英文，国家能源局 / 中电联 / CPIA 用中文；
- **不要回显你已经拿到的数字**——"719.2万千瓦""169GW"这类查询只可能返回同一批转述；
  要主源就去发布方自己的记录端点或索引页；
- 查到的每个来源记 `url`/`locator` 与 `independence_group`，写进 `queries` 只追加不改写。

**关闭一条 claim 就是停止条件（逐条收口）。** 两条合法出口，二者都算关门：

| 出口 | 条件 | 记录方式 |
| --- | --- | --- |
| 已坐实 | 可追溯来源支撑且无冲突；≥2 个独立来源互相印证时可标 `high` | `must_verify.status: verified` + **`entity_ids`** 链到坐实它的 findings/data_points（来源随实体传递，**不在 source_ids 重抄**；pack 有实体时这是唯一合法声明，`must_verify_unlinked` 为 major）；仅当 pack 没有 F/D 实体（D 类导入）才允许直接 `source_ids` |
| 降级收口 | 只有转述可拿、主源不可达 | **保留已拿到的 `source_ids`**，`status: unresolved`，并在 `unresolved` 写明缺失的主源 + 机制 + 影响 |

`status: verified` 的含义是"**可追溯且无冲突**"，不是"爬到了某个等级"——等级是页脚标注
元数据（§四）。validator 按此执行：verified 条目的 `entity_ids` 必须指向存在且未冲突的实体
（`must_verify_unknown_entity` / `must_verify_conflicted_entity`）；条目列出的来源必须被某个
链接实体使用（`must_verify_orphan_source`）——账本只记一份，两处记数必然漂移。清单条数 3–5
越界是 minor 提示，不是门禁——小 deck 不该为凑数编 claim。

2026-09-30 结论：**等级门就是"搜很多次"的根因。** 直连主源的理由只有两个——**逐字保真**
（上屏数字要原文）与**转述相互冲突**（需要原始出处仲裁）；"把 B 升成 S"永远不构成继续
检索的理由。

`must_verify` 的措辞必须是**内容**（会上屏的事实/数字，如"2030 年风光总装机目标 1200GW"），
**不是"找到 X 的官方出处"**——后者是一条没有终点的检索任务：主源打不开时它永远不满足，
于是只能一遍遍重试，这才是"搜很多次都找不到"的机器侧原因。

**结果页永远不是来源。** 这是证据分级规则（Tier），与后端好坏无关：`cn.bing.com` /
`www.bing.com` / `so.com` / `sogou.com` / `duckduckgo.com` / `lite.duckduckgo.com` /
`html.duckduckgo.com` / `search.brave.com` / `mojeek.com` / `search.yahoo.com` / `baidu.com` /
`google.com`、任何 `link?m=` 跳转，以及政府站的**站内检索接口返回的记录页**，都只算定位手段。
定位交给检索工具；要读的是它给出的**文档 URL**。`fetch-text` 不做题材审查：你让它取哪个 URL
它就取哪个，只在 provenance 里标出 host 类别（`host_class`），所以痕迹是诚实的，判断仍在
你这边——但结果页写进 `sources` 就是证据错误。

定位页的 `host_class` 为 `listing`：发布方记录端点、末级 /news、/press-releases、
/xwdt、/xwfb 和 index.htm/index.html。文章位于这些目录下不自动成为定位页；
政策正文和 PDF 是文档。定位页可以读取以发现文档，但不能作为 claim 的证据。

通道关闭之后仅暂停 WebSearch；WebFetch 文档与发布方目录、fetch-text、文件操作仍可用。
正文 Read 使用 offset/limit；Grep 的 content 模式必须设置正整数 head_limit，文件名/计数模式
可用；禁止 shell 把整页正文输出回上下文。搜索引擎结果页 WebFetch 仍拒绝。
无有效信封或校验报告时主流程记 RESEARCH_BLOCKED，不再 spawn 盲目续搜。

**确定性地取原文（不经小模型转述）**：`fetch-text` 把 HTTP 原文与抽取文本一起落盘，两份
sha256 一起写进 provenance。转述会改写数字，而会上屏的数字要求逐字引用：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" fetch-text \
  --url <文档 URL> [--url <另一个>] --scope <A|B> \
  --out-dir <work-dir>/research/fetched
```

`--scope` 是**权限门**：只有 A/B 授权联网取原文，C/D 一律拒绝——与"D 类禁止联网"是同一条
规则，由工具机械执行而不是靠提醒。报告落在 `research/fetched/fetch-text-report.json`，每条
记录带 `raw_path` / `text_path` / `raw_sha256` / `text_sha256` / `charset` / `title`；
失败同样留痕（`reason` + `detail`）。引用时逐字取自 `text_path`，pack 的 `url` 记
**文档 URL**（不是跳转链接），locator 可带该原文的 sha256。

### 新任务交接与原文绑定

主流程写 research-task.json（schema：research-task.schema.json），运行
validate_research_task.py 后显式 spawn；prompt 只给 task 和 work-dir 的绝对路径。
背景、scope、档位、输入文件与 claims 的 id/原文/acceptance 都在 task，避免转抄漂移。
例子见 examples/research-task.json。校验 pack 自动发现 task（也可传 --task），所有任务 claim 必须逐字保留并收口。

新 A/B 包默认启用 evidence_contract=source-backed-v1：每个可用 F/D/Q 至少有一个可读取的
来源片段绑定 entity_id → source_id → excerpt + text_path + text_sha256 + locator + support_note。
一个直接来源即可支持普通论断，默认 medium；不为所有辅助来源重复建立绑定。
数字仍须在片段中直接出现，直接引语必须逐字一致；搜索摘要只能用于定位，不能作为事实账本。
正文路径必须在 work-dir/research 下；web 来源需成功的 fetch-report 将 URL 与同一文本绑定。
support_note 解释语义支持关系，机器不宣称自动证明语义。

claims 新增 importance=core|supporting（默认 core）、verification=source|text|cross_check（默认 source）。
关键数字指定 text，要求 year/unit/region/metric 与原文对应；可用 context_excerpt 引用同一
原文中的表头或年份说明。争议结论指定 cross_check，要求至少两个独立来源并满足原文校验。
text-bound-v1 保留为显式严格模式，继续要求每个使用的来源绑定，不作为普通任务默认。
计算值/单位转换由下游记录原值和计算，不能冒充原文数字。

claim/实体状态为 located（仅找到）、usable（可引用且记录限制）、verified（完成要求的核验）、
unresolved（缺失与影响）。located/unresolved 不编入事实账本，usable 可以 medium 继续。
校验 ok 只表示契约有效；delivery_status 独立分为 ready、partial、insufficient。
核心 claims 都达到 usable/verified 且无其他缺口为 ready；仅辅助缺口为 partial；核心缺口为
insufficient，编译 Slide Spec 时明确拒绝并列出缺口，不能把“返回了包”当成研究完成。

任务默认自动发现 work-dir/research-task.json，编译器也重验任务与验证报告哈希；省略 --task
不能绕过新任务规则。spawn 冻结任务绑定，C/D 在网络工具调用前拒绝；缓存也先检查 scope。
旧包没有任务文件仍兼容且保留未绑定提示。输出禁止落在 plugin 或 marketplace 内。

抓取使用 --workers 4（可选 1–8），URL 去重，每条完成立即写盘；报告采用锁和原子替换，
保留失败历史。URL/内容哈希隔离文件，复用前核验 raw/text 哈希。退化判定只针对查询/目录
locator，不把同一文档的跟踪或签名参数视为故障。

首次拿到有效证据就保存 research-pack.json 并运行校验，自动更新 research-progress.json。
每轮新增有用证据后再次保存；中断后读取进度和报告，仅续做 pending_claims、未满足的
验收条件和未抓取 URL。已完成内容不重搜。核心满足后优先 partial 交接；继续研究必须指明
能补齐的口径、冲突或关键证据。连续工作没有有效进展时返回当前包与具体缺口，不能无限等待。
工具边界现在机械检查 research-control.json：ready/partial、总时间耗尽或无有效进展时
停止新增检索，但允许保存/校验/回传当前包。默认 simple 为总 120 秒/停滞 60 秒，
停滞计时从首次实际检索开始，准备阶段不算搜索停滞。standard 为 300/120 秒，deep 为 900/240 秒；任务可用 time_budget_seconds 与
stall_timeout_seconds 覆盖。只有新增成功正文或有效包才能刷新进度，失败与重复不刷新。
这是工具边界收口，不是强杀模型或中断正在执行的 HTTP 请求；模型请求本身仍由宿主超时处理。
新输入或具体环境变化后，主流程可运行 research_control.py --work-dir <work-dir> --resume
--reason <具体变化> 显式续做；保留已完成证据与历史，研究员不得自行重置计时。
simple/source 任务的一个直接片段已满足要求且校验 ready 后立即回传，不额外挖图表候选或
独立出处。fetch-text 返回的 text_sha256 直接复用，不再另起命令计算。元数据与摘录核验
批量执行。主流程只调用 research_handoff.py --work-dir 一次，完成当前任务/产物/校验/执行回执与
正文绑定重验；输出只含统计和缺口，避免逐字段往返。不得为确认路径浏览插件目录/hooks/环境。

来源增加 origin_id 表示原始报告/数据集，跨域转载同源按该标识合并，independence_note
不能绕过它；同域托管确实独立报告仍允许用 independence_note 解释。

**主源直取路线**：索引给不出东西时，直接取 claim 所属发布方的文档——政策原文（gov.cn
政策库）、部委统计发布页、国际组织报告页/PDF、论文原文。同一天实测：`gov.cn` 政策原文页
回报了标题、发文机关、日期与全部量化目标（逐字），而 `fetch-text` 对同一页给出 8210 字符
正文 + 两份 sha256——这就是"逐字引用"能落地的前提。

受阻原因按机制分开记录：`search_unavailable`（索引没返回结果）、`not_found`（有覆盖但检索
不到）、`access_blocked`（有覆盖但打不开）。三者对下游的意义不同，不许合并成一句"查不到"。

**档位必须按证据需求选，scenario 只定默认**：需核验的数据点/claims ≥ 10 或 slide_count ≥ 12
时至少 `standard`；≥ 18 或 slide_count ≥ 15 时用 `deep`。宁可初始档位高一级——gap-fill
重入实测代价约 7 个请求（主会话 SendMessage + 等待 + 核验，研究员重入 + 重校验；
2026-09-19 实测），而同样的检索在第一次暖上下文里多跑只多 1–2 个请求。档位选低的表现是
把 8 个维度的 deck 压进 5 个维度（2026-09-17 live），不是研究员搜多了。

### 启动前声明与停止条件

检索开始前，Research Pack 必须先列出 **3–5 条 `must_verify` claim**（真正决定内容成立与否的
待证论断；条数越界是 minor 提示，小 deck 不凑数）并选定深度档位。**claim 写成内容，不写成
检索任务**——"2030 年风光总装机目标
1200GW" 可以关门，"找到 12 亿千瓦目标的官方出处" 在主源打不开时永远关不上，于是只能反复重试。
停止条件是**收益充分**，不是次数用尽，出口只有两个（逐条收口，见上"检索机制"）：

- 每条 claim 有可追溯来源支撑且无冲突（≥2 个独立来源印证可标 `high`），**或**
- 只有转述可拿时保留 `source_ids` 并把该条标 `status: unresolved` + 写明缺失主源与影响；
- 继续前必须指出下一步的新增收益：独立数据出处、缺失口径、冲突解释或可读取原文；无收益就 unresolved 收口。有效部分包仍返回 RESEARCH_DONE，主流程根据 completion 与 unresolved.impact 删去或弱化表述；
- 全部 claim 处理完毕即停止检索——多搜不是为了凑数，换措辞重试同一 claim 不算新证据；
- `validate_research_pack.py` 校验逐条覆盖（`must_verify_uncovered` 等，major）；
  声明数量 3–5 越界（`must_verify_count`）是 minor 提示，不是门禁。

2026-09-22 实测：一个研究员为有时效数据的主题跑了 42 分钟 / 4.0M token，其中相当部分超出
"足够来源"——声明先行、逐条关门才是刹车。2026-09-29 实测的教训是另一半：那次**声明写得像
检索任务、`verified` 又判得太松**（5 条全 verified 而 8 条 unresolved 说只有媒体转述），
于是 86 次检索里 49 次白费——刹车失灵不在次数，在口径。

### 补检（gap-fill）

- 授权补检时写明本次要核验的 claim 清单；研究员按 claim 收益决定检索量，不受次数配额。
- **禁止删除已执行的 queries 记录**——pack 是审计记录，只追加不改写（2026-09-17 live：
  为迎合上限删记录的路径已被废除，上限本身也不复存在）。

## 八、上下文防火墙

这是把研究拆成独立角色的主要理由。原始检索会产出大量低价值内容（搜索结果页、网页
正文、论文摘要、失败信息、重复资料），如果让主流程直接承接，上下文会迅速膨胀。

```text
原始检索上下文  ~100k tokens
        ↓  子代理内部消化
Research Pack    ~8k tokens
```

契约：

- 原始结果落盘 `outputs/.pptx-work/<work-id>/research/<topic>.json`；
- 回传主流程的**只有** Research Pack 本身；
- 主流程**不得**要求子代理"把搜到的东西贴过来看看"。

## 九、检索受阻必须留痕

打不开网页、来源付费、来源不可得——**不许静默降级**，一律写进 `unresolved`：
搜索层面的失败同样留痕——`research/search-log.json` 的 `search_executions` 必须包含
每次实际执行的检索（含空返回 / 返回无关结果 / 超时重试，标 `status: failed`）；每条失败记录
带 `signature` 记失败签名（`backend_not_executed` = 检索没执行，见§七；`index_empty` = 执行了
但没有覆盖；`irrelevant`；`blocked` = captcha / 登录墙）。`signature` 是**分类**不是计数：
它决定该 claim 记哪种机制、下一步换哪条通道。gap-fill 的检索
必须**追加**写入该日志（`n` 续号），不得只改 pack。`pack.queries` 只记成功拿到结果的检索，
失败调用不进 `queries`——但没有日志留痕，就无法审计两者之间的差额（2026-09-19 实测：
search-log 停在初始 7 条，gap-fill 第 8 条检索只存在于 pack，日志与事实脱节）。

这份留痕**不是纸面承诺**：校验步骤必须带 `--search-log` 与 `--fetch-report`，validator 机械审计
日志与 pack 的差额（`query_unlogged`）、重复查询（`duplicate_query`）、换措辞重试
（`reworded_retry`）、把整句话粘进检索框（`over_broad_query`）、抓取结果页当证据
（`result_page_fetched`）、**在同一个不按请求作答的端点上反复换参数**（`degenerate_channel`，
从 fetch 报告的 `raw_sha256` 重算，不依赖工具版本）、**整轮检索都没执行**（
`search_backend_not_executed`，全部失败记录的 `signature` 都是 `backend_not_executed` 时触发）
——全部 minor：审计提示行为，不设门禁、不数次数。

抓取侧的 `fetch-text-report.json` 由工具自己算出 `degenerate_channels`（§七最后一条），
并且**跨调用累积**：同一次 `--out-dir` 的下一次 `fetch-text` 会读到上一次的记录。判定一旦成立，
同一端点的**新**请求不再发出（记录 `reason: channel_closed`，不产生新的 HTTP）；已经取回的
真结果仍留在报告里。能返回真正文的参数值必须出现在判定成立的那一次调用中，否则改走文档 URL，
不要再换 `t=`。`research/fetched/<子目录>` 会折回 `research/fetched`，所以逐 URL 分子目录盖不住
这份报告。工具 stdout 只给本次新增的行和通道判定，正文留在 `text_path`——用 Read 的 offset/limit
取要引用的几行，不要 cat / grep / print 整页回到对话里。


判定口径经过一轮校准（0.23.9），只抓站得住的信号：`reworded_retry` 要求两条失败查询的
**数字集完全相同**——换了数字（2025→2026）就是另一个可回答单元，不是换措辞；
`over_broad_query` **只归因实际失败的长查询**（成功的首发长句不算错，n=1 样本里那 49 字符
成功查询就是旧口径的误报）。advisory 有强制出口：validator 一行输出与 Evidence 编译器的
ok 行都固定带 `retrieval audit — N advisory: …`，主管道读编译器输出就看见——不依赖谁
主动去翻 validation 报告。

```yaml
unresolved:
  - query: "IPCC AR6 WGIII 原始表格"
    reason: access_blocked
    impact: "对应条目置信度降为 medium，页面按'区间'表述"
```

这条来自一次真实教训：某次运行中 WebFetch 被域名策略拦截，只能退到搜索摘要，但
当时没有留下任何结构化记录，导致后面无法判断哪些数据需要复核。

## 十、与图片检索的分工

本文件**只管知识**（事实、数据、论文、引用、证据）。图片素材另走
`image-sourcing.md` 的能力声明与权限门禁。

两者的优化目标不同，不要合并成一个"超级代理"：

| | 知识检索 | 视觉素材检索 |
| --- | --- | --- |
| 首要指标 | 可信度、正确性、时效性、可追溯 | 分辨率、构图、版权、风格适配、可裁剪性 |

## Evidence Map 的确定性边界

`research_pack_to_evidence.py` 的产出受 `evidence-map.schema.json` 约束（编译器在写盘前
验证，失败即退出码 2）。它的确定性要说清楚，避免过度承诺：

| 性质 | 状态 |
| --- | --- |
| **语义内容确定性** | ✅ 同一份 pack 编译两次，`ref_map`、`evidence_ledger`、`source_index`、`semantic_sha256` 完全一致 |
| **字节级位置无关确定性** | 🟡 完整 JSON 里 `provenance` 记录绝对路径，因此**相同内容 + 不同工作目录**会得到不同的文件字节 |

`semantic_sha256` 刻意只覆盖语义内容，不含 `provenance`。**不要为了"字节也一样"把审计
路径删掉**——路径是追溯所需的信息，而需要比较"是否是同一份证据"时用 `semantic_sha256`
即可。冻结时绑定的是文件 SHA-256（含路径），所以跨机器的字节差异不会造成误判，只会
让"换个目录重新编译"需要重新 freeze。

## 可验证标准

- `scripts/validate_research_pack.py <pack>` 0 blocker；
- Research Pack 里每条 `source` 都有 `url` 或 `locator`（可追溯）；用户文件有导入回执绑定；
- 每个 `confidence: high` 的条目都有 ≥2 个独立来源印证；
- 出现 `conflict: true` 的条目同时 `confidence: low`，且有对应 `conflicts` 记录；
- 检索受阻都出现在 `unresolved` 里（含后端空返回的 `search_unavailable`），没有静默降级；
- 每条 claim 要么有可追溯来源支撑且无冲突，要么在 `unresolved` 里有写明影响的记录
  ——档位只定深度，不对 `queries` / `sources` 设数量上限；等级 letter 不构成任何标准。

研究正文的 Grep 未传 head_limit 时，PreToolUse 自动补 80 并保留其他参数，不再先拒绝再重试；
显式无效值仍需纠正。实现遵循 [Claude Code hooks 的 updatedInput 契约](https://code.claude.com/docs/en/hooks#pretooluse-decision-control)。
