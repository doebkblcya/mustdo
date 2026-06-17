# Todo Analyzer

Todo Analyzer 是一个轻量语音待办工具。第一版聚焦一个核心动作：按住说话，自动新增待办。修改、删除、完成和改时间都由用户在界面中手动完成。

Web Demo 不是临时页面，而是用于验证后端 API、语音链路、AI prompt 和产品交互的第一客户端。后续微信小程序和 iOS 客户端应复用同一套后端能力。

详细架构、进度和展望见 [docs/PROJECT.md](docs/PROJECT.md)。

## 当前状态

已完成 MVP 主链路：

- 用户名/密码登录。
- 单次邀请码注册。
- 按用户隔离待办数据。
- 按住说话录音，最长 30 秒。
- 前端采集并下采样为 `16kHz/16bit/mono PCM`。
- 录音期间通过 WebSocket 流式发送 PCM，后端按讯飞协议代理语音听写。
- 后端连上讯飞后才通知前端展示识别组件，连接阶段不显示误导性转写状态。
- 后端调用 DeepSeek 将文本解析为结构化待办。
- 待办自动写入 SQLite。
- 今天 / 明天 / 后续动态分类。
- 无具体时间事项置顶，有具体时间事项以 timeline 展示。
- 手动编辑内容、日期、时间、完成状态和删除。
- 过期待办前端隐藏，脚本定期清理。
- Web Demo 使用白底淡灰 liquid glass 风格。

## 技术栈

后端：

- FastAPI
- SQLite
- Pydantic
- HttpOnly Cookie Session
- 讯飞语音听写 WebAPI
- DeepSeek Chat Completions JSON Output

前端：

- 无构建静态 Web Demo
- 原生 HTML/CSS/JavaScript
- Web Audio API 录音和 PCM 下采样
- FastAPI 静态文件托管

## 项目结构

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py                 FastAPI 入口和静态前端托管
│   │   ├── db.py                   SQLite schema 和连接
│   │   ├── config.py               环境配置
│   │   ├── security.py             密码、邀请码、session hash
│   │   ├── routers/
│   │   │   ├── auth.py             注册、登录、登出、当前用户
│   │   │   ├── todos.py            待办查询、编辑、删除
│   │   │   └── voice.py            语音转写和 AI 新增
│   │   └── services/
│   │       ├── audio.py            音频读取和 PCM 校验
│   │       ├── iflytek.py          讯飞语音听写 WebSocket 客户端
│   │       ├── voice_stream.py     流式识别编排和前端事件
│   │       ├── deepseek.py         DeepSeek JSON 解析
│   │       └── todos.py            待办业务逻辑
│   └── scripts/
│       ├── init_db.py              初始化数据库
│       ├── create_invite.py        创建单次邀请码
│       ├── list_invites.py         查看邀请码记录
│       └── cleanup_overdue.py      清理过期待办
├── frontend/
│   ├── index.html                  Web Demo 入口
│   ├── app.js                      前端状态、录音、API、渲染
│   └── styles.css                  Liquid glass UI
└── docs/
    └── PROJECT.md                  架构、进度和展望
```

## 本地运行

```bash
cd backend
cp .env.example .env
uv sync
uv run python scripts/init_db.py
uv run python scripts/create_invite.py
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

打开：

```text
http://localhost:8000
```

`.env` 至少需要配置：

```bash
SECRET_KEY=change-me
IFLYTEK_APP_ID=
IFLYTEK_API_KEY=
IFLYTEK_API_SECRET=
DEEPSEEK_API_KEY=
```

正式生成邀请码前应先固定 `SECRET_KEY`。邀请码 hash 依赖 `SECRET_KEY`，如果生成邀请码后再改 `SECRET_KEY`，旧邀请码会失效。

## 语音链路

当前语音新增链路分为两段：

```text
浏览器录音 -> WS /api/voice/stream -> 讯飞语音听写 -> transcript
transcript -> POST /api/todos/ai -> DeepSeek JSON Output -> SQLite
```

前端按住语音按钮后先展示“准备语音服务”的加载态，同时申请麦克风、建立后端 WebSocket，并把采集到的音频先缓存在本地。后端完成 session 认证并连上讯飞后，才向前端发送 `ready`。前端收到 `ready` 后切换到录音/转写组件，并开始发送 `16kHz/16bit/mono PCM`。

后端职责边界：

- `routers/voice.py`：认证、WebSocket 收发、HTTP API 和错误响应。
- `services/voice_stream.py`：流式识别编排，产生 `ready`、`partial`、`final` 事件。
- `services/iflytek.py`：讯飞鉴权 URL、1280B/40ms 分帧、结束帧和结果解析。
- `services/deepseek.py`：将 transcript 解析成 JSON 待办并做后端校验。

DeepSeek 返回空待办数组属于正常业务边界。后端会返回 `200` 和 `items=[]`，前端展示“未添加待办”，不会当作解析服务故障处理。

如果本机代理接管 `*.xfyun.cn` 的 `wss` 流量，讯飞握手可能超时。开发时建议让 `iat-api.xfyun.cn` 和 `*.xfyun.cn` 走直连。

## 常用脚本

初始化数据库：

```bash
cd backend
uv run python scripts/init_db.py
```

生成单次邀请码：

```bash
cd backend
uv run python scripts/create_invite.py
```

查看邀请码记录：

```bash
cd backend
uv run python scripts/list_invites.py
```

清理过期待办：

```bash
cd backend
uv run python scripts/cleanup_overdue.py
```

## API 摘要

- `POST /api/auth/register`：用户名/密码/邀请码注册
- `POST /api/auth/login`：登录
- `POST /api/auth/logout`：登出
- `GET /api/me`：当前用户
- `GET /api/todos`：获取今天/明天/后续分组
- `PATCH /api/todos/{id}`：编辑内容、日期、时间、状态
- `DELETE /api/todos/{id}`：删除待办
- `WS /api/voice/stream`：流式上传 PCM 并返回实时/最终转写文本
- `POST /api/voice/transcriptions`：上传音频并返回转写文本
- `POST /api/todos/ai`：将转写文本解析并新增待办

## 基础验证

```bash
python -m compileall backend/app backend/scripts
node --check frontend/app.js
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```

## 参考

- 讯飞语音听写 WebAPI：https://www.xfyun.cn/doc/asr/voicedictation/API.html
- DeepSeek Chat Completions：https://api-docs.deepseek.com/api/create-chat-completion
- DeepSeek JSON Output：https://api-docs.deepseek.com/guides/json_mode/
