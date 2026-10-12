# Model-led design

主会话负责整套页面的构图、实现、看图和修改。新任务默认 `design_freedom: auto`，与 `quality_level` 独立。

- `auto`：自由坐标页面，直接使用共享绘图工具；harness 统一登记元素、写讲稿和构建报告。
- `guided`：作者明确选用现有六种 move。
- `deterministic`：作者选用现有布局库及组件。

后两者是可选工具。遇到表达或适配问题，作者可以改字号、区域、文案或选择另一种工具，不按失败次数自动改变设计模式。用户品牌、模板、logo 和明确保留项继续有效。

gallery、配色、panel、motif 和字号只是参考。Art Direction 可选，不能成为构图前的文书负担。先看真实素材，明确一页需要解释的关系，再选择视觉表达；禁止编造比较数据。没有全局字号地板、统一比例、图片配额或必须模仿的 treatment。

Slide Spec 2.1 冻结 `semantic_requirements.must_convey` 和 `must_show_exact`；展示文案可重写。实际文案保存为 `presentation_copy`。精确项和数字采用完整 token 回读检查，旧 1.0/2.0 保留原匹配行为。

核心语义、证据边界及视觉表达由同一主会话对照当前页面、实际文本和讲稿自检。**不再提供独立 critic 验收，不把自检描述成独立核验。** 生产工具检查事实精确项、文件有效性和当前渲染绑定，不评分审美。

文本使用共享 fontkit 测量与中文断行。字体测量不能替代看最终渲染。字号必须是有效正数；接口返回具体几何问题，作者在原修复预算内直接改页。

旧 Spec 可读取；旧工作记录仅保留查看，不自动迁移。生产命令与写法见 `../skills/sp-deck/references/main-session-production.md`。
