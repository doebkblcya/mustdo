# Mustdo V2 优化方案

V2 围绕更顺畅的微信使用体验、更透明的 AI 处理过程，以及待办的提醒、整理和短期找回能力展开。

## 需求文档

1. [微信静默登录](./01-wechat-login.md)
2. [微信待办提醒](./02-wechat-reminder.md)
3. [ASR 与 AI 统一处理面板](./03-ai-processing-panel.md)
4. [垃圾桶与逾期待办](./04-trash-and-overdue.md)
5. [一键移到明天](./05-move-to-tomorrow.md)
6. [完成项显示控制](./06-completed-visibility.md)
7. [今天与明天的 AI 动态整理](./07-ai-organize.md)
8. [内部用户与用量管理后台](./08-admin-dashboard.md)

## 产品主流程

```text
微信静默登录
    ↓
语音或文字输入
    ↓
统一面板展示 ASR、AI 解析和保存过程
    ↓
待办进入今天、明天或后续列表
    ↓
用户按需设置微信提醒、AI 整理或调整日期
    ↓
已删除及已逾期事项在七天处理窗口内可恢复
```
