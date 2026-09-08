# 微信小程序动画与视觉效果：能力边界和 Mustdo 实现建议

调研日期：2026-09-04。代码基线：`c49ec00`。

本文用于选择动画方案和规划前端改造。结论来自微信官方文档、微信官方开源仓库及 Mustdo 静态代码检查；尚未进行真机性能测试。文中的时长、数量和优先级是项目建议，不是微信平台限制，也不代表已实现。

## 1. 结论与建议路线

微信小程序可以实现精致工具类 App 所需的大部分动效，包括按钮反馈、勾选回弹、列表增删过渡、跟手侧滑、弹窗、滚动联动、动态插画和局部粒子。Canvas/WebGL 还可以扩展到自定义图形和 3D，但这些能力有额外的资源、适配和维护成本。[官方动画文档](https://developers.weixin.qq.com/miniprogram/dev/framework/view/animation.html)、[Canvas 文档](https://developers.weixin.qq.com/miniprogram/dev/component/canvas.html)

对 Mustdo，建议依次采用：

1. 保留 WebView，统一按压、勾选、面板和状态切换的视觉反馈。
2. 用 WXSS / `this.animate()` 承担预先确定的动画；将需要连续跟手的动画优先评估为 WXS 实现。
3. 优化列表重排和日历展开，补齐取消、回滚、后台暂停与减少动态效果。
4. 仅在需要品牌插画或短暂庆祝时加入 Lottie / Canvas。
5. 如果主要瓶颈仍是复杂手势、页面联动或长列表，再单独评估 Skyline 试点。

当前最有价值的工作是提升常用操作的连续性，并减少高频跨线程更新。没有必要为了普通淡入、回弹或毛玻璃效果先迁移整个渲染引擎。

## 2. 如何理解“支持”

一个效果应分别检查四件事：

| 维度 | 要回答的问题 | 不能据此直接推出什么 |
|---|---|---|
| API / 样式能力 | 该接口、属性或组件是否存在？ | 存在不等于任意参数组合可用 |
| 渲染引擎 | 当前页面是 WebView 还是 Skyline？ | 同为 WXSS 不等于两种引擎表现一致 |
| 客户端环境 | 微信版本、基础库、操作系统、桌面端是否覆盖？ | 开发者工具选择某基础库不等于所有用户采用该版本 |
| 实际性能 | 目标设备在真实页面上是否流畅？ | 单个样例流畅不等于长列表、键盘和网络更新并发时流畅 |

本项目的 `project.config.json` 选择基础库 `3.15.2`，但它不是线上用户的最低版本承诺。需要明确发布时的最低基础库，并记录测试设备的实际环境。

### 2.1 已核对的能力入口版本

| 能力 | 官方文档标注 | 使用边界 |
|---|---|---|
| WXS 响应事件 | 基础库 2.4.4 起 | 本文主要用于 WebView 跟手交互；WXS 与普通 JS 环境不同 |
| `this.animate()` / 滚动驱动关键帧 | 基础库 2.9.0 起 | 动画文档明确标注为 WebView 能力 |
| 新 Canvas 2D | 基础库 2.9.0 起 | 指定 `type="2d"`；旧 Canvas API 已停止维护 |
| Canvas WebGL 类型 | 基础库 2.7.0 起 | 具体上下文能力、扩展及驱动仍需检查 |
| `page-container` / `share-element` | 组件入口为基础库 2.16.0 起 | 子属性可能要求更高版本，不能按入口版本推定全部可用 |
| `wx.getSkylineInfo()` | 基础库 2.26.2 起 | 查询支持情况，不代表页面实际已使用 Skyline |

来源：[WXS](https://developers.weixin.qq.com/miniprogram/dev/framework/view/interactive-animation.html)、[动画](https://developers.weixin.qq.com/miniprogram/dev/framework/view/animation.html)、[Canvas](https://developers.weixin.qq.com/miniprogram/dev/component/canvas.html)、[page-container](https://developers.weixin.qq.com/miniprogram/dev/component/page-container.html)、[share-element](https://developers.weixin.qq.com/miniprogram/dev/component/share-element.html)、[Skyline 环境查询](https://developers.weixin.qq.com/miniprogram/dev/api/base/system/wx.getSkylineInfo.html)。

这些是历史能力入口，不是建议 Mustdo 回退到这些版本。Skyline 引擎、客户端和新增属性还存在各自的版本要求。

### 2.2 官方资料也存在描述差异

本次读取发现，Skyline 兼容页仍列出了较早的移动端支持版本及桌面端未支持说明；官方开源资料提供了不同的环境基线。一些样式也存在差异，例如网站 WXSS 表列出单背景限制，而官方 Skyline 技能资料列出背景图最多两个值。不能把不同资料拼成一份宣称覆盖所有版本的支持表。

实际决策应使用目标引擎版本对应的文档、`wx.getSkylineInfo()` 返回信息及页面实例的 `this.renderer`，再配合真机验证。对资料冲突的高级效果，本文采用保守实现并保留回退。[Skyline 兼容页](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/migration/compatibility.html)、[官方 Skyline 概览资料](https://github.com/wechat-miniprogram/skyline-skills/blob/master/skills/skyline-overview/SKILL.md)、[官方样式资料](https://github.com/wechat-miniprogram/skyline-skills/blob/master/skills/skyline-wxss/SKILL.md)

## 3. 视觉效果的实现范畴

下面“适合”表示建议纳入 Mustdo 的产品方案；“条件使用”表示有实现路径，但需控制效果规模、验证目标环境。

| 效果 | WebView 实现方向 | Skyline 注意点 | Mustdo 建议 / 降级 |
|---|---|---|---|
| 圆角、边框、纯色层次 | WXSS | 检查边框组合、布局默认值 | 适合，作为基础视觉 |
| 渐变背景、柔和光晕 | 渐变或预渲染图片 | 核对渐变语法与多背景限制 | 适合小面积静态使用；降级纯色 / 图片 |
| 阴影、悬浮感 | `box-shadow`，静态阴影配合轻微位移 | 网站样式表注明多阴影叠加限制 | 适合；复杂多层阴影合并为单层 |
| 毛玻璃 | 半透明底色加 `backdrop-filter` 增强 | 模糊、透明度混用及多函数存在限制 | 条件使用；回退高不透明度底色 |
| 按钮按压、图标回弹 | `hover-class`、transition、关键帧 | 基础 transform / opacity 路径优先 | 第一优先级 |
| 状态呼吸、旋转、骨架闪动 | CSS animation | 核对关键帧支持与结束样式 | 第一优先级；减少动态时静态显示 |
| 弹窗进入、退出 | 位移 + 透明度，或 `page-container` | 可进一步用 worklet 手势驱动 | 第一优先级；回退短淡入 |
| 列表插入、删除、排序 | 稳定 ID + 测量 + 位移动画 | 按需渲染使屏外节点测量更复杂 | 第二优先级；只动画可见受影响项 |
| 跟手侧滑、拖拽、回弹 | WXS / 适配的内置交互组件 | worklet + 手势系统更接近渲染线程 | 第二优先级；保留按钮操作 |
| 滚动缩放、顶栏淡入、视差 | `this.animate()` 的滚动时间线 | 使用引擎对应滚动 / worklet 接口 | 低幅度、局部使用；回退固定样式 |
| 卡片放大为详情的共享元素 | `share-element` + `page-container` | 额外支持手势和逐帧回调等属性 | 条件使用；回退普通弹窗 |
| 任意跨页面联动转场 | 常规路由能力有限 | 连续 Skyline 页面可自定义路由 | 当前不作为必要目标 |
| 图标路径绘制、形状变形 | Canvas / 经验证的 Lottie 资源 | 不能把 SVG 图片当成可操作 DOM | 可做单个重点反馈；回退 PNG |
| 动态插画 | Lottie Canvas 渲染，或 GIF 等图片资源 | 验证 Canvas、导出特性及资源加载 | 仅空状态等局部场景使用 |
| 录音声波、进度图形 | 少量节点，或 Canvas 2D | 需验证绘制和事件兼容 | 声波是否反映真实音量需另接音频数据 |
| 粒子、纸屑、轨迹 | Canvas 2D，复杂场景可 WebGL | 控制透明叠加和画布成本 | 短时、局部、可关闭 |
| 卡片翻转、轻透视 | WebView 的变换能力，需验证组合 | 不按 WebView 的 3D 样式能力推定支持 | 条件使用；回退缩放淡入 |
| 3D 模型、着色器图形 | Canvas WebGL + 适配引擎 | 单独核对图形管线与组件支持 | 当前不建议加入主流程 |
| 液态玻璃、背景折射 | 简化视觉可用图片 / 渐变；真实折射需专项图形实现 | 没有可据此假定任意 UI 背景折射的通用方案 | 用半透明、描边和光晕表达质感 |

以上基础动画路径依据[微信动画文档](https://developers.weixin.qq.com/miniprogram/dev/framework/view/animation.html)，Skyline 样式限制依据[WXSS 支持表](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/wxss.html)；图形与资源路径依据[Canvas](https://developers.weixin.qq.com/miniprogram/dev/component/canvas.html)、[图片组件](https://developers.weixin.qq.com/miniprogram/dev/component/image.html)及[官方 Lottie 适配库](https://github.com/wechat-miniprogram/lottie-miniprogram)。表中的具体产品取舍是基于这些能力做出的工程判断。

### 3.1 毛玻璃可以用，但不要让它承担全部层次表达

建议先设计在没有模糊时也清楚的面板：接近不透明的底色、明确的边缘、轻阴影、足够的文本对比度。通过真机验证后，再降低底色不透明度并打开背景模糊。

动画时优先移动面板、改变独立遮罩的透明度，避免持续改变大面积模糊半径。全屏背景正在滚动时再叠加模糊，通常比静态小面板更值得关注绘制开销。这是性能取舍，不是“毛玻璃不能做”的结论。

Skyline 官方样式表明确记录 `backdrop-filter` 的多函数限制、与 opacity 混用的问题和部分 blur 表现差异，因此应把这一组合列为专项验收项。[官方 WXSS 支持表](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/wxss.html)

### 3.2 SVG、动图和动态插画不是同一种能力

`image` 官方支持 PNG、SVG、WebP、GIF 等格式，但 SVG 有百分比单位、`<style>` 等限制，不同渲染引擎的缩放也有差异。加载一张 SVG 图片，不等于能通过 JS 操作里面的路径或运行任意 SVG 动画。[图片组件文档](https://developers.weixin.qq.com/miniprogram/dev/component/image.html)

Mustdo 目前使用 PNG 图标，SVG 保留为源素材。这符合当前项目已有的兼容性取舍；没有必要为简单勾选回弹切换图标格式，直接缩放 PNG 的外层节点即可。

GIF 适合简单播放；需要精确控制进度、复用状态或与业务事件协调时，优先评估 Canvas / Lottie。WebP 静态格式支持也不能自动推导出全部动画编码和平台组合都可靠。

Lottie 需要经过小程序适配，官方适配库通过 Canvas 工作，不支持 expressions。设计交付时应选定实际播放器版本，用真实导出文件检查遮罩、渐变、字体与图片资源；复杂 AE 效果不能假设完整还原。[官方 Lottie 仓库](https://github.com/wechat-miniprogram/lottie-miniprogram)

### 3.3 3D 能力是上限证明，当前不宜成为依赖

WebGL 可以用于自定义渲染、粒子和模型。微信提供的 `threejs-miniprogram` 适配仓库在 README 中标注 Three.js 版本为 `0.108.0`，说明“存在官方适配”不能推导为“可以直接接入最新 Three.js 插件生态”。版本维护、加载器、纹理与着色器兼容性需要单独评估。[官方 Three.js 适配仓库](https://github.com/wechat-miniprogram/threejs-miniprogram)

同时，不应假设 WebGL 能直接读取并折射其他 WXML 节点的实时画面；普通 UI 与图形画布不是可以任意共享纹理的统一场景。真实背景折射不纳入本轮承诺。XR/AR 也需要另做专项调研，本次不提供其逐功能兼容表。

## 4. 动画机制如何选择

### 4.1 WXSS transition / animation：默认起点

适合颜色变化、淡入淡出、按压、旋转、固定回弹和简单序列。业务层只切换状态，渲染侧推进中间帧，不需要 JS 每帧发送位置。

建议使用明确的动画属性，避免 `transition: all` 让后续新增的布局属性也被意外动画化。WebView 中优先采用 transform 和 opacity，通常更容易减少布局与绘制成本，但它们不保证任何组合都走 GPU，也不保证固定帧率。大面积透明叠加仍可能昂贵。[浏览器厂商动画性能指南](https://web.dev/articles/animations-guide)

以下是 WebView 按压反馈示意，不是对项目的实际修改：

```xml
<view class="pressable" hover-class="pressable--down" hover-stay-time="80">
  <text>添加待办</text>
</view>
```

```css
.pressable {
  transition: transform 100ms ease-out;
}
.pressable--down {
  transform: scale(0.97);
}
```

业务按钮仍需保留正确的交互语义、禁用态和事件处理。列表侧滑和按压缩放建议放在不同的包裹节点上，避免两个功能争用同一个 transform。

### 4.2 `this.animate()`：由业务触发的关键帧

适合勾选、弹窗和一次性状态反馈。它可以一次提交关键帧和时长，不必用 `setData` 逐帧更新样式。普通固定回弹可以用少量缩放关键帧近似；需要中途接管速度和连续拖拽的场景，则不能把固定关键帧当成完整物理系统。

注意动画样式可能覆盖原样式，需要管理 `clearAnimation()` 和最终状态。重复点击、取消及节点被销毁时，也要避免旧回调修改新状态。旧 `wx.createAnimation()` 可以理解为历史方案，新代码优先评估官方推荐的关键帧接口。[关键帧动画说明](https://developers.weixin.qq.com/miniprogram/dev/framework/view/animation.html)

### 4.3 WXS：WebView 中的跟手动画

目前侧滑的链路是：触摸事件到逻辑层 → JS 计算位置 → `setData` 回视图层。WXS 可以在视图层响应触摸并用组件描述对象调整样式，减少往返通信。[WXS 官方原理](https://developers.weixin.qq.com/miniprogram/dev/framework/view/interactive-animation.html)

建议划分职责：

- WXS 管理拖拽位置、方向锁定、阻尼和视觉回弹。
- 普通 JS 管理业务数据、API 请求、成功或失败状态。
- 通过 `callMethod` 在手势结束、越过业务阈值等少量节点同步结果。
- 使用 WXS 提供的 `requestAnimationFrame` 时，按实际时间推进动画，不假定每次回调间隔都是 16ms。

WXS 的 `setStyle` 优先级高于 WXML 绑定样式，必须明确谁拥有位移状态，以及外部数据刷新时如何复位。官方也记录了原生组件事件、input / textarea 的输入事件限制；因此不能把整个表单逻辑直接搬进 WXS。[WXS 接口与限制](https://developers.weixin.qq.com/miniprogram/dev/framework/view/interactive-animation.html)

### 4.4 滚动驱动：绑定进度，避免逐次 setData

WebView 的 `this.animate()` 可以把动画进度绑定到 `scroll-view` 的滚动范围，用于顶栏淡入、元素缩放或小幅视差。它不是浏览器 CSS `animation-timeline` / `scroll-timeline` 语法的通用支持承诺，也不是任意页面滚动源都可绑定。[滚动驱动动画](https://developers.weixin.qq.com/miniprogram/dev/framework/view/animation.html)

Mustdo 可以在出现明确需求后使用；当前列表阅读和操作优先，持续大幅视差没有必要。

### 4.5 Skyline worklet：复杂手势与物理动画

worklet 配合共享变量和 `applyAnimatedStyle` 可以在 UI 线程驱动样式，内置 timing、spring、decay 及组合能力。适合可打断的弹簧、连续跟手、多元素联动。[Worklet 文档](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/worklet.html)

需要注意两处描述的范围：worklet 专页将动画接口标为 Skyline 能力；发布页又说明部分能力有 WebView 兼容处理。不能因此承诺降级后仍有相同的 UI 线程执行方式和手势体验。Mustdo 应将“Skyline 原生路径”和“WebView 兼容路径”分别设计、分别测试。[发布与降级说明](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/migration/release.html)

迁移不是只改 `renderer`：还要检查组件框架、编译配置、默认盒模型、导航、滚动、样式差异、路由和生命周期。可以按页面或分包渐进迁移。WebView 下采用的 WXS 实现在 Skyline 的执行位置与部分查询行为也会改变，不应原样套用性能结论。[Skyline 架构](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/introduction.html)、[迁移兼容性](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/migration/compatibility.html)

### 4.6 Canvas / Lottie：局部绘制，不重写整个界面

适合图形、声波、插画、路径和粒子。建议使用新 Canvas 2D，明确设置画布尺寸和像素比例，并按目标设备限制分辨率。放大画布尺寸会明显增加像素处理和内存开销，不能无限按高 DPI 放大。

绘制状态保存在绘制对象里，不为每个粒子逐帧 `setData`。页面隐藏时暂停，组件销毁时释放动画和资源。首次载入失败应显示静态资源，避免一个装饰动画阻塞待办主流程。Canvas 不自动提供与普通文本、按钮相同的语义，关键业务内容仍用 WXML 展示。

需要单独检查画布层级和触摸穿透。官方 Canvas 页面还列出了 iOS `pointer-events` 限制及 WebGL 真机调试限制，因此“覆盖整个页面但不拦截点击”的粒子层不能只靠通用 CSS 假设成立；WebGL 应按文档用真机预览验证。[Canvas 注意事项](https://developers.weixin.qq.com/miniprogram/dev/component/canvas.html)

## 5. 共享元素、页面过渡和原生组件

### 5.1 页面内展开与真正的跨页面转场

WebView 可以通过 `share-element` 与 `page-container` 配合，让列表卡片看起来展开成详情。它主要属于当前页面与页面容器之间的映射，不代表普通 `navigateTo` 可以任意共享元素。[共享元素文档](https://developers.weixin.qq.com/miniprogram/dev/component/share-element.html)

`page-container` 可以协助处理页面内弹层的返回操作，但官方列有单页容器数量等限制，且鸿蒙端返回拦截存在特别说明。采用前需要检查 Mustdo 的编辑面板与处理面板是否会争用容器。[页面容器文档](https://developers.weixin.qq.com/miniprogram/dev/component/page-container.html)

Skyline 的自定义路由可以协调前后页面的进入、退出、下沉和手势返回，要求连续 Skyline 页面。对于当前 Mustdo，以页面内弹窗完成编辑已经有清晰路径，跨页联动不是必要前置条件。[自定义路由文档](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/custom-route.html)

### 5.2 不要沿用“原生组件永远盖在最上层”的旧结论

官方原生组件文档说明，同层渲染已解除许多旧层级限制，但组件内部仍由原生渲染，内部样式不一定能由外部 WXSS 控制，input 聚焦状态也有例外。要依据组件、状态和客户端判断。[原生组件文档](https://developers.weixin.qq.com/miniprogram/dev/component/native-component.html)

Mustdo 的编辑和输入栏涉及 textarea、键盘高度、页面滚动及弹层位移。验收时应覆盖：焦点获取、光标可见、键盘弹出 / 收起、面板拖动、点击穿透和返回操作。建议避免在正在输入的控件上做大幅缩放或复杂旋转。

## 6. Mustdo 当前实现与具体风险

以下依据 `c49ec00` 的实际代码。性能项为风险判断，不是已测得的掉帧结论。

| 位置 | 已有实现 | 值得改进的地方 |
|---|---|---|
| [app.json](../miniprogram/app.json) / 页面 JSON | 未配置 Skyline，使用默认 WebView | 第一阶段可以直接在现有引擎上改造 |
| [project.config.json](../miniprogram/project.config.json) | 基础库 3.15.2；`compileWorklet: false`；`es6: true` | 如试点 Skyline，应核对实际编译输出，不能只看一个开关推定 worklet 可用性 |
| [app.wxss](../miniprogram/app.wxss) | 渐变、阴影、按压、骨架呼吸 | 统一样式与动效参数，减少重复实现 |
| [utils/api.js](../miniprogram/utils/api.js) 的 `spring()` | `setInterval(tick, 16)`，积分步长固定 0.016 秒 | 定时器不与屏幕刷新严格同步；卡顿时动画时长可能漂移；动画与网络工具混在一起 |
| [todos.js](../miniprogram/pages/todos/todos.js) 的 `_animateCheck` | 每帧写 `items[idx].checkScale` | 用固定关键帧替换；控制器以稳定 ID 管理，避免排序后旧 index 指向其他项 |
| 同文件 `onItemTouchMove` / `_springTo` | 手势和回弹每帧写 `swipeX` | 优先评估 WXS；保留现有方向判断、按钮点击和纵向滚动行为 |
| 同文件 `_fitCalendarHeight` | 测量后逐帧更新 `calHeight` | 高度影响文档流，会持续推动布局；不宜盲目扩大使用 |
| 同文件 `_animateSheetIn` / `_animateSheetOut` | 逐帧更新位移和遮罩透明度 | 固定进入退出交给动画 API；跟手部分独立处理 |
| [todos.wxml](../miniprogram/pages/todos/todos.wxml) 的编辑面板 | 面板是透明度遮罩节点的子节点 | 当前父级 opacity 会同时淡化面板；若要独立控制，应拆分遮罩和面板节点 |
| [processing-panel](../miniprogram/components/processing-panel/processing-panel.js) | 保存后步骤全绿；结果可见；1.3 秒自动关闭 | 后续动效应沿现有状态机增加，保留自动关闭与可关闭状态约束 |

### 6.1 减少动态效果目前未形成闭环

[app.js](../miniprogram/app.js) 设置了 `globalData.reducedMotion`，但代码搜索未发现将它同步到待办页面 data 或根节点 class 的逻辑。现有样式使用 `page.reduced-motion ...`，当前 WXML 也没有对应接线。

此外，现有判断根据字号和旧 Android 版本做启发式推断，不能等同于读取到了用户的系统“减少动态效果”偏好；JS 弹簧也没有消费这个开关。

建议增加明确的应用内动效偏好，在页面根节点与独立组件中统一应用，同时控制 CSS、JS 动画、Canvas 和循环效果。自定义组件默认样式隔离，不能指望页面选择器自动控制处理面板内部。

### 6.2 后台、取消和数据刷新

待办页面在 `onUnload` 调用 `_stopAllSprings()`，但目前没有对应的 `onHide` 暂停处理。短动画未必造成持续严重问题，但新增循环效果前应补齐隐藏和恢复行为。

优化时还要保证：动画被取消不取消已经发起的保存；请求失败仍能回滚；快速重复勾选不会被旧回调覆盖；切换日期或重建 AI 分组后，旧动画不会继续更新已换位置的条目。微信官方建议避免后台页面持续高频更新。[setData 性能指南](https://developers.weixin.qq.com/miniprogram/dev/framework/performance/tips/runtime_setData.html)

## 7. 建议的实现规范

### 7.1 时长和运动幅度

下面是设计起点，需要在产品中调试，不是平台保证：

| 场景 | 建议时长 | 建议表现 |
|---|---|---|
| 按压反馈 | 80–120ms | 缩放到 0.97 左右，松手恢复 |
| 勾选 / 图标状态 | 160–240ms | 一次轻微回弹，不连续晃动 |
| 内容淡入 / Tab 切换 | 140–220ms | 淡入，必要时小幅位移 |
| 面板进入 | 220–300ms | 减速进入，遮罩同步变化 |
| 面板退出 | 160–220ms | 更快离开，不阻塞下一步 |
| 列表位置变化 | 180–260ms | 只移动受影响的可见条目 |
| 装饰性循环 | 按场景设置 | 仅在对应状态可见时运行 |

同类操作使用同类节奏。不要为展示动画而延迟 API 请求，也不要把“用户已完成操作”与“动画播放结束”混为一谈。现有处理面板 1.3 秒是结果阅读停留时间，不是面板动画时长。

### 7.2 元素移除与列表重排

节点直接 `wx:if=false` 会被移除，无法继续播放退出动画。应先进入离场状态，结束后再移除；减少动态或异常取消时直接收敛到最终状态，不能让数据操作永久等待动画事件。

列表重排可以采用 FLIP 思路：记录变化前位置 → 更新最终顺序 → 测量新位置 → 用反向位移暂时保持旧视觉位置 → 动画到零位移。这是推荐实现方法，不是小程序自带的自动布局动画接口。

实施时只测量必要的可见节点，批量读位置、批量写样式，使用稳定 ID。侧滑位移与重排位移放在不同包裹层，避免 transform 互相覆盖。Skyline 按需渲染下，屏外节点可能无法直接测量，要额外设计。[Skyline 节点测量限制](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/migration/compatibility.html)

日历高度变化确实需要推动列表时，可以采用一次布局变更配合位移过渡，或保留短时、局部高度动画并验证性能；不能直接用 `scaleY` 缩扁内容来替代所有布局变化。

### 7.3 建议的代码组织

后续实现时再创建以下资源，不需要一次引入通用动画框架：

```text
miniprogram/
  styles/motion.wxss       # 通用按压、淡入、轻回弹
  utils/motion.js          # 动效偏好、时长、控制器与取消
  components/todo-row/     # 必要时拆出单条待办的状态与动画
  components/.../*.wxs     # 需要跟手的局部行为
```

建议拆分有明确性能收益的部分，不为复用而先重写全部页面。动画模块应独立于请求工具，业务状态和视觉进度分开存放。

### 7.4 降级策略

| 正常效果 | 减少动态 / 性能不足时 | 必须保留 |
|---|---|---|
| 弹簧、惯性 | 短过渡或直接到终点 | 最终位置与可操作状态 |
| 列表重排动画 | 直接更新列表 | 顺序与当前选择 |
| 毛玻璃 | 高不透明度背景 | 层次、可读性 |
| 声波、插画、粒子 | 静态图标 / 状态文字 | 正在录音、处理中、成功或失败的含义 |
| 自定义路由 | 普通页面跳转 | 返回与业务流程 |

优先使用 API 存在性检测和实际 renderer；`wx.canIUse` 仅在对应 API / 组件支持其检测语法时使用，不能把它当成通用 CSS 属性检测器。设备型号或系统版本可以辅助分档，但不能替代能力检查和测量。

## 8. 分阶段实施清单

### P0：先修复动效基础设施

- 接通减少动态效果，并让 CSS、组件和 JS 共用偏好。
- 将勾选固定回弹改为关键帧，减少页面级逐帧更新。
- 动画以稳定 ID 管理，补齐重复触发、取消、隐藏和销毁处理。
- 对当前版本录制真机基线，作为后续比较依据。

### P1：完成高频交互的质感升级

- 统一按钮按压和 Tab 切换反馈。
- 编辑面板拆开遮罩与内容，统一进入退出节奏。
- 处理面板沿“输入 / 识别 → 解析 → 保存”状态变化增加局部过渡。
- 保留已有结果展示、保存后全绿停留、自动关闭和错误重试规则。
- 结果行较多时限制错峰延迟，避免在 1.3 秒停留结束前仍未展示完整。

### P2：改善连续运动

- 侧滑与回弹试点 WXS，验证与纵向滚动、子按钮点击的竞争关系。
- 列表增删和置顶使用稳定 ID、有限测量和位移过渡。
- 优化日历展开与快速切换月份时的动画接管。
- 检查键盘、编辑弹窗、请求回调和列表更新并发时的体验。

### P3：选择性增强

- 为全部完成或空状态添加一处轻量 Canvas / Lottie 动画。
- 仅在实测收益明确时试点 Skyline；试点可以按页面开展。
- 若要自定义跨页转场，试点范围应包括相邻的连续 Skyline 页面。
- 引入依赖前记录构建包增量、资源加载时间和维护版本。

P0–P2 已足以覆盖当前 Mustdo 的主要体验提升。P3 需要具体设计需求和测量结果支持。

## 9. 真机验收方案

### 9.1 环境覆盖

至少覆盖一台常用 iPhone、一台主流 Android 和一台性能较弱的 Android；若产品承诺桌面或鸿蒙支持，增加对应微信客户端。记录设备、系统、微信、基础库和 renderer，不能只记录手机型号。

若引入 Skyline，分别测试实际 Skyline 路径与 WebView 回退路径，尤其是手势、滚动组件、共享元素及返回行为。官方发布文档说明不支持 Skyline 的环境可回退 WebView，但增强特性仍需要兼容设计。[发布说明](https://developers.weixin.qq.com/miniprogram/dev/framework/runtime/skyline/migration/release.html)

### 9.2 场景覆盖

| 场景 | 重点检查 |
|---|---|
| 连续快速勾选、取消勾选 | 不误改其他条目、不被旧回调覆盖 |
| 长列表滚动时侧滑 | 纵向滚动与横向手势可正确区分 |
| 删除 / 置顶后立即切 Tab | 离场与重排不残留位移 |
| 弱网、请求失败 | 视觉反馈及时，业务结果与回滚正确 |
| 面板开关、键盘弹出、拖动 | 遮罩、光标、焦点和点击区域正确 |
| 连续展开日历、切换月份 | 动画可接管，最终高度正确 |
| 处理面板解析多条 / 零条 / 保存失败 | 结果展示、停留时间、重试与关闭规则正确 |
| 页面隐藏、切后台、返回 | 无无意义持续绘制；恢复后状态正确 |
| 减少动态效果开启 | 无弹跳、持续闪动或粒子；业务信息完整 |
| 图片 / 动画资源加载失败 | 静态回退可见，主流程不受阻 |

### 9.3 指标和停止条件

可先使用 20 条、100 条和 300 条待办作为自建压力样本，保留相同数据用于前后对比；这些数量不是微信限制。

记录高频操作的帧耗时分布、明显长帧、输入反馈延迟、`setData` 更新频率与耗时、重复开关面板后的内存趋势，以及新增资源的包体积。60Hz 屏幕每帧约 16.7ms，120Hz 约 8.3ms，这是刷新预算参考，不是当前项目的实测结果或承诺。

`setUpdatePerformanceListener` 可以帮助分析组件更新开销，但它不是完整 GPU 帧率测试。开发者工具用于定位，最终手感、键盘和原生组件行为以真机为准。[更新性能统计入口](https://developers.weixin.qq.com/miniprogram/dev/framework/performance/tips/runtime_setData.html)

建议验收标准：正常目标设备上高频操作无可感知的持续卡顿；性能较弱设备可使用简化效果；隐藏后停止装饰性循环；快速重复操作、错误回滚与资源失败均能回到正确最终状态。达标后停止继续堆叠效果。

## 10. 本次范围与待验证问题

已完成：官方能力调查、渲染引擎与资源方案比较、当前实现检查、实施优先级与验收计划。

待验证：

- 目标用户实际微信与基础库分布，是否必须覆盖桌面 / 鸿蒙。
- 当前侧滑、弹窗、日历在较弱设备上的真实瓶颈。
- 毛玻璃与原生输入控件在目标环境中的组合表现。
- 引入具体 Lottie 资源后的视觉还原、内存和包体积。
- Skyline 在目标环境的实际启用情况，以及对应版本的样式支持。

本文没有将建议转成实现，也没有进行真机验收。后续可从 P0 和 P1 开始，逐项把“待验证”更新为有设备、版本和结果记录的结论。
