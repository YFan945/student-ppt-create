# Live E2E 提示词与运行说明（评审第 14 项）

评审第 14 项要求"真实 Claude Code Live E2E"。它其实是两个不同的问题，混淆后才显得不可负担：

| 问题 | 含义 | 能否机械断言 | 载体 |
| --- | --- | --- | --- |
| **MECHANISM** | 主流程是否真的在独立 context 里起了一个前台子代理（0.12.0 起为显式 spawn `presentation-researcher`） | 便宜、与模型无关 → 可经常跑、可断言 | `scripts/smoke_research_fork.py`（用 `claude -p --output-format json` 的 `subagent_stats`） |
| **ARTIFACT** | 那个子代理是否真的产出了符合 schema 的 Research Pack | 取决于模型与网络是否放行 | 同上，外加 `validate_research_pack.py` |

机制半边是 item 14 的核心——它把"文档说检索被隔离"变成"运行时确实 spawn 了一个前台子代理"的硬证据。
**判定标准（0.12.0 起）**：`subagent_stats.spawned >= 1`，且 `started_in_background == 0`。
`context: fork` 的 fork 事件不再被接受为替代证据：两次 Live 实测都在 `spawned = 0` 的情况下
没有任何 subagent 事件，而 skill 实际内联跑在主会话里（见 `FINDINGS.md` 第三、六节）。
产物半边（真实联网检索质量）需要真实模型 + 网络，成本随网络放开，单独报告。

## Headless 权限（`claude -p`）

`--permission-mode acceptEdits` 只自动放行工作目录（及 `--add-dir`）里的写文件和常见
`mkdir`/`mv`/`cp`。研究员要 Read 插件根下的 references / 跑 `validate_research_pack.py`，
以及 Bash / PowerShell，在 `-p` 下会变成 `permission_denials`（0.13.0 实测，见
`FINDINGS.md` 第七节）。

脚手架因此会：

- `--add-dir <plugin-dir>`，让插件根成为额外工作目录
- `--allowedTools` 预放行 `presentation-researcher` 的工具，外加父会话 spawn 用的 `Agent` / `Skill`
- 场景 D 再加 `--disallowedTools WebSearch,WebFetch`（禁网失败即关）
- **不用** `bypassPermissions`

`permission_denials` 非空时，机制半边仍然失败。不要把 denials 从判定里拿掉。

## 目录内容

- `ai-agent-trends-2026.brief.md` —— 场景 A 的 Presentation Brief（联网，2026 AI Agent 趋势）
- `own-paper-d-mode.brief.md` —— 场景 D 的 Presentation Brief（禁网，仅用用户论文）
- `sample-paper.md` —— D 模式样例材料（真实使用时替换为 owner 自己的论文）
- `run-ai-agent-trends.md` —— 场景 A 的完整 Live E2E 提示词 / 运行单（含校验链 + 复盘数字表）
- `run-own-paper-d-mode.md` —— 场景 D 的完整 Live E2E 提示词 / 运行单

## 两种跑法

### A. 经脚手架（推荐，自动断言）

```bash
# 场景 A（联网）
python plugins/student-presentation-suite/scripts/smoke_research_fork.py \
  --plugin-dir plugins/student-presentation-suite --scenario ai-agent-trends \
  --model <model> --max-budget-usd 3 --validate \
  --output outputs/_analysis/live-a-result.json

# 场景 D（禁网）
python plugins/student-presentation-suite/scripts/smoke_research_fork.py \
  --plugin-dir plugins/student-presentation-suite --scenario d-mode \
  --materials plugins/student-presentation-suite/scripts/live_prompts/sample-paper.md \
  --model <model> --max-budget-usd 1 --validate \
  --output outputs/_analysis/live-d-result.json
```

`--scenario smoke` 使用一条明确的 Python 官方文档论断，普通单源 medium 即可。
加 `--stream --output <临时项目路径>/result.json` 会同时保存 `result.stream.jsonl`，
用于区分主流程准备、子代理检索与交接耗时；预算耗尽或权限拒绝不算端到端通过。

退出码：0 = 机制 ok 且产物落地；2 = 机制失败（fork 没发生）；3 = 机制 ok 但没写出 Research Pack。

### B. 裸跑（看 envelope）

```bash
claude -p "/student-presentation-suite:sp-research <work_id> <brief绝对路径> <scope> <materials>" \
  --plugin-dir plugins/student-presentation-suite \
  --add-dir plugins/student-presentation-suite \
  --output-format json \
  --allowedTools "Read,Write,Edit,Grep,Glob,Bash,PowerShell,Agent,Skill,WebSearch,WebFetch" \
  --permission-mode acceptEdits --max-budget-usd <n> --no-session-persistence
```

场景 D 把 `WebSearch,WebFetch` 从 `--allowedTools` 拿掉，并加上
`--disallowedTools "WebSearch,WebFetch"`。完整命令见 `run-own-paper-d-mode.md`。

## 默认模型被限流时

`claude` 的限流按模型隔离。若默认模型 429，用 `--model <其他模型>` 切过去即可继续。
smoke 脚手架透传 `--model`，直接加在命令后。

## 事后复盘要记的数字

两份 `run-*.md` 末尾各有一张表（`subagent_stats.spawned`、`total_cost_usd`、`terminal_reason`、
pack 各项计数、`validate_research_pack` 的 `ok`、D 模式还要记 `queries` 长度与 source type）。
跑完把实际数字填进去，作为"真实运行验证"的凭据。

## 复杂联网研究验收

从仓库根目录执行：

```powershell
python plugins/student-presentation-suite/scripts/research_acceptance_matrix.py --output-dir "$env:TEMP/research-acceptance"
```

三项实际 Claude 运行：中文技术文档多论断、GIL 独立交叉核验、指定缺失链接后的 partial 交接。
前两项强制核验实际 WebSearch 事件。缺失链接是人为故障注入，不是真实文献。
每个场景输出原始 result/stream、独立工作目录和 matrix.json，记录耗时、工具数、搜索调用、
日志失败数、核心缺口及交付状态。报告逐场景给出通过条件，失败不算机制成功。
每次只运行一个样本，不报告总体成功率；查询失败数是日志口径，不是自动语义相关性评分。
可用 --case multi-cn|cross-check|gap 单独复测。每场景费用上限 $3，Claude 子进程等待上限 420 秒（超时终止进程树并保留事件流），外层等待上限 600 秒。

2026-10-01 的真实运行结果、前轮失败及修复边界见 [研究验收记录](research-acceptance-2026-10-01.md)。
