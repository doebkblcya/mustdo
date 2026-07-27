# CLAUDE.md

> Todo Analyzer 代码库参考。本文档供 Claude 和其他 AI 辅助工具理解项目架构、约定和上下文。

## 项目现状

- **后端**：FastAPI + SQLite，活跃开发中
- **小程序**：微信原生小程序，`miniprogram/`，活跃开发中，复用后端 API
- **前端 Web**：`frontend/`（Vite + React + TypeScript），**已废弃，不再更新**
- **当前分支**：`main`

详细产品文档见 `docs/PROJECT.md`，本文档侧重代码实现细节和约定。

## 产品定位

Todo Analyzer — 轻量语音待办工具。语音只做"新增待办"，修改、删除、完成、改时间全部手动操作。

核心原则：
- 主流程要短：按住说话，松手自动转写→解析→入库
- 语音不做危险操作：不通过 AI 修改或删除已有事项
- AI 结果不做确认弹窗：解析过程可见，失败不写数据
- 多端优先：小程序是第一移动客户端，复用后端 API

## 项目结构

```
mustdo/
├── backend/                  # FastAPI + SQLite（主力）
│   ├── app/
│   │   ├── main.py           # 应用入口、CORS、静态文件托管、lifecycle
│   │   ├── config.py         # Settings dataclass，读取 .env
│   │   ├── db.py             # SQLite 连接 + schema 初始化
│   │   ├── deps.py           # FastAPI 依赖：get_db、current_user
│   │   ├── errors.py         # 统一错误模型（code/message/details）
│   │   ├── schemas.py        # Pydantic 请求/响应模型
│   │   ├── security.py       # 密码 hash、session token、邀请码
│   │   ├── time_utils.py     # Asia/Shanghai 时间工具
│   │   ├── routers/
│   │   │   ├── auth.py       # 注册、登录、登出、/me
│   │   │   ├── todos.py      # 待办 CRUD
│   │   │   └── voice.py      # 语音识别 + AI 解析
│   │   └── services/
│   │       ├── audio.py      # 上传音频 PCM 校验/转码
│   │       ├── asr.py        # 火山引擎录音文件极速版 HTTP 客户端
│   │       ├── deepseek.py   # DeepSeek JSON 解析和校验
│   │       └── todos.py      # 待办分组、CRUD、清理
│   ├── scripts/
│   │   ├── init_db.py
│   │   ├── create_invite.py
│   │   ├── list_invites.py
│   │   └── cleanup_overdue.py
│   └── tests/
│       ├── test_auth.py
│       ├── test_deepseek.py
│       ├── test_errors.py
│       ├── test_todos_api.py
│       └── test_voice.py
├── frontend/                 # 【已废弃】Vite + React + TypeScript
│   └── src/
│       ├── App.tsx           # 页面级状态编排
│       ├── api/client.ts     # API client + 错误处理
│       ├── auth/AuthPage.tsx
│       ├── todos/TodoDashboard.tsx, TodoItem.tsx, types.ts
│       ├── voice/VoiceButton.tsx, VoiceOverlay.tsx, useVoiceRecorder.ts, audio.ts, types.ts
│       ├── utils/date.ts
│       └── styles.css        # Liquid glass UI
├── miniprogram/              # 微信小程序（原生框架）
│   ├── app.js, app.json, app.wxss
│   ├── config.js             # 后端 API 地址
│   ├── pages/auth/
│   ├── pages/todos/
│   └── utils/api.js          # Bearer Token API client
└── docs/PROJECT.md           # 详细产品文档
```

## 后端架构

### 技术栈

- **FastAPI**（同步路由，非 async handler 除非必要）
- **SQLite**（WAL 模式，`check_same_thread=False`）
- **httpx**（DeepSeek HTTP 调用）
- **websockets**（讯飞 ASR WebSocket）
- **Pydantic v2**（请求校验和 JSON 解析）
- **uv**（包管理）

### 数据库 Schema

```sql
-- 用户表
users (id, username, username_normalized UNIQUE, password_hash, status, created_at, updated_at, last_login_at)
  status: 'active' | 'disabled'

-- 邀请码（单次使用）
invite_codes (id, code_hash UNIQUE, status, label, created_at, used_at, used_by_user_id)
  status: 'active' | 'redeemed' | 'revoked'

-- 登录态
sessions (id, user_id FK, token_hash UNIQUE, created_at, expires_at, revoked_at)

-- 待办（软删除）
todos (id, user_id FK, content, due_date, due_time?, status, created_at, updated_at, deleted_at?)
  status: 'pending' | 'done'
  due_time: NULL 或 HH:MM

-- 索引
idx_sessions_token_hash, idx_todos_user_due_date, idx_todos_user_deleted
```

### 时间处理

- 所有时间以 `Asia/Shanghai` 存储（ISO 字符串），SQLite 无原生 datetime
- `now_shanghai()` → `datetime` 对象（带时区）
- `today_date()` → 当天 `date`
- `utcish_now_iso()` → 当前上海时间 ISO 字符串（函数名故意标示"非真正 UTC"，存储用）
- `tomorrow_date()` → 明天 `date`

### 认证体系

**双模式认证**：

| 模式 | Cookie 来源 | 用途 |
|------|------------|------|
| Cookie Session | `HttpOnly` cookie（`todo_session`） | Web 端 |
| Bearer Token | `Authorization: Bearer <token>` header | 小程序、API 客户端 |

**注册流程**：
1. 需要 `username` + `password` + `invite_code`
2. 邀请码 hash 比对（不存明文），单次使用
3. `users` 表 username_normalized 唯一约束
4. 密码：`pbkdf2_sha256$iterations$salt$digest`，210,000 迭代

**登录态**：
- token 存 hash（`hmac-sha256` with `SECRET_KEY`）
- `current_user` 依赖注入：Cookie → Bearer → 401
- WebSocket 认证：从 cookie 或 header 提取 token

### 错误模型（统一格式）

```json
{"code": "machine_readable_code", "message": "中文用户提示", "details": null}
```

约定：
- `code`：稳定机器码，用于前端状态机、测试断言
- `message`：可直接展示的中文文案
- `details`：参数校验的结构化信息；无则为 `null`
- FastAPI 参数校验错误统一返回 `code=validation_error`，status=422
- WebSocket 语音流错误事件：`{type: "error", error: "..."}`

已定义的错误码：`bad_request`, `unauthorized`, `not_found`, `conflict`, `unsupported_media_type`, `validation_error`, `internal_error`, `upstream_error`, `invalid_account_input`, `invalid_invite_code`, `username_exists`, `invalid_credentials`, `todo_not_found`, `content_required`, `due_date_required`, `recording_too_short`, `recording_too_long`, `audio_empty`, `audio_transcode_failed`, `speech_recognition_failed`, `todo_parse_unavailable`, `todo_save_failed`

### API 路由摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | Cookie 注册 |
| POST | `/api/auth/login` | Cookie 登录 |
| POST | `/api/auth/token/register` | Bearer Token 注册（小程序用） |
| POST | `/api/auth/token/login` | Bearer Token 登录（小程序用） |
| POST | `/api/auth/logout` | 登出（双模式） |
| GET | `/api/me` | 当前用户 |
| GET | `/api/todos` | 获取分组待办（today/tomorrow/upcoming） |
| PATCH | `/api/todos/{id}` | 编辑待办 |
| DELETE | `/api/todos/{id}` | 软删除待办 |
| WS | `/api/voice/stream` | 流式上传 PCM，返回实时/最终转写文本 |
| POST | `/api/voice/transcriptions` | 上传音频文件转写（兼容入口） |
| POST | `/api/todos/ai` | 转写文本 → AI 解析 → 新增待办 |
| GET | `/api/health` | 健康检查 |

### 待办规则

- 每条必须有 `due_date`，无声明时默认今天
- 模糊日期（"有空""回头""改天"）→ 今天
- 模糊时段（"上午""下午""晚上"）→ `due_time = null`
- "周五" → 不早于今天的最近周五
- "下周五" → 下一个自然周周五
- "月底" → 当月最后一天
- "下午三点""9:30" → HH:MM
- AI 返回过去日期 → 归正为今天
- content 去掉日期和时间表达，保留动作和对象

**动态分类**（不存入数据库）：
- `due_date == 今天` → today
- `due_date == 明天` → tomorrow
- `due_date > 明天` → upcoming
- `due_date < 今天` → 隐藏，脚本定期清理

**排序**：`(done?, has_time?, time_or_empty, id)`

### 语音和 AI 数据流

```
前端按住 → 申请麦克风 → 本地录音（16kHz/16bit/mono PCM）
  → 松手 → wx.uploadFile POST /api/voice/transcriptions
  → 后端 PCM → WAV header → base64 → POST 火山引擎极速版
  → https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash
  → 返回 transcript
  → POST /api/todos/ai 发 transcript
  → DeepSeek JSON Output 解析
  → 校验 content/due_date/due_time
  → 写入 SQLite
```

**失败策略**：
- 无可用文本：不写数据库
- transcript 无待办：返回 200 + `items=[]`
- DeepSeek 失败或格式非法：不写数据库
- 数据库保存失败：不写数据库
- 火山引擎 ASR 失败：返回 502

### 模块职责

| 模块 | 职责 |
|------|------|
| `routers/voice.py` | HTTP 边界、认证、输入校验、响应 |
| `services/asr.py` | 火山引擎极速版：PCM→WAV→base64→HTTP POST→返回文本 |
| `services/deepseek.py` | transcript → 结构化待办 JSON 解析和校验 |
| `services/audio.py` | 音频格式校验、PCM 转码（ffmpeg fallback） |
| `services/todos.py` | 待办分组、CRUD、清理 |

### 火山引擎 ASR 协议

- 接口：`POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash`
- 认证：新版控制台 `X-Api-Key`，旧版 `X-Api-App-Key` + `X-Api-Access-Key`
- 音频格式：WAV/MP3/OGG OPUS（后端自动将 PCM 封装 WAV header）
- 资源 ID：`volc.bigasr.auc_turbo`
- 同步接口：一次请求即返回结果，无需轮询
- 响应：`result.text` 提取识别文本

### DeepSeek 配置

- Model：`deepseek-v4-flash`（可配置）
- `response_format: {type: "json_object"}`
- `thinking: {type: "disabled"}` — **必须禁用**，否则思考 token 浪费
- `temperature: 0.1`
- `max_tokens: 1200`
- `httpx.AsyncClient` 复用全局单例（shutdown 时自动关闭）
- JSON 解析支持 fenced code block（` ```json...``` `）

## 后端代码约定

### 数据库连接

- `get_connection()` 在 `db.py`：创建连接，开启 WAL + foreign_keys + busy_timeout
- `get_db()` 在 `deps.py`：FastAPI 依赖生成器，内部调用 `get_connection()`
- 路由中用 `Depends(get_db)` 获取连接
- 测试/脚本中用 `get_connection()` + 手动 `close()`
- SQLite 连接配置 `check_same_thread=False` 以支持多线程

### 事务处理

- 简单操作：`db.execute()` + `db.commit()` + 手动 try/except
- 多步操作（如注册）：`db.execute("BEGIN IMMEDIATE")` → 操作 → `db.commit()` / `db.execute("ROLLBACK")`
- `HTTPException` 需要在事务内单独 catch 后 rollback 再 raise

### 安全

- Session token 和邀请码**不存明文**，存 `hmac-sha256` hash（key 为 `SECRET_KEY`）
- 邀请码明**只在生成时输出一次**
- Session token 生成：`secrets.token_urlsafe(32)`
- 密码验证用 `hmac.compare_digest`（防 timing attack）
- 邀请码格式：`TODO-XXXX-XXXX-XXXX`，字母表排除 `0OI1`

### 测试

- 运行：`PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v`
- 编译检查：`python -m compileall backend/app backend/scripts backend/tests`
- 测试用临时 SQLite 文件 + `patch.dict(os.environ)` 注入配置
- 外部依赖（讯飞、DeepSeek）用 mock/fake 替代
- 测试后清理：`tmpdir.cleanup()` + `get_settings.cache_clear()`

## 小程序（活跃维护）

- 原生微信小程序框架
- Bearer Token 认证，调用 `/api/auth/token/register` 和 `/api/auth/token/login`
- 后续请求带 `Authorization: Bearer <token>`
- 语音通过 `wx.getRecorderManager` 采集 PCM，`wx.connectSocket` 发送
- 微信后台需配置 request 和 socket 合法域名

## 前端 Web（已废弃）

- Vite + React + TypeScript，liquid glass UI 风格
- Web Audio API 录音（`ScriptProcessorNode`，已废弃 API）
- WebSocket 流式上传 PCM 到后端
- `App.tsx` 负责页面级状态，`useVoiceRecorder` hook 管理录音全生命周期
- API 代理：Vite dev server 代理 `/api` 到后端
- 生产构建：FastAPI 托管 `frontend/dist`（`FRONTEND_DIST_DIR` 存在时自动启用）
- **不再接受新功能开发**

## 已知限制

- 自动化测试仍较少，主要覆盖语音基础逻辑
- 没有忘记密码和管理员后台
- 语音只支持新增，不支持语音修改或删除
- ASR 和 LLM 依赖外部服务可用性
- SQLite 适合 MVP，多用户规模扩大需评估迁移 PostgreSQL

## 近期优化记录（2026-07-28）

已完成的优化：
1. SQLite 启用 WAL 模式 + `busy_timeout=5000`（并发读写性能）
2. 删除未使用的 `connection_context()`
3. `update_todo` 查询优化（3→2 次）+ `create_todos` 事务加 `BEGIN IMMEDIATE`
4. DeepSeek `httpx.AsyncClient` 全局复用（shutdown 自动关闭）
5. 前端乐观更新（toggle/save/delete 先更新 UI 再异步同步）
6. **ASR 迁移**：讯飞 IAT WebSocket → 火山引擎极速版 HTTP POST
   - 删除 `voice_stream.py`、`iflytek.py`（~400 行）
   - 新增 `services/asr.py`（~100 行）
   - 消除 EOS 等待（~1.5s 尾部延迟）
   - 小程序录音改为纯本地 + 松手后 HTTP 上传

已知待处理：
- `ScriptProcessorNode` → `AudioWorkletNode`（前端，但已废弃所以优先级低）
- CSS `backdrop-filter: blur(40px)` GPU 开销（前端，已废弃所以优先级低）
