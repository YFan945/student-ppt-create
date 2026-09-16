# 0.13.0 修复与验收记录

日期：2026-09-16。基线：main / d152cdb / 0.12.0。

| 检查项 | 本次落地 | 验收证据/边界 |
| --- | --- | --- |
| 1. QA notes / preview 接线 | QA 自动取 speaker-notes.md 和当前逐页 PNG，contact sheet 单独绑定 | 原样解析 next_command 到真实 delivery CLI；讲稿不缺失、预览覆盖 1/1；合成 gate 报告不会通过真实 delivery |
| 2. 生产模式 | create / edit_ooxml / rebuild_from_source 纳入 manifest；编辑解包/打包，重建要求 source-analysis | 真实 OOXML 编辑后重新打开、文本已变、原文件字节不变；PDF/图片不再走 create |
| 3. 工作流隔离 | work-id 私有 state，摘要和身份校验；benchmark 同步 | 两个 work-id 独立 plan；跨任务镜像被拒绝；旧全局状态须重新确认 |
| 4. Research | 真实子代理生命周期和成功 Write 生成 pack receipt；A/B/D plan 验证 | D-mode 实测 spawned=1、completed=1、foreground；9 findings / 5 sources，validator 0 blockers。首次严格 smoke 有权限拒绝，见 live_prompts/FINDINGS.md |
| 5. Visual critic | 独立 visual-critic，验证成功 Read 的全页 PNG/contact hash | 实测 spawned=1、completed=1、权限拒绝=0；4 张图的 Read hash 和报告全部匹配，消耗 $0.419370 |
| 6. 输出边界 | work-dir 必须位于项目 outputs/.pptx-work；禁止插件/marketplace 内生产，阻止输出名穿越和外部文件归档 | 边界拒绝测试通过；这不是执行任意用户脚本的 OS sandbox |
| 7. 核心 lint | Ruff 包含 skills | 本机完整 Ruff、ESLint、Prettier 通过 |
| 8. 发布治理 | main 必需 release-ready、禁止强推/删除；release workflow 先复用全部 validate jobs | 已通过 GitHub API 配置；保留管理员直接 push 权限以符合 owner 工作流。管理员仍能绕过平台检查，本项目发布流程不绕过 |
| 9. PowerPoint | COM smoke + 人工检查清单 | Office 16.0 实际只读打开并导出 3/3 页；逐页查看中英文字、图表和 raster crop/alpha。SVG、复杂母版、动画、编辑保存重开未测 |
| 10. Provider 授权 | 项目 JSON 不能授权 command；调用端另传用户批准的 command SHA256 | 未授权不执行，原 user-assets 路径保留；不抵御可任意改写本地代码的恶意进程 |
| 11. 首次 reference 成本 | next 从机器契约选取紧凑 stage contract，入口不预读整套 references | 按阶段提供规则和 policy hash；本次没有重跑 6-deck benchmark，不声称已测得整体 token 降幅 |
| 12. 文档漂移 | 修正未发布的 0.11.2、旧分支开篇及旧 QA 描述，增加当前文档检查 | 发布检查通过；历史 changelog 保留迁移历史，不把历史说明误判成当前安装源 |
| 13. 可复现性 | Claude Code 2.1.272、Ruff 0.16.7、pip-audit 2.9.0；Python 3.11/3.12 × Windows/Linux | CI 矩阵负责四种组合；本机测试使用 Python 3.11 |

附加修复：gate 的 `ok:false` 即使退出 0 也必须阻断；每轮先清除旧报告，防止失败后复用上轮成功报告；complete 再核对讲稿、预览、critic 和 QA 报告 hash。并行图片 hooks 按子代理序列化，避免 Read hash 被并发写入覆盖。

自动测试覆盖状态机、真实 delivery 接线、OOXML 编辑、重建模式、跨任务身份、路径边界、图片篡改、讲稿变动和独立 hook 凭据。全部 lint、插件/marketplace release checks、strict Claude manifests、runtime 环境检查和带渲染 smoke 均需通过后才发布。

运行时 hook 字段依据 [Claude Code 官方 hooks reference](https://code.claude.com/docs/en/hooks)，并已通过本机真实 child 运行验证。凭据是可信本机会话中的执行完整性记录，不是针对本机文件写入者的密码学证明，也不能证明模型审美评分客观正确。

本机最终测试：499 项，498 通过、1 项按环境条件跳过；benchmark 迁移后另复跑 27 项通过。runtime smoke 含实际渲染通过，strict 环境检查通过。
