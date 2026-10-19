# Art Direction 文件契约

`plan --art-direction <file.yaml|json>` 可选地绑定一份 Art Direction 文件。文件分两层键，两层可写在同一文件里（`examples/golden-sample/art-direction.yaml` 即如此）：

- **Token 键**：被生成路径直接消费，决定 deck.js 内联 TOKENS 的解析。
- **设计语言键**：v0.8 Art Direction 工件，由 `art_direction_check.py` 在冻结门禁校验，约束整副 deck 的视觉决策；不进入 TOKENS。

设计自由度与语义层级规则归 `model-led-design.md`，本文只写文件键契约。

## Token 键（生成路径消费）

| 键 | 类型 | 默认 | 消费点 | 作用 |
| --- | --- | --- | --- | --- |
| `style_seed` | string | Spec `meta.visual_style` | scaffold、`pptx_palette_check` | 风格名，解析 `references/design-tokens.json` 对应风格。scaffold 取 `style_seed` → `visual_style` 第一个非空；`pptx_palette_check` 同级另接受 `style_id` |
| `visual_style_custom` | object | — | scaffold、`pptx_palette_check` | `visual_style` 为 Other 时的自定义风格记录：`style_character` / `palette` / `dark_palette`(可选，缺省推导) / `backgrounds` / `svg_reference`，校验见 `shared/design_tokens.validate_custom_style` |
| `topic_accent` | 6 位 hex string | — | scaffold、`pptx_palette_check` | 把 `primary_accent` 移到该色相（保留种子亮度；对比度不达标则忽略），并重推导 `dark_palette` |
| `typography` | object | — | scaffold（model-led）、`copy_fit_preflight` | 整套字体定制通道：覆盖 `title_font` / `body_font` / `cjk_title_font` / `cjk_body_font` 等 `*_font` 键，合入内联 TOKENS 并驱动构建期 Latin→CJK `<a:ea>` 映射 |
| `palette_mode` | `"light"` \| `"dark"` | `"light"` | scaffold | `"dark"` 时把该风格解析后的 `dark_palette` 提升为 TOKENS 的 `palette`，整副 deck 默认深色，见下节；缺省/`"light"` 行为与未引入此键前逐字一致 |

未列入上表的键不进入 TOKENS。需要调整配色/字体时优先在这里声明，而不是手工改 `deck.js`——手工删除脚手架 marker 后 `deck.js` 冻结，scaffold 不再重写它。

## 深色模式：`palette_mode: "dark"`

每种内置风格在 `design-tokens.json` 都带 `dark_palette`（自定义风格未提供时由 `derive_dark_palette` 推导）。默认 `"light"` 只使用浅色 `palette`。设为 `"dark"` 时：

- TOKENS.`palette` = 该风格的 `dark_palette`；chart 分类色等附加角色已在解析期按深色表面适配，随之一并进入 `palette`。
- TOKENS.`palette_mode` = `"dark"`；TOKENS.`dark_palette` 原样保留，封面/章节/结尾页的 `paletteMode(tokens, 'dark')` 深浅三明治机制不受影响，内容页经默认 `palette` 解析到深色角色。
- `pptx_palette_check` 按浅、深两盘颜色的并集判定，深色 deck 无需额外开门。

这与设计语言键 `background_rhythm` 的页级 dark/light 三明治是两件事：`background_rhythm` 决定哪些页面用深盘，`palette_mode` 决定整副 deck 的默认盘。整副深色时选 `palette_mode: "dark"`，再配深色气质的风格（如 Ocean Tech、Midnight Business）作 `style_seed`。

拼写错误或未知值（如 `drak`）会被 `art_direction_check` 以 major 阻断——不会静默回落浅色。

## 设计语言键（v0.8 工件，`art_direction_check.py` 校验）

以下节必须存在且非空：`concept`、`color_system`、`typography`、`imagery`、`icon_language`、`chart_grammar`、`component_language`、`motif`、`background_rhythm`、`asset_plan`、`high_leverage_slides`。

| 节 | 键型 | 校验要点（细节以实现为准） |
| --- | --- | --- |
| `concept` | string | 视觉论题，过短报 minor |
| `color_system` | object | `dominant_share_pct` 必填，正常 55–75；`dominant_role` / `contrast_mode` / `accent_usage` 为自由文本 |
| `typography` | object | `slide_title_pt`、`body_pt` 必填；`cover_title_pt` / `key_statement_pt` / `caption_pt` 可选；model-led 下所有 `*_pt` 必须是正数 |
| `imagery` | object | `crop_language`、`treatment` 必填 |
| `icon_language` | object | 自由文本（usage/style/max_per_slide） |
| `chart_grammar` | object | `default`、`takeaway` 必填；文本不得承诺 line 系列描边/虚线编码（pptxgenjs 不支持） |
| `component_language` | object | `cards` 必填 |
| `motif` | object | `name` / `description` / `allowed_on` |
| `background_rhythm` | list | ≥3 条 `{role, mode}`（cover/content/section/closing）；high-score 至少两种 mode |
| `asset_plan` | object | 计数键 `hero_visuals` / `evidence_visuals` / `diagrams` / `native_charts` / `typography_led`；图像类 visual 需已声明图源，否则按能力分级 major/minor |
| `high_leverage_slides` | list | high-score：3–5 条 `{slide, reason}`，slide 为唯一正整数 |

文件级可选键：`version`、`grammar`、`avoid`（作者自查清单，门禁不读取）。

参考示例：`examples/golden-sample/art-direction.yaml` 是浅色正文 + 深封面/深结尾的三明治，未设 `palette_mode`（即默认 `"light"`）。
