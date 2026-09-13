# Visual Template Gallery（视觉模板样张库）

每分钟回答一个问题：**"这个风格做出来到底长什么样？"**

本目录的生成器为 **12 种风格各渲染 12 页高质量模板页**（共 144 页），页面实现全部来自
`skills/sp-deck/references/layout-library.json` 的归一化分区（normalized-safe-area），
配色、字号层级、母题与装饰来自 `references/design-tokens.json` 的
`palette` + `dark_palette` + `visual_language` + `svg_reference`。
因此这里渲染出的每一页都是风格契约的诚实实现，可直接作为生成时的视觉参考锚点。

## 每种风格包含的 9 种版式

| # | 版式 | layout id | 模式 | 演示内容 |
|---|------|-----------|------|----------|
| 1 | 分栏封面 | `cover-split` | 深色 | 眉标 + 大标题 + 副标题 + 母题视觉区 |
| 2 | 章节陈述 | `section-statement` | 深色 | 超大编号 + 章节标题 + 一句导语 |
| 3 | 论点聚焦 | `claim-focus` | 浅色 | 超大论点 + 强调行 + 判断规则行 |
| 4 | 数据论证 | `data-chart-takeaway` | 浅色 | 大数字先读 + 手绘图表（无网格线） |
| 5 | 前后对比 | `compare-before-after` | 浅色 | 不对称双面板（推荐方案占主导） |
| 6 | 时间线路径 | `timeline-roadmap` | 浅色 | 4 节点推理链 + 强调终点 + 结论面板 |
| 7 | 引语聚焦 | `quote-focus` | 浅色 | 大引号 + 金句 + 出处 |
| 8 | 图注案例 | `visual-annotated` | 浅色 | 风格化几何插图 + 逐条标注 |
| 9 | 收尾呼应 | `closing-takeaway` | 深色 | 回扣封面论点 + 来源栏 + Q&A |
| 10 | KPI 看板 | `data-kpi-row` | 浅色 | 三卡指标 + `emphasis` 放大关键数字 |
| 11 | 架构分层 | `architecture-layered` | 浅色 | 流程分层结构（取证写进流程） |
| 12 | 参考文献 | `references-clean` | 浅色 | `emphasis_marker` 逐条标注 + 证据闭环说明 |

## 风格个性来自 `visual_language`

同一版式在不同风格下呈现不同性格，由 design-tokens.json 中每风格的
`visual_language` 字段驱动：

- `rule` — 强调规则线手法：`bracket`（学术角括）/ `left-rail`（左竖轨）/
  `underline-left`（左对齐下划线）/ `top-band`（顶部色带）/ `slash`（斜切）
- `panel` — 面板处理：`outlined`（描边）/ `flush`（无面板纯排版）/
  `soft-fill`（浅面填充）/ `edge-band`（左缘强调条）
- `radius` — 圆角半径（极简/炭黑为直角，创意/珊瑚为大圆角）
- `motif_at` — SVG 母题位置：右上角 / 左下角 / 右缘
- `chart` — 签名图表语法：`columns`（柱）/ `line`（折线）/ `bars`（条形）
- `decor` — 装饰密度：`restrained`（克制，母题仅正文页）/ `balanced` / `expressive`
- `pattern` — 背景纹理：`dots` / `waves` / `grid` / `none`（章节页按 decor 密度调透明度）
- `emphasis_marker` — 列表强调符：`dot` / `square` / `slash` / `chevron` / `number` / `dash` / `leaf`
- `cover_band` — 封面装饰几何：`bottom-band` / `side-band` / `corner-block` / `none`

## 构建与产物

```bash
python examples/visual-template-gallery/build.py            # 生成 + 校验 + 渲染
python examples/visual-template-gallery/build.py --skip-render
```

产物（`.gitignore` 排除，不入库）：

- `outputs/visual-template-gallery/visual-template-gallery.pptx` — 144 页合订样张
- `outputs/visual-template-gallery/render/tpl-*.png` — 每页渲染图

`gallery-input.json` 由 `build.py` 从 `resolve_design_tokens()` 生成后写回本目录
（入库），是生成器的确定输入。

## 用法约定

- 生成正式 deck 前，可查阅对应风格的渲染页作为"上限参考"，但**不要复制页面内容**——
  样张的主题（AI 幻觉课程汇报）只是占位文案。
- 样张页通过全部文本适配守卫与打包校验；若自己的页面达不到同等的留白与层级，
  按 `pptx-visual-critic.md` 的返修路径处理，而不是放宽守卫。
