# 微信待办提醒 · 部署与联调清单

> 对应 `docs/v2/02-wechat-reminder.md`（设计）。实现已落地：后端接口/调度/发送 + 前端入口/面板/授权流。
> 本文档是从代码到线上可用的最后一步操作清单。

## 1. 常量与关键配置

| 项 | 值 / 位置 |
|----|-----------|
| 订阅消息模板 ID | `HWgp5u4Z_E3QD_vFMzHEZ3_gL0PDdsbtA5i7vjWQ9jc`（`miniprogram/config.js` 的 `SUBSCRIBE_TEMPLATE_ID`） |
| 后端环境变量 | `WECHAT_TEMPLATE_ID`（同一模板 ID）+ 已有的 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` |
| 发送载荷字段名 | `scheduler.py` 顶部：`FIELD_CONTENT=thing1`（事项主题）、`FIELD_TIME=time2`（事项时间）—— 必须与模板详情页里的字段 ID（`{{thing1.DATA}}`/`{{time2.DATA}}`）逐字一致，字段 ID 不符会报 47003 |
| 调度间隔 | `scheduler.py` 默认 30s；单 worker（`server.sh` 默认 `WORKERS=1`）保证唯一分发实例 |
| 消息跳转页面 | `pages/todos/todos`（固定待办列表页，不携带定位参数） |

## 2. 部署

```bash
# 1. 后端 .env 追加
echo "WECHAT_TEMPLATE_ID=HWgp5u4Z_E3QD_vFMzHEZ3_gL0PDdsbtA5i7vjWQ9jc" >> backend/.env

# 2. 重启服务（启动时自动补扫所有到期 pending 提醒）
cd backend && ./scripts/server.sh restart

# 3. 冒烟：健康检查 + 全套测试
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -v   # 101 个用例
```

## 3. 真机联调（微信开发者工具 → 真机预览）

1. 待办有具体时间 → 卡片铃铛图标（未完成项）→ 点开「设置提醒」弹层。
2. 验证弹层：默认选中「准时提醒」；提前档位的提醒时间已过（剩余时间不足）→ 点选提示「剩余时间不足，无法提前 X 分钟」且不选中；待办时间本身已过 → 提示「剩余时间不足，无法设置提醒」，不打开弹层、不允许创建。
3. 选时间 → 点「确认提醒」→ 微信「订阅消息授权」弹窗 → 接受。
4. 卡片出现橙色「提醒 今天 14:30」行；铃铛变橙色。
5. 到点（可在面板选 1-2 分钟后的自定义时间加速验证）收到订阅消息。
6. 点消息 → 直接进入小程序待办列表页（无定位/高亮）。
7. 联动取消验证：
   - 勾选完成该待办 → 提醒取消（卡片提醒行消失）；
   - 改期（编辑面板改日期/时间）→ 提醒取消；
   - 一键移到明天 → 提醒取消；
   - 删除待办 → 提醒取消。
8. 拒绝授权路径：点确认时选「拒绝」→ 提示「未授权订阅，无法设置提醒」，不创建提醒。
9. 失败诊断：`backend/logs/uvicorn.log` 中 `reminder_send_failed` 行含微信 errcode（如 43101 用户拒收）；DB `todo_reminders.status='failed' + error_code` 可查。

## 4. 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 发送全部失败，日志 `47003` | 载荷字段名与模板字段 ID 不一致 → 以模板详情页 `{{thingX.DATA}}` 为准改 `scheduler.py` 的 `FIELD_*` 常量 |
| `40163/40029` | 登录凭证问题，与提醒无关，检查小程序 AppID |
| 授权后仍收不到消息 | 一次性订阅：每条提醒需一次授权；用户拒绝过则无额度；消息在体验版可收，无需发布 |
| 提醒状态显示 pending 但到点没发 | 检查服务器时间与 `TIMEZONE=Asia/Shanghai`；`remind_at <= now` 才会被调度扫描 |

## 5. 回归

- 后端：`backend/tests/test_reminders.py`（17 例）+ `test_reminders_api.py`（8 例），全套 101 绿。
- 前端逻辑（无需真机）：`node scripts/frontend_reminder_smoke.js`（默认准时/不足拦截/ISO 换算/授权流/联动清空/展示）。
