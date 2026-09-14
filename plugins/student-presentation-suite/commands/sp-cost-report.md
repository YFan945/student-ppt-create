---
name: sp-cost-report
description: 复盘一次会话的 token 与时间成本。解析会话日志，输出账目、上下文增长曲线、工具耗时排名与成本病灶。
---

# 会话成本复盘

运行 `${CLAUDE_PLUGIN_ROOT}/scripts/session_cost.py` 输出成本复盘报告。

## 用法

| 参数 | 作用 |
| --- | --- |
| （无参数） | 最近一次会话 |
| `--list` | 列出候选 transcript（按修改时间倒序） |
| `--last <n>` | 最近 n 次会话 |
| `--project <目录名>` | 按项目过滤，如 `E--test-ppt` |
| `--session <path>` | 指定 transcript |
| `--json` | 机器可读输出 |

日志位置：`<CLAUDE_CONFIG_DIR 或 ~/.claude>/projects/<项目>/<sessionId>.jsonl`。

## 何时运行

- 一次 PPTX 任务结束后，确认实际开销；
- 感觉某次会话"慢/贵"但说不清原因时；
- 调整 `references/cost-discipline.md` 的约束后，对比前后效果。

## 报告读法

报告按 `cost-discipline.md` 的乘法模型组织：

```text
总 token ≈ 请求数 × 平均常驻上下文
总时间  ≈ 请求数 × 单次预填充时间
```

重点看三处：

1. **Context buckets** — 多少比例的请求跑在 20 万 token 以上（对应 CD-4 阶段小结）；
2. **Tools 表** — 哪个工具的调用次数与输入体积最大（对应 CD-1 合并调用、CD-2 定点编辑）；
3. **Warnings** — 整文件重写、请求/工具往返比过高、cache-read 占比过高的自动提示。

报告只用于复盘，不改变任何产物，也不影响 `sp-deck` 的状态机。
