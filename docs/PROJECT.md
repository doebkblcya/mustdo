# Project Notes

本文档记录 Todo Analyzer 当前架构、前后端职责、已完成进度和后续展望。README 作为快速入口，本文件作为实现和迭代参考。

## 产品定位

Todo Analyzer 是一个轻量语音待办工具。第一版只让语音承担“新增待办”的职责，修改、删除、完成和改时间全部由用户在界面中手动完成。

核心原则：

- 主流程要短：按住说话，松手后自动转写、解析、入库。
- 语音不做危险操作：不通过 AI 修改或删除已有事项。
- AI 结果不做确认弹窗：解析过程可见，失败不写入数据。
- 多端优先：Web Demo 是第一客户端，后续微信小程序和 iOS 复用同一套后端 API。

## 当前架构

```text
Vite React Frontend
  - 登录/注册
  - 按住说话并采集 PCM
  - 待办时间页和手动编辑
        |
        v
FastAPI Backend
  - Session 认证和用户隔离
  - SQLite 持久化
  - 讯飞 ASR 封装
  - DeepSeek 结构化解析
        |
        +--> 讯飞语音听写 WebAPI
        |
        +--> DeepSeek Chat Completions JSON Output
```

后端统一持有第三方 API key、prompt、音频格式处理和数据库写入逻辑。前端不直连讯飞或 DeepSeek。

## 后端

后端位于 `backend/`，技术栈是 FastAPI + SQLite。

### 目录结构

```text
backend/
  app/
    config.py              配置加载，读取 .env
    db.py                  SQLite 连接和 schema 初始化
    deps.py                FastAPI 依赖，包括当前用户解析
    main.py                应用入口、路由注册、dist 前端托管
    schemas.py             Pydantic 请求/响应模型
    security.py            密码、邀请码、session token 哈希
    time_utils.py          Asia/Shanghai 时间工具
    routers/
      auth.py              注册、登录、登出、当前用户
      todos.py             待办查询、编辑、删除、完成状态
      voice.py             语音转写和 AI 新增待办
    services/
      audio.py             上传音频读取和 PCM 校验/转码入口
      iflytek.py           讯飞语音听写 WebSocket 客户端
      voice_stream.py      流式识别编排和前端事件
      deepseek.py          DeepSeek JSON 解析和校验
      todos.py             待办分组、创建、更新、清理
  scripts/
    init_db.py             初始化数据库
    create_invite.py       创建单次邀请码
    list_invites.py        查看邀请码记录
    cleanup_overdue.py     清理过期待办
```

### 数据模型

当前 SQLite schema 包含：

- `users`：用户名、密码 hash、状态、登录时间。
- `invite_codes`：单次邀请码 hash、状态、使用记录。
- `sessions`：登录 session token hash、过期和撤销状态。
- `todos`：用户待办，包含内容、日期、可选时间、完成状态和软删除字段。

邀请码和 session token 都不明文存库。邀请码明文只在生成时输出一次，hash 依赖 `SECRET_KEY`。

### 认证

当前用户系统是“用户名/密码 + 单次邀请码注册”：

- 注册需要 `username`、`password`、`invite_code`。
- 登录只需要 `username`、`password`。
- Web 端使用 HttpOnly Cookie 保存 session。
- 所有待办 API 都从 session 解析 `user_id`，前端不传 `user_id`。
- 暂不支持忘记密码、邮箱、手机号和第三方登录。

### 待办规则

- 每条待办必须有 `due_date`。
- 没声明日期时默认为中国上海时区的今天。
- 模糊日期也默认为今天，例如“有空”“回头”“改天”。
- `due_time` 可为空。
- 没声明具体时间时，`due_time = null`。
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

### 语音和 AI 数据流

```text
1. 前端按住说话，申请麦克风并建立 WS /api/voice/stream。
2. 后端完成 Cookie session 认证。
3. 后端连接讯飞语音听写 WebSocket。
4. 连接阶段前端展示“准备语音服务”加载态，不展示转写状态。
5. 讯飞连接成功后，后端向前端发送 ready。
6. 前端收到 ready 后才切换到录音/转写组件，并开始发送本地缓冲的 PCM。
7. 前端实时采集并下采样为 16kHz/16bit/mono PCM。
8. 前端把 PCM chunk 发送给后端，不参与讯飞协议分帧。
9. 后端按讯飞文档统一拆成 1280B/40ms 音频帧并代理语音听写。
10. 前端松手后发送 end，等待 transcript。
11. 后端优先使用讯飞 final transcript。
12. 如果 final 超时但有 partial transcript，则使用 partial transcript。
13. POST /api/todos/ai 发送 transcript。
14. 后端调用 DeepSeek，要求 JSON Output。
15. 后端校验 content、due_date、due_time。
16. 校验成功后写入 SQLite。
17. 前端刷新待办并展示已添加结果。
```

失败策略：

- 讯飞连接未就绪：前端只展示准备态，不展示录音/转写状态。
- 实时语音识别 final 超时但已有 partial：使用 partial。
- 语音识别没有可用文本：不写入数据库。
- transcript 中没有可新增待办：返回 `200` 和 `items=[]`，前端展示“未添加待办”。
- DeepSeek 请求失败或返回格式非法：不写入数据库。
- 数据库保存失败：不写入数据库，前端展示错误。

模块边界：

- `routers/voice.py` 只负责 WebSocket/HTTP 边界、用户认证、输入校验和响应。
- `services/voice_stream.py` 负责编排讯飞连接、音频流、识别事件和最终结果。
- `services/iflytek.py` 只处理讯飞协议：鉴权 URL、音频帧、结束帧和返回解析。
- `services/deepseek.py` 只处理 transcript 到结构化待办的 JSON 解析和校验。

网络策略：

- 讯飞 `wss://iat-api.xfyun.cn/v2/iat` 建议走直连，避免代理影响 WebSocket/TLS 握手。

### API 摘要

- `POST /api/auth/register`：用户名/密码/邀请码注册
- `POST /api/auth/login`：登录
- `POST /api/auth/logout`：登出
- `GET /api/me`：当前用户
- `GET /api/todos`：获取今天/明天/后续分组
- `PATCH /api/todos/{id}`：编辑内容、日期、时间、状态
- `DELETE /api/todos/{id}`：软删除待办
- `WS /api/voice/stream`：流式上传 PCM 并返回实时/最终转写文本
- `POST /api/voice/transcriptions`：上传音频并返回转写文本，保留作兼容入口
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
- FastAPI 参数校验错误统一返回 `code=validation_error`。
- WebSocket 语音流沿用事件消息，错误事件仍为 `{type: "error", error: "..."}`。

## 前端

前端位于 `frontend/`，当前是 Vite + React + TypeScript 的独立 SPA。开发时由 Vite 提供前端服务并代理 `/api` 和 `/api/voice/stream` 到 FastAPI；代理目标由 `frontend/.env.local` 的 `API_PROXY_TARGET` 配置。生产构建后，FastAPI 可在存在 `frontend/dist` 时托管构建产物。

### 目录结构

```text
frontend/
  package.json       前端脚本和依赖
  vite.config.ts     Vite 配置和 API/WebSocket 代理
  index.html         Vite 入口
  src/
    App.tsx          应用状态编排
    api/             API client 和后端类型
    auth/            登录注册组件
    todos/           待办页面组件
    voice/           录音、WebSocket 和语音组件
    utils/           日期等通用工具
    styles.css       Liquid glass 风格和响应式布局
```

### 页面结构

已登录页面包含：

- 顶部栏：产品名、当前用户、登出按钮。
- 时间范围切换：今天 / 明天 / 后续，移动端保持一行三列。
- 待办页面：每次只展示一个时间范围。
- 无具体时间分组：没有 `due_time` 的事项放在时间线最上方。
- 时间线分组：有 `due_time` 的事项按时间展示。
- 底部语音按钮：按住录音并流式转写，松手后解析。
- 解析组件：连接阶段展示准备态；语音服务 ready 后展示录音/转写状态，随后展示解析、未添加、已添加或错误状态。

### 前端状态

`App.tsx` 中维护页面级状态，语音细节由 `voice/useVoiceRecorder.ts` 管理：

- `user`：当前登录用户。
- `authMode`：登录或注册。
- `todos`：后端返回的分组待办。
- `activeView`：当前时间页，值为 `today`、`tomorrow` 或 `upcoming`。
- `editingId` / `editValues`：当前编辑中的待办。
- `overlay`：语音解析组件状态，由语音 hook 暴露。
- `recording`：录音状态，由语音 hook 暴露。

### 录音实现

Web Demo 使用浏览器 Web Audio API：

- `getUserMedia` 获取麦克风。
- `AudioContext` + `ScriptProcessor` 收集音频帧。
- 前端下采样为 `16kHz`。
- 转为 `16bit little-endian PCM`。
- 后端发送 `ready` 前，PCM 暂存在前端内存队列。
- 收到 `ready` 后，通过 `/api/voice/stream` WebSocket 流式发送 PCM chunk。

这个设计减少了后端对 `ffmpeg` 的依赖。后端仍保留非 PCM 上传时尝试转码的扩展口。

### UI 风格

当前 UI 是白色背景 + 淡灰半透明 liquid glass：

- 背景为纯白。
- 组件为淡灰半透明玻璃。
- 字体为黑色系。
- 组件使用厚 `backdrop-filter: blur(40px) saturate(1.8)`。
- 使用白色内高光、灰色折射边缘和柔和阴影提升层次。
- 今天/明天/后续 tab 使用滑动玻璃指示器。

## 当前进度

已完成：

- FastAPI 后端项目结构。
- SQLite schema 初始化。
- 用户名/密码登录。
- 单次邀请码注册。
- HttpOnly Cookie session。
- 待办按用户隔离。
- 待办查询、编辑、删除、完成状态。
- 今天/明天/后续动态分组。
- 过期待办隐藏和清理脚本。
- 前端按住说话。
- 前端 PCM 下采样和 WebSocket 流式上传。
- 前端从单文件原生 JS 迁移为 Vite + React + TypeScript。
- 讯飞语音听写 WebAPI 封装。
- 语音流式编排服务，`ready` 只代表讯飞服务已连接。
- DeepSeek JSON 解析封装。
- 解析过程组件和错误展示。
- Web Demo liquid glass UI。
- 邀请码创建和查看脚本。
- 语音链路基础单元测试。

已验证：

- Python 语法编译：`python -m compileall backend/app backend/scripts backend/tests`
- 后端单元测试：`PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v`
- 数据库初始化脚本。
- 邀请码生成和列表脚本。
- 待办保存逻辑。

## 已知限制

- 自动化测试仍较少，目前主要覆盖语音基础逻辑。
- 没有忘记密码和管理员后台。
- 没有用户资料、账号绑定或多设备管理。
- Web Demo 不支持手动新增文本待办。
- 语音只支持新增，不支持语音修改或删除。
- ASR 和 LLM 依赖外部服务可用性。
- 本地未安装前端 npm 依赖时无法运行 TypeScript 检查，需要先执行 `cd frontend && npm install`。
- 本地 SQLite 适合 MVP 和小范围测试，后续多用户规模扩大时需要评估迁移。

## 后续展望

短期：

- 增加后端单元测试，覆盖认证、待办分组、时间规则和 AI JSON 校验。
- 增加前端错误态和加载态细节。
- 优化 prompt 测试样例，沉淀常见语音表达。
- 增加简单的管理员脚本：重置密码、禁用用户、撤销邀请码。
- 将过期清理接入 cron 或后台定时任务。

中期：

- 支持微信小程序客户端，复用现有 API。
- 支持 iOS 客户端，仍由后端统一调用 ASR/LLM。
- 增加 Bearer token 模式，兼容小程序和移动端安全存储。
- 增加账号绑定设计，为 Web、微信和 iOS 同步做准备。
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
cp .env.example .env
uv sync
uv run python scripts/init_db.py
uv run python scripts/create_invite.py
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端开发服务：

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

开发访问 `http://localhost:5173`。前端地址配置：

```bash
# 浏览器运行时 API 地址；留空则请求当前站点 /api
VITE_API_BASE_URL=

# Vite 开发代理目标；后端部署到服务器后可改成服务器地址
API_PROXY_TARGET=http://127.0.0.1:8000
```

如果前端直连后端服务器，需要在后端 `.env` 配置允许的前端来源：

```bash
FRONTEND_ORIGINS=http://localhost:5173,https://your-frontend.example.com
```

如果前端和后端是不同站点并直接跨域访问，生产环境通常还需要：

```bash
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=none
```

查看邀请码：

```bash
cd backend
uv run python scripts/list_invites.py
```

清理过期待办：

```bash
cd backend
uv run python scripts/cleanup_overdue.py
```

基础验证：

```bash
python -m compileall backend/app backend/scripts backend/tests
(cd frontend && npm run typecheck)
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```
