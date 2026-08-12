# Project Notes

本文档记录 Mustdo 当前架构、前后端职责、已完成进度和后续展望。README 作为快速入口，本文件作为实现和迭代参考。

## 产品定位

Mustdo 是一个轻量语音待办工具。第一版只让语音承担“新增待办”的职责，修改、删除、完成和改时间全部由用户在界面中手动完成。

核心原则：

- 主流程要短：按住说话，松手后自动转写、解析、入库。
- 语音不做危险操作：不通过 AI 修改或删除已有事项。
- AI 结果不做确认弹窗：解析过程可见，失败不写入数据。
- 多端优先：微信小程序是第一客户端，后续 iOS 复用同一套后端 API。

## 当前架构

```text
微信小程序
  - Bearer Token 登录/注册
  - 按住说话，松手后 HTTP POST 上传完整音频
  - 复用同一套待办 API
        |
        v
FastAPI Backend
  - Bearer Token 认证和用户隔离
  - SQLite 持久化
  - 火山引擎 ASR 封装
  - DeepSeek 结构化解析
        |
        +--> 火山引擎录音文件极速版（HTTP POST）
        |
        +--> DeepSeek Chat Completions JSON Output
```

后端统一持有第三方 API key、prompt、音频格式处理和数据库写入逻辑。前端不直连火山引擎或 DeepSeek。

## 后端

后端位于 `backend/`，技术栈是 FastAPI + SQLite。

### 目录结构

```text
backend/
  app/
    config.py              配置加载，读取 .env
    db.py                  SQLite 连接、schema 初始化与增量迁移
    deps.py                FastAPI 依赖，包括当前用户解析
    errors.py              统一错误模型 {code, message, details}
    main.py                应用入口、生命周期、路由注册
    schemas.py             Pydantic 请求/响应模型
    security.py            密码、邀请码、session token 哈希
    time_utils.py          Asia/Shanghai 时间工具
    routers/
      auth.py              注册、登录、登出、当前用户
      todos.py             待办查询、编辑、删除、完成状态
      voice.py             语音转写和 AI 新增待办
    services/
      audio.py             上传音频读取、时长校验、非 PCM 格式 ffmpeg 转码
      asr.py               火山引擎录音文件极速版 HTTP 客户端
      deepseek.py          DeepSeek JSON 解析和校验
      todos.py             待办分组、创建、更新、清理
  scripts/
    init_db.py             初始化数据库
    create_invite.py       创建邀请码（支持 --type single/multi）
    list_invites.py        查看邀请码记录
    clear_invites.py       清空所有邀请码
    cleanup_overdue.py     清理过期待办
    server.sh              后台启动/停止/重启/日志（生产用）
```

### 数据模型

当前 SQLite schema 包含：

- `users`：用户名、密码 hash、状态、登录时间。
- `invite_codes`：单次/多次邀请码 hash、类型、状态、使用记录。
- `sessions`：登录 session token hash、过期和撤销状态。
- `todos`：用户待办，包含内容、日期、可选时间、置顶状态、完成状态和软删除字段。

邀请码和 session token 都不明文存库。邀请码明文只在生成时输出一次，hash 依赖 `SECRET_KEY`。

### 认证

当前用户系统是”用户名/密码 + 邀请码注册”：

- 注册需要 `username`、`password`、`invite_code`。
- 邀请码支持 `single`（单次使用，格式 `TODO-S-...`）和 `multi`（长期使用，格式 `TODO-M-...`）。
- 登录只需要 `username`、`password`。
- 使用 Bearer Token 认证，`Authorization: Bearer <token>` header。
- 所有待办 API 都从 session 解析 `user_id`，客户端不传 `user_id`。
- 用户名 3-24 位字母/数字/下划线，密码至少 8 位。
- 用户被禁用（`status='disabled'`）后已有 session 立即失效（查询时校验用户状态）。
- 暂不支持忘记密码、邮箱、手机号和第三方登录。

### 待办规则

- 每条待办必须有 `due_date`。
- 没声明日期时默认为中国上海时区的今天。
- 模糊日期也默认为今天，例如”有空””回头””改天”。
- `due_time` 可为空。
- 没声明具体时间时，`due_time = null`。
- “后天””大后天”直接计算为对应日期。
- “晚上/下午/早上”等模糊时段不转成具体时间。
- “周五”解析为不早于今天的最近周五。
- “下周五”解析为下一个自然周周五。
- “月底”解析为当月最后一天。
- AI 如果返回过去日期，后端会归正为今天，避免新增后立即被隐藏。

分类动态计算，不存入数据库：

- `due_date = 今天`：今天
- `due_date = 明天`：明天
- `due_date > 明天`：后续
- `due_date < 今天`：隐藏，并由脚本定期清理

排序规则（分组内）：置顶优先 → pending 优先 → 无具体时间优先 → 时间升序 → id 升序。

### 语音和 AI 数据流

```text
1. 小程序按住说话，本地录音（16kHz/16bit/mono PCM）。
2. 松手后，wx.uploadFile POST /api/voice/transcriptions 上传完整音频文件。
3. 后端 PCM → WAV header → base64 → POST 火山引擎极速版。
4. 火山引擎返回识别文本 transcript。
5. POST /api/todos/ai 发送 transcript。
6. 后端调用 DeepSeek，要求 JSON Output。
7. 后端校验 content、due_date、due_time。
8. 校验成功后写入 SQLite。
9. 前端刷新待办并展示已添加结果。
```

失败策略：

- 录音过短（`MIN_AUDIO_SECONDS` 默认 0.5s）→ 400 `recording_too_short`；超过上限 → 400 `recording_too_long`。
- 非 PCM 格式（mp3/m4a 等）：后端自动 ffmpeg 转码为 16k/mono/s16le；未安装 ffmpeg 返回 415。
- 火山引擎检测到静音/空音频（状态码 20000003）→ 返回 `200` 和空 transcript，不写入数据库。
- 火山引擎 ASR 其他失败：返回 502，不写入数据库。
- transcript 中没有可新增待办：返回 `200` 和 `items=[]`，前端展示”未添加待办”。
- DeepSeek 请求失败或返回格式非法：返回 502，不写入数据库。
- 数据库保存失败：返回 500，不写入数据库，前端展示错误。

模块边界：

- `routers/voice.py` 只负责 HTTP 边界、用户认证、输入校验和响应。
- `services/asr.py` 负责 PCM→WAV→base64、火山引擎 HTTP 请求、返回文本提取。
- `services/deepseek.py` 只处理 transcript 到结构化待办的 JSON 解析和校验。

ASR 协议：

- 接口：`POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash`
- 同步 HTTP POST，一次请求即返回结果，无需轮询
- 音频格式：WAV（后端自动将 PCM 封装 44 字节 WAV header）
- 认证：优先新版控制台 `X-Api-Key`（`VOLC_API_KEY`）；未配置时回退旧版 `X-Api-App-Key` + `X-Api-Access-Key`
- 静音/空音频（状态码 20000003）不视为错误，返回空 transcript
- 详见 `docs/极速版.md`

### API 摘要

- `GET /api/health`：健康检查（无鉴权）
- `POST /api/auth/token/register`：注册并返回 Bearer Token
- `POST /api/auth/token/login`：登录并返回 Bearer Token
- `POST /api/auth/logout`：登出，撤销 Bearer Token
- `GET /api/me`：当前用户
- `GET /api/todos`：获取今天/明天/后续分组
- `PATCH /api/todos/{id}`：编辑内容、日期、时间、状态、置顶
- `DELETE /api/todos/{id}`：软删除待办
- `POST /api/voice/transcriptions`：上传音频文件并返回转写文本
- `POST /api/todos/ai`：将转写文本解析并新增待办

### 错误模型

普通 HTTP API 的错误响应统一为：

```json
{
  "code": "todo_not_found",
  "message": "待办不存在",
  "details": null
}
```

约定：

- `code` 是稳定机器码，用于前端状态机、多端客户端和测试断言。
- `message` 是可直接展示给用户的中文文案。
- `details` 用于参数校验等结构化信息；没有时为 `null`。
- FastAPI 参数校验错误统一返回 `code=validation_error`，`details` 为明细数组：`[{field, message, type}, ...]`。
- 未显式指定 code 的 HTTPException 按状态码映射默认 code/message（见 `app/errors.py`）。

## 微信小程序

小程序位于 `miniprogram/`，当前是原生小程序项目骨架。

### 目录结构

```text
miniprogram/
  app.json              小程序页面和窗口配置
  app.js                全局启动逻辑
  app.wxss              全局样式
  config.js             后端 API 地址
  pages/
    auth/               登录 / 注册
    todos/              待办列表和语音输入
  utils/api.js          Bearer Token API client
```

小程序使用 Bearer Token 认证，登录/注册调用 `/api/auth/token/*` 获取 token，后续请求带：

```text
Authorization: Bearer <token>
```

微信后台需要配置：

```text
request 合法域名：https://mustdo.doebkblcya.com
```

语音链路：小程序用 `wx.getRecorderManager` 采集 `16kHz/mono/PCM` 音频（上限 60s，配置在 `config.js`），松手后通过 `wx.uploadFile` 一次性上传到 `POST /api/voice/transcriptions`。后端将 PCM 封装 WAV header 后调用火山引擎极速版 ASR，返回转写文本。

### 滑动交互

卡片支持左右滑动操作：

- **右滑**：露出置顶区域，松手切换置顶状态，乐观更新 + 本地排序
- **左滑**：露出删除区域，松手弹回后弹出确认框
- **编辑按钮**：始终可见，不参与滑动
- 滑动硬上限 80px，不超出彩色区域

### 卡片状态

- **done**：仅文字内容降透明度，卡片背景保持不透明（避免背后滑动区透出）
- **pinned**：暖白底色 + 左侧橙色 accent 线，视觉层级区别于普通卡片

## 当前进度

已完成：

- FastAPI 后端项目结构。
- SQLite schema 初始化 + 增量迁移（邀请码 type、待办 pinned 列自动补列）。
- 用户名/密码登录和单次/长期邀请码注册。
- Bearer Token 认证，disabled 用户 session 失效，启动时清理过期/撤销 session。
- 待办按用户隔离。
- 待办查询、编辑、删除、完成状态、置顶。
- 今天/明天/后续动态分组 + 置顶优先排序。
- 过期待办隐藏和清理脚本。
- 统一错误模型 `{code, message, details}`（含 422 校验明细），`/api/health` 健康检查。
- 录音时长校验（下限 0.5s / 上限 60s）+ 非 PCM 格式 ffmpeg 转码。
- 微信小程序（原生框架），含滑动交互和卡片状态系统、无障碍适配（大字号/旧安卓降级动画）。
- 小程序按住说话、松手 HTTP POST 上传（60s 上限）。
- 火山引擎录音文件极速版 ASR 封装（新旧版控制台认证兼容）。
- DeepSeek JSON 解析封装（few-shot prompt + 动态日期，容错 fenced JSON 包裹）。
- 邀请码创建、查看、清空脚本。
- 后端单元测试 5 个文件 20 个用例。

已验证：

- Python 语法编译：`python -m compileall backend/app backend/scripts backend/tests`
- 后端单元测试：`PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v`
  - `test_auth.py`：登录/当前用户/登出
  - `test_todos_api.py`：删除接口
  - `test_voice.py`：WAV 封装、ASR 成功/静音/失败、上传校验、AI 空结果
  - `test_deepseek.py`：thinking 禁用、fenced JSON、空内容、空 items
  - `test_errors.py`：统一错误模型与校验明细
- 数据库初始化脚本和增量迁移。
- 邀请码生成和列表脚本。
- 待办保存逻辑。

## 已知限制

- 自动化测试覆盖认证、待办、语音、DeepSeek 解析和错误模型（20 个用例），但缺少待办分组/时间规则、编辑置顶交互、并发等场景。
- 没有忘记密码和管理员后台。
- 没有用户资料、账号绑定或多设备管理。
- 语音只支持新增，不支持语音修改或删除。
- ASR 和 LLM 依赖外部服务可用性。
- 本地 SQLite 适合 MVP 和小范围测试，后续多用户规模扩大时需要评估迁移。

## 后续展望

短期：

- 继续补测试：待办分组/时间规则、编辑和置顶交互、清理脚本。
- 优化 prompt 测试样例，沉淀常见语音表达。
- 增加简单的管理员脚本：重置密码、禁用用户、撤销邀请码。

中期：

- 支持 iOS 客户端，仍由后端统一调用 ASR/LLM。
- 增加账号绑定设计，为多端同步做准备。
- 增加任务搜索、过期查看和完成项折叠。

长期：

- 根据真实使用数据评估是否加入提醒。
- 评估是否从 SQLite 迁移到 PostgreSQL。
- 评估多 ASR/LLM 供应商切换能力。
- 引入更完整的观测：请求日志、错误追踪、第三方 API 延迟统计。
- 设计多端同步和离线缓存策略。

## 运行和维护

初始化和运行：

```bash
cd backend
cp .env.example .env          # 编辑 .env，填入 VOLC_API_KEY 和 DEEPSEEK_API_KEY
uv sync
uv run python scripts/init_db.py
uv run python scripts/create_invite.py
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务器后台运行：

```bash
cd backend
scripts/server.sh start
scripts/server.sh status
scripts/server.sh logs
scripts/server.sh restart
scripts/server.sh stop
```

`scripts/server.sh` 默认绑定 `0.0.0.0:8000`；运行日志在 `backend/logs/uvicorn.log`，pid 文件在 `backend/run/uvicorn.pid`。如需只允许本机反向代理访问，可用 `HOST=127.0.0.1 scripts/server.sh start`。

创建邀请码：

```bash
cd backend
uv run python scripts/create_invite.py          # 单次
uv run python scripts/create_invite.py --type multi  # 长期
```

查看邀请码：

```bash
cd backend
uv run python scripts/list_invites.py
```

清空邀请码：

```bash
cd backend
uv run python scripts/clear_invites.py
```

清理过期待办：

```bash
cd backend
uv run python scripts/cleanup_overdue.py
```

基础验证：

```bash
python -m compileall backend/app backend/scripts backend/tests
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```
