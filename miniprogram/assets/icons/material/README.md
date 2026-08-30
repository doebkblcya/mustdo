# Material Symbols

Local copies of Google Material Symbols Outlined, sourced from the official
`google/material-design-icons` repository. Default assets use the 24px
outlined variant. Files ending in `_fill` use the `FILL=1` variant required
by the Stitch prototype.

`calendar_month.svg` and `schedule.svg` are used by the edit and reminder
bottom sheets and come from the same official outlined set.

`mic_off.svg` is used by the microphone-permission state. `refresh_white.svg`
keeps the official refresh path and fixes its color for a black primary button.

`check_white.svg`, `delete_error.svg`, and `error_red.svg` retain the official
paths and only set a fixed UI color for use in WeChat `<image>` elements, which
cannot inherit the surrounding text color.

Source: https://github.com/google/material-design-icons

## PNG 构建产物（`../png/`）

`icons/png/*.png` 是 `icons/material/*.svg` 的 96×96（3x）透明 PNG 导出，
由 `rsvg-convert -w 96 -h 96` 批量生成。原因：微信小程序 `<image>` 组件对
本地 SVG 的 iOS 渲染兼容性不可靠，PNG 三端稳定。所有 wxml 引用 `.png`；
SVG 文件保留为原始资源，改色/改尺寸后需重新导出。

`auto_awesome.svg` 源文件原缺 `viewBox`（旧版 24px 坐标系），已补
`viewBox="0 0 24 24"`（注意：该文件与其余 960 网格文件坐标系不同）。
