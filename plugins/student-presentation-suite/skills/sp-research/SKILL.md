---
name: sp-research
description: Use only for a clearly student-owned academic context when a deck needs external facts, current data, statistics, or citations that must not be invented, or when the user restricts sourcing to their own material. Collects, grades, and cross-checks sources into a Research Pack. Does not design slides, write speaker notes, or produce PPTX.
version: 0.10.0
---

# Student Presentation Research

为需要外部知识支撑的内容提供**筛选过、可追溯、可引用、可直接进入 Slide Spec** 的研究材料。

设计宗旨：**Search for evidence, not text.** 不是"帮 PPT 找点内容"，而是"识别需要证据
支持的论断，检索高质量来源，完成交叉验证，压缩成结构化 Research Pack"。

## 职责

- 判断哪些内容该查、哪些不该查 → 本 skill
- 检索、分级、交叉验证、留痕 → 本 skill
- 排页、写正文、写讲稿 → `sp-outline`
- 可编辑 PPTX / 版式 / 视觉 → `sp-deck`
- 审查与评分 → `sp-review`

**只做证据层。** 不决定版式、不设计页面、不生成 PPTX、不改视觉风格、不撰写成段讲稿。
职责混在一起会污染后面每一层的产物。

## 快速约束

- 加载 `../../references/research-workflow.md`（A/B/C/D 判定、分级、交叉验证、预算、留痕）
- 加载 `../../references/evidence-and-citations.md`（Claim → Evidence → Source 链路）
- 产出只按 `../../references/research-pack.schema.json` 的形状，**不写自然语言小作文**
- 检索一律在子代理内完成；主流程只接收 Research Pack，不接收原始网页
- 不编造数字、日期、机构、引文；查不到就进 `unresolved`，不许静默降级
- 输出写入 `outputs/`，不得写入 `${CLAUDE_PLUGIN_ROOT}`

## 工作流

1. **Research Need Analysis**：读 Presentation Brief 与 Slide Spec 草稿，把待证内容拆成
   逐条 Claim，判定 A / B / C / D，并给出优先级。C 类不消耗预算，D 类立即停止检索。
2. **定档位**：按 `scenario` 推导 `simple` / `standard` / `deep`（见 research-workflow.md
   第七节），用户可覆盖。
3. **逐 Claim 检索**：以 Claim 而非主题为调用单位；对每个待证论断选来源、取数、记录
   `url` 或 `locator`。
4. **分级与交叉验证**：按 Tier S/A/B/C/D 标注来源；数字必须多源比对，量级不一致时标
   `conflict: true` 并把 `confidence` 降为 `low`，同时在 `conflicts` 里逐条列出取值与来源。
5. **补知识缺口**：把"发展迅速"这类未量化陈述标为 `knowledge_gaps` 并去补；补不上的
   明确标 `unresolved: true` 并写原因。
6. **标可视化机会**：把适合画图的材料标成 `visual_candidates`（类型 + 优先级），只标
   类型，不决定画法。
7. **校验并交接**：运行 `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_research_pack.py"
   <research-pack.json>`，0 blocker 后把 `research-pack.json` 交给 `sp-outline`。

## 输出契约

- 唯一交付物 `outputs/.pptx-work/<work-id>/research-pack.json`（形状见 schema）
- 原始检索结果落盘 `outputs/.pptx-work/<work-id>/research/<topic>.json`，**不回传主流程**
- `queries` 只记录**实际执行过**的检索词，用于复现与审计
- 检索受阻写进 `unresolved`（`access_blocked` / `not_found` / `tier_unavailable` /
  `paywalled` / `out_of_budget`），并写明对论断的影响
- 校验报告 `research-pack-validation.json` 随 pack 一起留存

## 与图片检索的分工

本 skill 只负责**知识**（事实、数据、论文、引用、证据）。照片、示意图、截图、Logo 等
视觉素材走 `image-sourcing.md` 的能力声明与权限门禁，两者优化目标不同，不合并。
