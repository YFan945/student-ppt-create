# Research Workflow

本文件拥有外部知识获取规则：权限、来源支持、核验、收口与恢复。Research Pack 形状见 research-pack.schema.json，引用编译见 evidence-and-citations.md。

## 目标与分工

研究员查证会上屏的事实、数字和引文，产出可追溯的 Research Pack。内容支持由研究员阅读判断；校验器检查引用完整性、明确的数值矛盾和交付缺口，不宣称自动证明语义。
研究不决定版式、不写成段讲稿、不生成 PPTX。主会话负责内容组织、设计和制作。

## 范围与权限

| scope | 处理 |
| --- | --- |
| A | 最新政策、数据、版本、产品现状必须查；不能用模型记忆冒充最新证据 |
| B | 正式课程、论文或竞赛事实应查；缺证据时明确保留缺口或无来源限定 |
| C | 仅整理既有内容，不检索 |
| D | 用户限定材料，禁止联网；默认 import_user_materials.py 导入，不派代理 |

C/D 在网络调用和缓存读取前检查。研究员不能通过改任务文件扩大联网授权；用户授权变更后，由主会话用 research_control.py --rebind --reason <说明> 更新权限。普通内容修订无需此操作。D 来源限 user-file，queries 为空。用户明确要求研究员整理 D 材料时仍不得联网。

## 任务和继续研究

主会话写 research-task.json：背景、范围、输入路径和逐条 claim 的 ID、验收要求。校验后显式调用 student-presentation-suite:presentation-researcher，不使用 context: fork。
默认批量处理独立查询，复用已读文档。按实际内容确定 claim 数量，不凑 3–5 条。
importance 为 core/supporting；verification 为 source/text/cross_check。simple/standard/deep 仅是建议，不限制次数、总时长或修复轮数。
任务通过稳定 ID 关联；工具推导无歧义的 entity_ids/claim_id，内容无需在多个表中逐字重复。
任务可以收敛或补充，当前任务是准据；普通修改不冻结、不需要 rebind。兼容命令 research_control.py --rebind 仅记录变更，无理由字数门槛。

同一任务同一时刻只运行一个研究员。失败、正常结束后允许顺序恢复或定向补检，优先续做已有缺口，不重复研究已完成部分。
主会话可用宿主 resume 继续已有 agent；宿主已终止它时可重新派发。需要时运行 research_control.py --resume --reason <本次目标> 清理旧活动标记。
不区分“只许恢复一次”的基础设施和内容例外；unknown_payload 不构成故障证明，也不禁止正常修复。

## 来源和读取方式

搜索定位来源，获取正文核实。主源直取、浏览器阅读、下载后自行解析 PDF、OCR、表格转录和用户文件都可使用；不得为了工具不支持 PDF 而放弃已经取得的原文去找二手散文。
fetch-text 是可选的确定性抓取工具，不是唯一可信入口：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" fetch-text --url <document> --scope A --out-dir <work-dir>/research/fetched
```

同一 URL 优先复用缓存，工具自动保存原始字节、抽取文本、获取时间和 SHA-256。缓存哈希用于发现损坏、重新抓取，普通包不要求 text_path/text_sha256/fetch-report 一致。
合法文件移动、重解析、换行和编码调整不使证据失效。无本地文本也可记录浏览器/PDF页码、表号及支持说明。
搜索摘要仅供定位，不能冒充已阅读正文。目录页或 index.html 若确实载有正式数据，可以按实际内容引用；不能仅凭 URL 形状拒绝。

## 普通证据契约：source-backed-v1

每个使用的实体有来源引用和至少一条 evidence：entity_id、source_id，以及 excerpt 或 support_note。推荐保留 locator（页码、表号、段落）和获取方式 method。
来源最少填写 id、title、url 或 locator；短字符串也可作稳定ID，推荐沿用F/D/Q/S编号以便人读。类型、等级、独立组、查询历史和本地文件信息均可选；工具补足兼容字段。
一条直接来源可支持普通论断，默认 medium；不用为每个补充来源重复提取、绑定和填写审查表。
extra 字段允许保留；工具仍拒绝重复 ID、缺失的引用目标和不可追溯来源。

数字按独立数值 token 比对，保留表格单元格边界；2,383.2 和 2383.20 视为数值等价，820 不匹配 1820。单位、年份和适用范围从段落/章节/表头整体核对，不要求每个片段重复抄齐。
四舍五入、单位转换、简单算术允许记录 source_value（原值）和 transformation（说明），显示值不能伪装成来源原值；跨范围、跨年份差异不能自动消解。
普通事实允许归纳、OCR校正和表格转录。直接引语保留逐字含义核对，允许抽取造成的空白差异；不得把转述伪装成引语。

复读一次原文是否支持主体、时间、因果和适用范围。不要求 support_check 表；愿意记录时可在实体上写一次，也兼容旧 binding 记录。
qualified 只需在 notes/limitations 任何一处保留有效限制，无固定 usable/medium 组合要求。明确 unsupported/mismatch 的内容不能进入可用账本。
这是同一研究员自查，不是独立评审；哈希、回执和已填写的表格都不能证明结论真实。

## 可选严格模式

只有用户明确要求逐字、逐源审计时才设置 text-bound-v1。它保留本地原文、逐字摘录、哈希和抓取记录核对，不作为普通作业默认，也不能因解析失败擅自开启或升级。
semantic_review_required 为兼容提示，普通模式不产生逐绑定审查门槛。

## 来源分级与交叉核验

S/A/B/C/D 为标注元数据，不是门槛；不得为升级等级继续搜索。观点来源按观点归属表述，不冒充公认事实。
high 或 cross_check 要求至少两个独立来源。根据原始报告/数据集判断独立性；同 origin_id 或声明组的转载合并。同一域名不必然同源，跨域也不必然独立，不按域名硬合并。
冲突先检查年份、地区、单位和统计定义；实质冲突保留记录和限制，不任挑一个数字。

## 失败与停止

- backend_not_executed 只来自结构化运行时执行状态，暂停 WebSearch；WebFetch、主源直取、文件解析仍可用。
- unknown_payload 是格式未知，仅诊断；空结果不证明内容不存在。
- 同端点不同请求返回相同字节记 degenerate_channels 诊断，不永久禁止后续新 URL。
- 验证码、付费或登录受阻记录 access_blocked；允许换合法可用路线，不绕过访问控制。
- 修正语言、名称、年份、过滤条件，以及用已知数字追查出处，均可合理执行；不因查询外形要求修脚本。
- 核心满足后优先交付；继续必须有具体缺口或补检目标，不能无目的重复。

状态：located 仅定位；usable 已有支持并保留限制；verified 满足任务核验；unresolved 记录缺口。located/unresolved 不进入事实账本。
交付：ready 完整；partial 仅有辅助缺口；insufficient 有核心缺口。有效 JSON 不等于研究充分，核心缺口仍阻止作为已完成证据编译。
明确停止请求始终生效。任务调整自动重新判断，不以文件字节变化阻断。

## 交接和诊断

研究结果放项目 outputs/.pptx-work/<work-id>；不写安装插件或市场仓库。
默认回 RESEARCH_DONE/RESEARCH_BLOCKED 路径与状态；原始材料留文件。遇到疑点可附少量关键证据供主会话复核，不倾倒整页正文。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/research_handoff.py" --work-dir <work-dir>
```

交接校验当前内容并自动刷新报告。不要求旧校验报告、研究员身份回执或 Pack 哈希链相互锁定；报告和执行统计是工具维护的观测信息。
compiler 同样校验当前内容，自动刷新传入的旧报告。实际内容错误仍需修复，不为 stale receipt 反复重建 Pack。
搜索载荷由 hooks 自动记录；模型不用在查询表、日志和载荷里重复抄写。没有 WebSearch 的合法直取无需编造 queries。

`validate_research_pack.py --audit` 可选输出检索诊断（含重复查询、长查询和数字回显），不需要清零，不要求逐项解释。默认不报告 unused_source、claim数量或查询形状噪声。
Read/Grep 使用适当窗口控制上下文；允许自写有界读取和其他解析器。research_excerpt.py 只是便利工具，可指定最大摘录长度，不强制2000字符上限或固定目录名。

## 任务忠实与通知收口

claim 验收条件来自用户目标、材料和已确认摘要。研究员可解释含义或提出增强建议，但不得把宽泛趋势擅自改成特定年份/地区/容量分布的必填指标，不为自己新增的精确条件判定核心不足。需要新增事实时先核实依据。换词或语序调整不算事实纠正。

当前交接结果为准。正常结束通知与后台完成事件若指向同一份包，不触发再次审查、补检或PPT重建。只针对实际错误、明确缺口或实质变化继续。没有可选hook回执不表示任务失败；先读取一次权威状态，只有状态改变或明确故障才继续查询，不反复轮询。正常任务不预读校验器实现、不遍历全部API；遇到具体错误且用法说明不足时才定点排查。

研究员校验、handoff和证据编译共享当前输入校验缓存；任务、权限或绑定原文变化会失效，报告刷新不算新证据。当前验证显示核心缺口或旧结论失效时，sufficient_evidence自动解除；用户明确停止继续生效。主流程只消费一次交接，不让outline重复调用相同handoff。
