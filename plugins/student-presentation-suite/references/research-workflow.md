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
| **C 不用查** | 与外部事实无关的任务：过渡页、把已有材料概括成三点、重排用户提供的结构 | 不消耗检索预算 |
| **D 禁止查** | 用户明确限定范围："只根据我上传的论文 / 只用课程 PPT / 不要用外部资料" | 立即停止检索，只整理用户材料 |

D 类是硬约束：一旦触发，`sp-research` 不发起任何检索，只把用户材料整理成 Research Pack
（`queries` 为空、`sources` 只含用户材料）。

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

## 四、来源分级

| Tier | 内容 | 可用于 |
| --- | --- | --- |
| **S** | 法律法规、官方文件、官方数据库、论文原文、政府统计数据 | 一切 |
| **A** | 顶会论文、权威研究机构、高校、国际组织、上市公司财报 | 一切 |
| **B** | 主流媒体（Reuters / Bloomberg / Nature News 等） | 事实依据、行业趋势、案例 |
| **C** | 技术博客、行业博客、厂商博客 | 案例、实现细节；**不作为事实依据** |
| **D** | 论坛、社区、个人博客 | **仅**可作为"用户观点/舆论"引用 |

不同用途的最低要求：

| 用途 | 最低 tier |
| --- | --- |
| 事实依据、数字 | **S / A**（`data_point` 至少 S/A/B） |
| 行业趋势判断 | S / A / B |
| 案例 | A / B / C |
| 用户观点、舆论 | 可以 D |

`validate_research_pack.py` 会强制前两条：`confidence: high` 的 finding 必须至少有一个
S/A 来源；任何 `data_point` 必须至少有一个 S/A/B 来源；只有 D 级来源的 finding 不能
声明为 medium 及以上。

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

## 七、预算

| 档位 | max queries | max sources | 适用 |
| --- | --- | --- | --- |
| `simple` | 3 | 5 | 普通课程展示、小组作业 |
| `standard` | 8 | 12 | 课程答辩、结题答辩 |
| `deep` | 15 | 25 | 论文汇报、竞赛答辩、毕业答辩 |

检索还要限制页面抓取次数：`simple` 12 次、`standard` 30 次、`deep` 50 次
`WebFetch`。同一 URL 复用已抓取结果，失败最多重试一次。达到上限后，优先保留
会上屏的关键论断；其余记入 `unresolved`，不得把未经核实的数字写成已验证。
`research-execution.json` 记录实际 `WebSearch` / `WebFetch` 次数，供成本复盘。

默认由 `scenario` 推导，用户可覆盖。硬约束是：**不要为了某一页的一句话搜索二十个网页。**
超限由 `validate_research_pack.py` 拦截。

**档位必须按证据需求选，scenario 只定默认**：需核验的数据点/claims ≥ 10 或 slide_count ≥ 12
时至少 `standard`；≥ 18 或 slide_count ≥ 15 时用 `deep`。宁可初始档位高一级——cap 触发后的
gap-fill 重入实测代价约 7 个请求（主会话 SendMessage + 等待 + 核验，研究员重入 + 重校验；
2026-09-19 实测），而同样的检索在第一次暖上下文里多跑只多 1–2 个请求。上限拦截的本意是防
"为一句话搜二十个网页"，不是把 8 个维度的 deck 压进 5 个维度的预算（2026-09-17 live：
deep 16/15 被迫整轮回退、12 页压成 10 页——那就是档位选低了，不是研究员浪费）。

### 补检（gap-fill）与预算申报

- 授权补检前，主会话必须先报告**剩余额度**（`ppt_pipeline.py next` 在 work-dir 有
  pack 时会给出 `budget: {band, used, cap, approved_headroom, remaining}`），授权消息
  必须写明剩余次数；研究员耗尽即停。
- 补检确实需要超出档位上限时，唯一合规路径是在 pack 里写
  `budget_extension: {extra_queries: N, approved_by: user, reason: ...}`——必须由用户
  明确批准。**禁止删除已执行的 queries 记录来迎合上限**（2026-09-17 live：deep 档
  16/15 被迫回退整轮 gap-fill，12 页压成 10 页）。
- `validate_research_pack.py` 按 `cap + extra_queries` 放行；申报字段不完整（缺
  reason / approved_by 不是 user / extra_queries < 1）判 `budget_extension_invalid`。

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
每次实际执行的检索（含并发失败/超时重试，标 `status: failed`）；gap-fill 的检索必须
**追加**写入该日志（`n` 续号），不得只改 pack。预算计数以 `pack.queries` 成功记录为准，
失败调用不占额，但没有日志留痕就无法审计这个差额（2026-09-19 实测：search-log 停在
初始 7 条，gap-fill 第 8 条检索只存在于 pack，日志与事实脱节）。

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
- Research Pack 里每条 `source` 都有 `url` 或 `locator`（可追溯）；
- 每个 `data_point` 的 `confidence: high` 都有 ≥2 个独立来源；
- 出现 `conflict: true` 的条目同时 `confidence: low`，且有对应 `conflicts` 记录；
- 检索受阻都出现在 `unresolved` 里，没有静默降级；
- `queries` / `sources` 数量在所选档位上限内。
