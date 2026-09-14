# Live E2E 提示词与运行说明（评审第 14 项）

评审第 14 项要求"真实 Claude Code Live E2E"。它其实是两个不同的问题，混淆后才显得不可负担：

| 问题 | 含义 | 能否机械断言 | 载体 |
| --- | --- | --- | --- |
| **MECHANISM** | `context: fork` + `agent: <plugin>:<name>` 是否真的在独立 context 里起了一个前台子代理 | 便宜、与模型无关 → 可经常跑、可断言 | `scripts/smoke_research_fork.py`（用 `claude -p --output-format json` 的 `subagent_stats`） |
| **ARTIFACT** | 那个子代理是否真的产出了符合 schema 的 Research Pack | 取决于模型与网络是否放行 | 同上，外加 `validate_research_pack.py` |

机制半边是 item 14 的核心——它把"文档说检索被隔离"变成"运行时确实 fork 了一个前台子代理"的硬证据。
产物半边（真实联网检索质量）需要真实模型 + 网络，成本随网络放开，单独报告。

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

退出码：0 = 机制 ok 且产物落地；2 = 机制失败（fork 没发生）；3 = 机制 ok 但没写出 Research Pack。

### B. 裸跑（看 envelope）

```bash
claude -p "/student-presentation-suite:sp-research <work_id> <brief绝对路径> <scope> <materials>" \
  --plugin-dir plugins/student-presentation-suite \
  --output-format json \
  --permission-mode acceptEdits --max-budget-usd <n> --no-session-persistence
```

## 默认模型被限流时

`claude` 的限流按模型隔离。若默认模型 429，用 `--model <其他模型>` 切过去即可继续。
smoke 脚手架透传 `--model`，直接加在命令后。

## 事后复盘要记的数字

两份 `run-*.md` 末尾各有一张表（`subagent_stats.spawned`、`total_cost_usd`、`terminal_reason`、
pack 各项计数、`validate_research_pack` 的 `ok`、D 模式还要记 `queries` 长度与 source type）。
跑完把实际数字填进去，作为"真实运行验证"的凭据。
