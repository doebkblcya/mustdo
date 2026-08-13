# CLAUDE.md

> Mustdo 代码库参考。详细产品文档见 `docs/PROJECT.md`。

## 项目现状

- **后端**：FastAPI + SQLite，**前端**：微信原生小程序 `miniprogram/`
- 当前分支：`main`，活跃开发中

## 产品定位

Mustdo — 轻量语音待办工具。语音只做"新增待办"，修改/删除/完成/置顶全部手动操作。核心原则：主流程短（按→说→松→入库）、语音不做危险操作、AI 结果不做确认弹窗。

## 项目结构

```
mustdo/
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, db.py, deps.py, errors.py, schemas.py, security.py, time_utils.py
│   │   ├── routers/  (auth.py, todos.py, voice.py)
│   │   └── services/ (audio.py, asr.py, deepseek.py, todos.py)
│   ├── scripts/  (init_db.py, create_invite.py, list_invites.py, clear_invites.py, cleanup_overdue.py, server.sh)
│   └── tests/  (test_auth.py, test_todos_api.py, test_voice.py, test_deepseek.py, test_errors.py)
├── miniprogram/
│   ├── app.js/json/wxss, config.js
│   ├── pages/auth/, pages/todos/
│   └── utils/api.js
└── docs/PROJECT.md
```

## 后端

### 技术栈
FastAPI（同步路由）+ SQLite（WAL，`check_same_thread=False`）+ httpx + Pydantic v2 + uv。
pyproject 中 `websockets` 是讯飞流式方案遗留依赖（未使用，可清理）。`imageio-ffmpeg` 提供内置静态 ffmpeg，用于非 PCM 音频转码（Windows/macOS 微信客户端不支持 PCM 录音，会上传 mp3）。

### 数据库 Schema

```sql
users (id, username, username_normalized UNIQUE, password_hash, status, ...)
  status: 'active' | 'disabled'

invite_codes (id, code_hash UNIQUE, type, status, label, ...)
  type: 'single' | 'multi'
  status: 'active' | 'redeemed' | 'revoked'
  single 使用后→redeemed；multi 保持 active

sessions (id, user_id FK, token_hash UNIQUE, created_at, expires_at, revoked_at)

todos (id, user_id FK, content, due_date, due_time?, pinned, status, deleted_at?, ...)
  status: 'pending' | 'done'
  pinned: 0 | 1 (默认 0)
  due_time: NULL 或 HH:MM
```

### 时间
Asia/Shanghai，ISO 字符串存储。`today_date()`, `tomorrow_date()`, `utcish_now_iso()`

### 认证
Bearer Token。注册需 `username + password + invite_code`，邀请码 hash 比对。密码 `pbkdf2_sha256`（210,000 迭代）。Token/session 存 hmac-sha256 hash。

### 待办规则
- 每条必有 `due_date`，无声明→今天。模糊日期（"有空""回头"）→今天
- "后天""大后天"→动态计算。"周五"→最近周五；"下周五"→下周周五
- 模糊时段→ `due_time = null`；具体时间→ HH:MM
- 过去日期→归正为今天。content 去掉日期和时间表达

**动态分类**：due_date==今天→today，==明天→tomorrow，>明天→upcoming，<今天→隐藏并定期清理

**排序**：`(not pinned?, done?, has_time?, time_or_empty, id)` — 置顶优先→pending 优先→无时间优先→时间升序→id 升序

### API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/token/register` | 注册 |
| POST | `/api/auth/token/login` | 登录 |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/me` | 当前用户 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/todos` | 分组待办 |
| PATCH | `/api/todos/{id}` | 编辑（content/due_date/due_time/status/pinned） |
| DELETE | `/api/todos/{id}` | 软删除 |
| POST | `/api/voice/transcriptions` | 音频→火山 ASR→文本 |
| POST | `/api/todos/ai` | 文本→DeepSeek→新增待办 |

### 错误格式
`{"code": "machine_code", "message": "中文提示", "details": null}`。code 稳定、message 可展示。校验错误统一 `validation_error`（422）。

### 语音/AI 数据流
小程序录音（16kHz/mono/PCM，上限 60s，下限 `MIN_AUDIO_SECONDS`，太短返回 `recording_too_short`）→ `wx.uploadFile` → 后端 PCM→WAV→base64→火山引擎极速版 HTTP POST → transcript → DeepSeek JSON Output → 校验入库。失败不写数据库。静音音频（火山 20000003）返回 200 + 空 transcript，不报错。非 PCM 格式上传走 ffmpeg 转码（`services/audio.py`，系统 ffmpeg 优先、缺失时用 imageio-ffmpeg 内置二进制，两者都没有才返回 415）。

### 火山 ASR
端点 `POST .../api/v3/auc/bigmodel/recognize/flash`，资源 `volc.bigasr.auc_turbo`，同步接口。认证优先新版 `X-Api-Key`（`VOLC_API_KEY`），缺失时回退旧版 `X-Api-App-Key` + `X-Api-Access-Key`。

### DeepSeek
`deepseek-v4-flash`，`thinking: disabled`，`temperature: 0.1`，`max_tokens: 1200`，`response_format: json_object`。httpx.AsyncClient 全局复用。Prompt 动态计算 today/tomorrow/next_friday 等日期，含 few-shot 示例。

### 代码约定
- 数据库：`Depends(get_db)` 在路由中获取连接。简单操作用 `execute()+commit()`，多步用 `BEGIN IMMEDIATE`→`commit()`/`rollback()`
- 安全：邀请码/密码/token 均不存明文。邀请码格式 `TODO-S/M-XXXX-XXXX-XXXX`，字母表排除 `0OI1`
- 测试：`PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v`（5 个文件 20 个用例：认证/待办/语音/DeepSeek/错误模型）。临时 SQLite + env patch

## 小程序

原生框架。Bear Token 认证，`config.js` 配 API 地址和 `RECORD_MAX_DURATION=60000`。

### 滑动交互
- **右滑**（80px 硬上限）：露出置顶区 → 松手超过 40px 阈值 → 乐观更新 + 本地 `_todoSort` 排序 + API 后台确认
- **左滑**（80px 硬上限）：露出删除区 → 松手超过 40px → spring 弹回 → `wx.showModal` 确认 → 删除
- **编辑按钮**：始终可见，不参与滑动
- Spring 引擎：自定义物理引擎在 `api.js` 中

### 卡片状态
- **done**：只有 `.todo-content { opacity: 0.5 }` + 文字划线，卡片背景不透明（防滑动区透出）
- **pinned**：暖白底 `#fffaf3` + 左侧 6rpx 橙色 accent（`::before`）

### 关键约定
- 乐观更新后用本地排序不用 `loadTodos`（即时响应，无骨架屏）
- 回滚用 `id` 定位不用 `index`（排序后 index 会变）
- 用 `bindtouch*` 不用 `catchtouch*`（避免拦截子元素 tap）
- Swipe `setData` 路径：`items[X].swipeX`，读 `this.data.items[index].swipeX`

## 已知限制
- 自动化测试少，无忘记密码/管理员后台
- 语音只支持新增，SQLite 适合 MVP
