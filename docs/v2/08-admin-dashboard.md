# 内部用户与用量管理后台

## 目标

在服务器本机运行独立管理网页，用于查看用户、统计外部服务用量、设置用户额度、管理用户状态，以及受控地查看和修改用户待办。

## 部署结构

管理后台使用独立 FastAPI 应用和端口：

```text
公网 nginx
    └── Mustdo API · 127.0.0.1:8000

服务器本机
    └── Mustdo Admin · 127.0.0.1:8001
```

启动命令：

```bash
uv run uvicorn app.admin:app --host 127.0.0.1 --port 8001
```

管理员通过 SSH 隧道访问：

```bash
ssh -L 8001:127.0.0.1:8001 todo@服务器
```

浏览器入口：

```text
http://127.0.0.1:8001
```

后台使用独立启动脚本、PID 文件和日志文件，并在部署文档中记录启动、停止、重启和查看日志的方法。

## 管理员认证

- 后台提供独立登录页。
- `.env` 保存 `ADMIN_PASSWORD_HASH`。
- 密码校验成功后创建管理员 Session。
- Session Cookie 设置 `HttpOnly` 和 `SameSite=Strict`。
- 管理员 Session 默认有效 8 小时。
- 登录失败进行频率控制并记录安全日志。
- 后台提供退出登录入口。

## 技术实现

- 后端沿用 FastAPI 和 SQLite。
- 页面采用服务端 HTML 模板、轻量 CSS 和原生 JavaScript。
- 管理后台与主 API 共享数据库访问层和待办领域服务。
- 表格接口支持分页、筛选和排序。
- 所有管理操作使用管理员身份校验。

## 总览页面

总览支持今天、最近 7 天和最近 30 天三个时间范围。

展示指标：

- 用户总数；
- 活跃用户数；
- 新增待办数量；
- ASR 请求次数；
- ASR 音频总分钟数；
- AI 新增解析次数；
- AI 动态整理次数；
- DeepSeek 输入和输出 Token；
- 提醒创建数量；
- 提醒发送成功与失败数量；
- 上游服务成功率；
- ASR 和 AI 平均耗时。

## 用户列表

用户列表展示：

- Mustdo 用户 ID；
- 管理员备注；
- 脱敏后的微信 `openid`；
- 用户状态；
- 首次登录时间；
- 最近活跃时间；
- 待办总数；
- 未完成数；
- 已完成数；
- 逾期数；
- 今日 ASR 时长；
- 今日 AI 调用次数。

列表支持：

- 按用户 ID 和管理员备注搜索；
- 按用户状态筛选；
- 按最近活跃时间、待办数量和 AI 用量排序；
- 分页查看；
- 进入用户详情。

管理员可以为微信用户设置备注，用于识别测试账号、个人账号和受邀用户。

## 用户状态管理

用户详情页提供：

- 修改管理员备注；
- 启用用户；
- 禁用用户；
- 撤销用户全部 Session；
- 设置每日 AI 调用额度；
- 设置每日 ASR 音频秒数额度；
- 恢复默认额度。

禁用用户后，其现有 Session 立即失效。重新启用后，用户可以再次通过微信登录。

## 用户用量统计

用户详情支持今天、7 天、30 天和自定义日期范围。

统计内容：

- ASR 请求次数、音频秒数和平均耗时；
- AI 新增解析次数；
- AI 动态整理次数；
- DeepSeek 输入和输出 Token；
- 新增待办数量；
- 创建提醒数量；
- 提醒发送成功和失败数量；
- 上游服务失败次数。

## 每日用量数据

按上海时区将用量聚合到用户和自然日：

```sql
CREATE TABLE user_usage_daily (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    usage_date TEXT NOT NULL,
    asr_requests INTEGER NOT NULL DEFAULT 0,
    asr_seconds REAL NOT NULL DEFAULT 0,
    ai_parse_requests INTEGER NOT NULL DEFAULT 0,
    ai_organize_requests INTEGER NOT NULL DEFAULT 0,
    ai_input_tokens INTEGER NOT NULL DEFAULT 0,
    ai_output_tokens INTEGER NOT NULL DEFAULT 0,
    todos_created INTEGER NOT NULL DEFAULT 0,
    reminders_created INTEGER NOT NULL DEFAULT 0,
    reminders_sent INTEGER NOT NULL DEFAULT 0,
    reminder_failures INTEGER NOT NULL DEFAULT 0,
    upstream_failures INTEGER NOT NULL DEFAULT 0,
    asr_latency_ms_total INTEGER NOT NULL DEFAULT 0,
    ai_latency_ms_total INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, usage_date)
);
```

业务调用完成后使用 SQLite UPSERT 累加对应字段：

- ASR：请求次数、音频秒数、耗时和上游结果；
- AI 新增：请求次数、Token、耗时和新增待办数；
- AI 整理：整理次数、Token 和耗时；
- 微信提醒：创建、发送成功和发送失败数量。

DeepSeek 用量读取接口响应中的实际 `usage` 数据。

## 用户额度

```sql
CREATE TABLE user_limits (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    daily_ai_requests INTEGER,
    daily_asr_seconds INTEGER,
    updated_at TEXT NOT NULL
);
```

额度检查规则：

- ASR 在读取音频时长后、请求语音服务前检查；
- AI 在请求 DeepSeek 前检查；
- AI 新增解析和 AI 动态整理共同计入每日 AI 次数；
- 每天按上海时区自然日重新计算当日用量；
- 达到额度时返回稳定错误码、当前用量和每日额度；
- 管理员修改额度后立即生效。

## 用户待办管理

用户详情页提供待办表格，展示：

- 内容；
- 日期和时间；
- 状态；
- 置顶状态；
- 提醒状态；
- 创建时间；
- 更新时间；
- 删除时间。

筛选条件：

- 今天；
- 明天；
- 后续；
- 已完成；
- 已逾期；
- 已删除；
- 全部；
- 内容关键词；
- 日期范围。

管理员可以执行：

- 修改内容；
- 修改日期和时间；
- 修改完成状态；
- 修改置顶状态；
- 软删除待办；
- 恢复已删除待办。

管理操作复用待办领域服务和数据校验规则。完成、删除、改期时同步处理提醒状态；恢复时按照原日期是否过期决定恢复到原日期或今天。

## 管理操作审计

所有产生数据变化的后台操作写入审计日志：

```sql
CREATE TABLE admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    user_id INTEGER,
    before_data TEXT,
    after_data TEXT,
    created_at TEXT NOT NULL
);
```

审计内容包括：

- 用户启用与禁用；
- Session 撤销；
- 用户备注和额度修改；
- 待办内容、日期、时间、状态和置顶修改；
- 待办软删除与恢复。

待办详情显示最近一次管理员修改时间。审计页面支持按操作类型、用户和日期查询。

## 管理后台接口

```http
POST /admin/api/login
POST /admin/api/logout

GET  /admin/api/overview
GET  /admin/api/users
GET  /admin/api/users/{user_id}
GET  /admin/api/users/{user_id}/usage
PUT  /admin/api/users/{user_id}/status
PUT  /admin/api/users/{user_id}/note
PUT  /admin/api/users/{user_id}/limits
POST /admin/api/users/{user_id}/revoke-sessions

GET    /admin/api/users/{user_id}/todos
PATCH  /admin/api/users/{user_id}/todos/{todo_id}
DELETE /admin/api/users/{user_id}/todos/{todo_id}
POST   /admin/api/users/{user_id}/todos/{todo_id}/restore

GET /admin/api/audit-logs
```

## 验收标准

- 管理后台仅通过服务器本机端口和 SSH 隧道访问。
- 管理员登录后可以查看总体用量趋势。
- 用户列表支持搜索、筛选、排序和分页。
- 用户详情可以查看分时段用量和待办数据。
- 管理员可以设置备注、状态和每日额度。
- 达到额度后 ASR 或 AI 请求得到明确提示。
- 管理员可以修改、软删除和恢复用户待办。
- 待办修改正确联动提醒状态。
- 所有后台数据修改均生成审计日志。
- 管理数据和待办数据按目标用户准确关联。
